from __future__ import annotations

import copy
import hashlib
import json
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
from .cache import BoundedTTLCache
from .industry_strength import (
    LOOKBACK_TRADING_DAYS,
    SAMPLE_COUNT,
    TOP_N,
    build_industry_strength,
    fixed_sample_dates,
)
from .patterns import CATEGORY_ORDER, score_category_arrays, score_stock
from .repository import LocalMarketRepository, json_value
from .similarity import (
    ALGORITHM as SIMILARITY_ALGORITHM,
    FrozenTemplate,
    load_frozen_templates,
    score_latest_cross_section,
    z_log_close,
)
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
        self.frozen_templates = load_frozen_templates(
            self.settings.similarity_templates_path
        )
        self._frozen_templates_by_id = {
            item.key: item for item in self.frozen_templates
        }
        self._materialized_frozen_templates: dict[tuple, dict[str, Any]] = {}
        self._similarity_score_cache: dict[tuple, pd.DataFrame] = {}
        self._similarity_lock = threading.RLock()
        self._screen_lock = threading.RLock()
        self._screen_cache: BoundedTTLCache[
            tuple, dict[str, Any]
        ] = BoundedTTLCache(2, 10 * 60, max_bytes=64 * 1024 * 1024)
        self._completed_screens: BoundedTTLCache[
            str, dict[str, Any]
        ] = BoundedTTLCache(8, 10 * 60, max_bytes=64 * 1024 * 1024)
        self._industry_strength_cache: BoundedTTLCache[
            tuple, dict[str, Any]
        ] = BoundedTTLCache(2, 10 * 60, max_bytes=32 * 1024 * 1024)
        # The prepared input contains large NumPy arrays for the whole board.
        # A 2 GB machine should never retain multiple historical cutoffs.
        self._industry_strength_input_cache: BoundedTTLCache[
            tuple, dict[str, Any]
        ] = BoundedTTLCache(1, 10 * 60, max_bytes=192 * 1024 * 1024)
        self._industry_strength_inflight: dict[tuple, threading.Event] = {}
        self._industry_strength_lock = threading.RLock()
        # Full-market screening and industry strength both build large temporary
        # frames. Serializing them prevents two peaks from overlapping.
        self._heavy_compute_lock = threading.Lock()

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

    @staticmethod
    def _template_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("template name is required")
        if len(name) > 80:
            raise ValueError("template name cannot exceed 80 characters")
        return name

    @staticmethod
    def _template_date(value: Any, label: str) -> str:
        raw = str(value or "").strip().replace("-", "")
        if len(raw) != 8 or not raw.isdigit():
            raise ValueError(f"{label} must use YYYYMMDD")
        datetime.strptime(raw, "%Y%m%d")
        return raw

    @staticmethod
    def _template_public(
        item: dict[str, Any], *, include_bars: bool = False
    ) -> dict[str, Any]:
        hidden = {"z_values"}
        if not include_bars:
            hidden.add("bars")
        return {
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key not in hidden
        }

    @staticmethod
    def _source_bars(frame: pd.DataFrame) -> list[dict[str, Any]]:
        rows = []
        for row in frame.sort_values("trade_date").itertuples(index=False):
            date = str(row.trade_date)
            rows.append(
                {
                    "trade_date": date,
                    "time": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                    "open": float(row.qfq_open),
                    "high": float(row.qfq_high),
                    "low": float(row.qfq_low),
                    "close": float(row.qfq_close),
                }
            )
        return rows

    @staticmethod
    def _normalized_curve(bars: list[dict[str, Any]]) -> list[float]:
        if not bars:
            return []
        first = float(bars[0]["close"])
        if first <= 0:
            return []
        return [float(row["close"]) / first * 100.0 for row in bars]

    def _load_source_window(
        self,
        source_ts_code: str,
        start_date: str,
        end_date: str,
        expected_bars: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[float]]:
        frame = self.repository.recent_qfq_daily(
            start_date, end_date, {source_ts_code}
        )
        frame = (
            frame[frame["ts_code"].astype(str).eq(source_ts_code)]
            .sort_values("trade_date")
            .drop_duplicates("trade_date", keep="last")
        )
        if frame.empty:
            raise ValueError("template source window has no local qfq bars")
        if (
            str(frame.iloc[0]["trade_date"]) != start_date
            or str(frame.iloc[-1]["trade_date"]) != end_date
        ):
            raise ValueError(
                "template start_date and end_date must both be actual trading dates"
            )
        if expected_bars is not None and len(frame) != expected_bars:
            raise RuntimeError(
                f"frozen template expects {expected_bars} bars; found {len(frame)}"
            )
        if expected_bars is None and not 20 <= len(frame) <= 240:
            raise ValueError("custom template window must contain 20 to 240 trading days")
        vector = z_log_close(frame["qfq_close"].to_numpy(dtype=float)).tolist()
        return self._source_bars(frame), vector

    def _materialize_frozen_template(
        self, definition: FrozenTemplate
    ) -> dict[str, Any]:
        snapshots = self.repository.snapshots()
        precomputed_path = (
            self.settings.project_root
            / "public"
            / "template-definitions"
            / f"{definition.key}.json"
        )
        precomputed_token = (
            precomputed_path.stat().st_mtime_ns
            if precomputed_path.is_file()
            else None
        )
        key = (
            definition.key,
            snapshots.daily_kline,
            snapshots.adj_factor,
            precomputed_token,
        )
        with self._similarity_lock:
            cached = self._materialized_frozen_templates.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
        bars: list[dict[str, Any]] | None = None
        vector: list[float] | None = None
        precomputed_data_as_of: str | None = None
        if precomputed_token is not None:
            try:
                payload = json.loads(precomputed_path.read_text(encoding="utf-8"))
                metadata = payload.get("template", {})
                raw_bars = payload.get("bars", [])
                valid = (
                    payload.get("algorithm") == SIMILARITY_ALGORITHM
                    and metadata.get("id") == definition.key
                    and metadata.get("source_ts_code")
                    == definition.source_ts_code
                    and metadata.get("start_date") == definition.start_date
                    and metadata.get("end_date") == definition.end_date
                    and int(metadata.get("window_bars", 0))
                    == definition.window_bars
                    and len(raw_bars) == definition.window_bars
                    and str(raw_bars[0].get("trade_date", ""))
                    == definition.start_date
                    and str(raw_bars[-1].get("trade_date", ""))
                    == definition.end_date
                )
                if valid:
                    dates = [
                        str(row.get("trade_date", ""))
                        for row in raw_bars
                    ]
                    valid = (
                        dates == sorted(set(dates))
                        and all(re.fullmatch(r"\d{8}", value) for value in dates)
                    )
                if valid:
                    for row in raw_bars:
                        open_price = float(row["open"])
                        high_price = float(row["high"])
                        low_price = float(row["low"])
                        close_price = float(row["close"])
                        if not (
                            np.isfinite(
                                [open_price, high_price, low_price, close_price]
                            ).all()
                            and 0 < low_price
                            and low_price <= min(open_price, close_price)
                            and high_price >= max(open_price, close_price)
                        ):
                            valid = False
                            break
                if valid:
                    closes = [float(row["close"]) for row in raw_bars]
                    vector = z_log_close(closes).tolist()
                    bars = [
                        {
                            "trade_date": str(row["trade_date"]),
                            "time": str(row["time"]),
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row.get("volume", 0)),
                        }
                        for row in raw_bars
                    ]
                    precomputed_data_as_of = str(
                        payload.get("data_as_of", "")
                    )
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                bars = None
                vector = None
        if bars is None or vector is None:
            bars, vector = self._load_source_window(
                definition.source_ts_code,
                definition.start_date,
                definition.end_date,
                definition.window_bars,
            )
        item = {
            **definition.public_dict(),
            "name": definition.label,
            "bars": bars,
            "curve": self._normalized_curve(bars),
            "z_values": vector,
            "data_as_of": (
                precomputed_data_as_of
                or snapshots.adj_factor
                or definition.end_date
            ),
        }
        with self._similarity_lock:
            self._materialized_frozen_templates[key] = copy.deepcopy(item)
        return item

    def _template_record(self, template_id: str) -> dict[str, Any]:
        resolved = str(template_id or "").strip()
        frozen = self._frozen_templates_by_id.get(resolved)
        if frozen is not None:
            return self._materialize_frozen_template(frozen)
        custom = self.state_store.similarity_template(resolved)
        if custom is None:
            raise LookupError(f"template not found: {resolved}")
        custom["algorithm"] = SIMILARITY_ALGORITHM
        custom["curve"] = self._normalized_curve(custom["bars"])
        return custom

    def _precomputed_template_scores(
        self, template: dict[str, Any], as_of: str
    ) -> tuple[pd.DataFrame, int, str] | None:
        template_id = str(template["id"])
        if template_id not in self._frozen_templates_by_id:
            return None
        project_root = getattr(getattr(self, "settings", None), "project_root", None)
        if project_root is None:
            project_root = self.settings.project_root if hasattr(self, "settings") else None
        if project_root is None:
            return None
        candidates = [
            project_root / "public" / "template-rankings" / f"{template_id}.json",
            project_root / "public" / "template-breadth-v3.json",
        ]
        cache = getattr(self, "_precomputed_similarity_cache", {})
        for path in candidates:
            if not path.exists():
                continue
            token = path.stat().st_mtime_ns
            cache_key = (str(path), token, template_id, as_of)
            cached = cache.get(cache_key)
            if cached is not None:
                frame, total, source = cached
                return frame.copy(), total, source
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if path.name == "template-breadth-v3.json":
                payload_as_of = str(payload.get("asOf", payload.get("as_of", "")))
                template_payload = next(
                    (
                        item
                        for item in payload.get("templates", [])
                        if str(item.get("key", item.get("id", ""))) == template_id
                    ),
                    None,
                )
                if template_payload is None:
                    continue
                raw_items = template_payload.get("top100", [])
                summary = template_payload.get("summary", {})
                total = int(
                    summary.get(
                        "eligibleCount",
                        summary.get("eligible_count", len(raw_items)),
                    )
                )
            else:
                payload_as_of = str(payload.get("as_of", payload.get("asOf", "")))
                if str(payload.get("template_id", "")) != template_id:
                    continue
                metadata = payload.get("template", {})
                if (
                    payload.get("algorithm") != SIMILARITY_ALGORITHM
                    or str(metadata.get("source_ts_code", ""))
                    != str(template.get("source_ts_code", ""))
                    or str(metadata.get("start_date", ""))
                    != str(template.get("start_date", ""))
                    or str(metadata.get("end_date", ""))
                    != str(template.get("end_date", ""))
                    or int(metadata.get("window_bars", 0))
                    != int(template["window_bars"])
                ):
                    continue
                raw_items = payload.get("items", [])
                total = int(
                    payload.get(
                        "total_eligible",
                        payload.get("totalEligible", len(raw_items)),
                    )
                )
            if payload_as_of.replace("-", "") != as_of or len(raw_items) < 100:
                continue
            rows = []
            for index, raw in enumerate(raw_items[:100], 1):
                start_date = str(
                    raw.get("start_date", raw.get("window_start", ""))
                ).replace("-", "")
                end_date = str(
                    raw.get("end_date", raw.get("window_end", ""))
                ).replace("-", "")
                if len(start_date) != 8 or len(end_date) != 8:
                    rows = []
                    break
                ts_code = str(raw.get("ts_code", ""))
                rank = int(raw.get("rank", index))
                window_bars = int(
                    raw.get("window_bars", template["window_bars"])
                )
                score = float(raw["score"])
                if (
                    rank != index
                    or not ts_code
                    or end_date != as_of
                    or window_bars != int(template["window_bars"])
                    or not np.isfinite(score)
                ):
                    rows = []
                    break
                rows.append(
                    {
                        "rank": rank,
                        "ts_code": ts_code,
                        "code": str(raw.get("code", ts_code.split(".")[0])),
                        "name": str(raw.get("name", ts_code)),
                        "industry": str(
                            raw.get("industry", raw.get("industry_name", ""))
                        ),
                        "score": score,
                        "start_date": start_date,
                        "end_date": end_date,
                        "window_bars": window_bars,
                    }
                )
            if (
                len(rows) != 100
                or len({row["ts_code"] for row in rows}) != 100
                or any(
                    rows[index]["score"] < rows[index + 1]["score"]
                    for index in range(len(rows) - 1)
                )
            ):
                continue
            frame = pd.DataFrame(rows).sort_values("rank").reset_index(drop=True)
            source = str(path.relative_to(project_root)).replace("\\", "/")
            cache[cache_key] = (frame.copy(), total, source)
            while len(cache) > 12:
                cache.pop(next(iter(cache)))
            self._precomputed_similarity_cache = cache
            return frame, total, source
        return None

    def templates(self) -> dict[str, Any]:
        frozen = [
            {**item.public_dict(), "name": item.label}
            for item in self.frozen_templates
        ]
        custom = []
        for item in self.state_store.list_similarity_templates():
            item["algorithm"] = SIMILARITY_ALGORITHM
            item["curve"] = self._normalized_curve(item["bars"])
            custom.append(self._template_public(item))
        return {
            "algorithm": SIMILARITY_ALGORITHM,
            "items": [*frozen, *custom],
            "frozen_count": len(frozen),
            "custom_count": len(custom),
        }

    def template(self, template_id: str) -> dict[str, Any]:
        return self._template_public(
            self._template_record(template_id), include_bars=True
        )

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = self._template_name(payload.get("name", payload.get("label")))
        raw_code = str(
            payload.get(
                "source_ts_code",
                payload.get("ts_code", payload.get("code", "")),
            )
        ).strip()
        source_ts_code = self.repository.resolve_code(raw_code)
        if source_ts_code is None:
            raise LookupError(f"stock not found: {raw_code}")
        start_date = self._template_date(payload.get("start_date"), "start_date")
        end_date = self._template_date(payload.get("end_date"), "end_date")
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        bars, vector = self._load_source_window(
            source_ts_code, start_date, end_date
        )
        snapshots = self.repository.snapshots()
        item = self.state_store.create_similarity_template(
            name=name,
            source_ts_code=source_ts_code,
            start_date=start_date,
            end_date=end_date,
            bars=bars,
            z_values=vector,
            data_as_of=snapshots.adj_factor or end_date,
        )
        item["algorithm"] = SIMILARITY_ALGORITHM
        item["curve"] = self._normalized_curve(item["bars"])
        return self._template_public(item, include_bars=True)

    def rename_template(
        self, template_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if template_id in self._frozen_templates_by_id:
            raise ValueError("frozen templates are read-only")
        name = self._template_name(payload.get("name", payload.get("label")))
        item = self.state_store.rename_similarity_template(template_id, name)
        if item is None:
            raise LookupError(f"template not found: {template_id}")
        item["algorithm"] = SIMILARITY_ALGORITHM
        item["curve"] = self._normalized_curve(item["bars"])
        # Renaming does not alter the selected window or its similarity signature.
        # Keep the response lightweight and leave the score cache intact.
        return self._template_public(item)

    def delete_template(self, template_id: str) -> dict[str, Any]:
        if template_id in self._frozen_templates_by_id:
            raise ValueError("frozen templates are read-only")
        if not self.state_store.delete_similarity_template(template_id):
            raise LookupError(f"template not found: {template_id}")
        with self._similarity_lock:
            self._similarity_score_cache = {
                key: value
                for key, value in self._similarity_score_cache.items()
                if key[0] != template_id
            }
        return {"deleted": True, "id": template_id}

    def template_stocks(
        self,
        template_id: str,
        limit: Any = 100,
        include_bars: Any = True,
    ) -> dict[str, Any]:
        request_started = time.perf_counter()
        parsed_limit = self._positive_integer(limit, "limit")
        if parsed_limit > 100:
            raise ValueError("limit cannot exceed the product Top100")
        if isinstance(include_bars, str):
            include_candidate_bars = include_bars.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            include_candidate_bars = bool(include_bars)
        resolved_template_id = str(template_id or "").strip()
        frozen_definition = self._frozen_templates_by_id.get(resolved_template_id)
        template = (
            {**frozen_definition.public_dict(), "name": frozen_definition.label}
            if frozen_definition is not None
            else self._template_record(resolved_template_id)
        )
        snapshots = self.repository.snapshots()
        available_dates = [
            value
            for value in (snapshots.daily_kline, snapshots.adj_factor)
            if value
        ]
        if not available_dates:
            raise FileNotFoundError("daily_kline data not found")
        # Similarity ranking uses forward-adjusted prices, so it must stop at the
        # latest date shared by both daily bars and adjustment factors. Daily
        # data can arrive one session earlier than factors during a sync.
        as_of = min(available_dates)
        ranking_started = time.perf_counter()
        ranking_cache_hit = False
        ranking_source = "computed"
        total_eligible: int | None = None
        precomputed = self._precomputed_template_scores(template, as_of)
        scores: pd.DataFrame | None = None
        vector: list[float] = []
        cache_key: tuple[Any, ...] | None = None
        if precomputed is not None:
            scores, total_eligible, ranking_source = precomputed
            ranking_cache_hit = True
        else:
            if frozen_definition is not None:
                template = self._materialize_frozen_template(frozen_definition)
            vector = [float(value) for value in template["z_values"]]
            signature = hashlib.sha256(
                np.asarray(vector, dtype=np.float64).tobytes()
            ).hexdigest()
            cache_key = (
                str(template["id"]),
                signature,
                as_of,
                snapshots.adj_factor,
            )
            with self._similarity_lock:
                scores = self._similarity_score_cache.get(cache_key)
            if scores is not None:
                ranking_cache_hit = True
        if scores is None:
            start = (
                datetime.strptime(as_of, "%Y%m%d") - timedelta(days=400)
            ).strftime("%Y%m%d")
            active = self.repository.basic()
            active_codes = set(active["ts_code"].astype(str))
            qfq = self.repository.recent_qfq_daily(start, as_of, active_codes)
            scores = score_latest_cross_section(
                qfq,
                template_z=vector,
                window_bars=int(template["window_bars"]),
                as_of=as_of,
            )
            with self._similarity_lock:
                if len(self._similarity_score_cache) >= 12:
                    self._similarity_score_cache.pop(
                        next(iter(self._similarity_score_cache))
                    )
                assert cache_key is not None
                self._similarity_score_cache[cache_key] = scores.copy()
        ranking_ms = (time.perf_counter() - ranking_started) * 1000
        has_public_metadata = {
            "code",
            "name",
            "industry",
        }.issubset(scores.columns)
        names: dict[str, str] = {}
        symbols: dict[str, str] = {}
        industry_map: dict[str, str] = {}
        if not has_public_metadata:
            active = self.repository.basic()
            names = active.set_index("ts_code")["name"].astype(str).to_dict()
            symbols = active.set_index("ts_code")["symbol"].astype(str).to_dict()
            industries = self.repository.industries()
            industry_map = (
                industries.drop_duplicates("ts_code")
                .set_index("ts_code")["l1_name"]
                .fillna("")
                .astype(str)
                .to_dict()
            )
        selected_scores = scores.head(parsed_limit)
        selected_codes = set(selected_scores["ts_code"].astype(str))
        candidate_bars_started = time.perf_counter()
        candidate_bars = (
            self.repository.recent_qfq_daily(
                str(selected_scores["start_date"].min()),
                str(selected_scores["end_date"].max()),
                selected_codes,
            )
            if include_candidate_bars and selected_codes
            else pd.DataFrame()
        )
        candidate_bars_ms = (time.perf_counter() - candidate_bars_started) * 1000
        items = []
        for rank, row in enumerate(selected_scores.itertuples(index=False), 1):
            code = str(row.ts_code)
            window_frame = (
                candidate_bars[
                    candidate_bars["ts_code"].astype(str).eq(code)
                    & candidate_bars["trade_date"].astype(str).between(
                        str(row.start_date), str(row.end_date)
                    )
                ]
                if not candidate_bars.empty
                else candidate_bars
            )
            items.append(
                {
                    "template_id": str(template["id"]),
                    "rank": int(getattr(row, "rank", rank)),
                    "ts_code": code,
                    "code": str(
                        getattr(row, "code", "")
                        or symbols.get(code, code.split(".")[0])
                    ),
                    "name": str(
                        getattr(row, "name", "") or names.get(code, code)
                    ),
                    "industry": str(
                        getattr(row, "industry", "")
                        or industry_map.get(code, "")
                    ),
                    "score": float(row.score),
                    "start_date": str(row.start_date),
                    "end_date": str(row.end_date),
                    "window_bars": int(row.window_bars),
                    **(
                        {"bars": self._source_bars(window_frame)}
                        if include_candidate_bars
                        else {}
                    ),
                }
            )
        total = total_eligible if total_eligible is not None else len(scores)
        return {
            "template": self._template_public(template),
            "items": items,
            "total": total,
            "total_eligible": total,
            "limit": parsed_limit,
            "as_of": as_of,
            "algorithm": SIMILARITY_ALGORITHM,
            "threshold_used": None,
            "ranking_scope": "within_template_only",
            "ranking_source": ranking_source,
            "cache_hit": ranking_cache_hit,
            "payload_mode": "with_candidate_bars"
            if include_candidate_bars
            else "ranking_metadata",
            "timings": {
                "ranking_ms": round(ranking_ms, 1),
                "candidate_bars_ms": round(candidate_bars_ms, 1),
                "total_ms": round(
                    (time.perf_counter() - request_started) * 1000, 1
                ),
            },
        }

    def industry_strength(
        self, pattern: str, end_date: str | None = None
    ) -> dict[str, Any]:
        request_started = time.perf_counter()
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
        source_token = self._industry_strength_source_token(snapshots)
        cache_key = (source_token, threshold_mtime, pattern, requested, cutoff)
        lock = getattr(self, "_industry_strength_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._industry_strength_lock = lock
        with lock:
            cache = getattr(self, "_industry_strength_cache", {})
            cached = cache.get(cache_key)
            if cached is not None:
                payload = copy.deepcopy(cached)
                payload["cache_hit"] = True
                payload["timings"] = {
                    "prepare_ms": 0.0,
                    "scoring_ms": 0.0,
                    "assembly_ms": 0.0,
                    "total_ms": round(
                        (time.perf_counter() - request_started) * 1000, 1
                    ),
                }
                return payload
            inflight = getattr(self, "_industry_strength_inflight", {})
            event = inflight.get(cache_key)
            owns_request = event is None
            if event is None:
                event = threading.Event()
                inflight[cache_key] = event
                self._industry_strength_inflight = inflight
        if not owns_request:
            event.wait()
            with lock:
                cached = getattr(self, "_industry_strength_cache", {}).get(cache_key)
            if cached is not None:
                payload = copy.deepcopy(cached)
                payload["cache_hit"] = True
                payload["timings"] = {
                    "prepare_ms": 0.0,
                    "scoring_ms": 0.0,
                    "assembly_ms": 0.0,
                    "total_ms": round(
                        (time.perf_counter() - request_started) * 1000, 1
                    ),
                }
                return payload
            return self.industry_strength(pattern, requested)

        try:
            heavy_lock = getattr(self, "_heavy_compute_lock", None)
            if heavy_lock is None:
                heavy_lock = threading.Lock()
                self._heavy_compute_lock = heavy_lock
            with heavy_lock:
                payload = self._calculate_industry_strength(
                    pattern=pattern,
                    requested=requested,
                    cutoff=cutoff,
                    snapshots=snapshots,
                    source_token=source_token,
                    request_started=request_started,
                )
            with lock:
                cache = getattr(self, "_industry_strength_cache", {})
                cache[cache_key] = copy.deepcopy(payload)
                while len(cache) > 2:
                    cache.pop(next(iter(cache)))
                self._industry_strength_cache = cache
            return payload
        finally:
            with lock:
                pending = getattr(self, "_industry_strength_inflight", {})
                pending.pop(cache_key, None)
                event.set()

    def _industry_strength_source_token(self, snapshots) -> tuple:
        def token(path) -> int | None:
            return path.stat().st_mtime_ns if path.is_file() else None

        daily = (
            self.repository.data_dir
            / "stock"
            / "daily_kline"
            / f"date={snapshots.daily_kline}"
            / "data.parquet"
        )
        st = (
            self.repository.data_dir
            / "stock"
            / "stock_st"
            / f"date={snapshots.stock_st}"
            / "data.parquet"
        )
        basic = self.repository.data_dir / "stock" / "basic" / "data.parquet"
        industry = (
            self.repository.data_dir
            / "stock"
            / "industry"
            / "sw_member"
            / "data.parquet"
        )
        return (
            snapshots.daily_kline,
            token(daily),
            snapshots.stock_st,
            token(st),
            token(basic),
            token(industry),
        )

    def _prepare_industry_strength_inputs(
        self, cutoff: str, snapshots, source_token: tuple
    ) -> dict[str, Any]:
        cache_key = (source_token, cutoff)
        lock = self._industry_strength_lock
        with lock:
            cached = getattr(self, "_industry_strength_input_cache", {}).get(cache_key)
        if cached is not None:
            return cached

        trade_dates = self.repository.trading_dates(cutoff, 240)
        sample_dates = fixed_sample_dates(trade_dates)
        if not sample_dates:
            raise ValueError("截止日期之前没有足够的真实交易日")
        query_start = trade_dates[0]
        daily = self.repository.recent_daily(
            query_start, sample_dates[-1], cache=False
        )
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

        grouped = []
        for code, frame in daily.groupby("ts_code", sort=False):
            dates = frame["trade_date"].astype(str).tolist()
            matrix = frame[["close", "high", "low", "vol"]].to_numpy(dtype=float)
            close, high, low, volume = matrix.T
            grouped.append(
                (
                    str(code),
                    dates,
                    close,
                    high,
                    low,
                    np.nan_to_num(volume, nan=0.0),
                )
            )
        prepared = {
            "trade_date_count": len(trade_dates),
            "sample_dates": sample_dates,
            "industries": industries,
            "contexts": contexts,
            "grouped": grouped,
            "names": names,
        }
        with lock:
            cache = getattr(self, "_industry_strength_input_cache", {})
            cache[cache_key] = prepared
            while len(cache) > 1:
                cache.pop(next(iter(cache)))
            self._industry_strength_input_cache = cache
        return prepared

    def _calculate_industry_strength(
        self,
        *,
        pattern: str,
        requested: str | None,
        cutoff: str,
        snapshots,
        source_token: tuple,
        request_started: float,
    ) -> dict[str, Any]:
        prepare_started = time.perf_counter()
        prepared = self._prepare_industry_strength_inputs(
            cutoff, snapshots, source_token
        )
        prepare_ms = (time.perf_counter() - prepare_started) * 1000
        sample_dates = prepared["sample_dates"]
        contexts = prepared["contexts"]
        names = prepared["names"]
        grouped = prepared["grouped"]
        top_by_date: dict[str, list[dict[str, Any]]] = {
            date: [] for date in sample_dates
        }

        def score_code(
            pair: tuple[str, list[str], np.ndarray, np.ndarray, np.ndarray, np.ndarray]
        ) -> list[tuple[str, dict[str, Any]]]:
            code, dates, close, high, low, volume = pair
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

        scoring_started = time.perf_counter()
        with ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="industry-strength"
        ) as pool:
            for stock_matches in pool.map(score_code, grouped, chunksize=8):
                for date, item in stock_matches:
                    top_by_date[date].append(item)

        for date in sample_dates:
            top_by_date[date].sort(
                key=lambda item: (-float(item["score"]), str(item["ts_code"]))
            )
            top_by_date[date] = top_by_date[date][:TOP_N]
        scoring_ms = (time.perf_counter() - scoring_started) * 1000

        assembly_started = time.perf_counter()
        warnings: list[str] = []
        if prepared["trade_date_count"] < LOOKBACK_TRADING_DAYS:
            warnings.append(
                f"截止日期前仅有 {prepared['trade_date_count']} 个可用交易日。"
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
            industries=prepared["industries"],
            top_by_date=top_by_date,
            warnings=warnings,
        )
        assembly_ms = (time.perf_counter() - assembly_started) * 1000
        payload["cache_hit"] = False
        total_ms = (time.perf_counter() - request_started) * 1000
        payload["elapsed_ms"] = round(total_ms, 1)
        payload["timings"] = {
            "prepare_ms": round(prepare_ms, 1),
            "scoring_ms": round(scoring_ms, 1),
            "assembly_ms": round(assembly_ms, 1),
            "total_ms": round(total_ms, 1),
        }
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
            heavy_lock = getattr(self, "_heavy_compute_lock", None)
            if heavy_lock is None:
                heavy_lock = threading.Lock()
                self._heavy_compute_lock = heavy_lock
            with heavy_lock:
                payload = self._run_screen(filters, snapshots, notify)
            with self._screen_lock:
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
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-ref") as pool:
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
        recent = self.repository.recent_daily(
            start, snapshots.daily_kline, cache=False
        )
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
                ) > 10 * 60:
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
