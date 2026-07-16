from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


CATEGORY_ORDER = ("breakout", "pullback", "range_bounce")


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def _return(values: np.ndarray, periods: int) -> float:
    if len(values) <= periods or values[-periods - 1] == 0:
        return 0.0
    return float(values[-1] / values[-periods - 1] - 1.0)


def _linear_fit(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 3 or not np.isfinite(values).all() or values[0] == 0:
        return 0.0, 0.0
    normalized = values / values[0]
    x = np.arange(len(values), dtype=float)
    x_centered = x - x.mean()
    y_centered = normalized - normalized.mean()
    denominator = float(np.dot(x_centered, x_centered))
    if denominator == 0:
        return 0.0, 0.0
    slope = float(np.dot(x_centered, y_centered) / denominator)
    intercept = float(normalized.mean() - slope * x.mean())
    predicted = slope * x + intercept
    residual = float(np.square(normalized - predicted).sum())
    total = float(np.square(normalized - normalized.mean()).sum())
    return float(slope * (len(values) - 1)), 0.0 if total == 0 else clamp(1 - residual / total)


def _breakout(close: np.ndarray, volume: np.ndarray, config: dict) -> dict[str, Any] | None:
    if len(close) < int(config["minimum_bars"]):
        return None
    ret20 = _return(close, 20)
    prior = close[-40:-5]
    prior_high = float(np.nanmax(prior)) if len(prior) else float(close[-2])
    breakout = 0.0 if prior_high <= 0 else float(close[-1] / prior_high - 1)
    old_volume = float(np.nanmean(volume[-25:-5]))
    new_volume = float(np.nanmean(volume[-5:]))
    volume_ratio = 1.0 if old_volume <= 0 else new_volume / old_volume
    ma20 = float(np.nanmean(close[-20:]))
    extension = 0.0 if ma20 <= 0 else float(close[-1] / ma20 - 1)
    slope20, fit20 = _linear_fit(close[-20:])
    target = config
    weights = target["weights"]
    first_wave = 1.0 - clamp(max(0.0, extension) / target["maximum_extension_from_ma20"])
    score = (
        weights["momentum"] * clamp(ret20 / target["momentum_20_target"])
        + weights["breakout"] * clamp((breakout + 0.015) / (target["breakout_target"] + 0.015))
        + weights["volume"] * clamp((volume_ratio - 0.8) / (target["volume_ratio_target"] - 0.8))
        + weights["trend_fit"] * fit20 * clamp(slope20 / 0.15)
        + weights["first_wave"] * first_wave
    )
    if ret20 < 0.03 or breakout < -0.035 or extension > target["maximum_extension_from_ma20"] * 1.5:
        score *= 0.62
    reasons = []
    if ret20 >= target["momentum_20_target"] * 0.65:
        reasons.append("近20日快速抬升")
    if breakout >= 0:
        reasons.append("价格突破近期平台")
    if volume_ratio >= target["volume_ratio_target"]:
        reasons.append("突破伴随放量")
    if 0 <= extension <= target["maximum_extension_from_ma20"]:
        reasons.append("仍处第一波合理乖离")
    if fit20 >= 0.65 and slope20 > 0:
        reasons.append("短期上行曲线拟合较好")
    return {
        "score": score,
        "reasons": reasons or ["短期结构接近启动形态"],
        "metrics": {
            "return_20": ret20,
            "breakout": breakout,
            "volume_ratio": volume_ratio,
            "ma20_extension": extension,
            "trend_fit_20": fit20,
        },
    }


def _pullback(close: np.ndarray, high: np.ndarray, config: dict) -> dict[str, Any] | None:
    if len(close) < int(config["minimum_bars"]):
        return None
    ret60 = _return(close, 60)
    peak = float(np.nanmax(high[-30:]))
    drawdown = 0.0 if peak <= 0 else float((peak - close[-1]) / peak)
    ma20 = float(np.nanmean(close[-20:]))
    ma40 = float(np.nanmean(close[-40:]))
    ma60 = float(np.nanmean(close[-60:]))
    ma_distance = min(abs(close[-1] / ma20 - 1), abs(close[-1] / ma40 - 1))
    base = float(np.nanmin(close[-60:]))
    advance = max(peak - base, 1e-9)
    retracement = float((peak - close[-1]) / advance)
    returns10 = np.diff(close[-11:]) / close[-11:-1]
    consolidation_vol = float(np.nanstd(returns10))
    slope60, fit60 = _linear_fit(close[-60:])
    weights = config["weights"]
    draw_mid = (config["shallow_drawdown_min"] + config["shallow_drawdown_max"]) / 2
    draw_half = (config["shallow_drawdown_max"] - config["shallow_drawdown_min"]) / 2
    draw_score = 1 - clamp(abs(drawdown - draw_mid) / max(draw_half, 1e-9))
    retrace_score = 1 - clamp(abs(retracement - 0.44) / 0.44)
    ma_score = 1 - clamp(ma_distance / config["maximum_ma20_distance"])
    if close[-1] >= ma60:
        ma_score = min(1.0, ma_score + 0.15)
    score = (
        weights["trend"] * clamp(ret60 / config["minimum_trend_return_60"])
        + weights["drawdown"] * draw_score
        + weights["ma_support"] * ma_score
        + weights["retracement"] * retrace_score
        + weights["consolidation"] * (1 - clamp(consolidation_vol / config["maximum_consolidation_volatility"]))
        + weights["trend_fit"] * fit60 * clamp(slope60 / 0.20)
    )
    if ret60 < 0.04 or close[-1] < ma60 * 0.95 or drawdown > config["shallow_drawdown_max"] * 1.4:
        score *= 0.62
    reasons = []
    if ret60 >= config["minimum_trend_return_60"]:
        reasons.append("中期上升趋势保持")
    if config["shallow_drawdown_min"] <= drawdown <= config["shallow_drawdown_max"]:
        reasons.append("高点后浅回撤")
    if ma_distance <= config["maximum_ma20_distance"]:
        reasons.append("回到均线支撑附近")
    if 0.32 <= retracement <= config["maximum_retracement_ratio"]:
        reasons.append("回撤接近38%/50%结构")
    if consolidation_vol <= config["maximum_consolidation_volatility"]:
        reasons.append("短线波动收敛")
    return {
        "score": score,
        "reasons": reasons or ["结构接近上升趋势回调"],
        "metrics": {
            "return_60": ret60,
            "drawdown_from_peak": drawdown,
            "ma_support_distance": ma_distance,
            "retracement_ratio": retracement,
            "consolidation_volatility": consolidation_vol,
            "trend_fit_60": fit60,
        },
    }


def _range_bounce(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, config: dict
) -> dict[str, Any] | None:
    if len(close) < int(config["minimum_bars"]):
        return None
    window = int(config["range_window"])
    c = close[-window:]
    h = high[-window:]
    lows = low[-window:]
    range_high = float(np.nanmax(h))
    range_low = float(np.nanmin(lows))
    span = max(range_high - range_low, 1e-9)
    position = float((close[-1] - range_low) / span)
    width = float(span / max(range_low, 1e-9))
    bounce5 = _return(close, 5)
    return80 = _return(close, min(79, window - 1))
    slope80, fit80 = _linear_fit(c)
    sideways = (1 - clamp(abs(return80) / config["maximum_trend_abs_return"])) * (1 - abs(slope80))
    touch_band = range_low + span * 0.08
    touches = int(np.count_nonzero(lows <= touch_band))
    weights = config["weights"]
    score = (
        weights["lower_position"] * (1 - clamp(position / config["maximum_range_position"]))
        + weights["bounce"] * clamp((bounce5 + 0.01) / (config["minimum_bounce_5"] + 0.01))
        + weights["range_width"] * clamp(width / config["minimum_range_width"])
        + weights["sideways_fit"] * clamp(sideways)
        + weights["support_touches"] * clamp(touches / 4)
    )
    if position > config["maximum_range_position"] * 1.5 or width < config["minimum_range_width"] * 0.6:
        score *= 0.58
    reasons = []
    if position <= config["maximum_range_position"]:
        reasons.append("位于80日区间下沿")
    if bounce5 >= config["minimum_bounce_5"]:
        reasons.append("下沿出现短线反弹")
    if width >= config["minimum_range_width"]:
        reasons.append("震荡区间宽度充分")
    if touches >= 3:
        reasons.append("区间支撑多次得到验证")
    if sideways >= 0.55:
        reasons.append("横盘曲线拟合较好")
    return {
        "score": score,
        "reasons": reasons or ["结构接近区间下沿反弹"],
        "metrics": {
            "range_position": position,
            "range_width": width,
            "bounce_5": bounce5,
            "return_80": return80,
            "support_touches": touches,
            "sideways_fit": sideways,
            "linear_fit_80": fit80,
        },
    }


def score_stock(
    frame: pd.DataFrame, thresholds: dict, assume_sorted: bool = False
) -> dict[str, Any]:
    if not assume_sorted:
        frame = frame.sort_values("trade_date").drop_duplicates("trade_date")
    frame = frame.tail(int(thresholds["screen"]["lookback_bars"]))
    if len(frame) < int(thresholds["screen"]["minimum_bars"]):
        return {
            "status": "not_calculated",
            "matches": [],
            "history_bars": len(frame),
            "warning": "可用交易日不足，尚未完成形态计算",
        }
    matrix = frame[["close", "high", "low", "vol"]].to_numpy(dtype=float)
    close, high, low, volume = matrix.T
    volume = np.nan_to_num(volume, nan=0.0)
    candidates = {
        "breakout": _breakout(close, volume, thresholds["breakout"]),
        "pullback": _pullback(close, high, thresholds["pullback"]),
        "range_bounce": _range_bounce(close, high, low, thresholds["range_bounce"]),
    }
    matches = []
    for category in CATEGORY_ORDER:
        details = candidates[category]
        if details is None or details["score"] < thresholds[category]["minimum_score"]:
            continue
        metrics = {
            key: round(float(value), 6) if isinstance(value, (float, np.floating)) else value
            for key, value in details["metrics"].items()
        }
        matches.append(
            {
                "category": category,
                "category_label": thresholds[category]["label"],
                "score": round(float(details["score"]), 2),
                "reasons": details["reasons"][:4],
                "metrics": metrics,
                "minimum_score": float(thresholds[category]["minimum_score"]),
            }
        )
    base = {
        "status": "matched" if matches else "no_match",
        "matches": matches,
        "history_bars": len(frame),
        "trade_date": str(frame.iloc[-1]["trade_date"]),
        "close": round(float(close[-1]), 3),
        "pct_chg": round(float(frame.iloc[-1].get("pct_chg", 0.0)), 3),
    }
    if not matches:
        return base
    primary = max(matches, key=lambda item: item["score"])
    return {**base, **primary}
