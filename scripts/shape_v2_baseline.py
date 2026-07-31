from __future__ import annotations

import argparse
import html
import json
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
from server.shape_v2 import CATEGORY_KEYS
from server.shape_v2.calibration import (
    CalibrationRound,
    build_calibration_summary,
    load_calibration_rounds,
    public_records,
)
from server.shape_v2.dataset import (
    anonymous_id,
    assign_research_split,
    blank_label_record,
    build_public_bars,
    build_public_sample,
    canonical_json,
    content_hash,
    source_group_id,
    validate_audit_manifest,
)
from server.shape_v2.metrics import calibration_diagnostics
from server.shape_v2.scoring import CATEGORY_WEIGHT_PRIORS, score_all


PRIVATE_ROOT = PROJECT_ROOT / "outputs" / "shape-v2" / ".private"
DEFAULT_BASELINE_ROOT = PROJECT_ROOT / "outputs" / "shape-v2" / "baseline-v1.1"
CATEGORY_LABELS = {
    "fresh_breakout": "刚突破",
    "healthy_uptrend": "健康上升趋势",
    "pullback_strengthening": "回调转强",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the provisional Shape V2 baseline and its anonymous tuning review."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    calibrate = subparsers.add_parser("calibrate")
    calibrate.add_argument(
        "--output", type=Path, default=DEFAULT_BASELINE_ROOT / "calibration"
    )
    rank = subparsers.add_parser("rank")
    rank.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_BASELINE_ROOT / "calibration" / "model.json",
    )
    rank.add_argument(
        "--output", type=Path, default=DEFAULT_BASELINE_ROOT / "tuning-review"
    )
    rank.add_argument("--end-date", default=None)
    rank.add_argument(
        "--candidate-limit",
        type=int,
        default=None,
        help="Deterministic debug limit after the tuning split; omit for the full local universe.",
    )
    rank.add_argument("--top-n", type=int, default=50)
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument(
        "--output", type=Path, default=DEFAULT_BASELINE_ROOT / "tuning-review"
    )
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _require_empty_output(path: Path) -> None:
    resolved = path.resolve()
    if PROJECT_ROOT.resolve() not in resolved.parents:
        raise ValueError(f"output must stay inside the project: {resolved}")
    if resolved.exists() and any(resolved.iterdir()):
        raise FileExistsError(f"output directory is not empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)


def _calibration_specs() -> list[CalibrationRound]:
    return [
        CalibrationRound(
            name=f"C{draft}",
            labels_path=PRIVATE_ROOT
            / "labels"
            / f"shape-v2.0.0-draft{draft}-labels.json",
            public_dir=PROJECT_ROOT
            / "outputs"
            / "shape-v2"
            / f"calibration-draft{draft}",
            audit_path=PRIVATE_ROOT
            / "audits"
            / f"calibration-draft{draft}-audit.json",
        )
        for draft in (1, 2, 3)
    ]


def calibrate(output: Path) -> dict[str, Any]:
    _require_empty_output(output)
    rounds = load_calibration_rounds(_calibration_specs())
    config = _load_json(
        PROJECT_ROOT / "config" / "shape_v2" / "research-v2.0.0-draft3.json"
    )
    summary = build_calibration_summary(
        rounds, config["categories"], CATEGORY_WEIGHT_PRIORS
    )
    records = public_records(rounds)
    predictions = {
        record["sample_id"]: score_all(record["facts"], summary) for record in records
    }
    diagnostics = calibration_diagnostics(records, predictions)
    ranked_records = [
        {
            "sample_id": record["sample_id"],
            "round": record["round"],
            "ratings": record["ratings"],
            "note": record["note"],
            "predictions": predictions[record["sample_id"]],
        }
        for record in records
    ]
    differences: dict[str, Any] = {}
    for category in CATEGORY_KEYS:
        false_positive = sorted(
            (
                item
                for item in ranked_records
                if item["ratings"][category] == 0
            ),
            key=lambda item: -float(item["predictions"][category]["score"]),
        )[:10]
        missed_positive = sorted(
            (
                item
                for item in ranked_records
                if item["ratings"][category] >= 2
            ),
            key=lambda item: float(item["predictions"][category]["score"]),
        )[:10]
        differences[category] = {
            "label": CATEGORY_LABELS[category],
            "highest_scored_human_0": false_positive,
            "lowest_scored_human_2_or_3": missed_positive,
        }
    _write_json(output / "model.json", summary)
    _write_json(output / "calibration-diagnostics.json", diagnostics)
    _write_json(output / "calibration-ranked.json", ranked_records)
    _write_json(
        output / "definition-differences.json",
        {
            "schema_version": "shape-v2-definition-differences/1",
            "status": "calibration_apparent_errors_only",
            "categories": differences,
        },
    )
    result = {
        "ok": True,
        "model": str(output / "model.json"),
        "diagnostics": str(output / "calibration-diagnostics.json"),
        "sample_count": len(records),
        "source_snapshot": summary["source"]["snapshots"],
        "network_used": False,
    }
    print(canonical_json(result))
    return result


def _load_excluded_codes() -> set[str]:
    codes: set[str] = set()
    for draft in (1, 2, 3):
        audit = _load_json(
            PRIVATE_ROOT / "audits" / f"calibration-draft{draft}-audit.json"
        )
        codes.update(str(item["ts_code"]) for item in audit["samples"])
    return codes


def _render_review_html(
    manifest: dict[str, Any],
    rankings: dict[str, list[dict[str, Any]]],
    samples: list[dict[str, Any]],
) -> str:
    rank_lookup: dict[str, list[str]] = {}
    for category, rows in rankings.items():
        for row in rows:
            rank_lookup.setdefault(row["sample_id"], []).append(
                f"{CATEGORY_LABELS[category]} #{row['rank']} / 分数 {row['score']:.3f}"
            )
    labels = [
        blank_label_record(sample["sample_id"], manifest["dataset_version"])
        for sample in samples
    ]
    cards = []
    for sample in samples:
        sample_id = sample["sample_id"]
        badges = "".join(
            f"<span class='badge'>{html.escape(value)}</span>"
            for value in rank_lookup.get(sample_id, [])
        )
        controls = []
        for category in CATEGORY_KEYS:
            buttons = "".join(
                f"<button data-sample='{sample_id}' data-category='{category}' "
                f"data-score='{score}'>{score}</button>"
                for score in range(4)
            )
            controls.append(
                f"<div class='rating'><strong>{CATEGORY_LABELS[category]}</strong>{buttons}</div>"
            )
        cards.append(
            f"""
<article class="card" id="{sample_id}">
  <h2>{sample_id}</h2><div class="badges">{badges}</div>
  <img src="charts/{sample_id}.svg" alt="{sample_id} 匿名K线" />
  {''.join(controls)}
  <textarea data-note="{sample_id}" placeholder="记录严重错误、代表性或与定义不一致之处"></textarea>
</article>"""
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>形态 V2 基准排名调优评审</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7fa;color:#172033}}
main{{max-width:1120px;margin:auto;padding:24px}} .summary,.card{{background:white;border-radius:14px;padding:18px;margin:16px 0;box-shadow:0 4px 16px #17203312}}
.card img{{width:100%;background:#0b1220;border-radius:10px}} .badge{{display:inline-block;background:#e8f0ff;color:#174ea6;border-radius:999px;padding:5px 9px;margin:3px}}
.rating{{display:flex;gap:8px;align-items:center;margin:10px 0}} button{{min-width:42px;padding:8px;border:1px solid #b8c3d6;border-radius:8px;background:white}}
button.selected{{background:#174ea6;color:white}} textarea{{width:100%;min-height:64px;box-sizing:border-box}} .sticky{{position:sticky;top:0;background:#f5f7faee;padding:10px 0;z-index:2}}
</style></head><body><main>
<section class="summary"><h1>形态分类 V2 · 基准排名调优评审</h1>
<p>本页只含评分日及以前120根匿名K线。证券、名称、行业、日期和未来数据均隐藏。</p>
<p>这批样本角色固定为 tuning；不是封存测试。三类独立打0~3分，允许重叠。</p></section>
<div class="sticky"><button id="download">导出标注</button> <span id="progress"></span></div>
{''.join(cards)}
<script>
const template={json.dumps(labels, ensure_ascii=False)};
const key="shape-v2-baseline-review:{manifest['dataset_version']}";
let labels=template; try{{const saved=JSON.parse(localStorage.getItem(key));if(Array.isArray(saved)&&saved.length===template.length)labels=saved;}}catch(e){{}}
const byId=Object.fromEntries(labels.map(x=>[x.sample_id,x]));
function refresh(){{document.querySelectorAll("button[data-score]").forEach(b=>b.classList.toggle("selected",byId[b.dataset.sample].ratings[b.dataset.category]===Number(b.dataset.score)));document.querySelectorAll("textarea[data-note]").forEach(t=>t.value=byId[t.dataset.note].note||"");const done=labels.filter(x=>Object.values(x.ratings).every(v=>v!==null)).length;document.getElementById("progress").textContent=`已完成 ${{done}} / ${{labels.length}}`;}}
function save(){{localStorage.setItem(key,JSON.stringify(labels));refresh();}}
document.querySelectorAll("button[data-score]").forEach(b=>b.onclick=()=>{{byId[b.dataset.sample].ratings[b.dataset.category]=Number(b.dataset.score);save();}});
document.querySelectorAll("textarea[data-note]").forEach(t=>t.onchange=()=>{{byId[t.dataset.note].note=t.value;save();}});
document.getElementById("download").onclick=()=>{{const blob=new Blob([JSON.stringify(labels,null,2)],{{type:"application/json"}});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="{manifest['dataset_version']}-labels.json";a.click();URL.revokeObjectURL(a.href);}};
refresh();
</script></main></body></html>"""


def _render_ranking_summary(
    manifest: dict[str, Any], rankings: dict[str, list[dict[str, Any]]]
) -> str:
    sections = []
    for category in CATEGORY_KEYS:
        rows = rankings[category]
        table_rows = []
        for row in rows:
            tier = "Top20" if row["rank"] <= 20 else "Top50"
            cap_text = "；".join(cap["message"] for cap in row["caps"]) or "无"
            table_rows.append(
                "<tr>"
                f"<td>{row['rank']}</td><td>{tier}</td>"
                f"<td><a href='index.html#{row['sample_id']}'>{row['sample_id']}</a></td>"
                f"<td>{float(row['score']):.4f}</td><td>{html.escape(cap_text)}</td>"
                "</tr>"
            )
        sections.append(
            f"<section><h2>{CATEGORY_LABELS[category]}</h2>"
            "<p>前 5 条先检查是否具有代表性；Top20 重点标严重错误；Top21~50 用于观察分层。</p>"
            "<table><thead><tr><th>排名</th><th>层级</th><th>匿名样本</th><th>分数</th><th>核心上限</th></tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody></table></section>"
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>形态 V2 Top20/Top50 排名索引</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1060px;margin:auto;padding:24px;color:#172033;background:#f5f7fa}}
section{{background:white;padding:20px;margin:18px 0;border-radius:12px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e1e5eb;text-align:left}}a{{color:#174ea6}}</style>
</head><body><h1>形态分类 V2 · Top20/Top50 排名索引</h1>
<p>模型 {html.escape(str(manifest['model_version']))}；本机快照 {manifest['source_snapshot']}；角色 tuning；无未来数据。</p>
<p>新样本尚无人工标签，因此纯度、严重错误率、NDCG 和两两排序准确率均待本轮标注后计算。</p>
{''.join(sections)}</body></html>"""


def summarize_existing(output: Path) -> dict[str, Any]:
    resolved = output.resolve()
    if PROJECT_ROOT.resolve() not in resolved.parents:
        raise ValueError(f"review output must stay inside the project: {resolved}")
    manifest = _load_json(resolved / "manifest.json")
    rankings = _load_json(resolved / "rankings.json")
    summary_path = resolved / "ranking-summary.html"
    if summary_path.exists():
        raise FileExistsError(f"ranking summary already exists: {summary_path}")
    summary_path.write_text(
        _render_ranking_summary(manifest, rankings), encoding="utf-8"
    )
    result = {"ok": True, "ranking_summary": str(summary_path)}
    print(canonical_json(result))
    return result


def rank(
    model_path: Path,
    output: Path,
    end_date_arg: str | None,
    candidate_limit: int | None,
    top_n: int,
) -> dict[str, Any]:
    if top_n < 50:
        raise ValueError("top-n must be at least 50 so Top20 and Top50 both exist")
    _require_empty_output(output)
    model = _load_json(model_path.resolve())
    config = _load_json(
        PROJECT_ROOT / "config" / "shape_v2" / "research-v2.0.0-draft3.json"
    )
    secret_path = PRIVATE_ROOT / "anonymization.key"
    secret = secret_path.read_bytes()
    if len(secret) < 32:
        raise ValueError("anonymization key is missing or invalid")
    settings = load_settings()
    repository = LocalMarketRepository(settings.zer0share_root, settings.zer0share_config)
    try:
        snapshots = repository.snapshots()
        if snapshots.daily_kline is None or snapshots.adj_factor is None:
            raise FileNotFoundError("local daily_kline and adj_factor snapshots are required")
        end_date = str(end_date_arg or snapshots.daily_kline).replace("-", "")
        end_date = min(end_date, snapshots.daily_kline, snapshots.adj_factor)
        excluded_codes = _load_excluded_codes()
        basic = repository.basic().copy()
        basic = basic[
            basic["list_status"].astype(str).eq("L")
            & basic["market"].astype(str).isin({"主板", "创业板", "科创板"})
        ]
        weights = config["split_policy"]["weights"]
        tuning_codes = sorted(
            code
            for code in basic["ts_code"].astype(str)
            if code not in excluded_codes
            and assign_research_split(source_group_id(secret, code), weights) == "tuning"
        )
        if candidate_limit is not None:
            if candidate_limit < top_n:
                raise ValueError("candidate-limit cannot be smaller than top-n")
            tuning_codes = tuning_codes[:candidate_limit]
        trading_dates = repository.trading_dates(end_date, limit=180)
        if len(trading_dates) < 120:
            raise ValueError("local snapshot does not provide 120 trading days")
        history = load_bulk_candidate_history(
            repository, tuning_codes, trading_dates[0], end_date
        )
        grouped = {
            str(code): frame.copy()
            for code, frame in history.groupby("ts_code", sort=False)
        }
        candidates: list[dict[str, Any]] = []
        failures: list[str] = []
        dataset_version = "shape-v2.0.0-baseline1.1-tuning"
        for code in tuning_codes:
            frame = grouped.get(code)
            if frame is None:
                failures.append(f"{code}: no local rows")
                continue
            try:
                bars, private = build_public_bars(frame, end_date, window_bars=120)
            except ValueError as exc:
                failures.append(f"{code}: {exc}")
                continue
            if private["resolved_score_date"] != end_date:
                failures.append(f"{code}: latest local bar is not {end_date}")
                continue
            sample_id = anonymous_id(secret, dataset_version, code, end_date)
            sample = build_public_sample(sample_id, dataset_version, "tuning", bars)
            candidates.append(
                {
                    "sample": sample,
                    "predictions": score_all(sample["shared_facts"], model),
                    "private": {
                        "sample_id": sample_id,
                        "split": "tuning",
                        "source_group_id": source_group_id(secret, code),
                        "ts_code": code,
                        "requested_score_date": end_date,
                        "resolved_score_date": end_date,
                        "source_trade_dates": private["source_trade_dates"],
                    },
                }
            )
        if len(candidates) < top_n:
            raise RuntimeError(f"only {len(candidates)} valid tuning candidates were scored")
        by_id = {item["sample"]["sample_id"]: item for item in candidates}
        rankings: dict[str, list[dict[str, Any]]] = {}
        selected_ids: set[str] = set()
        for category in CATEGORY_KEYS:
            ordered = sorted(
                candidates,
                key=lambda item: (
                    -float(item["predictions"][category]["score"]),
                    item["sample"]["sample_id"],
                ),
            )[:top_n]
            rankings[category] = []
            for index, item in enumerate(ordered, 1):
                sample_id = item["sample"]["sample_id"]
                selected_ids.add(sample_id)
                prediction = item["predictions"][category]
                rankings[category].append(
                    {
                        "rank": index,
                        "sample_id": sample_id,
                        "score": prediction["score"],
                        "raw_score": prediction["raw_score"],
                        "confidence": prediction["confidence"],
                        "caps": prediction["caps"],
                    }
                )
        selected = [by_id[sample_id] for sample_id in sorted(selected_ids)]
        public_samples = [item["sample"] for item in selected]
        manifest = {
            "schema_version": "shape-v2-ranking-review/1",
            "dataset_version": dataset_version,
            "model_version": model["model_version"],
            "role": "tuning",
            "status": "labels_pending",
            "source": "local zer0share offline snapshot",
            "source_snapshot": end_date,
            "network_used": False,
            "sample_count": len(public_samples),
            "scored_universe_count": len(candidates),
            "excluded_calibration_security_count": len(excluded_codes),
            "categories": [
                {"key": key, "label": CATEGORY_LABELS[key]} for key in CATEGORY_KEYS
            ],
            "samples": [
                {
                    "sample_id": sample["sample_id"],
                    "split": "tuning",
                    "path": f"samples/{sample['sample_id']}.json",
                    "chart": f"charts/{sample['sample_id']}.svg",
                    "content_hash": content_hash(sample),
                }
                for sample in public_samples
            ],
        }
        manifest["dataset_fingerprint"] = content_hash(manifest)
        private_samples = []
        for item in selected:
            private = dict(item["private"])
            private["public_content_hash"] = content_hash(item["sample"])
            private_samples.append(private)
        audit = {
            "schema_version": "shape-v2-private-audit/1",
            "dataset_version": dataset_version,
            "role": "tuning",
            "seed": "stable_hmac_split",
            "source": {
                "provider": "local_zer0share",
                "network_used": False,
                "snapshots": snapshots.as_dict(),
            },
            "samples": private_samples,
            "selection": "baseline_top50_per_category",
            "candidate_pool_count": len(candidates),
            "excluded_source_security_count": len(excluded_codes),
            "candidate_failures": failures,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        findings = validate_audit_manifest(audit)
        if findings:
            raise RuntimeError("leakage audit failed: " + "; ".join(findings))
        (output / "samples").mkdir()
        (output / "charts").mkdir()
        for sample in public_samples:
            _write_json(output / "samples" / f"{sample['sample_id']}.json", sample)
            (output / "charts" / f"{sample['sample_id']}.svg").write_text(
                render_svg(sample), encoding="utf-8"
            )
        _write_json(output / "manifest.json", manifest)
        _write_json(output / "rankings.json", rankings)
        _write_json(
            output / "labels-template.json",
            [
                blank_label_record(sample["sample_id"], dataset_version)
                for sample in public_samples
            ],
        )
        (output / "index.html").write_text(
            _render_review_html(manifest, rankings, public_samples), encoding="utf-8"
        )
        (output / "ranking-summary.html").write_text(
            _render_ranking_summary(manifest, rankings), encoding="utf-8"
        )
        audit_path = (
            PRIVATE_ROOT / "audits" / "baseline-v1.1-tuning-review-audit.json"
        )
        if audit_path.exists():
            raise FileExistsError(f"private audit already exists: {audit_path}")
        _write_json(audit_path, audit)
        result = {
            "ok": True,
            "output": str(output),
            "review": str(output / "index.html"),
            "private_audit": str(audit_path),
            "source_snapshot": end_date,
            "network_used": False,
            "scored_universe_count": len(candidates),
            "review_sample_count": len(public_samples),
            "leakage_findings": findings,
        }
        print(canonical_json(result))
        return result
    finally:
        repository._duck.close()


def main() -> int:
    args = parse_args()
    if args.command == "calibrate":
        calibrate(args.output)
    elif args.command == "rank":
        rank(
            args.model,
            args.output,
            args.end_date,
            args.candidate_limit,
            args.top_n,
        )
    elif args.command == "summarize":
        summarize_existing(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
