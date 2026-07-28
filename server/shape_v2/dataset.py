from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np
import pandas as pd

from . import CATEGORY_KEYS, RESEARCH_SPLITS, SCHEMA_VERSION
from .facts import extract_shared_facts


FORBIDDEN_PUBLIC_KEYS = {
    "code",
    "ts_code",
    "symbol",
    "name",
    "industry",
    "industry_code",
    "industry_name",
    "trade_date",
    "score_date",
    "requested_score_date",
    "resolved_score_date",
    "future",
    "future_return",
    "forward_return",
}


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def anonymous_id(secret: bytes, dataset_version: str, ts_code: str, score_date: str) -> str:
    raw = f"{dataset_version}|{ts_code}|{score_date}".encode("utf-8")
    digest = hmac.new(secret, raw, hashlib.sha256).hexdigest()[:12].upper()
    return f"S-{digest}"


def source_group_id(secret: bytes, ts_code: str) -> str:
    digest = hmac.new(secret, f"group|{ts_code}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"G-{digest[:16].upper()}"


def assign_research_split(group_id: str, weights: dict[str, float]) -> str:
    if tuple(weights) != RESEARCH_SPLITS:
        raise ValueError(f"split weights must be ordered as {RESEARCH_SPLITS}")
    total = float(sum(weights.values()))
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError("split weights must sum to 1")
    position = int(hashlib.sha256(group_id.encode("utf-8")).hexdigest(), 16) / (2**256)
    cumulative = 0.0
    for split, weight in weights.items():
        cumulative += float(weight)
        if position < cumulative:
            return split
    return RESEARCH_SPLITS[-1]


def assign_grouped_splits(
    group_ids: Iterable[str], weights: dict[str, float]
) -> dict[str, str]:
    """Assign whole groups while keeping small datasets close to target proportions."""
    if tuple(weights) != RESEARCH_SPLITS:
        raise ValueError(f"split weights must be ordered as {RESEARCH_SPLITS}")
    total_weight = float(sum(weights.values()))
    if not math.isclose(total_weight, 1.0, abs_tol=1e-9):
        raise ValueError("split weights must sum to 1")
    groups = sorted(
        {str(group_id) for group_id in group_ids},
        key=lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )
    raw_counts = {split: len(groups) * float(weight) for split, weight in weights.items()}
    counts = {split: int(math.floor(value)) for split, value in raw_counts.items()}
    remainder = len(groups) - sum(counts.values())
    remainder_order = sorted(
        RESEARCH_SPLITS,
        key=lambda split: (-(raw_counts[split] - counts[split]), RESEARCH_SPLITS.index(split)),
    )
    for split in remainder_order[:remainder]:
        counts[split] += 1
    assignments: dict[str, str] = {}
    cursor = 0
    for split in RESEARCH_SPLITS:
        for group_id in groups[cursor : cursor + counts[split]]:
            assignments[group_id] = split
        cursor += counts[split]
    return assignments


def _clean_window(
    frame: pd.DataFrame, score_date: str, window_bars: int
) -> tuple[pd.DataFrame, list[str]]:
    required = {"trade_date", "open", "high", "low", "close", "vol", "adj_factor"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"source frame is missing columns: {', '.join(sorted(missing))}")
    work = frame.copy()
    work["trade_date"] = (
        work["trade_date"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
    )
    work = work[
        work["trade_date"].str.fullmatch(r"\d{8}", na=False)
        & work["trade_date"].le(str(score_date))
    ]
    for column in ("open", "high", "low", "close", "vol", "adj_factor"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = (
        work.sort_values("trade_date")
        .drop_duplicates("trade_date", keep="last")
        .tail(window_bars)
        .reset_index(drop=True)
    )
    if len(work) != window_bars:
        raise ValueError(f"sample requires exactly {window_bars} past bars; found {len(work)}")
    work = work.dropna(subset=["open", "high", "low", "close"])
    if len(work) != window_bars or not (work[["open", "high", "low", "close"]] > 0).all().all():
        raise ValueError("sample contains missing or non-positive OHLC values")
    if work["adj_factor"].notna().sum() == 0:
        raise ValueError("sample has no local adjustment factor")
    work["adj_factor"] = work["adj_factor"].ffill().bfill()
    if work["adj_factor"].isna().any() or not (work["adj_factor"] > 0).all():
        raise ValueError("sample adjustment factor cannot be completed safely")
    anchor_factor = float(work["adj_factor"].iloc[-1])
    multiplier = work["adj_factor"] / anchor_factor
    for column in ("open", "high", "low", "close"):
        work[column] = work[column] * multiplier
    work["high"] = work[["open", "high", "low", "close"]].max(axis=1)
    work["low"] = work[["open", "high", "low", "close"]].min(axis=1)
    work["vol"] = work["vol"].fillna(0).clip(lower=0)
    dates = work["trade_date"].astype(str).tolist()
    return work, dates


def build_public_bars(
    frame: pd.DataFrame, score_date: str, window_bars: int = 120, price_anchor: float = 100.0
) -> tuple[list[dict[str, float | int]], dict[str, Any]]:
    """Censor at score_date, adjust only with factors known by then, and anonymize axes."""
    work, source_dates = _clean_window(frame, score_date, window_bars)
    first_close = float(work["close"].iloc[0])
    price_multiplier = price_anchor / first_close
    nonzero_volume = work.loc[work["vol"] > 0, "vol"].to_numpy(dtype=float)
    volume_anchor = float(np.median(nonzero_volume)) if len(nonzero_volume) else 1.0
    bars: list[dict[str, float | int]] = []
    for index, row in work.iterrows():
        bars.append(
            {
                "t": int(index - (window_bars - 1)),
                "open": round(float(row["open"]) * price_multiplier, 6),
                "high": round(float(row["high"]) * price_multiplier, 6),
                "low": round(float(row["low"]) * price_multiplier, 6),
                "close": round(float(row["close"]) * price_multiplier, 6),
                "volume": round(float(row["vol"]) / volume_anchor, 6),
            }
        )
    private = {
        "source_trade_dates": source_dates,
        "resolved_score_date": source_dates[-1],
        "price_anchor_raw": first_close,
        "volume_anchor_raw": volume_anchor,
    }
    return bars, private


def build_public_sample(
    sample_id: str,
    dataset_version: str,
    split: str,
    bars: list[dict[str, float | int]],
) -> dict[str, Any]:
    sample = {
        "schema_version": SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "sample_id": sample_id,
        "split": split,
        "bar_count": len(bars),
        "normalization": {
            "price": "first adjusted close = 100",
            "volume": "median nonzero volume = 1",
            "time": f"T-{len(bars) - 1} ... T0",
        },
        "bars": bars,
        "shared_facts": extract_shared_facts(bars),
    }
    validate_public_payload(sample)
    return sample


def blank_label_record(sample_id: str, dataset_version: str) -> dict[str, Any]:
    return {
        "schema_version": "shape-v2-labels/1",
        "dataset_version": dataset_version,
        "sample_id": sample_id,
        "reviewer_id": "",
        "ratings": {category: None for category in CATEGORY_KEYS},
        "core_contradictions": {category: [] for category in CATEGORY_KEYS},
        "note": "",
    }


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_public_payload(payload: dict[str, Any]) -> None:
    leaked = sorted({key for key in _walk_keys(payload) if key.lower() in FORBIDDEN_PUBLIC_KEYS})
    if leaked:
        raise ValueError(f"public payload contains identity/future fields: {', '.join(leaked)}")
    if payload.get("bar_count") != len(payload.get("bars", [])):
        raise ValueError("bar_count does not match bars")
    bars = payload.get("bars", [])
    if not bars or bars[-1].get("t") != 0:
        raise ValueError("public bars must end at anonymous scoring point T0")
    allowed_bar_keys = {"t", "open", "high", "low", "close", "volume"}
    if any(set(bar) != allowed_bar_keys for bar in bars):
        raise ValueError("public bar schema is not the approved anonymous OHLCV schema")


def validate_audit_manifest(audit: dict[str, Any]) -> list[str]:
    """Return leakage findings; an empty list means the audit passes."""
    findings: list[str] = []
    samples = list(audit.get("samples", []))
    group_splits: dict[str, set[str]] = defaultdict(set)
    security_splits: dict[str, set[str]] = defaultdict(set)
    seen_samples: set[str] = set()
    for item in samples:
        sample_id = str(item.get("sample_id", ""))
        if not sample_id or sample_id in seen_samples:
            findings.append(f"duplicate or empty sample_id: {sample_id!r}")
        seen_samples.add(sample_id)
        split = str(item.get("split", ""))
        group_splits[str(item.get("source_group_id", ""))].add(split)
        security_splits[str(item.get("ts_code", ""))].add(split)
        dates = [str(value) for value in item.get("source_trade_dates", [])]
        if not dates or dates != sorted(set(dates)):
            findings.append(f"{sample_id}: source dates are empty, duplicated, or unsorted")
        if dates and dates[-1] != str(item.get("resolved_score_date", "")):
            findings.append(f"{sample_id}: last visible bar differs from resolved score date")
        requested = str(item.get("requested_score_date", ""))
        if dates and requested and dates[-1] > requested:
            findings.append(f"{sample_id}: sample contains a bar after requested score date")
    for group_id, splits in group_splits.items():
        if len(splits) > 1:
            findings.append(f"group {group_id} crosses splits: {sorted(splits)}")
    for ts_code, splits in security_splits.items():
        if len(splits) > 1:
            findings.append(f"security {ts_code} crosses splits: {sorted(splits)}")
    return findings
