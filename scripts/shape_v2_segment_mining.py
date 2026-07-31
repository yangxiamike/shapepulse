from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.shape_v2_dataset import load_bulk_candidate_history, render_svg
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


PRIVATE_ROOT = PROJECT_ROOT / "outputs" / "shape-v2" / ".private"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "template-discovery-v2"
    / "healthy-uptrend-segments"
)
DATASET_VERSION = "shape-v2.0.0-template-segments2-healthy-uptrend"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine historical 120-bar healthy-uptrend template segments."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--history-bars", type=int, default=620)
    parser.add_argument("--endpoint-step", type=int, default=15)
    return parser.parse_args()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _ramp(value: float, low: float, high: float) -> float:
    if math.isclose(low, high):
        return float(value >= high)
    return _clip((value - low) / (high - low))


def _band(value: float, low: float, high: float, softness: float) -> float:
    if low <= value <= high:
        return 1.0
    if value < low:
        return _clip(1.0 - (low - value) / softness)
    return _clip(1.0 - (value - high) / softness)


def path_risk_metrics(bars: list[dict[str, float]]) -> dict[str, float]:
    """Measure drawdown across the whole visible path, without future bars."""
    close = np.asarray([float(bar["close"]) for bar in bars], dtype=float)
    if len(close) != 120 or np.any(~np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("path metrics require 120 finite positive closes")

    def max_drawdown(values: np.ndarray) -> float:
        peaks = np.maximum.accumulate(values)
        return float(np.max(1.0 - values / peaks))

    def worst_return(days: int) -> float:
        returns = close[days:] / close[:-days] - 1.0
        return float(np.min(returns))

    anchor_indices = np.arange(0, 120, 10)
    anchors = close[anchor_indices]
    anchor_up_ratio = float(np.mean(anchors[1:] > anchors[:-1]))
    recent = close[-40:]
    running_peaks = np.maximum.accumulate(recent)
    recent_drawdowns = 1.0 - recent / running_peaks
    trough_index = int(np.argmax(recent_drawdowns))
    peak_index = int(np.argmax(recent[: trough_index + 1]))
    recent_peak = float(recent[peak_index])
    recent_trough = float(recent[trough_index])
    pullback_span = recent_peak - recent_trough
    recovery_fraction = (
        float((recent[-1] - recent_trough) / pullback_span)
        if pullback_span > 0
        else 0.0
    )
    return {
        "max_drawdown_120": max_drawdown(close),
        "max_drawdown_60": max_drawdown(close[-60:]),
        "worst_return_5": worst_return(5),
        "worst_return_10": worst_return(10),
        "anchor_up_ratio": anchor_up_ratio,
        "recent_pullback_depth_40": float(recent_drawdowns[trough_index]),
        "recent_pullback_low_age": float(len(recent) - 1 - trough_index),
        "recent_recovery_fraction": recovery_fraction,
    }


def healthy_segment_prefilter(
    facts: dict[str, float], path: dict[str, float]
) -> dict[str, Any]:
    """Strict visual prior for complete, low-drawdown 120-bar uptrends."""
    def f(key: str, default: float = 0.0) -> float:
        return float(facts.get(key, default))

    def p(key: str) -> float:
        return float(path[key])

    total_return = max(f("return_119"), 0.05)
    terminal_concentration = max(0.0, f("return_20")) / total_return
    components = {
        "full_window_rise": _band(f("return_119"), 0.20, 0.72, 0.22),
        "mid_window_rise": _band(f("return_60"), 0.10, 0.38, 0.16),
        "rise_exists_before_tail": _ramp(
            f("prior_return_60_ex_last_10"), 0.06, 0.22
        ),
        "full_window_fit": _ramp(f("trend_fit_120"), 0.55, 0.86),
        "mid_window_fit": _ramp(f("trend_fit_60"), 0.55, 0.86),
        "controlled_full_drawdown": 1.0
        - _ramp(p("max_drawdown_120"), 0.075, 0.145),
        "controlled_recent_drawdown": 1.0
        - _ramp(p("max_drawdown_60"), 0.055, 0.12),
        "no_fast_break": _ramp(p("worst_return_10"), -0.13, -0.045),
        "moderate_recent_volatility": 1.0
        - _ramp(f("volatility_20"), 0.022, 0.040),
        "moderate_mid_volatility": 1.0
        - _ramp(f("volatility_60"), 0.024, 0.042),
        "not_single_spike": 1.0
        - _ramp(f("largest_up_day_share_20"), 0.24, 0.45),
        "not_terminally_overextended": _band(
            f("ma20_extension"), -0.02, 0.085, 0.07
        ),
        "rise_not_tail_only": _band(terminal_concentration, 0.08, 0.55, 0.25),
        "stepwise_progress": _ramp(p("anchor_up_ratio"), 0.55, 0.82),
        "moving_average_order": _ramp(f("ma_alignment"), 0.72, 1.0),
    }
    weights = {
        "full_window_rise": 1.5,
        "mid_window_rise": 1.0,
        "rise_exists_before_tail": 1.75,
        "full_window_fit": 2.0,
        "mid_window_fit": 1.25,
        "controlled_full_drawdown": 3.5,
        "controlled_recent_drawdown": 2.5,
        "no_fast_break": 2.0,
        "moderate_recent_volatility": 1.25,
        "moderate_mid_volatility": 1.25,
        "not_single_spike": 1.0,
        "not_terminally_overextended": 1.0,
        "rise_not_tail_only": 1.5,
        "stepwise_progress": 1.5,
        "moving_average_order": 1.0,
    }
    score = sum(components[key] * weights[key] for key in components) / sum(
        weights.values()
    )
    hard_findings = []
    if p("max_drawdown_120") > 0.145:
        hard_findings.append("full_path_drawdown_too_large")
    if p("max_drawdown_60") > 0.12:
        hard_findings.append("recent_drawdown_too_large")
    if p("worst_return_10") < -0.13:
        hard_findings.append("fast_break_too_deep")
    if f("return_119") < 0.18:
        hard_findings.append("insufficient_full_window_rise")
    if f("trend_fit_120") < 0.50:
        hard_findings.append("weak_full_window_continuity")
    if f("prior_return_60_ex_last_10") < 0.04:
        hard_findings.append("rise_not_established_before_tail")
    if terminal_concentration > 0.68:
        hard_findings.append("rise_too_concentrated_near_tail")
    if f("volatility_60") > 0.045:
        hard_findings.append("mid_window_volatility_too_high")
    if hard_findings:
        score *= 0.20
    diagnostics = {
        **{key: round(float(value), 8) for key, value in path.items()},
        "terminal_concentration": round(terminal_concentration, 8),
        "return_119": f("return_119"),
        "return_60": f("return_60"),
        "prior_return_60_ex_last_10": f("prior_return_60_ex_last_10"),
        "trend_fit_120": f("trend_fit_120"),
        "trend_fit_60": f("trend_fit_60"),
        "volatility_20": f("volatility_20"),
        "volatility_60": f("volatility_60"),
    }
    return {
        "score": round(float(score), 8),
        "components": {key: round(value, 8) for key, value in components.items()},
        "hard_findings": hard_findings,
        "diagnostics": diagnostics,
    }


def _excluded_codes() -> set[str]:
    paths = [
        PRIVATE_ROOT / "audits" / f"calibration-draft{draft}-audit.json"
        for draft in (1, 2, 3)
    ]
    paths.append(PRIVATE_ROOT / "audits" / "baseline-v1.1-tuning-review-audit.json")
    codes: set[str] = set()
    for path in paths:
        if path.exists():
            audit = json.loads(path.read_text(encoding="utf-8"))
            codes.update(str(item["ts_code"]) for item in audit.get("samples", []))
    return codes


def _candidate_endpoint_indices(row_count: int, step: int) -> list[int]:
    indices = list(range(119, row_count, step))
    if row_count >= 120 and indices[-1] != row_count - 1:
        indices.append(row_count - 1)
    return indices


def _render_index(rows: list[dict[str, Any]], snapshot: str) -> str:
    cards = []
    for index, item in enumerate(rows, 1):
        sample = item["sample"]
        d = item["analysis"]["diagnostics"]
        cards.append(
            f"""<article>
<h2>#{index} · {sample['sample_id']} · 区间候选分 {item['analysis']['score']:.3f}</h2>
<p>整段最大回撤 {d['max_drawdown_120']:.1%}；近60日最大回撤 {d['max_drawdown_60']:.1%}；
最差10日 {d['worst_return_10']:.1%}；120日涨幅 {d['return_119']:.1%}；
趋势连续度 {d['trend_fit_120']:.3f}；末端涨幅集中度 {d['terminal_concentration']:.1%}</p>
<img src="charts/{sample['sample_id']}.svg" alt="{sample['sample_id']}">
</article>"""
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>健康上升趋势 · 历史区间候选</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f7fa;color:#162033}}
main{{max-width:1120px;margin:auto;padding:24px}}
header,article{{background:#fff;border-radius:14px;padding:18px;margin:16px 0;box-shadow:0 4px 16px #17203312}}
img{{width:100%;display:block}}p{{color:#526079;line-height:1.7}}
.warn{{color:#9a5a00;background:#fff6db;padding:12px;border-radius:10px}}
</style></head><body><main><header>
<h1>健康上升趋势 · 历史区间候选</h1>
<p class="warn">这是“历史区间挖掘”的候选页，不是最终封存模板。旧版固定看 20260727 末端；
本版在独立 template 分区里滚动寻找 120 根K线片段，并把整段大回撤设为硬矛盾。</p>
<p>数据仅来自本机 zer0share 快照 {snapshot}；每个片段只使用评分日及以前数据；
同一股票只保留一个得分最高片段。</p>
</header>{''.join(cards)}</main></body></html>"""


def main() -> int:
    args = parse_args()
    if args.count < 20:
        raise ValueError("count must be at least 20")
    if args.history_bars < 240:
        raise ValueError("history-bars must be at least 240")
    if args.endpoint_step < 5:
        raise ValueError("endpoint-step must be at least 5")
    output = args.output.resolve()
    if PROJECT_ROOT.resolve() not in output.parents:
        raise ValueError("output must stay inside the project")
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
        weights = config["split_policy"]["weights"]
        codes = sorted(
            code
            for code in basic["ts_code"].astype(str)
            if code not in excluded
            and assign_research_split(source_group_id(secret, code), weights)
            == "template"
        )
        dates = repository.trading_dates(end_date, limit=args.history_bars)
        history = load_bulk_candidate_history(repository, codes, dates[0], end_date)
        grouped = {
            str(code): frame.sort_values("trade_date").reset_index(drop=True)
            for code, frame in history.groupby("ts_code", sort=False)
        }

        best_by_code: list[dict[str, Any]] = []
        scanned_window_count = 0
        failures: list[str] = []
        for code in codes:
            frame = grouped.get(code)
            if frame is None or len(frame) < 120:
                failures.append(f"{code}: fewer than 120 rows")
                continue
            best: dict[str, Any] | None = None
            for endpoint_index in _candidate_endpoint_indices(
                len(frame), args.endpoint_step
            ):
                score_date = str(frame.iloc[endpoint_index]["trade_date"])[:8]
                window_frame = frame.iloc[endpoint_index - 119 : endpoint_index + 1]
                try:
                    bars, private = build_public_bars(
                        window_frame, score_date, window_bars=120
                    )
                    sample_id = anonymous_id(
                        secret, DATASET_VERSION, code, score_date
                    )
                    sample = build_public_sample(
                        sample_id, DATASET_VERSION, "template", bars
                    )
                    path = path_risk_metrics(bars)
                    analysis = healthy_segment_prefilter(
                        sample["shared_facts"], path
                    )
                except (ValueError, TypeError) as exc:
                    failures.append(f"{code}@{score_date}: {exc}")
                    continue
                scanned_window_count += 1
                item = {
                    "sample": sample,
                    "analysis": analysis,
                    "private": {
                        "sample_id": sample_id,
                        "split": "template",
                        "source_group_id": source_group_id(secret, code),
                        "ts_code": code,
                        "requested_score_date": score_date,
                        "resolved_score_date": private["resolved_score_date"],
                        "source_trade_dates": private["source_trade_dates"],
                    },
                }
                if best is None or (
                    item["analysis"]["score"],
                    item["sample"]["sample_id"],
                ) > (
                    best["analysis"]["score"],
                    best["sample"]["sample_id"],
                ):
                    best = item
            if best is not None:
                best_by_code.append(best)

        eligible = [
            item
            for item in best_by_code
            if not item["analysis"]["hard_findings"]
        ]
        selected = sorted(
            eligible,
            key=lambda item: (
                -float(item["analysis"]["score"]),
                item["sample"]["sample_id"],
            ),
        )[: args.count]
        if len(selected) < args.count:
            raise RuntimeError(
                f"only {len(selected)} candidates pass strict path constraints"
            )

        (output / "samples").mkdir()
        (output / "charts").mkdir()
        public_rankings = []
        private_samples = []
        for rank, item in enumerate(selected, 1):
            sample = item["sample"]
            _write_json(output / "samples" / f"{sample['sample_id']}.json", sample)
            (output / "charts" / f"{sample['sample_id']}.svg").write_text(
                render_svg(sample), encoding="utf-8"
            )
            public_rankings.append(
                {
                    "rank": rank,
                    "sample_id": sample["sample_id"],
                    **item["analysis"],
                }
            )
            private = dict(item["private"])
            private["public_content_hash"] = content_hash(sample)
            private_samples.append(private)

        manifest = {
            "schema_version": "shape-v2-template-segment-mining/1",
            "dataset_version": DATASET_VERSION,
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
            "dataset_version": DATASET_VERSION,
            "role": "template",
            "seed": "stable_hmac_split",
            "source": {
                "provider": "local_zer0share",
                "network_used": False,
                "snapshots": snapshots.as_dict(),
            },
            "samples": private_samples,
            "selection": "historical_120_bar_segment_mining_strict_path_v2",
            "history_bars": args.history_bars,
            "endpoint_step": args.endpoint_step,
            "security_pool_count": len(codes),
            "scanned_window_count": scanned_window_count,
            "eligible_security_count": len(eligible),
            "one_segment_per_security": True,
            "candidate_failure_count": len(failures),
            "candidate_failures_preview": failures[:200],
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        findings = validate_audit_manifest(audit)
        if findings:
            raise RuntimeError("leakage audit failed: " + "; ".join(findings))

        _write_json(output / "manifest.json", manifest)
        _write_json(output / "rankings.json", public_rankings)
        (output / "index.html").write_text(
            _render_index(selected, end_date), encoding="utf-8"
        )
        audit_path = (
            PRIVATE_ROOT
            / "audits"
            / "template-discovery-v2-healthy-uptrend-segments-audit.json"
        )
        if audit_path.exists():
            raise FileExistsError(f"private audit already exists: {audit_path}")
        _write_json(audit_path, audit)
        print(
            canonical_json(
                {
                    "ok": True,
                    "output": str(output),
                    "review": str(output / "index.html"),
                    "private_audit": str(audit_path),
                    "source_snapshot": end_date,
                    "network_used": False,
                    "security_pool_count": len(codes),
                    "scanned_window_count": scanned_window_count,
                    "eligible_security_count": len(eligible),
                    "selected_count": len(selected),
                    "leakage_findings": findings,
                }
            )
        )
        return 0
    finally:
        repository._duck.close()


if __name__ == "__main__":
    raise SystemExit(main())
