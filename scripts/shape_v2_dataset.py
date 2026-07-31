from __future__ import annotations

import argparse
import html
import json
import random
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.config import load_settings
from server.repository import LocalMarketRepository
from server.shape_v2 import CATEGORY_KEYS
from server.shape_v2.dataset import (
    anonymous_id,
    assign_grouped_splits,
    blank_label_record,
    build_public_bars,
    build_public_sample,
    canonical_json,
    content_hash,
    source_group_id,
    validate_audit_manifest,
)
from server.shape_v2.selection import PROFILE_QUOTAS, select_targeted_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an offline, anonymous Shape V2 review dataset from local zer0share."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "shape_v2" / "research-v2.0.0-draft1.json",
    )
    parser.add_argument("--role", choices=("calibration", "research"), default="calibration")
    parser.add_argument("--count", type=int, default=18)
    parser.add_argument(
        "--selection",
        choices=("uniform", "targeted"),
        default="uniform",
        help="Use targeted only for calibration packs; selection profiles stay private.",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=None,
        help="Number of private candidates to inspect before targeted selection.",
    )
    parser.add_argument(
        "--exclude-audit",
        action="append",
        type=Path,
        default=[],
        help="Private audit whose source securities must not be reused.",
    )
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "shape-v2" / "calibration-draft1",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "shape-v2" / ".private" / "anonymization.key",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("formal_scoring_enabled") is not False:
        raise ValueError("phase-1 generator requires formal_scoring_enabled=false")
    if [item["key"] for item in config["categories"]] != list(CATEGORY_KEYS):
        raise ValueError("category keys do not match the approved V2 research namespace")
    return config


def load_or_create_secret(path: Path) -> bytes:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        secret = path.read_bytes()
        if len(secret) < 32:
            raise ValueError("anonymization key must contain at least 32 bytes")
        return secret
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    return secret


def choose_candidate_dates(
    repository: LocalMarketRepository, end_date: str, seed: int, limit: int = 420
) -> list[str]:
    dates = repository.trading_dates(end_date, limit=limit)
    if len(dates) < 180:
        raise ValueError("local trading calendar does not provide enough history")
    # Keep enough room for old and recent structures without using the earliest edge.
    pool = dates[max(120, len(dates) - 360) :]
    rng = random.Random(seed ^ 0x5A17)
    rng.shuffle(pool)
    return pool


def load_excluded_codes(paths: list[Path]) -> set[str]:
    excluded: set[str] = set()
    for path in paths:
        with path.resolve().open("r", encoding="utf-8") as handle:
            audit = json.load(handle)
        excluded.update(str(item["ts_code"]) for item in audit.get("samples", []))
    return excluded


def load_bulk_candidate_history(
    repository: LocalMarketRepository,
    codes: list[str],
    start_date: str,
    end_date: str,
):
    daily_source = str(
        repository.data_dir / "stock" / "daily_kline" / "date=*" / "data.parquet"
    )
    adjustment_source = str(
        repository.data_dir / "stock" / "adj_factor" / "date=*" / "data.parquet"
    )
    sql = (
        "SELECT d.ts_code,CAST(d.trade_date AS VARCHAR) AS trade_date,"
        "d.open,d.high,d.low,d.close,d.pre_close,d.vol,d.amount,a.adj_factor "
        "FROM read_parquet(?, hive_partitioning=true, union_by_name=true) d "
        "LEFT JOIN read_parquet(?, hive_partitioning=true, union_by_name=true) a "
        "USING(ts_code,trade_date) "
        "WHERE d.trade_date>=? AND d.trade_date<=? "
        "AND d.ts_code IN (SELECT unnest(?)) "
        "ORDER BY d.ts_code,d.trade_date"
    )
    with repository._query_lock:
        return repository._duck.execute(
            sql, [daily_source, adjustment_source, start_date, end_date, codes]
        ).fetchdf()


