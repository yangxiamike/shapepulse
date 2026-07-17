from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable

import pandas as pd

from .config import Settings, load_settings, load_thresholds
from .patterns import CATEGORY_ORDER, score_stock
from .repository import LocalMarketRepository, json_value
from .state import StateStore


ALLOWED_BOARDS = {"主板", "创业板", "科创板"}


class MarketService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.thresholds = load_thresholds(self.settings.thresholds_path)
        self._threshold_mtime = self.settings.thresholds_path.stat().st_mtime_ns
        self.repository = LocalMarketRepository(
            self.settings.zer0share_root, self.settings.zer0share_config
        )
        self.state_store = StateStore(self.settings.state_db)
        self._screen_lock = threading.RLock()
        self._screen_cache: dict[tuple, dict[str, Any]] = {}
        self._completed_screens: dict[str, dict[str, Any]] = {}

    def health(self) -> dict[str, Any]:
        payload = self.repository.health()
        payload.update(
            {
                "service": "手动跟踪市场 local API",
                "threshold_version": self.thresholds.get("version"),
                "state_db": str(self.settings.state_db),
            }
        )
        return payload

    def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        limit = max(1, min(50, int(limit)))
        return {"query": query, "results": self.repository.search(query, limit)}

    def industries(self) -> dict[str, Any]:
        frame = self.repository.industries()
        if frame.empty:
            return {"items": [], "as_of": None, "source": "申万一级行业（本地 zer0share）"}
        items = []
        for (code, name), group in frame.groupby(["l1_code", "l1_name"], sort=False):
            items.append({"code": str(code), "name": str(name), "stock_count": int(len(group))})
        items.sort(key=lambda item: (item["name"], item["code"]))
        industry_file = self.repository.data_dir / "stock" / "industry" / "sw_member" / "data.parquet"
        as_of = datetime.fromtimestamp(industry_file.stat().st_mtime).astimezone().date().isoformat()
        return {
            "items": items,
            "names": [item["name"] for item in items],
            "as_of": as_of,
            "source": "申万一级行业（本地 zer0share）",
        }

    def stock(self, code: str, mark_viewed: bool = False) -> dict[str, Any] | None:
        payload = self.repository.stock(code)
        if payload is None:
            return None
        if mark_viewed:
            self.state_store.update(payload["code"], "viewed")
        payload["state"] = self.state_store.for_code(payload["code"])
        return payload

    def bars(
        self,
        code: str,
        start_date: str | None = None,
        end_date: str | None = None,
        adjust: str = "qfq",
        period: str = "1d",
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        adjust = adjust.lower()
        if adjust in {"none", "unadjusted"}:
            adjust = "raw"
        if adjust not in {"raw", "qfq", "hfq"}:
            raise ValueError("adjust must be raw, qfq, or hfq")
        period = period.lower()
        aliases = {
            "d": "1d", "day": "1d", "w": "1w", "week": "1w",
            "m": "1m", "month": "1m", "q": "1q", "quarter": "1q",
            "y": "1y", "year": "1y",
        }
        period = aliases.get(period, period)
        if period not in {"1d", "1w", "1m", "1q", "1y"}:
            raise ValueError("period must be 1d, 1w, 1m, 1q, or 1y")
        if start_date:
            self._validate_date(start_date, "start")
        if end_date:
            self._validate_date(end_date, "end")
            if start_date and end_date < start_date:
                raise ValueError("end must be on or after start")
        if limit is not None:
            limit = self._positive_integer(limit, "limit")
        return self.repository.bars(code, start_date, end_date, adjust, period, limit)

    @staticmethod
    def _validate_date(value: str, label: str) -> None:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"{label} must use YYYYMMDD") from exc

    @staticmethod
    def _positive_integer(value: Any, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a positive integer")
        raw = str(value).strip()
        if not re.fullmatch(r"[0-9]+", raw):
            raise ValueError(f"{label} must be a positive integer")
        parsed = int(raw)
        if parsed < 1:
            raise ValueError(f"{label} must be a positive integer")
        return parsed

    def screen(
        self,
        options: dict[str, Any] | None = None,
        save_history: bool = False,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        notify = progress or (lambda _stage, _completed, _total: None)
        notify("准备本地数据", 0, 1)
        threshold_mtime = self.settings.thresholds_path.stat().st_mtime_ns
        if threshold_mtime != self._threshold_mtime:
            with self._screen_lock:
                self.thresholds = load_thresholds(self.settings.thresholds_path)
                self._threshold_mtime = threshold_mtime
                self._screen_cache.clear()
        filters = self._normalize_filters(options or {})
        snapshots = self.repository.snapshots()
        cache_key = (
            snapshots.daily_kline,
            snapshots.daily_basic,
            snapshots.stock_st,
            self._threshold_mtime,
            tuple(filters["boards"]),
            tuple(filters["industries"]),
            filters["market_cap_min_yi"],
            filters["market_cap_max_yi"],
            filters["exclude_st"],
            filters["top_k"],
            filters["mode"],
        )
        with self._screen_lock:
            cached = self._screen_cache.get(cache_key)
        if cached is None:
            payload = self._run_screen(filters, snapshots, notify)
            with self._screen_lock:
                if len(self._screen_cache) >= 8:
                    self._screen_cache.pop(next(iter(self._screen_cache)))
                self._screen_cache[cache_key] = copy.deepcopy(payload)
        else:
            payload = copy.deepcopy(cached)
            payload["cache_hit"] = True
            payload["timings"] = {
                "reference_ms": 0.0,
                "daily_query_ms": 0.0,
                "scoring_ms": 0.0,
                "assembly_ms": 0.0,
            }
            notify("命中筛选缓存", 1, 1)
        evaluations = payload.pop("_evaluations", [])
        previous = self.state_store.previous_category_counts(
            filters, payload["as_of"]["daily"]
        )
        if previous is None:
            payload["comparison_as_of"] = None
            payload["category_deltas"] = {category: None for category in CATEGORY_ORDER}
        else:
            previous_date, previous_counts = previous
            payload["comparison_as_of"] = previous_date
            payload["category_deltas"] = {
                category: payload["counts"]["by_category"].get(category, 0)
                - int(previous_counts.get(category, 0))
                for category in CATEGORY_ORDER
            }
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        payload["timings"]["total_ms"] = payload["elapsed_ms"]
        payload["rule_version"] = self.thresholds.get("version")
        screen_token = uuid.uuid4().hex
        payload["screen_token"] = screen_token
        self._remember_completed_screen(screen_token, payload, evaluations)
        if save_history:
            payload["history_run_id"] = self.save_screen_snapshot(screen_token)[
                "history_run_id"
            ]
        notify("筛选完成", 1, 1)
        return payload

    def _remember_completed_screen(
        self, screen_token: str, payload: dict[str, Any], evaluations: list[dict[str, Any]]
    ) -> None:
        now = time.monotonic()
        with self._screen_lock:
            expired = [
                token
                for token, item in self._completed_screens.items()
                if now - float(item["created_monotonic"]) > 15 * 60
            ]
            for token in expired:
                self._completed_screens.pop(token, None)
            while len(self._completed_screens) >= 32:
                self._completed_screens.pop(next(iter(self._completed_screens)))
            self._completed_screens[screen_token] = {
                "created_monotonic": now,
                "payload": copy.deepcopy(payload),
                "evaluations": copy.deepcopy(evaluations),
                "history_run_id": None,
            }

    def _normalize_filters(self, source: dict[str, Any]) -> dict[str, Any]:
        defaults = self.thresholds["screen"]
        boards = source.get("boards", source.get("board", defaults["default_board"]))
        if isinstance(boards, str):
            boards = [item.strip() for item in boards.split(",") if item.strip()]
        boards = list(dict.fromkeys(boards or [defaults["default_board"]]))
        unknown = set(boards).difference(ALLOWED_BOARDS)
        if unknown:
            raise ValueError(f"unsupported boards: {', '.join(sorted(unknown))}")
        industries = source.get("industries", source.get("industry", []))
        if isinstance(industries, str):
            industries = [item.strip() for item in industries.split(",") if item.strip()]
        industries = list(dict.fromkeys(str(item).strip() for item in (industries or []) if str(item).strip()))
        industry_frame = self.repository.industries()
        available_industries = set(industry_frame.get("l1_name", pd.Series(dtype=str)).dropna().astype(str))
        available_industries.update(industry_frame.get("l1_code", pd.Series(dtype=str)).dropna().astype(str))
        unknown_industries = set(industries).difference(available_industries)
        if unknown_industries:
            raise ValueError(f"unsupported industries: {', '.join(sorted(unknown_industries))}")

        def optional_cap(name: str) -> float | None:
            value = source.get(name)
            if value is None or (isinstance(value, str) and not value.strip()):
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a non-negative number or empty") from exc
            if not pd.notna(parsed) or parsed < 0:
                raise ValueError(f"{name} must be a non-negative number or empty")
            return parsed

        operator = None
        has_range = any(key in source for key in ("market_cap_min_yi", "market_cap_max_yi"))
        if has_range:
            cap_min = optional_cap("market_cap_min_yi")
            cap_max = optional_cap("market_cap_max_yi")
        elif any(key in source for key in ("market_cap_yi", "market_cap", "market_cap_operator", "operator")):
            operator = str(source.get("market_cap_operator", source.get("operator", "gte"))).lower()
            aliases = {">=": "gte", ">": "gt", "<=": "lte", "<": "lt"}
            operator = aliases.get(operator, operator)
            if operator not in {"gte", "gt", "lte", "lt"}:
                raise ValueError("market_cap_operator must be gte, gt, lte, or lt")
            legacy_value = source.get("market_cap_yi", source.get("market_cap"))
            try:
                cap = float(legacy_value)
            except (TypeError, ValueError) as exc:
                raise ValueError("market_cap_yi must be a non-negative number") from exc
            if not pd.notna(cap) or cap < 0:
                raise ValueError("market_cap_yi must be a non-negative number")
            # Legacy strict operators cannot be represented by the inclusive V1.2
            # range. Keep them in compatibility fields and apply below.
            cap_min = cap if operator in {"gte", "gt"} else None
            cap_max = cap if operator in {"lte", "lt"} else None
        else:
            cap_min = optional_cap("market_cap_min_yi")
            cap_max = optional_cap("market_cap_max_yi")
        if cap_min is not None and cap_max is not None and cap_min > cap_max:
            raise ValueError("market_cap_min_yi cannot exceed market_cap_max_yi")
        top_k = self._positive_integer(source.get("top_k", defaults["default_top_k"]), "top_k")
        mode = str(source.get("mode", "combined"))
        if mode not in {"combined", "per_category"}:
            raise ValueError("mode must be combined or per_category")
        exclude_raw = source.get("exclude_st", defaults["default_exclude_st"])
        if isinstance(exclude_raw, str):
            exclude_st = exclude_raw.lower() not in {"0", "false", "no"}
        else:
            exclude_st = bool(exclude_raw)
        return {
            "boards": boards,
            "industries": industries,
            "market_cap_min_yi": cap_min,
            "market_cap_max_yi": cap_max,
            "market_cap_operator": operator,
            "exclude_st": exclude_st,
            "top_k": top_k,
            "mode": mode,
        }

    def _run_screen(
        self,
        filters: dict[str, Any],
        snapshots,
        progress: Callable[[str, int, int], None],
    ) -> dict[str, Any]:
        if snapshots.daily_kline is None or snapshots.daily_basic is None:
            raise FileNotFoundError("daily_kline and daily_basic are required for screening")
        reference_started = time.perf_counter()
        progress("读取股票、估值和 ST 快照", 0, 3)
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-ref") as pool:
            basic_future = pool.submit(self.repository.basic)
            valuation_future = pool.submit(self.repository.daily_basic_snapshot)
            st_future = pool.submit(self.repository.st_snapshot)
            industry_future = pool.submit(self.repository.industries)
            basic = basic_future.result()
            progress("读取股票、估值和 ST 快照", 1, 3)
            valuation_date, valuation = valuation_future.result()
            progress("读取股票、估值和 ST 快照", 2, 3)
            st_date, st = st_future.result()
            industry = industry_future.result()
        progress("读取股票、估值和 ST 快照", 3, 3)
        pool = basic[basic["market"].isin(filters["boards"])].merge(
            valuation, on="ts_code", how="left", suffixes=("", "_daily")
        )
        industry = industry[["ts_code", "l1_code", "l1_name"]].drop_duplicates("ts_code", keep="first")
        pool = pool.merge(industry, on="ts_code", how="left")
        pool["total_mv_yi"] = pool["total_mv"] / 10000.0
        valid_valuation = pool["total_mv_yi"].notna()
        comparison = self._market_cap_mask(pool["total_mv_yi"], filters)
        if filters["industries"]:
            comparison &= pool["l1_name"].isin(filters["industries"]) | pool["l1_code"].isin(filters["industries"])
        eligible = pool[valid_valuation & comparison].copy()
        st_codes = set(st["ts_code"].astype(str)) if not st.empty else set()
        eligible["is_st"] = eligible["ts_code"].isin(st_codes)
        if filters["exclude_st"]:
            eligible = eligible[~eligible["is_st"]]
        reference_ms = (time.perf_counter() - reference_started) * 1000

        end = datetime.strptime(snapshots.daily_kline, "%Y%m%d")
        start = (end - timedelta(days=220)).strftime("%Y%m%d")
        query_started = time.perf_counter()
        progress("读取近 220 天本地日线", 0, 1)
        recent = self.repository.recent_daily(start, snapshots.daily_kline)
        recent = recent[recent["ts_code"].isin(set(eligible["ts_code"]))]
        recent = recent.sort_values(["ts_code", "trade_date"])
        daily_query_ms = (time.perf_counter() - query_started) * 1000
        progress("读取近 220 天本地日线", 1, 1)
        meta = eligible.set_index("ts_code").to_dict("index")
        scored: list[dict[str, Any]] = []
        category_scored: dict[str, list[dict[str, Any]]] = {
            category: [] for category in CATEGORY_ORDER
        }
        evaluations: list[dict[str, Any]] = []
        scoring_started = time.perf_counter()
        grouped = recent.groupby("ts_code", sort=False)
        total_groups = grouped.ngroups
        for position, (code, frame) in enumerate(grouped, 1):
            result = score_stock(frame, self.thresholds, assume_sorted=True)
            details = meta[str(code)]
            latest_row = frame.iloc[-1]
            sparkline = [
                round(float(value), 3) for value in frame.tail(8)["close"].tolist()
            ]
            common = {
                "code": str(code),
                "ts_code": str(code),
                "symbol": json_value(details.get("symbol")),
                "name": json_value(details.get("name")),
                "market": json_value(details.get("market")),
                "exchange": json_value(details.get("exchange")),
                "industry_code": json_value(details.get("l1_code")),
                "industry_name": json_value(details.get("l1_name")),
                "total_mv_yi": round(float(details["total_mv_yi"]), 2),
                "circ_mv_yi": None
                if pd.isna(details.get("circ_mv"))
                else round(float(details["circ_mv"]) / 10000.0, 2),
                "is_st": bool(details["is_st"]),
                "open": json_value(latest_row.get("open")),
                "high": json_value(latest_row.get("high")),
                "low": json_value(latest_row.get("low")),
                "pre_close": json_value(latest_row.get("pre_close")),
                "volume": json_value(latest_row.get("vol")),
                "amount": json_value(latest_row.get("amount")),
                "turnover_rate": json_value(details.get("turnover_rate")),
                "total_mv": json_value(details.get("total_mv")),
                "circ_mv": json_value(details.get("circ_mv")),
                "sparkline": sparkline,
                "trade_date": result.get("trade_date"),
                "history_bars": result.get("history_bars", len(frame)),
            }
            evaluations.append(
                {
                    "ts_code": str(code),
                    "status": result["status"],
                    "matches": result.get("matches", []),
                    "trade_date": result.get("trade_date"),
                    "history_bars": result.get("history_bars", len(frame)),
                    "warning": result.get("warning"),
                }
            )
            if result["status"] == "matched":
                scored.append({**common, **{k: v for k, v in result.items() if k != "matches"}})
                for match in result["matches"]:
                    category_scored[match["category"]].append(
                        {
                            **common,
                            "close": result.get("close"),
                            "pct_chg": result.get("pct_chg"),
                            **match,
                        }
                    )
            if position == 1 or position % 100 == 0 or position == total_groups:
                progress("计算三类形态", position, total_groups)
        evaluated_codes = {item["ts_code"] for item in evaluations}
        for code in eligible["ts_code"].astype(str):
            if code not in evaluated_codes:
                evaluations.append(
                    {
                        "ts_code": code,
                        "status": "not_calculated",
                        "matches": [],
                        "history_bars": 0,
                        "warning": "本地日线不足，尚未完成形态计算",
                    }
                )
        scoring_ms = (time.perf_counter() - scoring_started) * 1000
        assembly_started = time.perf_counter()
        scored.sort(key=lambda item: (-item["score"], item["ts_code"]))
        categories: dict[str, list[dict]] = {}
        for category in CATEGORY_ORDER:
            category_scored[category].sort(
                key=lambda item: (-item["score"], item["ts_code"])
            )
            items = [
                copy.deepcopy(item)
                for item in category_scored[category][: filters["top_k"]]
            ]
            for index, item in enumerate(items, 1):
                item["rank"] = index
                item["category_rank"] = index
                item["match_score"] = item.get("score")
            categories[category] = items
        combined = [copy.deepcopy(item) for item in scored[: filters["top_k"]]]
        category_ranks = {
            (item["category"], item["ts_code"]): item["rank"]
            for items in categories.values()
            for item in items
        }
        for index, item in enumerate(combined, 1):
            item["rank"] = index
            item["category_rank"] = category_ranks.get((item["category"], item["ts_code"]))
            item["match_score"] = item.get("score")
        warnings = []
        if snapshots.daily_kline != valuation_date:
            warnings.append(f"行情截至 {snapshots.daily_kline}，估值截至 {valuation_date}")
        if filters["exclude_st"] and st_date != snapshots.daily_kline:
            warnings.append(f"ST 名单截至 {st_date}，与行情日期不同")
        if snapshots.adj_factor != snapshots.daily_kline:
            warnings.append(
                f"复权因子截至 {snapshots.adj_factor}，与行情日期不同"
            )
        missing_valuation = int((~valid_valuation).sum())
        if missing_valuation:
            warnings.append(f"{missing_valuation} 只股票缺少最新市值，未进入筛选")
        assembly_ms = (time.perf_counter() - assembly_started) * 1000
        return {
            "as_of": {
                "daily": snapshots.daily_kline,
                "valuation": valuation_date,
                "st": st_date,
                "adj_factor": snapshots.adj_factor,
            },
            "filters": filters,
            "counts": {
                "board_pool": int(len(pool)),
                "eligible": int(len(eligible)),
                "scored": int(len(scored)),
                "by_category": {
                    category: len(category_scored[category])
                    for category in CATEGORY_ORDER
                },
            },
            "mode": filters["mode"],
            "top_k": filters["top_k"],
            "results": combined,
            "categories": categories,
            "warnings": warnings,
            "cache_hit": False,
            "timings": {
                "reference_ms": round(reference_ms, 1),
                "daily_query_ms": round(daily_query_ms, 1),
                "scoring_ms": round(scoring_ms, 1),
                "assembly_ms": round(assembly_ms, 1),
            },
            "_evaluations": evaluations,
        }

    @staticmethod
    def _market_cap_mask(values: pd.Series, filters: dict[str, Any]) -> pd.Series:
        result = pd.Series(True, index=values.index)
        cap_min = filters.get("market_cap_min_yi")
        cap_max = filters.get("market_cap_max_yi")
        if cap_min is not None:
            result &= values.ge(cap_min)
        if cap_max is not None:
            result &= values.le(cap_max)
        # V1.2 bounds are inclusive; strict operators only remain for V1.1 callers.
        if filters.get("market_cap_operator") == "gt" and cap_min is not None:
            result &= values.gt(cap_min)
        if filters.get("market_cap_operator") == "lt" and cap_max is not None:
            result &= values.lt(cap_max)
        return result

    def state(self, history_limit: int = 20) -> dict[str, Any]:
        payload = self.state_store.snapshot(max(1, min(100, int(history_limit))))
        basic = self.repository.basic().set_index("ts_code")
        for bucket in ("viewed", "saved", "pending", "watchlist"):
            for item in payload[bucket]:
                code = item["ts_code"]
                if code in basic.index:
                    row = basic.loc[code]
                    item.update(
                        {
                            "name": json_value(row["name"]),
                            "symbol": json_value(row["symbol"]),
                            "market": json_value(row["market"]),
                        }
                    )
        for item in payload["history"]["recommendations"]:
            code = item["ts_code"]
            if code in basic.index:
                row = basic.loc[code]
                item.update(
                    {
                        "name": json_value(row["name"]),
                        "symbol": json_value(row["symbol"]),
                        "market": json_value(row["market"]),
                    }
                )
        return payload

    def save_screen_snapshot(
        self,
        screen_token: str | None = None,
        fallback_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = str(screen_token or "").strip()
        if token:
            with self._screen_lock:
                entry = self._completed_screens.get(token)
                if entry is not None and time.monotonic() - float(
                    entry["created_monotonic"]
                ) > 15 * 60:
                    self._completed_screens.pop(token, None)
                    entry = None
            if entry is None and fallback_filters is None:
                raise LookupError("screen_token is unknown or expired; run the screen again")
        else:
            entry = None
        if entry is None:
            generated = self.screen(fallback_filters or {}, False)
            token = generated["screen_token"]

        # Keep the lock through persistence so retrying the same token is idempotent.
        with self._screen_lock:
            entry = self._completed_screens.get(token)
            if entry is None:
                raise LookupError("screen_token is unknown or expired; run the screen again")
            existing_run_id = entry.get("history_run_id")
            payload = copy.deepcopy(entry["payload"])
            if existing_run_id:
                payload["history_run_id"] = existing_run_id
                return payload
            filters = payload["filters"]
            history_results = payload["results"]
            if filters["mode"] == "per_category":
                history_results = [
                    item
                    for category in CATEGORY_ORDER
                    for item in payload["categories"][category]
                ]
            run_id = self.state_store.record_screen(
                payload["as_of"]["daily"],
                filters,
                history_results,
                evaluations=entry["evaluations"],
                category_counts=payload["counts"]["by_category"],
                warnings=payload["warnings"],
                rule_version=payload.get("rule_version"),
                payload=payload,
                saved_by_user=True,
            )
            entry["history_run_id"] = run_id
        payload["history_run_id"] = run_id
        return payload

    def saved_snapshots(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        return self.state_store.list_saved_snapshots(page, page_size)

    def saved_snapshot(self, run_id: str) -> dict[str, Any]:
        payload = self.state_store.saved_snapshot(run_id)
        if payload is None:
            raise LookupError(f"saved screen snapshot not found: {run_id}")
        return payload

    def pattern_pool(self, category: str, limit: Any = 200) -> dict[str, Any]:
        category = str(category).strip().lower()
        if category not in CATEGORY_ORDER:
            raise ValueError(f"category must be one of: {', '.join(CATEGORY_ORDER)}")
        parsed_limit = self._positive_integer(limit, "limit")
        saved = self.state_store.latest_saved_category(category)
        if saved is not None:
            run, items = saved
            if items:
                pool = items[:parsed_limit]
                return {
                    "category": category,
                    "category_label": self.thresholds[category]["label"],
                    "available_categories": self._pattern_categories(),
                    "items": [self._pool_item(item, index) for index, item in enumerate(pool, 1)],
                    "total": len(items),
                    "source": "saved_snapshot",
                    "snapshot_id": run["run_id"],
                    "as_of": run["snapshot_date"],
                }
        current = self.screen({"mode": "per_category", "top_k": parsed_limit}, False)
        items = current["categories"][category]
        return {
            "category": category,
            "category_label": self.thresholds[category]["label"],
            "available_categories": self._pattern_categories(),
            "items": [self._pool_item(item, index) for index, item in enumerate(items, 1)],
            "total": current["counts"]["by_category"][category],
            "source": "current_calculation",
            "snapshot_id": None,
            "as_of": current["as_of"]["daily"],
        }

    @staticmethod
    def _pool_item(item: dict[str, Any], fallback_rank: int) -> dict[str, Any]:
        return {
            "code": item.get("code", item.get("ts_code")),
            "ts_code": item.get("ts_code", item.get("code")),
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "score": item.get("score"),
            "rank": item.get("category_rank", item.get("rank", fallback_rank)),
        }

    def _pattern_categories(self) -> list[dict[str, str]]:
        return [
            {"category": category, "label": str(self.thresholds[category]["label"])}
            for category in CATEGORY_ORDER
        ]

    def update_state(self, code: str, action: str) -> dict[str, Any]:
        resolved = self.repository.resolve_code(code)
        if resolved is None:
            raise LookupError(f"stock not found: {code}")
        return self.state_store.update(resolved, action)

    def pattern(self, code: str, history_limit: int = 10) -> dict[str, Any] | None:
        resolved = self.repository.resolve_code(code)
        if resolved is None:
            return None
        payload = self.state_store.pattern_for_code(resolved, history_limit)
        payload["rule_version"] = self.thresholds.get("version")
        payload["rules"] = {
            category: {
                key: value
                for key, value in self.thresholds[category].items()
                if key not in {"weights"}
            }
            for category in CATEGORY_ORDER
        }
        payload["as_of"] = self.repository.snapshots().as_dict()
        return payload
