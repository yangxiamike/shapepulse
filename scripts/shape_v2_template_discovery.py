from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


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
    / "template-discovery-v1"
    / "healthy-uptrend"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover independent healthy-uptrend template candidates."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _ramp(value: float, low: float, high: float) -> float:
    return _clip((value - low) / (high - low))


def _band(value: float, low: float, high: float, softness: float) -> float:
    if low <= value <= high:
        return 1.0
    if value < low:
        return _clip(1.0 - (low - value) / softness)
    return _clip(1.0 - (value - high) / softness)


def healthy_visual_prefilter(facts: dict[str, float]) -> dict[str, Any]:
    """Broad visual prior that avoids selecting only terminal high-volatility moves."""
    f = lambda key, default=0.0: float(facts.get(key, default))
    total_return = max(f("return_119"), 0.05)
    terminal_concentration = max(0.0, f("return_20")) / total_return
    components = {
        "full_window_rise": _band(f("return_119"), 0.20, 0.90, 0.25),
        "mid_window_rise": _band(f("return_60"), 0.12, 0.48, 0.18),
        "rise_exists_before_tail": _ramp(f("prior_return_60_ex_last_10"), 0.06, 0.24),
        "full_window_fit": _ramp(f("trend_fit_120"), 0.38, 0.78),
        "mid_window_fit": _ramp(f("trend_fit_60"), 0.50, 0.86),
        "positive_mid_slope": _band(f("trend_slope_60"), 0.10, 0.42, 0.18),
        "positive_full_slope": _band(f("trend_slope_120"), 0.12, 0.65, 0.25),
        "moving_average_order": _ramp(f("ma_alignment"), 0.70, 1.0),
        "controlled_drawdown": 1.0 - _ramp(f("drawdown_60"), 0.10, 0.23),
        "not_range_bound": 1.0 - _ramp(f("range_staleness_60"), 0.42, 0.78),
        "moderate_recent_volatility": 1.0 - _ramp(f("volatility_20"), 0.026, 0.050),
        "moderate_mid_volatility": 1.0 - _ramp(f("volatility_60"), 0.028, 0.052),
        "not_single_spike": 1.0 - _ramp(f("largest_up_day_share_20"), 0.25, 0.52),
        "not_terminally_overextended": _band(f("ma20_extension"), 0.0, 0.10, 0.08),
        "rise_not_tail_only": _band(terminal_concentration, 0.12, 0.62, 0.35),
        "balanced_positive_days": _band(f("positive_day_ratio_60"), 0.50, 0.68, 0.14),
    }
    weights = {
        "full_window_rise": 1.5,
        "mid_window_rise": 1.5,
        "rise_exists_before_tail": 2.0,
        "full_window_fit": 2.0,
        "mid_window_fit": 2.0,
        "positive_mid_slope": 1.5,
        "positive_full_slope": 1.5,
        "moving_average_order": 1.5,
        "controlled_drawdown": 1.5,
        "not_range_bound": 1.5,
        "moderate_recent_volatility": 1.25,
        "moderate_mid_volatility": 1.25,
        "not_single_spike": 1.5,
        "not_terminally_overextended": 1.25,
        "rise_not_tail_only": 2.0,
        "balanced_positive_days": 0.75,
    }
    weighted_score = sum(components[key] * weights[key] for key in components)
    score = weighted_score / sum(weights.values())
    hard_findings = []
    if f("prior_return_60_ex_last_10") <= 0:
        hard_findings.append("rise_only_near_tail")
    if f("volatility_20") >= 0.055:
        hard_findings.append("terminal_volatility_too_high")
    if f("largest_up_day_share_20") >= 0.55:
        hard_findings.append("single_spike_dominated")
    if f("range_staleness_60") >= 0.80:
        hard_findings.append("stale_range")
    if f("trend_slope_120") <= 0 or f("return_119") <= 0:
        hard_findings.append("no_full_window_rise")
    if hard_findings:
        score *= 0.35
    return {
        "score": round(float(score), 8),
        "components": {key: round(value, 8) for key, value in components.items()},
        "hard_findings": hard_findings,
        "diagnostics": {
            "terminal_concentration": round(terminal_concentration, 8),
            "volatility_20": f("volatility_20"),
            "volatility_60": f("volatility_60"),
            "largest_up_day_share_20": f("largest_up_day_share_20"),
            "ma20_extension": f("ma20_extension"),
            "return_119": f("return_119"),
            "return_60": f("return_60"),
            "prior_return_60_ex_last_10": f("prior_return_60_ex_last_10"),
            "trend_fit_120": f("trend_fit_120"),
            "trend_fit_60": f("trend_fit_60"),
            "drawdown_60": f("drawdown_60"),
        },
    }


