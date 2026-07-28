from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.shape_v2_dataset import load_bulk_candidate_history, render_svg
from scripts.shape_v2_segment_mining import (
    PRIVATE_ROOT,
    _band,
    _candidate_endpoint_indices,
    _excluded_codes,
    _ramp,
    path_risk_metrics,
)
from server.config import load_settings
from server.repository import LocalMarketRepository
from server.shape_v2.dataset import (
    anonymous_id,
    assign_research_split,
    build_public_bars,
    build_public_sample,
    canonical_json,
    content_hash,
    source_group_id,
    validate_audit_manifest,
)
from server.shape_v2.facts import extract_shared_facts


CATEGORY_SPECS = {
    "fresh_breakout": {
        "label": "刚突破",
        "slug": "fresh-breakout-segments",
        "dataset_version": "shape-v2.0.0-template-segments3-fresh-breakout",
        "audit_name": "template-discovery-v3-fresh-breakout-segments-audit.json",
    },
    "pullback_strengthening": {
        "label": "回调转强",
        "slug": "pullback-strengthening-segments",
        "dataset_version": "shape-v2.0.0-template-segments3-pullback-strengthening",
        "audit_name": "template-discovery-v3-pullback-strengthening-segments-audit.json",
    },
}
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine independent fresh-breakout and pullback-strengthening segments."
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--history-bars", type=int, default=620)
    parser.add_argument("--endpoint-step", type=int, default=15)
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=tuple(CATEGORY_SPECS),
        default=list(CATEGORY_SPECS),
    )
    parser.add_argument("--research-version", type=int, default=3)
    return parser.parse_args()


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _weighted_score(
    components: dict[str, float], weights: dict[str, float]
) -> float:
    return sum(components[key] * weights[key] for key in components) / sum(
        weights.values()
    )


