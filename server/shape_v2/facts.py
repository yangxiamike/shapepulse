from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np


def _clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return default
    return float(numerator / denominator)


def _return(values: np.ndarray, periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    return _safe_ratio(float(values[-1]), float(values[-periods - 1]), 1.0) - 1.0


def _linear_fit(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 3 or not np.isfinite(values).all() or values[0] <= 0:
        return 0.0, 0.0
    normalized = values / values[0]
    x = np.arange(len(values), dtype=float)
    centered_x = x - x.mean()
    denominator = float(np.dot(centered_x, centered_x))
    if denominator == 0:
        return 0.0, 0.0
    slope = float(np.dot(centered_x, normalized - normalized.mean()) / denominator)
    predicted = slope * x + float(normalized.mean() - slope * x.mean())
    residual = float(np.square(normalized - predicted).sum())
    total = float(np.square(normalized - normalized.mean()).sum())
    fit = 0.0 if total == 0 else max(0.0, min(1.0, 1.0 - residual / total))
    return float(slope * (len(values) - 1)), fit


def _window_max(values: np.ndarray, window: int) -> float:
    return float(np.nanmax(values[-min(window, len(values)) :]))


def _window_min(values: np.ndarray, window: int) -> float:
    return float(np.nanmin(values[-min(window, len(values)) :]))


def _volatility(close: np.ndarray, window: int) -> float:
    values = close[-min(window + 1, len(close)) :]
    if len(values) < 3:
        return 0.0
    returns = np.diff(values) / values[:-1]
    return float(np.nanstd(returns))


def _positive_day_ratio(close: np.ndarray, window: int) -> float:
    values = close[-min(window + 1, len(close)) :]
    if len(values) < 2:
        return 0.0
    changes = np.diff(values)
    return float(np.count_nonzero(changes > 0) / len(changes))


def _prior_breakout(high: np.ndarray, close: np.ndarray, window: int, exclude_recent: int = 3) -> float:
    end = max(1, len(high) - exclude_recent)
    start = max(0, end - window)
    prior = high[start:end]
    if not len(prior):
        return 0.0
    return _safe_ratio(float(close[-1]), float(np.nanmax(prior)), 1.0) - 1.0


def extract_shared_facts(bars: Iterable[dict[str, Any]], minimum_bars: int = 120) -> dict[str, float]:
    """Compute V2 factual features from an already scoring-date-censored window."""
    rows = list(bars)
    if len(rows) < minimum_bars:
        raise ValueError(f"at least {minimum_bars} bars are required")
    rows = rows[-minimum_bars:]
    close = np.asarray([row["close"] for row in rows], dtype=float)
    high = np.asarray([row["high"] for row in rows], dtype=float)
    low = np.asarray([row["low"] for row in rows], dtype=float)
    volume = np.asarray([row["volume"] for row in rows], dtype=float)
    if not (
        np.isfinite(close).all()
        and np.isfinite(high).all()
        and np.isfinite(low).all()
        and np.isfinite(volume).all()
        and (close > 0).all()
    ):
        raise ValueError("bars contain non-finite or non-positive prices")

    facts: dict[str, float] = {}
    for period in (3, 5, 10, 20, 60, 119):
        facts[f"return_{period}"] = _return(close, period)
    for period in (10, 20, 60, 120):
        slope, fit = _linear_fit(close[-period:])
        facts[f"trend_slope_{period}"] = slope
        facts[f"trend_fit_{period}"] = fit
    moving_averages = {
        period: float(np.nanmean(close[-period:])) for period in (5, 10, 20, 60, 120)
    }
    for period, average in moving_averages.items():
        facts[f"ma{period}_extension"] = _safe_ratio(float(close[-1]), average, 1.0) - 1.0
    facts["ma_alignment"] = float(
        sum(
            left >= right
            for left, right in zip(
                (moving_averages[5], moving_averages[10], moving_averages[20], moving_averages[60]),
                (moving_averages[10], moving_averages[20], moving_averages[60], moving_averages[120]),
            )
        )
        / 4.0
    )
    for period in (20, 60, 120):
        peak = _window_max(high, period)
        trough = _window_min(low, period)
        facts[f"drawdown_{period}"] = max(
            0.0, 1.0 - _safe_ratio(float(close[-1]), peak, 1.0)
        )
        facts[f"range_position_{period}"] = _safe_ratio(
            float(close[-1] - trough), peak - trough, 0.5
        )
    facts["breakout_vs_prior_20"] = _prior_breakout(high, close, 20)
    facts["breakout_vs_prior_60"] = _prior_breakout(high, close, 60)
    high60_index = int(np.nanargmax(high[-60:]))
    facts["days_since_60_high"] = float(59 - high60_index)

    breakout_index: int | None = None
    breakout_resistance = 0.0
    breakout_resistance_window = 0
    # Calibration needs to distinguish the breakout day, the 1-3 bar hold,
    # and the later 5-15 bar decay stage. Keep the event search inside that
    # explicit review horizon so an old breakout cannot remain "fresh".
    for index in range(max(20, len(close) - 16), len(close)):
        # A meaningful event may break a clear local structure without clearing
        # an unrelated old 60-day high. Detect both horizons, then leave quality,
        # continuity and old-high context to the independent breakout scorer.
        event_candidates: list[tuple[int, float]] = []
        for resistance_window in (20, 60):
            prior = high[max(0, index - resistance_window) : index]
            if len(prior) < min(20, resistance_window):
                continue
            resistance = float(np.nanmax(prior))
            if close[index] >= resistance * 1.003:
                event_candidates.append((resistance_window, resistance))
        if event_candidates:
            breakout_resistance_window, breakout_resistance = min(
                event_candidates, key=lambda item: item[1]
            )
            breakout_index = index
            break
    if breakout_index is None:
        facts["breakout_age"] = 99.0
        facts["breakout_hold_margin"] = -1.0
        facts["breakout_current_margin"] = -1.0
        facts["breakout_post_event_drawdown"] = 1.0
        facts["breakout_confirmed"] = 0.0
        facts["breakout_day_return"] = _return(close, 1)
        facts["breakout_resistance_window"] = 0.0
        prior_breakout_volume = float(np.nanmean(volume[-21:-1]))
        facts["breakout_volume_ratio"] = _safe_ratio(
            float(volume[-1]), prior_breakout_volume, 1.0
        )
        pre_breakout_close = close[-21:-1]
    else:
        age = len(close) - 1 - breakout_index
        facts["breakout_age"] = float(age)
        facts["breakout_hold_margin"] = (
            _safe_ratio(
                float(np.nanmin(close[breakout_index:])), breakout_resistance, 1.0
            )
            - 1.0
        )
        facts["breakout_current_margin"] = (
            _safe_ratio(float(close[-1]), breakout_resistance, 1.0) - 1.0
        )
        facts["breakout_post_event_drawdown"] = max(
            0.0,
            1.0
            - _safe_ratio(
                float(close[-1]),
                float(np.nanmax(high[breakout_index:])),
                1.0,
            ),
        )
        facts["breakout_confirmed"] = float(
            age >= 1 and facts["breakout_hold_margin"] >= -0.015
        )
        facts["breakout_day_return"] = (
            _safe_ratio(float(close[breakout_index]), float(close[breakout_index - 1]), 1.0)
            - 1.0
        )
        facts["breakout_resistance_window"] = float(breakout_resistance_window)
        prior_breakout_volume = float(
            np.nanmean(volume[max(0, breakout_index - 20) : breakout_index])
        )
        facts["breakout_volume_ratio"] = _safe_ratio(
            float(volume[breakout_index]), prior_breakout_volume, 1.0
        )
        pre_breakout_close = close[max(0, breakout_index - 21) : breakout_index]
    context_end = breakout_index if breakout_index is not None else len(close)
    context_start = max(0, context_end - 40)
    pre_breakout_context_close = close[context_start:context_end]
    pre_breakout_context_high = high[context_start:context_end]
    pre_breakout_context_low = low[context_start:context_end]
    if len(pre_breakout_context_close) >= 20:
        context_slope, context_fit = _linear_fit(pre_breakout_context_close)
        facts["pre_breakout_return_40"] = (
            _safe_ratio(
                float(pre_breakout_context_close[-1]),
                float(pre_breakout_context_close[0]),
                1.0,
            )
            - 1.0
        )
        facts["pre_breakout_trend_slope_40"] = context_slope
        facts["pre_breakout_trend_fit_40"] = context_fit
        context_high = float(np.nanmax(pre_breakout_context_high))
        context_low = float(np.nanmin(pre_breakout_context_low))
        facts["pre_breakout_range_width_40"] = _safe_ratio(
            context_high - context_low,
            float(np.nanmean(pre_breakout_context_close)),
            0.0,
        )
        facts["pre_breakout_context_bars"] = float(
            len(pre_breakout_context_close)
        )
    else:
        facts["pre_breakout_return_40"] = 0.0
        facts["pre_breakout_trend_slope_40"] = 0.0
        facts["pre_breakout_trend_fit_40"] = 0.0
        facts["pre_breakout_range_width_40"] = 0.0
        facts["pre_breakout_context_bars"] = float(
            len(pre_breakout_context_close)
        )
    facts["breakout_approach_return_5"] = (
        _safe_ratio(
            float(pre_breakout_close[-1]),
            float(pre_breakout_close[-6]),
            1.0,
        )
        - 1.0
        if len(pre_breakout_close) >= 6
        else 0.0
    )
    facts["breakout_approach_positive_ratio_10"] = _positive_day_ratio(
        pre_breakout_close, 10
    )
    facts["pre_breakout_volatility_20"] = (
        float(np.nanstd(np.diff(pre_breakout_close) / pre_breakout_close[:-1]))
        if len(pre_breakout_close) >= 3
        else 0.0
    )
    recent_returns = np.diff(close[-21:]) / close[-21:-1]
    positive_returns = np.clip(recent_returns, 0.0, None)
    facts["largest_up_day_share_20"] = _safe_ratio(
        float(np.nanmax(positive_returns)),
        float(np.nansum(positive_returns)),
        0.0,
    )

    early_high_window = high[:-30]
    if len(early_high_window):
        early_high = float(np.nanmax(early_high_window))
        early_high_index = int(np.nanargmax(early_high_window))
        facts["old_high_gap_120"] = (
            _safe_ratio(float(close[-1]), early_high, 1.0) - 1.0
        )
        facts["days_since_old_high"] = float(len(close) - 1 - early_high_index)
        rejections = 0
        for index in range(1, len(early_high_window) - 1):
            if (
                early_high_window[index] >= early_high * 0.97
                and early_high_window[index] >= early_high_window[index - 1]
                and early_high_window[index] >= early_high_window[index + 1]
            ):
                rejections += 1
        facts["old_high_rejection_count"] = float(rejections)
    else:
        facts["old_high_gap_120"] = 0.0
        facts["days_since_old_high"] = 0.0
        facts["old_high_rejection_count"] = 0.0

    for period in (10, 20, 60):
        facts[f"volatility_{period}"] = _volatility(close, period)
    facts["positive_day_ratio_20"] = _positive_day_ratio(close, 20)
    facts["positive_day_ratio_60"] = _positive_day_ratio(close, 60)

    old_volume = float(np.nanmean(volume[-25:-5]))
    recent_volume = float(np.nanmean(volume[-5:]))
    facts["volume_ratio_5_20"] = _safe_ratio(recent_volume, old_volume, 1.0)
    changes20 = np.diff(close[-21:])
    daily_volume20 = volume[-20:]
    up_volume = float(np.nanmean(daily_volume20[changes20 > 0])) if np.any(changes20 > 0) else 0.0
    down_volume = (
        float(np.nanmean(daily_volume20[changes20 < 0])) if np.any(changes20 < 0) else 0.0
    )
    facts["up_down_volume_ratio_20"] = _safe_ratio(up_volume, down_volume, 1.0)
    high5 = _window_max(high, 5)
    low5 = _window_min(low, 5)
    facts["close_location_5"] = _safe_ratio(float(close[-1] - low5), high5 - low5, 0.5)
    facts["rebound_from_10_low"] = _safe_ratio(
        float(close[-1]), _window_min(low, 10), 1.0
    ) - 1.0
    facts["prior_return_60_ex_last_10"] = (
        _safe_ratio(float(close[-11]), float(close[-61]), 1.0) - 1.0
    )

    peak60_relative = int(np.nanargmax(high[-60:]))
    peak60_absolute = len(high) - 60 + peak60_relative
    pullback_duration = len(high) - 1 - peak60_absolute
    peak60 = float(high[peak60_absolute])
    pullback_depth = max(0.0, 1.0 - _safe_ratio(float(close[-1]), peak60, 1.0))
    prior_low_start = max(0, peak60_absolute - 60)
    prior_low = float(np.nanmin(low[prior_low_start : peak60_absolute + 1]))
    prior_advance = max(0.0, _safe_ratio(peak60, prior_low, 1.0) - 1.0)
    facts["pullback_duration_60"] = float(pullback_duration)
    facts["pullback_speed_60"] = _safe_ratio(
        pullback_depth, float(max(pullback_duration, 1)), 0.0
    )
    facts["prior_advance_before_peak"] = prior_advance
    facts["retracement_of_prior_advance"] = _safe_ratio(
        peak60 - float(close[-1]), peak60 - prior_low, 0.0
    )
    rolling_five_returns = [
        _safe_ratio(float(close[index]), float(close[index - 5]), 1.0) - 1.0
        for index in range(max(5, len(close) - 20), len(close))
    ]
    facts["worst_5day_return_20"] = (
        float(min(rolling_five_returns)) if rolling_five_returns else 0.0
    )
    turn_components = (
        _clamp01(max(0.0, facts["return_3"]) / 0.05),
        _clamp01(max(0.0, facts["return_5"]) / 0.08),
        float(close[-1] >= moving_averages[10]),
        _clamp01(facts["close_location_5"]),
        _clamp01(max(0.0, facts["rebound_from_10_low"]) / 0.10),
    )
    facts["turn_confirmation"] = float(sum(turn_components) / len(turn_components))
    range_components = (
        1.0 - _clamp01(abs(facts["return_60"]) / 0.15),
        1.0 - _clamp01(facts["trend_fit_60"]),
        _clamp01(facts["days_since_60_high"] / 40.0),
    )
    facts["range_staleness_60"] = float(sum(range_components) / len(range_components))

    previous_close = close[:-1]
    true_ranges = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - previous_close), np.abs(low[1:] - previous_close)),
    )
    facts["atr_14_pct"] = _safe_ratio(
        float(np.nanmean(true_ranges[-14:])), float(close[-1]), 0.0
    )
    return {
        key: round(float(value), 8)
        for key, value in facts.items()
        if math.isfinite(float(value))
    }