def _excluded_codes() -> set[str]:
    paths = [
        PRIVATE_ROOT / "audits" / f"calibration-draft{draft}-audit.json"
        for draft in (1, 2, 3)
    ]
    paths.append(PRIVATE_ROOT / "audits" / "baseline-v1.1-tuning-review-audit.json")
    codes: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        audit = json.loads(path.read_text(encoding="utf-8"))
        codes.update(str(item["ts_code"]) for item in audit.get("samples", []))
    return codes


def _render_index(rows: list[dict[str, Any]], snapshot: str) -> str:
    cards = []
    for index, item in enumerate(rows, 1):
        sample = item["sample"]
        analysis = item["analysis"]
        diagnostics = analysis["diagnostics"]
        cards.append(
            f"""<article>
<h2>#{index} · {sample['sample_id']} · 独立视觉预筛 {analysis['score']:.3f}</h2>
<p>120日涨幅 {diagnostics['return_119']:.1%}；60日涨幅 {diagnostics['return_60']:.1%}；
前段60日涨幅 {diagnostics['prior_return_60_ex_last_10']:.1%}；20日波动 {diagnostics['volatility_20']:.2%}；
60日回撤 {diagnostics['drawdown_60']:.1%}</p>
<img src="charts/{sample['sample_id']}.svg" alt="{sample['sample_id']}">
</article>"""
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>健康趋势独立模板候选</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f4f7fa;color:#162033}}main{{max-width:1120px;margin:auto;padding:24px}}
header,article{{background:#fff;border-radius:14px;padding:18px;margin:16px 0;box-shadow:0 4px 16px #17203312}}img{{width:100%;display:block}}p{{color:#526079}}</style>
</head><body><main><header><h1>健康上升趋势 · 独立模板候选</h1>
<p>来源：独立 template 分区；本机快照 {snapshot}。预筛优先完整120日上升、前段已有趋势、低至中等波动和受控回撤，压低尾端暴冲与单点尖峰。</p>
</header>{''.join(cards)}</main></body></html>"""


def main() -> int:
    args = parse_args()
    if args.count < 10:
        raise ValueError("count must be at least 10")
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
        dates = repository.trading_dates(end_date, limit=180)
        history = load_bulk_candidate_history(repository, codes, dates[0], end_date)
        grouped = {
            str(code): frame.copy()
            for code, frame in history.groupby("ts_code", sort=False)
        }
        candidates = []
        failures = []
        dataset_version = "shape-v2.0.0-template-discovery1-healthy-uptrend"
        for code in codes:
            frame = grouped.get(code)
            if frame is None:
                failures.append(f"{code}: no rows")
                continue
            try:
                bars, private = build_public_bars(frame, end_date, window_bars=120)
            except ValueError as exc:
                failures.append(f"{code}: {exc}")
                continue
            if private["resolved_score_date"] != end_date:
                failures.append(f"{code}: stale latest bar")
                continue
            sample_id = anonymous_id(secret, dataset_version, code, end_date)
            sample = build_public_sample(sample_id, dataset_version, "template", bars)
            analysis = healthy_visual_prefilter(sample["shared_facts"])
            candidates.append(
                {
                    "sample": sample,
                    "analysis": analysis,
                    "private": {
                        "sample_id": sample_id,
                        "split": "template",
                        "source_group_id": source_group_id(secret, code),
                        "ts_code": code,
                        "requested_score_date": end_date,
                        "resolved_score_date": end_date,
                        "source_trade_dates": private["source_trade_dates"],
                    },
                }
            )
        selected = sorted(
            candidates,
            key=lambda item: (
                -float(item["analysis"]["score"]),
                item["sample"]["sample_id"],
            ),
        )[: args.count]
        if len(selected) < args.count:
            raise RuntimeError(f"only {len(selected)} valid template candidates")
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
            "schema_version": "shape-v2-template-discovery/1",
            "dataset_version": dataset_version,
            "role": "template",
            "status": "visual_review_pending",
            "source": "local zer0share offline snapshot",
            "source_snapshot": end_date,
            "network_used": False,
            "candidate_pool_count": len(candidates),
            "sample_count": len(selected),
            "excluded_prior_review_security_count": len(excluded),
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
            "dataset_version": dataset_version,
            "role": "template",
            "seed": "stable_hmac_split",
            "source": {
                "provider": "local_zer0share",
                "network_used": False,
                "snapshots": snapshots.as_dict(),
            },
            "samples": private_samples,
            "selection": "healthy_visual_prefilter_v1",
            "candidate_pool_count": len(candidates),
            "excluded_source_security_count": len(excluded),
            "candidate_failures": failures,
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
            PRIVATE_ROOT / "audits" / "template-discovery-v1-healthy-uptrend-audit.json"
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
                    "candidate_pool_count": len(candidates),
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