def breakout_segment_prefilter(
    facts: dict[str, float], path: dict[str, float]
) -> dict[str, Any]:
    """Independent prior for a meaningful breakout that is still fresh."""

    def f(key: str, default: float = 0.0) -> float:
        return float(facts.get(key, default))

    age = f("breakout_age", 99.0)
    if 1 <= age <= 3:
        freshness = 1.0
    elif age == 0:
        freshness = 0.72
    elif 4 <= age <= 7:
        freshness = _clip(0.82 - (age - 4) * 0.12)
    elif 8 <= age <= 15:
        freshness = _clip(0.38 - (age - 8) * 0.04)
    else:
        freshness = 0.0
    resistance_window = f("breakout_resistance_window")
    structure_quality = 1.0 if resistance_window >= 60 else (
        0.72 if resistance_window >= 20 else 0.0
    )
    pre_return = f("pre_breakout_return_40")
    pre_slope = f("pre_breakout_trend_slope_40")
    pre_fit = f("pre_breakout_trend_fit_40")
    pre_range = f("pre_breakout_range_width_40")
    pre_return_60 = f("pre_breakout_return_60")
    pre_slope_60 = f("pre_breakout_trend_slope_60")
    pre_fit_60 = f("pre_breakout_trend_fit_60")
    pre_return_100 = f("pre_breakout_return_100")
    pre_slope_100 = f("pre_breakout_trend_slope_100")
    pre_fit_100 = f("pre_breakout_trend_fit_100")
    pre_position_100 = f("pre_breakout_range_position_100", 0.5)
    pre_drawdown_100 = f("pre_breakout_drawdown_from_high_100")
    consolidation_quality = (
        _band(pre_return, -0.12, 0.08, 0.10)
        * (1.0 - _ramp(abs(pre_slope), 0.08, 0.22))
        * _band(pre_range, 0.05, 0.24, 0.16)
    )
    decline_quality = (
        _ramp(-pre_return, 0.05, 0.24)
        * _ramp(-pre_slope, 0.04, 0.24)
    )
    setup_quality = max(consolidation_quality, decline_quality)
    recent_rise_strength = max(pre_return_60, pre_slope_60)
    long_rise_strength = max(pre_return_100, pre_slope_100)
    recent_non_rising = 1.0 - _ramp(recent_rise_strength, 0.08, 0.18)
    long_non_rising = 1.0 - _ramp(long_rise_strength, 0.15, 0.30)
    bottom_context = 1.0 - _ramp(pre_position_100, 0.70, 0.92)
    reset_drawdown = _ramp(pre_drawdown_100, 0.04, 0.12)
    reset_quality = max(
        long_non_rising,
        bottom_context,
        reset_drawdown,
        decline_quality,
    )
    raw_transition_quality = max(
        decline_quality,
        consolidation_quality * recent_non_rising * reset_quality,
    )
    recent_mature_uptrend = (
        pre_return > 0.06
        and pre_slope > 0.045
        and pre_fit > 0.70
    )
    long_mature_uptrend = (
        pre_return_100 > 0.08
        and pre_slope_100 > 0.07
        and pre_fit_100 > 0.60
    )
    established_uptrend = (
        recent_mature_uptrend
        or long_mature_uptrend
        or (
            raw_transition_quality < 0.40
            and (
                (
                    pre_return_60 > 0.10
                    and pre_slope_60 > 0.10
                    and pre_fit_60 > 0.50
                )
                or (
                    pre_return_100 > 0.18
                    and pre_slope_100 > 0.15
                    and pre_fit_100 > 0.50
                )
            )
        )
    )
    transition_quality = min(
        raw_transition_quality,
        0.20 if established_uptrend else 1.0,
    )
    components = {
        "fresh_stage": freshness,
        "long_consolidation_or_decline": setup_quality,
        "clear_state_transition": transition_quality,
        "not_already_uptrend": 0.0 if established_uptrend else 1.0,
        "confirmed_hold": _ramp(f("breakout_hold_margin"), -0.018, 0.015),
        "still_above_resistance": _band(
            f("breakout_current_margin"), 0.004, 0.085, 0.06
        ),
        "small_post_event_drawdown": 1.0
        - _ramp(f("breakout_post_event_drawdown"), 0.02, 0.085),
        "meaningful_structure": structure_quality,
        "near_larger_resistance": _ramp(
            f("breakout_vs_prior_60"), -0.14, 0.018
        ),
        "upper_part_of_full_range": _ramp(
            f("range_position_120"), 0.50, 0.96
        ),
        "old_high_context": _ramp(f("old_high_gap_120"), -0.25, 0.025),
        "coherent_breakout_day": _band(
            f("breakout_day_return"), 0.015, 0.095, 0.075
        ),
        "supportive_volume": _band(
            f("breakout_volume_ratio"), 0.95, 2.60, 1.60
        ),
        "controlled_approach": _band(
            f("breakout_approach_return_5"), -0.025, 0.10, 0.09
        ),
        "balanced_approach": _band(
            f("breakout_approach_positive_ratio_10"), 0.40, 0.80, 0.30
        ),
        "quiet_pre_breakout": 1.0
        - _ramp(f("pre_breakout_volatility_20"), 0.025, 0.052),
        "not_single_spike": 1.0
        - _ramp(f("largest_up_day_share_20"), 0.34, 0.65),
        "breakout_contrast": _ramp(
            f("breakout_day_return")
            / max(f("pre_breakout_volatility_20"), 0.008),
            1.2,
            3.5,
        ),
    }
    weights = {
        "fresh_stage": 3.0,
        "long_consolidation_or_decline": 3.0,
        "clear_state_transition": 5.0,
        "not_already_uptrend": 4.0,
        "confirmed_hold": 2.5,
        "still_above_resistance": 2.5,
        "small_post_event_drawdown": 2.0,
        "meaningful_structure": 2.0,
        "near_larger_resistance": 0.75,
        "upper_part_of_full_range": 0.75,
        "old_high_context": 0.50,
        "coherent_breakout_day": 1.5,
        "supportive_volume": 1.0,
        "controlled_approach": 1.25,
        "balanced_approach": 0.75,
        "quiet_pre_breakout": 1.0,
        "not_single_spike": 1.25,
        "breakout_contrast": 1.5,
    }
    score = _weighted_score(components, weights)
    hard_findings = []
    if not 0 <= age <= 15:
        hard_findings.append("no_fresh_breakout_event")
    if f("breakout_current_margin") < -0.015:
        hard_findings.append("fell_back_below_resistance")
    if f("breakout_hold_margin") < -0.03:
        hard_findings.append("failed_to_hold_breakout")
    if f("breakout_post_event_drawdown") > 0.10:
        hard_findings.append("post_breakout_drawdown_too_large")
    if f("breakout_day_return") > 0.15 or f("breakout_day_return") < -0.02:
        hard_findings.append("breakout_day_move_distorted")
    if f("pre_breakout_volatility_20") > 0.065:
        hard_findings.append("pre_breakout_structure_too_noisy")
    if f("largest_up_day_share_20") > 0.75:
        hard_findings.append("single_spike_dominated")
    if resistance_window < 20:
        hard_findings.append("no_meaningful_resistance")
    if f("pre_breakout_context_bars") < 35:
        hard_findings.append("pre_breakout_setup_too_short")
    if setup_quality < 0.40:
        hard_findings.append("no_long_consolidation_or_decline")
    if transition_quality < 0.40:
        hard_findings.append("no_clear_state_transition")
    if established_uptrend:
        hard_findings.append("already_established_uptrend")
    if hard_findings:
        score *= 0.20
    diagnostics = {
        "breakout_age": age,
        "breakout_resistance_window": resistance_window,
        "breakout_hold_margin": f("breakout_hold_margin"),
        "breakout_current_margin": f("breakout_current_margin"),
        "breakout_post_event_drawdown": f("breakout_post_event_drawdown"),
        "breakout_confirmed": f("breakout_confirmed"),
        "breakout_day_return": f("breakout_day_return"),
        "breakout_volume_ratio": f("breakout_volume_ratio"),
        "breakout_approach_return_5": f("breakout_approach_return_5"),
        "pre_breakout_volatility_20": f("pre_breakout_volatility_20"),
        "largest_up_day_share_20": f("largest_up_day_share_20"),
        "trend_slope_60": f("trend_slope_60"),
        "return_60": f("return_60"),
        "range_position_120": f("range_position_120"),
        "breakout_vs_prior_60": f("breakout_vs_prior_60"),
        "old_high_gap_120": f("old_high_gap_120"),
        "pre_breakout_return_40": pre_return,
        "pre_breakout_trend_slope_40": pre_slope,
        "pre_breakout_trend_fit_40": pre_fit,
        "pre_breakout_range_width_40": pre_range,
        "pre_breakout_return_60": pre_return_60,
        "pre_breakout_trend_slope_60": pre_slope_60,
        "pre_breakout_trend_fit_60": pre_fit_60,
        "pre_breakout_return_100": pre_return_100,
        "pre_breakout_trend_slope_100": pre_slope_100,
        "pre_breakout_trend_fit_100": pre_fit_100,
        "pre_breakout_range_position_100": pre_position_100,
        "pre_breakout_drawdown_from_high_100": pre_drawdown_100,
        "consolidation_quality": consolidation_quality,
        "decline_quality": decline_quality,
        "setup_quality": setup_quality,
        "recent_non_rising": recent_non_rising,
        "long_non_rising": long_non_rising,
        "bottom_context": bottom_context,
        "reset_drawdown": reset_drawdown,
        "reset_quality": reset_quality,
        "raw_transition_quality": raw_transition_quality,
        "transition_quality": transition_quality,
        "recent_mature_uptrend": float(recent_mature_uptrend),
        "long_mature_uptrend": float(long_mature_uptrend),
        "already_established_uptrend": float(established_uptrend),
        "max_drawdown_120": float(path["max_drawdown_120"]),
    }
    return {
        "score": round(float(score), 8),
        "components": {key: round(value, 8) for key, value in components.items()},
        "hard_findings": hard_findings,
        "diagnostics": {
            key: round(float(value), 8) for key, value in diagnostics.items()
        },
    }