def render_svg(sample: dict[str, Any]) -> str:
    bars = sample["bars"]
    width, height = 960, 520
    left, right, top = 44, 18, 24
    price_bottom, volume_top, volume_bottom = 370, 400, 488
    plot_width = width - left - right
    lows = [float(item["low"]) for item in bars]
    highs = [float(item["high"]) for item in bars]
    volumes = [float(item["volume"]) for item in bars]
    low, high = min(lows), max(highs)
    price_span = max(high - low, 1e-9)
    max_volume = max(max(volumes), 1e-9)
    step = plot_width / len(bars)
    body_width = max(1.2, step * 0.62)

    def y_price(value: float) -> float:
        return price_bottom - (value - low) / price_span * (price_bottom - top)

    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="匿名120日K线">',
        '<rect width="100%" height="100%" fill="#fbfaf6"/>',
        f'<text x="{left}" y="16" fill="#55615c" font-size="12">匿名样本 {html.escape(sample["sample_id"])}</text>',
    ]
    for index in range(5):
        y = top + (price_bottom - top) * index / 4
        chunks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#e4e1d9" stroke-width="1"/>'
        )
    for index, bar in enumerate(bars):
        x = left + step * (index + 0.5)
        open_y = y_price(float(bar["open"]))
        close_y = y_price(float(bar["close"]))
        high_y = y_price(float(bar["high"]))
        low_y = y_price(float(bar["low"]))
        rising = float(bar["close"]) >= float(bar["open"])
        color = "#d34f4f" if rising else "#2f8f70"
        chunks.append(
            f'<line x1="{x:.2f}" y1="{high_y:.2f}" x2="{x:.2f}" y2="{low_y:.2f}" stroke="{color}" stroke-width="1"/>'
        )
        body_y = min(open_y, close_y)
        body_height = max(1.0, abs(close_y - open_y))
        chunks.append(
            f'<rect x="{x-body_width/2:.2f}" y="{body_y:.2f}" width="{body_width:.2f}" height="{body_height:.2f}" fill="{color}" opacity="0.92"/>'
        )
        volume_height = float(bar["volume"]) / max_volume * (volume_bottom - volume_top)
        chunks.append(
            f'<rect x="{x-body_width/2:.2f}" y="{volume_bottom-volume_height:.2f}" width="{body_width:.2f}" height="{volume_height:.2f}" fill="{color}" opacity="0.55"/>'
        )
    chunks.extend(
        [
            f'<line x1="{left}" y1="{volume_top}" x2="{width-right}" y2="{volume_top}" stroke="#bfc5c1"/>',
            f'<text x="{left}" y="507" fill="#55615c" font-size="12">T-{len(bars)-1}</text>',
            f'<text x="{width-right-18}" y="507" fill="#55615c" font-size="12">T0</text>',
            f'<line x1="{width-right-step/2:.2f}" y1="{top}" x2="{width-right-step/2:.2f}" y2="{volume_bottom}" stroke="#202926" stroke-width="1.2" stroke-dasharray="4 3"/>',
            "</svg>",
        ]
    )
    return "".join(chunks)


def render_review_html(
    manifest: dict[str, Any], config: dict[str, Any], samples: list[dict[str, Any]]
) -> str:
    review_focus = str(config.get("review_focus", "")).strip()
    focus_html = (
        f'<p class="review-focus"><b>本轮重点：</b>{html.escape(review_focus)}</p>'
        if review_focus
        else ""
    )
    category_cards = "".join(
        f"<section><h3>{html.escape(item['label'])}</h3>"
        f"<p>{html.escape(item['definition'])}</p>"
        f"<small>核心矛盾：{'；'.join(html.escape(text) for text in item['core_contradictions'])}</small></section>"
        for item in config["categories"]
    )
    sample_cards = []
    for sample in samples:
        controls = "".join(
            f'<div class="rating-group"><b>{html.escape(item["label"])}</b>'
            f'<div class="score-buttons" role="radiogroup" aria-label="{html.escape(item["label"])}">'
            + "".join(
                f'<button type="button" data-sample="{sample["sample_id"]}" '
                f'data-category="{item["key"]}" data-score="{score}" '
                f'aria-pressed="false">{score}</button>'
                for score in range(4)
            )
            + "</div></div>"
            for item in config["categories"]
        )
        sample_cards.append(
            f'<article class="sample"><h2>{sample["sample_id"]}</h2>'
            f'<img src="charts/{sample["sample_id"]}.svg" alt="{sample["sample_id"]} 匿名K线"/>'
            f'<div class="ratings">{controls}</div>'
            f'<textarea data-note="{sample["sample_id"]}" placeholder="可选：写下边界判断或核心矛盾"></textarea>'
            "</article>"
        )
    labels = [blank_label_record(sample["sample_id"], manifest["dataset_version"]) for sample in samples]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>形态分类 V2 · 匿名校准包</title>
