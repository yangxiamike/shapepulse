from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd

from .config import Settings, load_settings, load_thresholds
from .industry_strength import (
    LOOKBACK_TRADING_DAYS,
    SAMPLE_COUNT,
    TOP_N,
    build_industry_strength,
    fixed_sample_dates,
)
from .patterns import CATEGORY_ORDER, score_category_arrays, score_stock
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
        self._industry_strength_cache: dict[tuple, dict[str, Any]] = {}

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

    def industry_strength(
        self, pattern: str, end_date: str | None = None
    ) -> dict[str, Any]:
        pattern = str(pattern or "breakout").strip()
        if pattern not in CATEGORY_ORDER:
            raise ValueError(
                "pattern must be breakout, pullback, or range_bounce"
            )
        snapshots = self.repository.snapshots()
        latest = snapshots.daily_kline
        if latest is None:
            raise FileNotFoundError("daily_kline is required for industry strength")
        requested = None if not end_date else str(end_date).replace("-", "")
        if requested:
            self._validate_date(requested, "end_date")
        cutoff = min(requested or latest, latest)
        threshold_mtime = self.settings.thresholds_path.stat().st_mtime_ns
        cache_key = (latest, snapshots.stock_st, threshold_mtime, pattern, cutoff)
        cache = getattr(self, "_industry_strength_cache", {})
        cached = cache.get(cache_key)
        if cached is not None:
            payload = copy.deepcopy(cached)
            payload["cache_hit"] = True
            return payload

        started = time.perf_counter()
        trade_dates = self.repository.trading_dates(cutoff, 240)
        sample_dates = fixed_sample_dates(trade_dates)
        if not sample_dates:
            raise ValueError("截止日期之前没有足够的真实交易日")
        query_start = trade_dates[0]
        daily = self.repository.recent_daily(query_start, sample_dates[-1])
        securities = self.repository.security_history().copy()
        industry_history = self.repository.industry_history().copy()
        st_history = self.repository.st_history(sample_dates[0], sample_dates[-1])

        for frame, columns in (
            (daily, ["ts_code", "trade_date"]),
            (securities, ["ts_code", "list_date", "delist_date"]),
            (industry_history, ["ts_code", "in_date", "out_date"]),
            (st_history, ["ts_code", "trade_date"]),
        ):
            for column in columns:
                if column in frame:
                    frame[column] = frame[column].fillna("").astype(str)

        industries = [
            {"code": str(code), "name": str(name)}
            for (code, name), _group in industry_history.groupby(
                ["l1_code", "l1_name"], sort=False
            )
        ]
        industries.sort(key=lambda item: (item["code"], item["name"]))

        board_securities = securities[securities["market"].eq("主板")].copy()
        board_codes = set(board_securities["ts_code"])
        daily = daily[daily["ts_code"].isin(board_codes)].sort_values(
            ["ts_code", "trade_date"]
        )
        names = (
            board_securities.drop_duplicates("ts_code", keep="last")
            .set_index("ts_code")["name"]
            .astype(str)
            .to_dict()
        )

        contexts: dict[str, dict[str, Any]] = {}
        for date in sample_dates:
            listed = board_securities[
                board_securities["list_date"].le(date)
                & (
                    board_securities["delist_date"].eq("")
                    | board_securities["delist_date"].gt(date)
                )
            ]
            eligible = set(listed["ts_code"])
            if not st_history.empty:
                eligible.difference_update(
                    st_history.loc[
                        st_history["trade_date"].eq(date), "ts_code"
                    ].astype(str)
                )
            active_members = industry_history[
                industry_history["in_date"].le(date)
                & (
                    industry_history["out_date"].eq("")
                    | industry_history["out_date"].ge(date)
                )
            ].sort_values(["ts_code", "in_date"])
            active_members = active_members.drop_duplicates(
                "ts_code", keep="last"
            )
            membership = active_members.set_index("ts_code")[
                ["l1_code", "l1_name"]
            ].to_dict("index")
            contexts[date] = {"eligible": eligible, "membership": membership}

        grouped = [
            (str(code), frame.reset_index(drop=True))
            for code, frame in daily.groupby("ts_code", sort=False)
        ]
        top_by_date: dict[str, list[dict[str, Any]]] = {
            date: [] for date in sample_dates
        }

        def score_code(
            pair: tuple[str, pd.DataFrame]
        ) -> list[tuple[str, dict[str, Any]]]:
            code, frame = pair
            dates = frame["trade_date"].astype(str).tolist()
            matrix = frame[["close", "high", "low", "vol"]].to_numpy(dtype=float)
            close, high, low, volume = matrix.T
            volume = np.nan_to_num(volume, nan=0.0)
            matches: list[tuple[str, dict[str, Any]]] = []
            for date in sample_dates:
                context = contexts[date]
                if code not in context["eligible"]:
                    continue
                end_index = bisect_right(dates, date)
                if end_index <= 0:
                    continue
                lookback = int(self.thresholds["screen"]["lookback_bars"])
                start_index = max(0, end_index - lookback)
                score = score_category_arrays(
                    pattern,
                    close[start_index:end_index],
                    high[start_index:end_index],
                    low[start_index:end_index],
                    volume[start_index:end_index],
                    self.thresholds,
                )
                if score is None:
                    continue
                industry = context["membership"].get(code, {})
                matches.append(
                    (
                        date,
                        {
                            "ts_code": code,
                            "name": names.get(code, code),
                            "score": score,
                            "industry_code": industry.get("l1_code"),
                            "industry_name": industry.get("l1_name"),
                        },
                    )
                )
            return matches

        with ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="industry-strength"
        ) as pool:
            for stock_matches in pool.map(score_code, grouped, chunksize=8):
                for date, item in stock_matches:
                    top_by_date[date].append(item)

        for date in sample_dates:
            top_by_date[date].sort(
                key=lambda item: (-float(item["score"]), str(item["ts_code"]))
            )
            top_by_date[date] = top_by_date[date][:TOP_N]

        warnings: list[str] = []
        if len(trade_dates) < LOOKBACK_TRADING_DAYS:
            warnings.append(
                f"截止日期前仅有 {len(trade_dates)} 个可用交易日。"
            )
        if len(sample_dates) < SAMPLE_COUNT:
            warnings.append(
                f"本地数据仅形成 {len(sample_dates)} 个采样节点。"
            )
        payload = build_industry_strength(
            pattern=pattern,
            pattern_label=str(self.thresholds[pattern]["label"]),
            requested_end_date=requested,
            sample_dates=sample_dates,
            industries=industries,
            top_by_date=top_by_date,
            warnings=warnings,
        )
        payload["cache_hit"] = False
        payload["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000, 1
        )
        payload["as_of"] = {
            "daily": snapshots.daily_kline,
            "st": snapshots.stock_st,
            "industry": datetime.fromtimestamp(
                (
                    self.repository.data_dir
                    / "stock"
                    / "industry"
                    / "sw_member"
                    / "data.parquet"
                ).stat().st_mtime
            ).astimezone().date().isoformat(),
        }
        cache[cache_key] = copy.deepcopy(payload)
        while len(cache) > 6:
            cache.pop(next(iter(cache)))
        self._industry_strength_cache = cache
        return payload

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
                scored.append({**common, **result})
                for match in result["matches"]:
                    category_scored[match["category"]].append(
                        {
                            **common,
                            "close": result.get("close"),
                            "pct_chg": result.get("pct_chg"),
                            "matches": copy.deepcopy(result["matches"]),
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
        snapshots = self.repository.snapshots()
        if snapshots.daily_kline is None:
            raise FileNotFoundError("daily_kline data not found; cannot calculate current pattern facts")
        end = datetime.strptime(snapshots.daily_kline, "%Y%m%d")
        start = (end - timedelta(days=220)).strftime("%Y%m%d")
        frame = self.repository.pattern_daily(resolved, start, snapshots.daily_kline)
        result = score_stock(frame, self.thresholds, assume_sorted=True)
        stored = self.state_store.pattern_for_code(resolved, history_limit)
        current = {
            "run_id": f"current-local-{snapshots.daily_kline}",
            "status": result["status"],
            "matches": result.get("matches", []),
            "trade_date": result.get("trade_date"),
            "history_bars": result.get("history_bars", len(frame)),
            "warning": result.get("warning"),
            "snapshot_date": snapshots.daily_kline,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "filters": {"source": "current_local_snapshot"},
            "run_warnings": [],
        }
        if result["status"] == "matched":
            state = "matched"
            message = "按最新本地数据计算，已匹配形态"
        elif result["status"] == "no_match":
            state = "calculated_no_match"
            message = "按最新本地数据计算，三类形态均不符合"
        else:
            state = "not_calculated"
            message = result.get("warning") or "最新本地数据不足，未能完成形态计算"
        payload = {
            "ts_code": resolved,
            "calculation_state": state,
            "message": message,
            "current": current,
            "history": stored.get("history", []),
            "source": "current_local_snapshot",
        }
        payload["rule_version"] = self.thresholds.get("version")
        payload["rules"] = {
            category: {
                key: value
                for key, value in self.thresholds[category].items()
                if key not in {"weights"}
            }
            for category in CATEGORY_ORDER
        }
        payload["as_of"] = snapshots.as_dict()
        return payload