def pullback_segment_prefilter(
    facts: dict[str, float], path: dict[str, float]
) -> dict[str, Any]:
    """Independent prior for a controlled pullback with present-day strengthening."""

    def f(key: str, default: float = 0.0) -> float:
        return float(facts.get(key, default))

    components = {
        "clear_prior_advance": _band(
            f("prior_advance_before_peak"), 0.16, 0.55, 0.25
        ),
        "controlled_depth": _band(f("drawdown_60"), 0.018, 0.105, 0.075),
        "visible_recent_pullback": _band(
            float(path["recent_pullback_depth_40"]), 0.035, 0.13, 0.075
        ),
        "recent_low_timing": _band(
            float(path["recent_pullback_low_age"]), 2.0, 12.0, 8.0
        ),
        "recovery_in_progress": _band(
            float(path["recent_recovery_fraction"]), 0.28, 1.02, 0.35
        ),
        "controlled_duration": _band(
            f("pullback_duration_60"), 3.0, 16.0, 10.0
        ),
        "controlled_speed": 1.0
        - _ramp(f("pullback_speed_60"), 0.010, 0.030),
        "proportionate_retracement": _band(
            f("retracement_of_prior_advance"), 0.12, 0.48, 0.28
        ),
        "no_fast_collapse": _ramp(f("worst_5day_return_20"), -0.13, -0.045),
        "turn_is_visible": _ramp(f("turn_confirmation"), 0.48, 0.86),
        "short_term_strength": _band(f("return_3"), 0.008, 0.065, 0.055),
        "five_day_strength": _band(f("return_5"), 0.012, 0.10, 0.075),
        "rebound_from_low": _band(
            f("rebound_from_10_low"), 0.018, 0.10, 0.075
        ),
        "near_short_average": _band(f("ma10_extension"), -0.015, 0.065, 0.06),
        "uptrend_context": _band(f("trend_slope_60"), 0.04, 0.42, 0.25),
        "not_stale_range": 1.0
        - _ramp(f("range_staleness_60"), 0.42, 0.75),
        "whole_path_not_broken": 1.0
        - _ramp(float(path["max_drawdown_120"]), 0.12, 0.24),
    }
    weights = {
        "clear_prior_advance": 2.5,
        "controlled_depth": 2.5,
        "visible_recent_pullback": 3.0,
        "recent_low_timing": 2.0,
        "recovery_in_progress": 2.5,
        "controlled_duration": 1.5,
        "controlled_speed": 1.5,
        "proportionate_retracement": 2.0,
        "no_fast_collapse": 2.0,
        "turn_is_visible": 3.0,
        "short_term_strength": 1.5,
        "five_day_strength": 1.25,
        "rebound_from_low": 1.25,
        "near_short_average": 1.0,
        "uptrend_context": 1.5,
        "not_stale_range": 1.0,
        "whole_path_not_broken": 1.5,
    }
    score = _weighted_score(components, weights)
    hard_findings = []
    if f("prior_advance_before_peak") < 0.12:
        hard_findings.append("no_clear_prior_advance")
    if f("drawdown_60") > 0.18:
        hard_findings.append("pullback_too_deep")
    if float(path["recent_pullback_depth_40"]) < 0.025:
        hard_findings.append("no_visible_recent_pullback")
    if float(path["recent_pullback_depth_40"]) > 0.18:
        hard_findings.append("recent_pullback_too_deep")
    if float(path["recent_pullback_low_age"]) > 18:
        hard_findings.append("recent_pullback_already_too_old")
    if float(path["recent_recovery_fraction"]) < 0.15:
        hard_findings.append("recovery_not_started")
    if float(path["recent_recovery_fraction"]) > 1.25:
        hard_findings.append("recovery_already_became_new_leg")
    if f("retracement_of_prior_advance") > 0.65:
        hard_findings.append("prior_advance_mostly_erased")
    if f("pullback_duration_60") > 27:
        hard_findings.append("pullback_too_long")
    if f("worst_5day_return_20") < -0.14:
        hard_findings.append("pullback_too_fast")
    if f("turn_confirmation") < 0.40:
        hard_findings.append("no_turn_confirmation")
    if f("return_3") < -0.02:
        hard_findings.append("still_weak_at_score_date")
    if f("trend_slope_60") < -0.06:
        hard_findings.append("mid_trend_broken")
    if float(path["max_drawdown_120"]) > 0.27:
        hard_findings.append("whole_path_drawdown_too_large")
    if hard_findings:
        score *= 0.20
    diagnostics = {
        "prior_advance_before_peak": f("prior_advance_before_peak"),
        "drawdown_60": f("drawdown_60"),
        "pullback_duration_60": f("pullback_duration_60"),
        "pullback_speed_60": f("pullback_speed_60"),
        "retracement_of_prior_advance": f("retracement_of_prior_advance"),
        "worst_5day_return_20": f("worst_5day_return_20"),
        "turn_confirmation": f("turn_confirmation"),
        "return_3": f("return_3"),
        "return_5": f("return_5"),
        "rebound_from_10_low": f("rebound_from_10_low"),
        "ma10_extension": f("ma10_extension"),
        "trend_slope_60": f("trend_slope_60"),
        "max_drawdown_120": float(path["max_drawdown_120"]),
        "recent_pullback_depth_40": float(path["recent_pullback_depth_40"]),
        "recent_pullback_low_age": float(path["recent_pullback_low_age"]),
        "recent_recovery_fraction": float(path["recent_recovery_fraction"]),
    }
    return {
        "score": round(float(score), 8),
        "components": {key: round(value, 8) for key, value in components.items()},
        "hard_findings": hard_findings,
        "diagnostics": {
            key: round(float(value), 8) for key, value in diagnostics.items()
        },
    }


