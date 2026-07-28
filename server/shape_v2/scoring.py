from __future__ import annotations

import math
from typing import Any

from . import CATEGORY_KEYS


CATEGORY_WEIGHT_PRIORS: dict[str, dict[str, float]] = {
    "fresh_breakout": {
        "breakout_age": 2.5,
        "breakout_hold_margin": 2.5,
        "breakout_current_margin": 2.0,
        "breakout_post_event_drawdown": 2.0,
        "breakout_confirmed": 2.5,
        "breakout_day_return": 1.0,
        "breakout_volume_ratio": 1.0,
        "breakout_approach_return_5": 1.0,
        "breakout_approach_positive_ratio_10": 1.0,
        "pre_breakout_volatility_20": 0.75,
        "largest_up_day_share_20": 0.75,
        "breakout_vs_prior_20": 2.0,
        "breakout_vs_prior_60": 1.25,
        "old_high_rejection_count": 0.75,
        "trend_slope_60": 1.0,
        "trend_fit_60": 0.75,
        "ma20_extension": 1.0,
    },
    "healthy_uptrend": {
        "return_20": 1.0,
        "return_60": 1.5,
        "return_119": 1.25,
        "trend_slope_20": 1.0,
        "trend_slope_60": 2.0,
        "trend_slope_120": 1.5,
        "trend_fit_20": 0.75,
        "trend_fit_60": 1.5,
        "trend_fit_120": 1.25,
        "ma20_extension": 0.75,
        "ma60_extension": 1.0,
        "ma_alignment": 1.5,
        "drawdown_60": 1.5,
        "drawdown_120": 1.25,
        "old_high_gap_120": 0.75,
        "days_since_old_high": 0.5,
        "old_high_rejection_count": 0.5,
        "range_staleness_60": 1.5,
    },
    "pullback_strengthening": {
        "prior_advance_before_peak": 2.0,
        "drawdown_20": 1.25,
        "drawdown_60": 1.75,
        "pullback_duration_60": 1.5,
        "pullback_speed_60": 1.5,
        "worst_5day_return_20": 1.0,
        "retracement_of_prior_advance": 1.75,
        "turn_confirmation": 2.5,
        "return_3": 1.0,
        "return_5": 1.0,
        "rebound_from_10_low": 1.25,
        "ma10_extension": 0.75,
        "ma20_extension": 0.75,
        "trend_slope_60": 1.25,
        "trend_fit_60": 0.75,
        "range_staleness_60": 1.5,
    },
}


def _cap(
    caps: list[dict[str, Any]], code: str, message: str, maximum: float
) -> None:
    caps.append({"code": code, "message": message, "maximum_score": maximum})


def _score_caps(category: str, facts: dict[str, float]) -> list[dict[str, Any]]:
    f = lambda key, default=0.0: float(facts.get(key, default))
    caps: list[dict[str, Any]] = []
    if category == "fresh_breakout":
        age = f("breakout_age", 99.0)
        if age >= 99:
            _cap(caps, "no_detectable_breakout", "未识别到近15根K线内的有效突破事件", 0.75)
        if age == 0:
            _cap(caps, "breakout_day_ceiling", "突破当天尚未经过持续性确认", 2.0)
        if age > 15:
            _cap(caps, "breakout_stale", "突破已经超出5至15根K线的校准观察期", 1.0)
        if f("breakout_hold_margin", -1.0) < -0.03:
            _cap(caps, "lost_breakout_level", "突破后明显跌回压力位下方", 0.75)
        if f("breakout_post_event_drawdown", 1.0) > 0.12:
            _cap(caps, "post_breakout_weakness", "突破后回撤过大，连续性被破坏", 0.75)
        if f("breakout_vs_prior_20") < -0.03 and f("breakout_vs_prior_60") < -0.05:
            _cap(caps, "no_meaningful_structure_break", "仍未打破清晰的20/60日局部结构", 1.0)
    elif category == "healthy_uptrend":
        if f("trend_slope_60") <= 0 and f("return_60") <= 0:
            _cap(caps, "non_rising_midterm_structure", "60日结构并未向上", 0.75)
        if f("drawdown_60") > 0.25:
            _cap(caps, "trend_drawdown_broken", "60日回撤过深，主要上升结构受损", 1.0)
        if f("range_staleness_60") > 0.85:
            _cap(caps, "stale_range", "走势已拖成缺乏方向的大区间", 1.0)
        if f("largest_up_day_share_20") > 0.65:
            _cap(caps, "single_spike_distortion", "近期上涨过度依赖单日尖峰", 1.25)
    elif category == "pullback_strengthening":
        if f("prior_advance_before_peak") < 0.08:
            _cap(caps, "no_prior_advance", "回调前缺少可辨认的上升基础", 0.75)
        if f("drawdown_60") > 0.30 or f("retracement_of_prior_advance") > 0.90:
            _cap(caps, "pullback_too_deep", "回撤已接近或超过此前上升段", 0.75)
        if f("pullback_duration_60") > 40:
            _cap(caps, "pullback_too_long", "回调持续过久，已接近区间化", 1.0)
        if f("turn_confirmation") < 0.25:
            _cap(caps, "no_turn_confirmation", "评分日附近尚无止跌或转强确认", 0.75)
        if f("worst_5day_return_20") < -0.18:
            _cap(caps, "pullback_too_fast", "近期出现深而快的回撤", 1.0)
    else:
        raise ValueError(f"unknown category: {category}")
    return caps


def score_category(
    facts: dict[str, float], category: str, model: dict[str, Any]
) -> dict[str, Any]:
    if category not in CATEGORY_KEYS:
        raise ValueError(f"unknown category: {category}")
    feature_keys = list(model["feature_keys"])
    missing = [key for key in feature_keys if key not in facts]
    if missing:
        raise ValueError(f"{category}: missing facts: {', '.join(missing)}")
    weighted_squared = 0.0
    total_weight = 0.0
    contributions: list[dict[str, float | str]] = []
    for key in feature_keys:
        stats = model["template"][key]
        weight = float(model["weights"][key])
        delta = (float(facts[key]) - float(stats["median"])) / float(stats["robust_scale"])
        contribution = weight * min(delta * delta, 64.0)
        weighted_squared += contribution
        total_weight += weight
        contributions.append(
            {
                "feature": key,
                "value": round(float(facts[key]), 8),
                "template_median": round(float(stats["median"]), 8),
                "standardized_delta": round(delta, 6),
                "weighted_distance": round(contribution, 6),
            }
        )
    distance = math.sqrt(weighted_squared / total_weight)
    distance_scale = max(float(model["distance_scale"]), 1e-6)
    raw_score = 3.0 * math.exp(-0.5 * (distance / distance_scale) ** 2)
    caps = _score_caps(category, facts)
    final_score = min([raw_score, *(float(item["maximum_score"]) for item in caps)])
    contributions.sort(key=lambda item: float(item["weighted_distance"]), reverse=True)
    return {
        "category": category,
        "score": round(max(0.0, min(3.0, final_score)), 6),
        "raw_score": round(max(0.0, min(3.0, raw_score)), 6),
        "distance": round(distance, 6),
        "confidence": str(model["confidence"]),
        "caps": caps,
        "largest_distance_contributors": contributions[:5],
    }


def score_all(facts: dict[str, float], summary: dict[str, Any]) -> dict[str, Any]:
    categories = summary.get("categories", {})
    if tuple(categories) != CATEGORY_KEYS:
        raise ValueError("calibration summary category order does not match V2 contract")
    return {
        key: score_category(facts, key, categories[key]) for key in CATEGORY_KEYS
    }
