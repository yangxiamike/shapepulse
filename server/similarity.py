from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ALGORITHM = "qfq_log_close_independent_z_single_window_pearson"


@dataclass(frozen=True)
class FrozenTemplate:
    key: str
    label: str
    source_ts_code: str
    start_date: str
    end_date: str
    window_bars: int

    def public_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "id": self.key,
            "source": "frozen",
            "kind": "frozen",
            "read_only": True,
            "algorithm": ALGORITHM,
        }


def load_frozen_templates(path: Path) -> tuple[FrozenTemplate, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("algorithm") != ALGORITHM:
        raise ValueError("frozen template algorithm does not match runtime")
    rows = payload.get("templates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("frozen template registry is empty")
    templates = tuple(
        FrozenTemplate(
            key=str(row["key"]),
            label=str(row["label"]),
            source_ts_code=str(row["source_ts_code"]),
            start_date=str(row["start_date"]),
            end_date=str(row["end_date"]),
            window_bars=int(row["window_bars"]),
        )
        for row in rows
    )
    keys = [item.key for item in templates]
    if len(keys) != len(set(keys)):
        raise ValueError("frozen template keys must be unique")
    for item in templates:
        if (
            len(item.start_date) != 8
            or not item.start_date.isdigit()
            or len(item.end_date) != 8
            or not item.end_date.isdigit()
            or item.start_date > item.end_date
            or item.window_bars < 2
        ):
            raise ValueError(f"invalid frozen template definition: {item.key}")
    return templates


def z_log_close(values: Iterable[float]) -> np.ndarray:
    close = np.asarray(list(values), dtype=float)
    if close.ndim != 1 or len(close) < 2:
        raise ValueError("template window needs at least two closes")
    if not np.isfinite(close).all() or np.any(close <= 0):
        raise ValueError("close values must be finite and positive")
    logged = np.log(close)
    standard_deviation = float(logged.std())
    if standard_deviation <= 1e-12:
        raise ValueError("template window has no usable price variation")
    return (logged - logged.mean()) / standard_deviation


def pearson_similarity(values: Iterable[float], template_z: Iterable[float]) -> float:
    template = np.asarray(list(template_z), dtype=float)
    candidate = z_log_close(values)
    if candidate.shape != template.shape:
        raise ValueError("candidate and template windows must have equal length")
    if not np.isfinite(template).all():
        raise ValueError("template z vector contains non-finite values")
    score = float(np.mean(candidate * template))
    if not math.isfinite(score) or score < -1.00000001 or score > 1.00000001:
        raise ValueError("Pearson similarity is outside [-1, 1]")
    return max(-1.0, min(1.0, score))


def score_latest_cross_section(
    qfq_daily: pd.DataFrame,
    *,
    template_z: Iterable[float],
    window_bars: int,
    as_of: str,
) -> pd.DataFrame:
    required = {"ts_code", "trade_date", "qfq_close"}
    missing = required.difference(qfq_daily.columns)
    if missing:
        raise ValueError(f"qfq daily data is missing: {', '.join(sorted(missing))}")
    vector = np.asarray(list(template_z), dtype=float)
    if len(vector) != int(window_bars):
        raise ValueError("template vector length differs from window_bars")
    rows: list[dict[str, Any]] = []
    for code, frame in qfq_daily.groupby("ts_code", sort=False):
        ordered = (
            frame.sort_values("trade_date")
            .drop_duplicates("trade_date", keep="last")
            .tail(int(window_bars))
        )
        if len(ordered) != int(window_bars):
            continue
        if str(ordered.iloc[-1]["trade_date"]) != str(as_of):
            continue
        closes = ordered["qfq_close"].to_numpy(dtype=float)
        try:
            score = pearson_similarity(closes, vector)
        except ValueError:
            continue
        rows.append(
            {
                "ts_code": str(code),
                "score": score,
                "start_date": str(ordered.iloc[0]["trade_date"]),
                "end_date": str(as_of),
                "window_bars": int(window_bars),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=["ts_code", "score", "start_date", "end_date", "window_bars"]
        )
    return pd.DataFrame(rows).sort_values(
        ["score", "ts_code"], ascending=[False, True]
    ).reset_index(drop=True)