SCORERS: dict[
    str, Callable[[dict[str, float], dict[str, float]], dict[str, Any]]
] = {
    "fresh_breakout": breakout_segment_prefilter,
    "pullback_strengthening": pullback_segment_prefilter,
}


def _diagnostic_text(category: str, diagnostics: dict[str, float]) -> str:
    if category == "fresh_breakout":
        return (
            f"突破年龄 {diagnostics['breakout_age']:.0f}根 · "
            f"压力窗口 {diagnostics['breakout_resistance_window']:.0f}日 · "
            f"当前高于压力 {diagnostics['breakout_current_margin']:.1%} · "
            f"突破后回撤 {diagnostics['breakout_post_event_drawdown']:.1%} · "
            f"突破量比 {diagnostics['breakout_volume_ratio']:.2f}"
        )
    return (
        f"前段涨幅 {diagnostics['prior_advance_before_peak']:.1%} · "
        f"回调深度 {diagnostics['drawdown_60']:.1%} · "
        f"回调时长 {diagnostics['pullback_duration_60']:.0f}根 · "
        f"转强确认 {diagnostics['turn_confirmation']:.2f} · "
        f"近3日 {diagnostics['return_3']:.1%}"
    )


def _render_index(
    category: str,
    rows: list[dict[str, Any]],
    snapshot: str,
    scanned_window_count: int,
) -> str:
    spec = CATEGORY_SPECS[category]
    cards = []
    for rank, item in enumerate(rows, 1):
        sample = item["sample"]
        cards.append(
            f"""<article>
<h2>#{rank} · {escape(sample['sample_id'])} · 候选分 {item['analysis']['score']:.3f}</h2>
<p>{escape(_diagnostic_text(category, item['analysis']['diagnostics']))}</p>
<img src="charts/{escape(sample['sample_id'])}.svg" alt="{escape(sample['sample_id'])}">
</article>"""
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>{spec['label']} · 历史区间候选</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f7fa;color:#162033}}
main{{max-width:1120px;margin:auto;padding:24px}}header,article{{background:#fff;border-radius:14px;padding:18px;margin:16px 0}}
img{{width:100%;display:block}}p{{color:#526079;line-height:1.7}}.warn{{background:#fff6db;padding:12px;border-radius:10px}}
</style></head><body><main><header><h1>{spec['label']} · 历史区间候选</h1>
<p class="warn">这是独立 template 分区的模子候选，不是封存评估。评分器只服务
“{spec['label']}”，不会复用健康上升趋势的门槛。</p>
<p>从 {scanned_window_count:,} 个历史120根K线区间中筛选；数据仅来自本机 zer0share
快照 {snapshot}；不使用未来数据；同一股票只保留一个区间。</p>
</header>{''.join(cards)}</main></body></html>"""


def main() -> int:
    args = parse_args()
    if args.count < 20:
        raise ValueError("count must be at least 20")
    if args.history_bars < 240:
        raise ValueError("history-bars must be at least 240")
    if args.endpoint_step < 5:
        raise ValueError("endpoint-step must be at least 5")
    if args.research_version < 1:
        raise ValueError("research-version must be positive")
    output_root = (
        args.output_root
        or (
            PROJECT_ROOT
            / "outputs"
            / "shape-v2"
            / f"template-discovery-v{args.research_version}"
        )
    ).resolve()
    if PROJECT_ROOT.resolve() not in output_root.parents:
        raise ValueError("output root must stay inside the project")
    active_specs = {}
    for category in args.categories:
        base = CATEGORY_SPECS[category]
        slug = str(base["slug"])
        active_specs[category] = {
            **base,
            "dataset_version": (
                f"shape-v2.0.0-template-segments{args.research_version}-"
                f"{slug.removesuffix('-segments')}"
            ),
            "audit_name": (
                f"template-discovery-v{args.research_version}-{slug}-audit.json"
            ),
        }
    outputs = {
        category: output_root / str(spec["slug"])
        for category, spec in active_specs.items()
    }
    for output in outputs.values():
        if output.exists() and any(output.iterdir()):
            raise FileExistsError(f"output directory is not empty: {output}")
        output.mkdir(parents=True, exist_ok=True)

    secret = (PRIVATE_ROOT / "anonymization.key").read_bytes()
    config = json.loads(
        (
            PROJECT_ROOT / "config" / "shape_v2" / "research-v2.0.0-draft3.json"
        ).read_text(encoding="utf-8")
    )
    settings = load_settings()
    repository = LocalMarketRepository(settings.zer0share_root, settings.zer0share_config)
    try:
        snapshots = repository.snapshots()
        if snapshots.daily_kline is None or snapshots.adj_factor is None:
            raise FileNotFoundError("local daily_kline and adj_factor snapshots are required")
        end_date = str(args.end_date or snapshots.daily_kline).replace("-", "")
        end_date = min(end_date, snapshots.daily_kline, snapshots.adj_factor)
        excluded = _excluded_codes()
        basic = repository.basic().copy()
        basic = basic[
            basic["list_status"].astype(str).eq("L")
            & basic["market"].astype(str).isin({"主板", "创业板", "科创板"})
        ]
        split_weights = config["split_policy"]["weights"]
        codes = sorted(
            code
            for code in basic["ts_code"].astype(str)
            if code not in excluded
            and assign_research_split(
                source_group_id(secret, code), split_weights
            )
            == "template"
        )
        dates = repository.trading_dates(end_date, limit=args.history_bars)
        history = load_bulk_candidate_history(repository, codes, dates[0], end_date)
        grouped = {
            str(code): frame.sort_values("trade_date").reset_index(drop=True)
            for code, frame in history.groupby("ts_code", sort=False)
        }
        best: dict[str, dict[str, dict[str, Any]]] = {
            category: {} for category in active_specs
        }
        scanned_window_count = 0
        failures: list[str] = []
        for code in codes:
            frame = grouped.get(code)
            if frame is None or len(frame) < 120:
                failures.append(f"{code}: fewer than 120 rows")
                continue
            for endpoint_index in _candidate_endpoint_indices(
                len(frame), args.endpoint_step
            ):
                score_date = str(frame.iloc[endpoint_index]["trade_date"])[:8]
                window_frame = frame.iloc[endpoint_index - 119 : endpoint_index + 1]
                try:
                    bars, _ = build_public_bars(
                        window_frame, score_date, window_bars=120
                    )
                    facts = extract_shared_facts(bars)
                    path = path_risk_metrics(bars)
                except (ValueError, TypeError) as exc:
                    failures.append(f"{code}@{score_date}: {exc}")
                    continue
                scanned_window_count += 1
                for category in active_specs:
                    scorer = SCORERS[category]
                    analysis = scorer(facts, path)
                    item = {
                        "code": code,
                        "score_date": score_date,
                        "endpoint_index": endpoint_index,
                        "analysis": analysis,
                    }
                    prior = best[category].get(code)
                    if prior is None or (
                        analysis["score"],
                        score_date,
                    ) > (
                        prior["analysis"]["score"],
                        prior["score_date"],
                    ):
                        best[category][code] = item

        result_summary: dict[str, Any] = {}
        for category, spec in active_specs.items():
            eligible = [
                item
                for item in best[category].values()
                if not item["analysis"]["hard_findings"]
            ]
            selected_records = sorted(
                eligible,
                key=lambda item: (
                    -float(item["analysis"]["score"]),
                    item["code"],
                    item["score_date"],
                ),
            )[: args.count]
            if len(selected_records) < args.count:
                raise RuntimeError(
                    f"{category}: only {len(selected_records)} strict candidates"
                )

            output = outputs[category]
            (output / "samples").mkdir()
            (output / "charts").mkdir()
            selected: list[dict[str, Any]] = []
            private_samples = []
            for record in selected_records:
                code = record["code"]
                endpoint_index = int(record["endpoint_index"])
                score_date = str(record["score_date"])
                window_frame = grouped[code].iloc[
                    endpoint_index - 119 : endpoint_index + 1
                ]
                bars, private = build_public_bars(
                    window_frame, score_date, window_bars=120
                )
                sample_id = anonymous_id(
                    secret, str(spec["dataset_version"]), code, score_date
                )
                sample = build_public_sample(
                    sample_id,
                    str(spec["dataset_version"]),
                    "template",
                    bars,
                )
                item = {"sample": sample, "analysis": record["analysis"]}
                selected.append(item)
                _write_json(output / "samples" / f"{sample_id}.json", sample)
                (output / "charts" / f"{sample_id}.svg").write_text(
                    render_svg(sample), encoding="utf-8"
                )
                private_samples.append(
                    {
                        "sample_id": sample_id,
                        "split": "template",
                        "source_group_id": source_group_id(secret, code),
                        "ts_code": code,
                        "requested_score_date": score_date,
                        "resolved_score_date": private["resolved_score_date"],
                        "source_trade_dates": private["source_trade_dates"],
                        "public_content_hash": content_hash(sample),
                    }
                )

            rankings = [
                {
                    "rank": rank,
                    "sample_id": item["sample"]["sample_id"],
                    **item["analysis"],
                }
                for rank, item in enumerate(selected, 1)
            ]
            manifest = {
                "schema_version": "shape-v2-template-segment-mining/1",
                "dataset_version": spec["dataset_version"],
                "category": category,
                "role": "template",
                "status": "visual_review_pending",
                "source": "local zer0share offline snapshot",
                "source_snapshot": end_date,
                "network_used": False,
                "history_bars": args.history_bars,
                "endpoint_step": args.endpoint_step,
                "security_pool_count": len(codes),
                "scanned_window_count": scanned_window_count,
                "one_segment_per_security": True,
                "eligible_security_count": len(eligible),
                "sample_count": len(selected),
                "samples": [
                    {
                        "sample_id": item["sample"]["sample_id"],
                        "split": "template",
                        "content_hash": content_hash(item["sample"]),
                    }
                    for item in selected
                ],
            }
            manifest["dataset_fingerprint"] = content_hash(manifest)
            audit = {
                "schema_version": "shape-v2-private-audit/1",
                "dataset_version": spec["dataset_version"],
                "category": category,
                "role": "template",
                "seed": "stable_hmac_split",
                "source": {
                    "provider": "local_zer0share",
                    "network_used": False,
                    "snapshots": snapshots.as_dict(),
                },
                "samples": private_samples,
                "selection": f"historical_120_bar_{category}_independent_v2",
                "history_bars": args.history_bars,
                "endpoint_step": args.endpoint_step,
                "security_pool_count": len(codes),
                "scanned_window_count": scanned_window_count,
                "eligible_security_count": len(eligible),
                "one_segment_per_security": True,
                "candidate_failure_count": len(failures),
                "candidate_failures_preview": failures[:200],
                "generated_at": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
            }
            findings = validate_audit_manifest(audit)
            if findings:
                raise RuntimeError(
                    f"{category} leakage audit failed: " + "; ".join(findings)
                )
            _write_json(output / "manifest.json", manifest)
            _write_json(output / "rankings.json", rankings)
            (output / "index.html").write_text(
                _render_index(category, selected, end_date, scanned_window_count),
                encoding="utf-8",
            )
            audit_path = PRIVATE_ROOT / "audits" / str(spec["audit_name"])
            if audit_path.exists():
                raise FileExistsError(f"private audit already exists: {audit_path}")
            _write_json(audit_path, audit)
            result_summary[category] = {
                "review": str(output / "index.html"),
                "private_audit": str(audit_path),
                "eligible_security_count": len(eligible),
                "selected_count": len(selected),
                "leakage_findings": findings,
            }

        print(
            canonical_json(
                {
                    "ok": True,
                    "source_snapshot": end_date,
                    "network_used": False,
                    "security_pool_count": len(codes),
                    "scanned_window_count": scanned_window_count,
                    "categories": result_summary,
                }
            )
        )
        return 0
    finally:
        repository._duck.close()


if __name__ == "__main__":
    raise SystemExit(main())
