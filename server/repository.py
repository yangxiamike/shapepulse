from __future__ import annotations

import copy
import math
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import duckdb
from zer0share.api import LocalPro


TABLE_PATHS = {
    "daily_kline": ("stock", "daily_kline"),
    "daily_basic": ("stock", "daily_basic"),
    "adj_factor": ("stock", "adj_factor"),
    "stock_st": ("stock", "stock_st"),
    "suspend_d": ("stock", "suspend_d"),
    "stk_limit": ("stock", "stk_limit"),
    "universe": ("stock", "universe"),
}


@dataclass(frozen=True)
class SnapshotDates:
    daily_kline: str | None
    daily_basic: str | None
    adj_factor: str | None
    stock_st: str | None
    suspend_d: str | None
    stk_limit: str | None
    universe: str | None

    def as_dict(self) -> dict[str, str | None]:
        return self.__dict__.copy()


def json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    return value


def row_dict(row: pd.Series) -> dict[str, Any]:
    return {str(key): json_value(value) for key, value in row.items()}


class LocalMarketRepository:
    """Small adapter around zer0share LocalPro with per-table snapshot awareness."""

    def __init__(self, zer0share_root: Path, config_path: Path):
        if not zer0share_root.is_dir():
            raise FileNotFoundError(f"zer0share root not found: {zer0share_root}")
        if not config_path.is_file():
            raise FileNotFoundError(f"zer0share config not found: {config_path}")
        self.root = zer0share_root
        self.config_path = config_path
        self.data_dir = self._read_data_dir()
        # settings.toml stores data_dir as a path relative to the zer0share repo.
        # Construct LocalPro with the resolved absolute path so starting this server
        # from another working directory can never redirect it to a wrong `data/`.
        self.pro = LocalPro(self.data_dir)
        self._lock = threading.RLock()
        self._query_lock = threading.RLock()
        self._duck = duckdb.connect()
        self._cache: dict[str, tuple[object, Any]] = {}

    def _read_data_dir(self) -> Path:
        with self.config_path.open("rb") as handle:
            config = tomllib.load(handle)
        configured = Path(config.get("paths", {}).get("data_dir", "data"))
        return configured if configured.is_absolute() else (self.root / configured).resolve()

    def latest_partition(self, table: str) -> str | None:
        parts = TABLE_PATHS[table]
        table_dir = self.data_dir.joinpath(*parts)
        if not table_dir.is_dir():
            return None
        latest: str | None = None
        if table == "universe":
            candidates = table_dir.glob("name=*/date=*")
        else:
            candidates = table_dir.glob("date=*")
        for path in candidates:
            raw = path.name.partition("=")[2]
            if len(raw) == 8 and raw.isdigit() and (latest is None or raw > latest):
                latest = raw
        return latest

    def snapshots(self) -> SnapshotDates:
        return SnapshotDates(**{table: self.latest_partition(table) for table in TABLE_PATHS})

    def _cached(self, key: str, token: object, loader):
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == token:
                return hit[1]
        value = loader()
        with self._lock:
            self._cache[key] = (token, value)
        return value

    def basic(self) -> pd.DataFrame:
        path = self.data_dir / "stock" / "basic" / "data.parquet"
        token = path.stat().st_mtime_ns
        return self._cached(
            "basic",
            token,
            lambda: self.pro.stock_basic(
                fields="ts_code,symbol,name,cnspell,market,exchange,list_status,list_date"
            ),
        )

    def industries(self) -> pd.DataFrame:
        path = self.data_dir / "stock" / "industry" / "sw_member" / "data.parquet"
        if not path.is_file():
            return pd.DataFrame(columns=["l1_code", "l1_name", "ts_code", "name", "is_new"])
        token = path.stat().st_mtime_ns
        return self._cached(
            "industries",
            token,
            lambda: self.pro.index_member_all(
                is_new="Y", fields="l1_code,l1_name,ts_code,name,is_new"
            ),
        )

    def daily_basic_snapshot(self) -> tuple[str | None, pd.DataFrame]:
        date = self.latest_partition("daily_basic")
        if date is None:
            return None, pd.DataFrame()
        path = self.data_dir / "stock" / "daily_basic" / f"date={date}" / "data.parquet"
        return date, self._cached(
            "daily_basic_latest",
            (date, path.stat().st_mtime_ns),
            lambda: pd.read_parquet(
                path,
                columns=[
                    "ts_code", "trade_date", "close", "turnover_rate",
                    "turnover_rate_f", "volume_ratio", "pe", "pe_ttm",
                    "pb", "total_mv", "circ_mv",
                ],
            ),
        )

    def st_snapshot(self) -> tuple[str | None, pd.DataFrame]:
        date = self.latest_partition("stock_st")
        if date is None:
            return None, pd.DataFrame(columns=["ts_code", "name", "trade_date", "type", "type_name"])
        path = self.data_dir / "stock" / "stock_st" / f"date={date}" / "data.parquet"
        return date, self._cached(
            "stock_st_latest",
            (date, path.stat().st_mtime_ns),
            lambda: pd.read_parquet(path),
        )

    def recent_daily(self, start_date: str, end_date: str) -> pd.DataFrame:
        token = (start_date, end_date, self.latest_partition("daily_kline"))
        return self._cached(
            "recent_daily",
            token,
            lambda: self.pro.daily(
                start_date=start_date,
                end_date=end_date,
                fields=(
                    "ts_code,trade_date,open,high,low,close,pre_close,"
                    "pct_chg,vol,amount"
                ),
            ),
        )

    def pattern_daily(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Reuse the current screening snapshot for one on-demand pattern evaluation."""
        recent = self.recent_daily(start_date, end_date)
        frame = recent[recent["ts_code"].astype(str).eq(code)].copy()
        return self._normalize_daily(frame)

    def daily_snapshot(self) -> tuple[str | None, pd.DataFrame]:
        date = self.latest_partition("daily_kline")
        if date is None:
            return None, pd.DataFrame()
        path = self.data_dir / "stock" / "daily_kline" / f"date={date}" / "data.parquet"
        return date, self._cached(
            "daily_snapshot",
            (date, path.stat().st_mtime_ns),
            lambda: pd.read_parquet(path),
        )

    def _daily_with_factors(
        self,
        code: str,
        start_date: str | None,
        end_date: str | None,
        include_factors: bool,
        limit: int | None = None,
    ) -> pd.DataFrame:
        latest_daily = self.latest_partition("daily_kline")
        latest_adj = self.latest_partition("adj_factor")
        token = (latest_daily, latest_adj)
        key = f"daily-source:{code}:{start_date}:{end_date}:{include_factors}:{limit}"
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == token:
                return hit[1].copy()
        daily_source = str(
            self.data_dir / "stock" / "daily_kline" / "date=*" / "data.parquet"
        )
        columns = (
            "d.ts_code,d.trade_date,d.open,d.high,d.low,d.close,"
            "d.pre_close,d.vol,d.amount"
        )
        params: list[object] = [daily_source]
        if include_factors:
            adj_source = str(
                self.data_dir / "stock" / "adj_factor" / "date=*" / "data.parquet"
            )
            sql = (
                f"SELECT {columns},a.adj_factor "
                "FROM read_parquet(?, hive_partitioning=true) d "
                "LEFT JOIN read_parquet(?, hive_partitioning=true) a "
                "USING(ts_code,trade_date) "
            )
            params.append(adj_source)
        else:
            sql = f"SELECT {columns} FROM read_parquet(?, hive_partitioning=true) d "
        where = ["d.ts_code=?"]
        params.append(code)
        if start_date is not None:
            where.append("d.trade_date>=?")
            params.append(start_date)
        if end_date is not None:
            where.append("d.trade_date<=?")
            params.append(end_date)
        sql += "WHERE " + " AND ".join(where)
        if limit is not None:
            sql = f"SELECT * FROM ({sql} ORDER BY d.trade_date DESC LIMIT ?) q ORDER BY trade_date"
            params.append(limit)
        else:
            sql += " ORDER BY d.trade_date"
        with self._query_lock:
            frame = self._duck.execute(sql, params).fetchdf()
        with self._lock:
            self._cache[key] = (token, frame.copy())
        return frame

    def bar_bounds(self, code: str) -> tuple[str | None, str | None]:
        latest = self.latest_partition("daily_kline")
        key = f"bar-bounds:{code}"
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == latest:
                return hit[1]
        source = str(self.data_dir / "stock" / "daily_kline" / "date=*" / "data.parquet")
        with self._query_lock:
            row = self._duck.execute(
                "SELECT min(trade_date), max(trade_date) FROM read_parquet(?, hive_partitioning=true) WHERE ts_code=?",
                [source, code],
            ).fetchone()
        value = (None, None) if row is None else tuple(None if item is None else str(item) for item in row)
        with self._lock:
            self._cache[key] = (latest, value)
        return value

    def _latest_factor(self, code: str, end_date: str) -> float | None:
        latest = self.latest_partition("adj_factor")
        key = f"latest-factor:{code}:{end_date}"
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == latest:
                return hit[1]
        source = str(self.data_dir / "stock" / "adj_factor" / "date=*" / "data.parquet")
        with self._query_lock:
            row = self._duck.execute(
                "SELECT adj_factor FROM read_parquet(?, hive_partitioning=true) "
                "WHERE ts_code=? AND trade_date<=? AND adj_factor IS NOT NULL "
                "ORDER BY trade_date DESC LIMIT 1",
                [source, code, end_date],
            ).fetchone()
        value = None if row is None else float(row[0])
        with self._lock:
            self._cache[key] = (latest, value)
        return value

    @staticmethod
    def _normalize_daily(frame: pd.DataFrame) -> pd.DataFrame:
        """Return one renderer-safe, date-aligned OHLCV row per trading day."""
        if frame.empty:
            return frame.copy()
        work = frame.copy()
        work["trade_date"] = (
            work["trade_date"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
        )
        work.loc[~work["trade_date"].str.fullmatch(r"\d{8}"), "trade_date"] = pd.NA
        numeric = ["open", "high", "low", "close", "pre_close", "vol", "amount", "adj_factor"]
        for column in numeric:
            if column in work:
                work[column] = pd.to_numeric(work[column], errors="coerce")
        work = work.dropna(subset=["trade_date", "open", "high", "low", "close"])
        work = work[(work[["open", "high", "low", "close"]] > 0).all(axis=1)]
        if work.empty:
            return work
        # A malformed high/low makes lightweight-charts discard the entire candle.
        # Preserve the source open/close and expand only the envelope when needed.
        work["high"] = work[["open", "high", "low", "close"]].max(axis=1)
        work["low"] = work[["open", "high", "low", "close"]].min(axis=1)
        for column in ("vol", "amount"):
            if column in work:
                work[column] = work[column].fillna(0).clip(lower=0)
        work = work.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        return work.reset_index(drop=True)

    def resolve_code(self, raw: str) -> str | None:
        query = raw.strip().upper()
        basic = self.basic()
        if not query:
            return None
        exact = basic[basic["ts_code"].str.upper().eq(query)]
        if exact.empty:
            exact = basic[basic["symbol"].astype(str).str.zfill(6).eq(query.zfill(6))]
        return None if exact.empty else str(exact.iloc[0]["ts_code"])

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        q = query.strip().upper()
        if not q:
            return []
        frame = self.basic().copy()
        symbol = frame["symbol"].astype(str).str.upper()
        code = frame["ts_code"].astype(str).str.upper()
        name = frame["name"].fillna("").astype(str)
        spell = frame["cnspell"].fillna("").astype(str).str.upper()
        matched = frame[
            symbol.str.contains(q, regex=False)
            | code.str.contains(q, regex=False)
            | name.str.contains(query.strip(), regex=False)
            | spell.str.contains(q, regex=False)
        ].copy()
        if matched.empty:
            return []
        matched["_rank"] = (
            code[matched.index].eq(q).astype(int) * 100
            + symbol[matched.index].eq(q).astype(int) * 95
            + name[matched.index].eq(query.strip()).astype(int) * 90
            + symbol[matched.index].str.startswith(q).astype(int) * 70
            + spell[matched.index].str.startswith(q).astype(int) * 60
            + name[matched.index].str.startswith(query.strip()).astype(int) * 50
        )
        matched = matched.sort_values(["_rank", "symbol"], ascending=[False, True]).head(limit)
        return [
            {
                "code": row["ts_code"],
                "ts_code": row["ts_code"],
                "symbol": row["symbol"],
                "name": row["name"],
                "pinyin": row["cnspell"],
                "market": row["market"],
                "exchange": row["exchange"],
            }
            for _, row in matched.iterrows()
        ]

    def stock(self, raw_code: str) -> dict[str, Any] | None:
        code = self.resolve_code(raw_code)
        if code is None:
            return None
        basic_row = self.basic()[self.basic()["ts_code"].eq(code)].iloc[0]
        basic_date, valuation = self.daily_basic_snapshot()
        value_row = valuation[valuation["ts_code"].eq(code)] if not valuation.empty else valuation
        st_date, st = self.st_snapshot()
        industry = self.industries()
        industry_row = industry[industry["ts_code"].eq(code)] if not industry.empty else industry
        daily_end, latest_quotes = self.daily_snapshot()
        quote = None
        if daily_end:
            quote_row = latest_quotes[latest_quotes["ts_code"].eq(code)]
            if not quote_row.empty:
                quote = row_dict(quote_row.iloc[-1])
        payload = row_dict(basic_row)
        payload["code"] = code
        payload["valuation"] = None if value_row.empty else row_dict(value_row.iloc[0])
        payload["quote"] = quote
        payload["industry"] = None if industry_row.empty else {
            "code": json_value(industry_row.iloc[0]["l1_code"]),
            "name": json_value(industry_row.iloc[0]["l1_name"]),
        }
        payload["is_st"] = bool(not st.empty and st["ts_code"].eq(code).any())
        adj_date = self.latest_partition("adj_factor")
        payload["as_of"] = {
            "quote": None if quote is None else quote.get("trade_date"),
            "valuation": basic_date,
            "st": st_date,
            "adj_factor": adj_date,
        }
        warnings = []
        quote_date = payload["as_of"]["quote"]
        if quote_date and basic_date != quote_date:
            warnings.append(f"行情截至 {quote_date}，估值截至 {basic_date}")
        if quote_date and st_date != quote_date:
            warnings.append(f"ST 名单截至 {st_date}，与行情日期不同")
        if quote_date and adj_date != quote_date:
            warnings.append(f"复权因子截至 {adj_date}，与行情日期不同")
        if payload["valuation"] is None:
            warnings.append("当前股票缺少最新估值数据")
        payload["warnings"] = warnings
        return payload

    def bars(
        self,
        raw_code: str,
        start_date: str | None,
        end_date: str | None,
        adjust: str,
        period: str,
        limit: int | None,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        code = self.resolve_code(raw_code)
        if code is None:
            return None
        latest_daily = self.latest_partition("daily_kline")
        if latest_daily is None:
            raise FileNotFoundError("daily_kline data not found")
        effective_end = min(end_date or latest_daily, latest_daily)
        oldest_available, newest_available = self.bar_bounds(code)
        adj_as_of = self.latest_partition("adj_factor")
        token = (latest_daily, adj_as_of)
        cache_key = f"bars:{code}:{start_date}:{effective_end}:{adjust}:{period}:{limit}"
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit is not None and hit[0] == token:
                payload = copy.deepcopy(hit[1])
                payload["cache_hit"] = True
                payload["timings"] = {
                    "total_ms": round((time.perf_counter() - started) * 1000, 1),
                    "query_ms": 0.0,
                    "adjust_ms": 0.0,
                    "aggregate_ms": 0.0,
                    "serialize_ms": 0.0,
                }
                return payload
        query_started = time.perf_counter()
        daily = self._daily_with_factors(
            code,
            start_date,
            effective_end,
            adjust in {"qfq", "hfq"},
            limit if period == "1d" else None,
        )
        daily = self._normalize_daily(daily)
        query_ms = (time.perf_counter() - query_started) * 1000
        warnings: list[str] = []
        used_adjust = adjust
        adjust_started = time.perf_counter()
        if adjust in {"qfq", "hfq"} and not daily.empty:
            factor_end = min(effective_end, adj_as_of) if adj_as_of else None
            if not factor_end or "adj_factor" not in daily or daily["adj_factor"].notna().sum() == 0:
                used_adjust = "raw"
                warnings.append("复权因子不可用，已返回未复权行情")
            else:
                daily["adj_factor"] = daily["adj_factor"].ffill()
                if daily["adj_factor"].isna().iloc[0]:
                    seed = self._latest_factor(code, str(daily["trade_date"].iloc[0]))
                    if seed:
                        daily["adj_factor"] = daily["adj_factor"].fillna(seed)
                daily["adj_factor"] = daily["adj_factor"].bfill()
                if effective_end > factor_end:
                    warnings.append(f"复权因子截至 {factor_end}，尾端沿用最近已知因子")
                if adjust == "qfq":
                    # Every segment uses the same latest local factor. Otherwise an
                    # older page would jump vertically when prepended to the chart.
                    anchor = self._latest_factor(code, latest_daily)
                    if not anchor:
                        anchor = float(daily["adj_factor"].iloc[-1])
                    multiplier = daily["adj_factor"] / anchor
                else:
                    multiplier = daily["adj_factor"]
                for column in ("open", "high", "low", "close", "pre_close"):
                    daily[column] = (daily[column] * multiplier).round(4)
                daily["change"] = (daily["close"] - daily["pre_close"]).round(2)
                daily["pct_chg"] = (daily["change"] / daily["pre_close"] * 100).round(2)
                daily = daily.drop(columns=["adj_factor"])
        adjust_ms = (time.perf_counter() - adjust_started) * 1000
        aggregate_started = time.perf_counter()
        if period != "1d" and not daily.empty:
            daily = self._resample(daily, period)
            if limit is not None:
                daily = daily.tail(limit)
        aggregate_ms = (time.perf_counter() - aggregate_started) * 1000
        serialize_started = time.perf_counter()
        records = []
        for _, row in daily.iterrows():
            trade_date = str(row["trade_date"])
            records.append(
                {
                    "time": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",
                    "trade_date": trade_date,
                    "open": json_value(row.get("open")),
                    "high": json_value(row.get("high")),
                    "low": json_value(row.get("low")),
                    "close": json_value(row.get("close")),
                    "pre_close": json_value(row.get("pre_close")),
                    "change": json_value(row.get("change")),
                    "pct_chg": json_value(row.get("pct_chg")),
                    "volume": json_value(row.get("vol")),
                    "amount": json_value(row.get("amount")),
                }
            )
        serialize_ms = (time.perf_counter() - serialize_started) * 1000
        payload = {
            "code": code,
            "period": period,
            "adjust": used_adjust,
            "requested_adjust": adjust,
            "as_of": {"daily": latest_daily, "adj_factor": adj_as_of},
            "bars": records,
            "range": {
                "requested_start": start_date,
                "requested_end": end_date,
                "returned_start": None if not records else records[0]["trade_date"],
                "returned_end": None if not records else records[-1]["trade_date"],
                "oldest_available": oldest_available,
                "newest_available": newest_available,
                "has_more_before": bool(
                    records and oldest_available and records[0]["trade_date"] > oldest_available
                ),
                "has_more_after": bool(
                    records and newest_available and records[-1]["trade_date"] < newest_available
                ),
            },
            "warnings": warnings,
            "cache_hit": False,
            "timings": {
                "query_ms": round(query_ms, 1),
                "adjust_ms": round(adjust_ms, 1),
                "aggregate_ms": round(aggregate_ms, 1),
                "serialize_ms": round(serialize_ms, 1),
                "total_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        }
        with self._lock:
            self._cache[cache_key] = (token, copy.deepcopy(payload))
        return payload

    @staticmethod
    def _resample(frame: pd.DataFrame, period: str) -> pd.DataFrame:
        rules = {"1w": "W-FRI", "1m": "ME", "1q": "QE-DEC", "1y": "YE-DEC"}
        rule = rules[period]
        work = frame.copy()
        work["_date"] = pd.to_datetime(work["trade_date"], format="%Y%m%d")
        work = work.set_index("_date")
        result = work.resample(rule).agg(
            {
                "ts_code": "last",
                "trade_date": "last",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "pre_close": "first",
                "vol": "sum",
                "amount": "sum",
            }
        ).dropna(subset=["close"])
        result["change"] = (result["close"] - result["pre_close"]).round(2)
        result["pct_chg"] = (result["change"] / result["pre_close"] * 100).round(2)
        return result.reset_index(drop=True)

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        basic_count = len(self.basic())
        return {
            "ok": True,
            "source": "local zer0share Parquet/DuckDB snapshot",
            "network": "not used",
            "zer0share_root": str(self.root),
            "config": str(self.config_path),
            "data_dir": str(self.data_dir),
            "snapshots": self.snapshots().as_dict(),
            "active_stocks": basic_count,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