<style>
body{{margin:0;background:#ece9e1;color:#18201d;font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:28px}}header,.definitions,.sample{{background:#fffdfa;border:1px solid #d6d2c8;border-radius:12px}}
header{{padding:20px}}h1{{margin:0 0 8px}}.definitions{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0;padding:16px}}
.definitions section{{padding:12px;background:#f3f1eb;border-radius:9px}}.definitions h3{{margin:0 0 6px}}.definitions small{{color:#6b5149}}
.sample{{margin:16px 0;padding:16px}}.sample h2{{margin:0 0 8px;font-size:17px}}img{{display:block;width:100%;background:#fbfaf6;border-radius:8px}}
.ratings{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}}.rating-group{{display:grid;gap:6px}}
.score-buttons{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}}button,textarea{{font:inherit}}
.score-buttons button{{min-height:42px;border:1px solid #a9a59a;border-radius:8px;background:#f5f3ed;color:#25302b;font-weight:800;cursor:pointer}}
.score-buttons button:hover{{background:#e7eee9}}.score-buttons button.selected{{background:#19231f;color:white;border-color:#19231f;box-shadow:0 0 0 2px #92d8b9}}
textarea{{padding:9px;border:1px solid #aaa59b;border-radius:7px;background:white;box-sizing:border-box;width:100%;min-height:70px;margin-top:10px}}
.action-bar{{position:sticky;bottom:12px;z-index:5;margin-top:14px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between;gap:12px;background:rgba(255,253,250,.96);border:1px solid #cfcac0;border-radius:10px;box-shadow:0 5px 20px rgba(24,32,29,.15)}}
.export-button{{padding:10px 16px;border:0;border-radius:8px;background:#19231f;color:white;font-weight:700;cursor:pointer}}
@media(max-width:760px){{.definitions,.ratings{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><h1>形态分类 V2 · 匿名样本校准</h1><p>只看 T0 及以前约 120 个交易日；价格和成交量已统一归一化。页面不含股票名称、代码、行业、真实日期或未来 K 线。</p>
{focus_html}
<p><b>操作：</b>每个类别直接点击 0、1、2、3。页面会自动保存本机草稿，全部完成后再导出 JSON。</p>
<p>0 不相关/矛盾　·　1 局部影子　·　2 类别成立但不理想　·　3 代表样本</p></header>
<div class="definitions">{category_cards}</div>
{''.join(sample_cards)}
<div class="action-bar"><b id="progress">已完成 0 / {len(samples)}</b><button class="export-button" id="export">导出本轮标签 JSON</button></div>
</main><script>
const template={json.dumps(labels, ensure_ascii=False)};
const storageKey="shape-v2-labels:{manifest['dataset_version']}";
let labels=template;
try{{
  const saved=JSON.parse(localStorage.getItem(storageKey)||"null");
  if(Array.isArray(saved)&&saved.length===template.length&&saved.every((item,index)=>item.sample_id===template[index].sample_id))labels=saved;
}}catch(_error){{labels=template;}}
const byId=Object.fromEntries(labels.map(item=>[item.sample_id,item]));
function updateProgress(){{
  const completed=labels.filter(item=>Object.values(item.ratings).every(value=>value!==null)).length;
  document.getElementById("progress").textContent=`已完成 ${{completed}} / ${{labels.length}}`;
}}
function persist(){{localStorage.setItem(storageKey,JSON.stringify(labels));updateProgress();}}
function paintButtons(){{
  document.querySelectorAll(".score-buttons button").forEach(button=>{{
    const selected=byId[button.dataset.sample].ratings[button.dataset.category]===Number(button.dataset.score);
    button.classList.toggle("selected",selected);button.setAttribute("aria-pressed",String(selected));
  }});
}}
document.querySelectorAll(".score-buttons button").forEach(button=>button.addEventListener("click",()=>{{
  byId[button.dataset.sample].ratings[button.dataset.category]=Number(button.dataset.score);
  paintButtons();persist();
}}));
document.querySelectorAll("textarea").forEach(el=>{{
  el.value=byId[el.dataset.note].note||"";
  el.addEventListener("input",()=>{{byId[el.dataset.note].note=el.value;persist();}});
}});
paintButtons();updateProgress();
document.getElementById("export").addEventListener("click",()=>{{
  const blob=new Blob([JSON.stringify(labels,null,2)],{{type:"application/json"}});
  const link=document.createElement("a"); link.href=URL.createObjectURL(blob);
  link.download="{manifest['dataset_version']}-labels.json"; link.click(); URL.revokeObjectURL(link.href);
}});
</script></body></html>"""


def main() -> int:
    args = parse_args()
    if args.count < 3:
        raise ValueError("count must be at least 3")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    config = load_config(args.config.resolve())
    if args.selection == "targeted" and args.role != "calibration":
        raise ValueError("targeted selection is only valid for isolated calibration packs")
    secret = load_or_create_secret(args.key_file)
    settings = load_settings()
    repository = LocalMarketRepository(settings.zer0share_root, settings.zer0share_config)
    try:
        snapshots = repository.snapshots()
        if snapshots.daily_kline is None or snapshots.adj_factor is None:
            raise FileNotFoundError("local daily_kline and adj_factor snapshots are required")
        end_date = str(args.end_date or snapshots.daily_kline).replace("-", "")
        if len(end_date) != 8 or not end_date.isdigit():
            raise ValueError("end-date must use YYYYMMDD")
        end_date = min(end_date, snapshots.daily_kline, snapshots.adj_factor)
        date_pool = choose_candidate_dates(repository, end_date, args.seed)
        basic = repository.basic().copy()
        basic = basic[
            basic["list_status"].astype(str).eq("L")
            & basic["market"].astype(str).isin({"主板", "创业板", "科创板"})
        ].sort_values("ts_code")
        excluded_codes = load_excluded_codes(args.exclude_audit)
        codes = [
            code
            for code in basic["ts_code"].astype(str).tolist()
            if code not in excluded_codes
        ]
        rng = random.Random(args.seed)
        rng.shuffle(codes)
        sample_config = config["sample"]
        split_weights = config["split_policy"]["weights"]
        targeted_config = config.get("targeted_calibration", {})
        candidate_count = int(
            args.candidate_count
            or targeted_config.get(
                "candidate_count",
                max(args.count * (12 if args.selection == "targeted" else 2), args.count),
            )
        )
        if candidate_count < args.count:
            raise ValueError("candidate-count cannot be smaller than count")
        query_code_count = min(len(codes), max(candidate_count + 80, int(candidate_count * 1.25)))
        query_codes = codes[:query_code_count]
        requested_dates = {
            code: date_pool[
                int(content_hash({"seed": args.seed, "code": code}), 16) % len(date_pool)
            ]
            for code in query_codes
        }
        earliest_requested = min(requested_dates.values())
        query_start = (
            datetime.strptime(earliest_requested, "%Y%m%d") - timedelta(days=260)
        ).strftime("%Y%m%d")
        bulk_history = load_bulk_candidate_history(
            repository, query_codes, query_start, end_date
        )
        grouped_history = {
            str(code): frame.copy()
            for code, frame in bulk_history.groupby("ts_code", sort=False)
        }
        candidate_items: list[dict[str, Any]] = []
        failures: list[str] = []
        for code in query_codes:
            if len(candidate_items) >= candidate_count:
                break
            requested_date = requested_dates[code]
            frame = grouped_history.get(code)
            if frame is None:
                failures.append(f"{code}@{requested_date}: no local rows")
                continue
            try:
                bars, private = build_public_bars(
                    frame,
                    requested_date,
                    window_bars=int(sample_config["window_bars"]),
                    price_anchor=float(sample_config["price_anchor"]),
                )
            except ValueError as exc:
                failures.append(f"{code}@{requested_date}: {exc}")
                continue
            resolved_date = str(private["resolved_score_date"])
            sample_id = anonymous_id(
                secret, config["dataset_version"], code, resolved_date
            )
            group_id = source_group_id(secret, code)
            split = "calibration" if args.role == "calibration" else "pending"
            sample = build_public_sample(
                sample_id, config["dataset_version"], split, bars
            )
            candidate_items.append(
                {
                    "sample": sample,
                    "audit": {
                        "sample_id": sample_id,
                        "public_content_hash": content_hash(sample),
                        "split": split,
                        "source_group_id": group_id,
                        "ts_code": code,
                        "requested_score_date": requested_date,
                        "resolved_score_date": resolved_date,
                        "source_trade_dates": private["source_trade_dates"],
                        "price_anchor_raw": private["price_anchor_raw"],
                        "volume_anchor_raw": private["volume_anchor_raw"],
                    },
                }
            )
        if len(candidate_items) < candidate_count:
            raise RuntimeError(
                f"only {len(candidate_items)} valid candidates were generated; "
                f"{len(failures)} candidates failed"
            )
        if args.selection == "targeted":
            quotas = dict(targeted_config.get("profile_quotas", PROFILE_QUOTAS))
            if sum(int(value) for value in quotas.values()) != args.count:
                raise ValueError("targeted profile quotas must sum to count")
            selected_items = select_targeted_candidates(candidate_items, quotas)
        else:
            selected_items = candidate_items[: args.count]
        public_samples = [item["sample"] for item in selected_items]
        audit_samples = []
        for item in selected_items:
            private = dict(item["audit"])
            if args.selection == "targeted":
                private["selection_profile"] = item["selection_profile"]
                private["selection_score"] = item["selection_score"]
            audit_samples.append(private)
        if args.role == "research":
            assignments = assign_grouped_splits(
                (item["source_group_id"] for item in audit_samples), split_weights
            )
            for sample, private in zip(public_samples, audit_samples):
                split = assignments[private["source_group_id"]]
                sample["split"] = split
                private["split"] = split
        public_samples.sort(key=lambda item: item["sample_id"])
        audit_samples.sort(key=lambda item: item["sample_id"])
        public_by_id = {sample["sample_id"]: sample for sample in public_samples}
        for private in audit_samples:
            private["public_content_hash"] = content_hash(
                public_by_id[private["sample_id"]]
            )
        audit = {
            "schema_version": "shape-v2-private-audit/1",
            "dataset_version": config["dataset_version"],
            "role": args.role,
            "seed": args.seed,
            "source": {
                "provider": "local_zer0share",
                "network_used": False,
                "snapshots": snapshots.as_dict(),
            },
            "samples": audit_samples,
            "selection": args.selection,
            "candidate_pool_count": len(candidate_items),
            "excluded_source_security_count": len(excluded_codes),
            "candidate_failures": failures,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        findings = validate_audit_manifest(audit)
        if findings:
            raise RuntimeError("leakage audit failed: " + "; ".join(findings))
        manifest = {
            "schema_version": "shape-v2-public-manifest/1",
            "dataset_version": config["dataset_version"],
            "role": args.role,
            "status": config.get("status", "definition_review"),
            "source": "local zer0share offline snapshot",
            "network_used": False,
            "selection": args.selection,
            "sample_count": len(public_samples),
            "window_bars": int(sample_config["window_bars"]),
            "categories": [
                {"key": item["key"], "label": item["label"]}
                for item in config["categories"]
            ],
            "split_policy": (
                {"calibration": 1.0}
                if args.role == "calibration"
                else split_weights
            ),
            "samples": [
                {
                    "sample_id": sample["sample_id"],
                    "split": sample["split"],
                    "path": f"samples/{sample['sample_id']}.json",
                    "chart": f"charts/{sample['sample_id']}.svg",
                    "content_hash": content_hash(sample),
                }
                for sample in public_samples
            ],
        }
        manifest["dataset_fingerprint"] = content_hash(manifest)
        output.mkdir(parents=True, exist_ok=True)
        (output / "samples").mkdir()
        (output / "charts").mkdir()
        for sample in public_samples:
            (output / "samples" / f"{sample['sample_id']}.json").write_text(
                json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (output / "charts" / f"{sample['sample_id']}.svg").write_text(
                render_svg(sample), encoding="utf-8"
            )
        labels = [
            blank_label_record(sample["sample_id"], config["dataset_version"])
            for sample in public_samples
        ]
        (output / "labels-template.json").write_text(
            json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "index.html").write_text(
            render_review_html(manifest, config, public_samples), encoding="utf-8"
        )
        private_audit_path = (
            args.key_file.resolve().parent / "audits" / f"{output.name}-audit.json"
        )
        private_audit_path.parent.mkdir(parents=True, exist_ok=True)
        private_audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            canonical_json(
                {
                    "ok": True,
                    "output": str(output),
                    "review": str(output / "index.html"),
                    "private_audit": str(private_audit_path),
                    "sample_count": len(public_samples),
                    "dataset_fingerprint": manifest["dataset_fingerprint"],
                    "leakage_findings": findings,
                    "network_used": False,
                    "source_snapshot": snapshots.daily_kline,
                }
            )
        )
        return 0
    finally:
        repository._duck.close()


if __name__ == "__main__":
    raise SystemExit(main())
