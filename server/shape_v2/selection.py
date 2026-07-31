from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable
from typing import Any


PROFILE_QUOTAS = {
    "breakout_clean_confirmed": 3,
    "breakout_day_unconfirmed": 2,
    "breakout_downtrend_lookalike": 2,
    "breakout_near_boundary": 3,
    "trend_clean": 3,
    "trend_old_high": 2,
    "trend_overextended": 1,
    "trend_range_boundary": 1,
    "pullback_shallow_confirmed": 2,
    "pullback_deep_fast": 2,
    "pullback_long_stale": 2,
    "pullback_moderate": 1,
}

BREAKOUT_STAGE_QUOTAS = {
    "breakout_stage_day": 2,
    "breakout_stage_hold_1_3": 3,
    "breakout_stage_aging_5_15": 3,
    "breakout_stage_range_retest": 2,
    "breakout_stage_downtrend_surge": 2,
}


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, float(value)))


def _ramp(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("ramp high must exceed low")
    return _clip((value - low) / (high - low))


def _band(value: float, low: float, high: float, softness: float) -> float:
    if low <= value <= high:
        return 1.0
    if value < low:
        return _clip(1.0 - (low - value) / softness)
    return _clip(1.0 - (value - high) / softness)


def _mean(*values: float) -> float:
    return float(sum(values) / max(len(values), 1))


def profile_score(profile: str, facts: dict[str, float]) -> float:
    f = lambda key, default=0.0: float(facts.get(key, default))
    scorers: dict[str, Callable[[], float]] = {
        "breakout_clean_confirmed": lambda: _mean(
            float(1 <= f("breakout_age", 99) <= 3),
            _ramp(f("breakout_hold_margin"), -0.015, 0.025),
            _ramp(f("breakout_vs_prior_20"), 0.0, 0.06),
            _ramp(f("trend_slope_60"), 0.0, 0.20),
            _band(f("ma20_extension"), 0.01, 0.16, 0.10),
            _ramp(f("breakout_volume_ratio"), 0.8, 1.8),
        ),
        "breakout_day_unconfirmed": lambda: _mean(
            float(f("breakout_age", 99) == 0),
            _ramp(f("breakout_vs_prior_20"), 0.0, 0.08),
            _ramp(f("breakout_day_return"), 0.02, 0.10),
            _ramp(f("breakout_volume_ratio"), 0.9, 2.0),
            _band(f("ma20_extension"), 0.02, 0.20, 0.12),
        ),
        "breakout_downtrend_lookalike": lambda: _mean(
            _ramp(-f("trend_slope_60"), 0.03, 0.25),
            _ramp(-f("return_60"), 0.03, 0.25),
            _ramp(f("rebound_from_10_low"), 0.04, 0.16),
            _band(f("breakout_vs_prior_20"), -0.18, 0.01, 0.10),
        ),
        "breakout_near_boundary": lambda: _mean(
            _band(f("breakout_vs_prior_20"), -0.025, 0.025, 0.05),
            _ramp(f("return_5"), 0.01, 0.10),
            _band(f("old_high_gap_120"), -0.05, 0.03, 0.08),
            1.0 - _ramp(f("range_staleness_60"), 0.65, 0.95),
        ),
        "breakout_stage_day": lambda: _mean(
            float(f("breakout_age", 99) == 0),
            _ramp(f("breakout_day_return"), 0.025, 0.10),
            _ramp(f("breakout_volume_ratio"), 1.0, 2.8),
            _ramp(f("breakout_vs_prior_20"), 0.0, 0.07),
            _ramp(f("breakout_approach_return_5"), 0.0, 0.08),
            _ramp(f("breakout_approach_positive_ratio_10"), 0.45, 0.75),
        ),
        "breakout_stage_hold_1_3": lambda: _mean(
            float(1 <= f("breakout_age", 99) <= 3),
            f("breakout_confirmed"),
            _ramp(f("breakout_hold_margin"), -0.015, 0.025),
            _ramp(f("breakout_current_margin"), 0.0, 0.08),
            1.0 - _ramp(f("breakout_post_event_drawdown"), 0.03, 0.10),
            _ramp(f("breakout_volume_ratio"), 0.9, 2.2),
        ),
        "breakout_stage_aging_5_15": lambda: _mean(
            float(5 <= f("breakout_age", 99) <= 15),
            f("breakout_confirmed"),
            _ramp(f("breakout_hold_margin"), -0.015, 0.025),
            _band(f("breakout_current_margin"), 0.0, 0.16, 0.10),
            1.0 - _ramp(f("breakout_post_event_drawdown"), 0.05, 0.16),
            _ramp(f("trend_slope_20"), 0.01, 0.20),
        ),
        "breakout_stage_range_retest": lambda: _mean(
            _band(f("breakout_vs_prior_20"), -0.015, 0.045, 0.05),
            _ramp(f("return_5"), 0.02, 0.10),
            _ramp(f("old_high_rejection_count"), 3.0, 8.0),
            1.0 - _ramp(f("trend_fit_60"), 0.35, 0.75),
            _ramp(f("breakout_volume_ratio"), 0.9, 2.5),
        ),
        "breakout_stage_downtrend_surge": lambda: _mean(
            _ramp(-f("trend_slope_60"), 0.03, 0.25),
            _ramp(-f("return_60"), 0.03, 0.25),
            _ramp(f("return_3"), 0.05, 0.16),
            _ramp(f("breakout_volume_ratio"), 1.0, 3.0),
            _band(f("breakout_vs_prior_20"), -0.02, 0.08, 0.08),
        ),
        "trend_clean": lambda: _mean(
            _ramp(f("return_60"), 0.08, 0.35),
            _ramp(f("trend_slope_60"), 0.06, 0.30),
            _ramp(f("trend_fit_60"), 0.45, 0.90),
            1.0 - _ramp(f("drawdown_60"), 0.08, 0.22),
            _ramp(f("ma_alignment"), 0.50, 1.0),
            1.0 - _ramp(f("range_staleness_60"), 0.45, 0.85),
        ),
        "trend_old_high": lambda: _mean(
            _ramp(f("return_60"), 0.08, 0.30),
            _ramp(f("trend_fit_60"), 0.35, 0.85),
            _band(f("old_high_gap_120"), -0.04, 0.035, 0.06),
            _ramp(f("days_since_old_high"), 35.0, 90.0),
            1.0 - _ramp(f("drawdown_60"), 0.10, 0.25),
        ),
        "trend_overextended": lambda: _mean(
            _ramp(f("return_60"), 0.15, 0.50),
            _ramp(f("ma20_extension"), 0.12, 0.28),
            _ramp(f("largest_up_day_share_20"), 0.25, 0.65),
            _ramp(f("trend_slope_60"), 0.10, 0.40),
        ),
        "trend_range_boundary": lambda: _mean(
            _ramp(f("range_staleness_60"), 0.55, 0.95),
            _band(f("return_60"), -0.08, 0.12, 0.10),
            _ramp(f("days_since_60_high"), 20.0, 50.0),
            1.0 - _ramp(f("trend_fit_60"), 0.20, 0.60),
        ),
        "pullback_shallow_confirmed": lambda: _mean(
            _ramp(f("prior_advance_before_peak"), 0.10, 0.35),
            _band(f("drawdown_60"), 0.05, 0.16, 0.08),
            _band(f("pullback_duration_60"), 3.0, 20.0, 12.0),
            _ramp(f("turn_confirmation"), 0.45, 0.85),
            1.0 - _ramp(f("range_staleness_60"), 0.55, 0.90),
        ),
        "pullback_deep_fast": lambda: _mean(
            _ramp(f("prior_advance_before_peak"), 0.18, 0.50),
            _ramp(f("drawdown_60"), 0.20, 0.38),
            _ramp(f("pullback_speed_60"), 0.012, 0.035),
            _ramp(-f("worst_5day_return_20"), 0.08, 0.22),
        ),
        "pullback_long_stale": lambda: _mean(
            _ramp(f("prior_advance_before_peak"), 0.10, 0.35),
            _ramp(f("pullback_duration_60"), 25.0, 50.0),
            _ramp(f("range_staleness_60"), 0.45, 0.90),
            1.0 - _ramp(f("turn_confirmation"), 0.45, 0.80),
        ),
        "pullback_moderate": lambda: _mean(
            _ramp(f("prior_advance_before_peak"), 0.12, 0.35),
            _band(f("drawdown_60"), 0.12, 0.24, 0.10),
            _band(f("pullback_duration_60"), 5.0, 25.0, 15.0),
            _ramp(f("turn_confirmation"), 0.30, 0.75),
        ),
    }
    if profile not in scorers:
        raise ValueError(f"unknown calibration profile: {profile}")
    return round(float(scorers[profile]()), 8)


def select_targeted_candidates(
    candidates: Iterable[dict[str, Any]],
    quotas: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Greedily fill private calibration profiles without exposing them to reviewers."""
    requested = dict(quotas or PROFILE_QUOTAS)
    if any(value < 0 for value in requested.values()):
        raise ValueError("profile quotas cannot be negative")
    pool = list(candidates)
    selected: list[dict[str, Any]] = []
    used_samples: set[str] = set()
    used_groups: set[str] = set()
    for profile, quota in requested.items():
        ranked = sorted(
            pool,
            key=lambda item: (
                -profile_score(profile, item["sample"]["shared_facts"]),
                hashlib.sha256(item["sample"]["sample_id"].encode("utf-8")).hexdigest(),
            ),
        )
        chosen = 0
        for item in ranked:
            sample_id = str(item["sample"]["sample_id"])
            group_id = str(item["audit"]["source_group_id"])
            if sample_id in used_samples or group_id in used_groups:
                continue
            enriched = dict(item)
            enriched["selection_profile"] = profile
            enriched["selection_score"] = profile_score(
                profile, item["sample"]["shared_facts"]
            )
            selected.append(enriched)
            used_samples.add(sample_id)
            used_groups.add(group_id)
            chosen += 1
            if chosen >= quota:
                break
        if chosen != quota:
            raise RuntimeError(
                f"profile {profile} requested {quota} samples but only selected {chosen}"
            )
    return selected
