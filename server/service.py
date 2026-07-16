from __future__ import annotations

import copy
import threading
import time
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
        start_date: str = "20150101",
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
        self._validate_date(start_date, "start")
        if end_date:
            self._validate_date(end_date, "end")
            if end_date < start_date:
                raise ValueError("end must be on or after start")
        return self.repository.bars(code, start_date, end_date, adjust, period, limit)

    @staticmethod
    def _validate_date(value: str, label: str) -> None:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"{label} must use YYYYMMDD") from exc

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
            filters["market_cap_operator"],
            filters["market_cap_yi"],
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
        if save_history:
            history_results = payload["results"]
            if filters["mode"] == "per_category":
                history_results = [
                    item for category in CATEGORY_ORDER for item in payload["categories"][category]
                ]
            payload["history_run_id"] = self.state_store.record_screen(
                payload["as_of"]["daily"],
                filters,
                history_results,
                evaluations=evaluations,
                category_counts=payload["counts"]["by_category"],
                warnings=payload["warnings"],
            )
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        payload["timings"]["total_ms"] = payload["elapsed_ms"]
        notify("筛选完成", 1, 1)
        return payload

    def _normalize_filters(self, source: dict[str, Any]) -> dict[str, Any]:
        defaults = self.thresholds["screen"]
        boards = source.get("boards", source.get("board", defaults["default_board"]))
        if isinstance(boards, str):
            boards = [item.strip() for item in boards.split(",") if item.strip()]
        boards = list(dict.fromkeys(boards or [defaults["default_board"]]))
        unknown = set(boards).difference(ALLOWED_BOARDS)
        if unknown:
            raise ValueError(f"unsupported boards: {', '.join(sorted(unknown))}")
        operator = str(source.get("market_cap_operator", source.get("operator", defaults["default_market_cap_operator"]))).lower()
        aliases = {">=": "gte", ">": "gt", "<=": "lte", "<": "lt"}
        operator = aliases.get(operator, operator)
        if operator not in {"gte", "gt", "lte", "lt"}:
            raise ValueError("market_cap_operator must be gte, gt, lte, or lt")
        cap = float(source.get("market_cap_yi", source.get("market_cap", defaults["default_market_cap_yi"])))
        if cap < 0:
            raise ValueError("market_cap_yi cannot be negative")
        top_k = int(source.get("top_k", defaults["default_top_k"]))
        top_k = max(1, min(int(defaults["max_top_k"]), top_k))
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
            "market_cap_operator": operator,
            "market_cap_yi": cap,
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
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="market-ref") as pool:
            basic_future = pool.submit(self.repository.basic)
            valuation_future = pool.submit(self.repository.daily_basic_snapshot)
            st_future = pool.submit(self.repository.st_snapshot)
            basic = basic_future.result()
            progress("读取股票、估值和 ST 快照", 1, 3)
            valuation_date, valuation = valuation_future.result()
            progress("读取股票、估值和 ST 快照", 2, 3)
            st_date, st = st_future.result()
        progress("读取股票、估值和 ST 快照", 3, 3)
        pool = basic[basic["market"].isin(filters["boards"])].merge(
            valuation, on="ts_code", how="left", suffixes=("", "_daily")
        )
        pool["total_mv_yi"] = pool["total_mv"] / 10000.0
        valid_valuation = pool["total_mv_yi"].notna()
        cap = filters["market_cap_yi"]
        op = filters["market_cap_operator"]
        comparison = {
            "gte": pool["total_mv_yi"].ge(cap),
            "gt": pool["total_mv_yi"].gt(cap),
            "lte": pool["total_mv_yi"].le(cap),
            "lt": pool["total_mv_yi"].lt(cap),
        }[op]
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
                    category_scored[match["category"]].append({**common, **match})
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
