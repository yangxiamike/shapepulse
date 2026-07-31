from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "template-discovery-v4"
    / "fresh-breakout-segments"
)
CURRENT_ROOT = PROJECT_ROOT / "outputs" / "shape-v2" / "template-current"


GROUPS = {
    "representative": [
        ("S-8B242C82BC39", 3, "较长平台整理后突然上破，突破后第1根仍守住，前后反差清楚。"),
        ("S-0F220ABC163E", 3, "上涨后经历较长高位整理，评分日前突然打破平台，不是短回调续涨。"),
        ("S-8C9D4D01396A", 3, "完整窗口长期震荡，突破前40根基本横向，尾端放量打破区间。"),
        ("S-B8EC79F5406B", 3, "前段上涨后长时间横盘消化，尾端突破整理高点并保持。"),
        ("S-FE4BA4AC4FB2", 3, "较长阴跌后形成底部结构，随后突然突破局部下降压力。"),
        ("S-166BB48D38C3", 3, "长期大区间整理，突破前40根近乎横盘，末端出现清晰上破。"),
        ("S-F515BA77EEAB", 3, "前期跳升后经历长平台，尾端重新突破平台高点，结构分段明确。"),
        ("S-DCF890A52A0B", 3, "较长下跌后在低位整理，评分日前突然向上打破局部结构。"),
        ("S-3738167AEB80", 3, "长时间阴跌与底部震荡后出现突破，突破前后斜率反差明显。"),
        ("S-64187E78306A", 3, "较长走弱后止跌整理，尾端快速越过近端压力，属于反转型突破。"),
    ],
    "boundary": [
        ("S-A18A00662A0A", 2, "长区间后突破成立，但历史波动较杂，压力结构不够标准。"),
        ("S-43589CFED1C2", 2, "长平台后的突破清楚，但此前有一次异常尖峰，代表性略弱。"),
        ("S-96B15FAE4940", 2, "阴跌后突然上破成立，但突破单日幅度偏大，先作边界。"),
        ("S-C1EBFD469049", 2, "平台整理时间足够，尾端突破可见，但完整窗口存在跳变。"),
        ("S-0A7AA77C743D", 2, "长期震荡后突破成立，但区间噪声偏大，不作为最标准模子。"),
    ],
    "reject_as_representative": [
        ("S-303C5BC0DB19", 1, "完整窗口仍是持续抬高，整理期不够独立，更接近上升趋势续涨。"),
        ("S-4F5134D87EB8", 1, "突破前已连续回升一段时间，突然性不足，容易混入趋势延续。"),
        ("S-26A352492727", 1, "整体仍处于上升趋势，末端新高更像小调整后的继续上涨。"),
        ("S-7F28F6AE5876", 1, "低点后已持续回升较久，评分日不是从长整理或长阴跌中突然突破。"),
        ("S-2C22F9EE5BF0", 1, "完整结构持续向上，尾端只是短暂停顿后续涨，不是标准刚突破。"),
    ],
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _card(
    group: str,
    sample_id: str,
    rating: int,
    reason: str,
    ranking: dict[str, Any],
) -> str:
    d = ranking["diagnostics"]
    setup_type = (
        "长阴跌"
        if d["decline_quality"] > d["consolidation_quality"]
        else "长整理"
    )
    return f"""<article class="{escape(group)}">
<h2>{escape(sample_id)} · {rating}分</h2>
<p>{escape(reason)}</p>
<p class="facts">{setup_type} · 突破前40根涨跌 {d['pre_breakout_return_40']:.1%} ·
突破日 {d['breakout_day_return']:.1%} · 突破后第 {d['breakout_age']:.0f} 根</p>
<img src="charts/{escape(sample_id)}.svg" alt="{escape(sample_id)}">
</article>"""


def main() -> int:
    rankings_rows = json.loads((ROOT / "rankings.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    rankings = {item["sample_id"]: item for item in rankings_rows}
    selected_ids = [
        sample_id
        for rows in GROUPS.values()
        for sample_id, _, _ in rows
    ]
    missing = sorted(set(selected_ids).difference(rankings))
    if missing:
        raise ValueError("shortlist ids missing: " + ", ".join(missing))
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("shortlist cannot reuse a sample")

    payload = {
        "schema_version": "shape-v2-template-segment-shortlist/1",
        "category": "fresh_breakout",
        "status": "ai_visual_provisional_after_setup_correction",
        "source_role": "template",
        "source_dataset": manifest["dataset_version"],
        "user_definition_correction": {
            "confirmed_at": "2026-07-28",
            "positive_setups": [
                "较长时间调整震荡后突然突破",
                "较长时间阴跌或走弱后突然突破",
            ],
            "explicit_negative": "已经形成上升趋势，仅在小调整后继续创新高",
            "corrected_sample": "S-6B0894760DEA",
        },
        "groups": {
            group: [
                {"sample_id": sample_id, "rating": rating, "reason": reason}
                for sample_id, rating, reason in rows
            ]
            for group, rows in GROUPS.items()
        },
    }
    _write_json(ROOT / "visual-shortlist.json", payload)
    labels = {
        "representative": "✅ 代表模子",
        "boundary": "⚠️ 边界片段",
        "reject_as_representative": "❌ 明确不作为模子",
    }
    sections = []
    for group, rows in GROUPS.items():
        cards = "".join(
            _card(group, sample_id, rating, reason, rankings[sample_id])
            for sample_id, rating, reason in rows
        )
        sections.append(f"<section><h1>{labels[group]}</h1>{cards}</section>")
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>刚突破 · 长整理或长阴跌后的突破</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f3f6f8;color:#152238}}
main{{max-width:1120px;margin:auto;padding:24px}}header,article{{background:#fff;border-radius:16px;padding:20px;margin:16px 0}}
header{{border-left:10px solid #178c66}}article{{border-left:9px solid #168d67}}
article.boundary{{border-left-color:#d29a18}}article.reject_as_representative{{border-left-color:#ba4545}}
h1,h2{{margin:.25em 0}}p{{line-height:1.65}}.notice{{background:#eef8f4;padding:14px;border-radius:12px}}
.facts{{color:#5c687b;font-size:14px}}img{{width:100%;display:block;margin-top:10px}}
</style></head><body><main><header>
<h1>刚突破 · 历史区间模子 v4</h1>
<p class="notice">刚突破必须来自较长时间的横盘整理，或较长时间的阴跌/走弱；
随后才出现突然打破结构。已经形成上升趋势、仅在小调整后继续创新高，不算刚突破。</p>
<p>扫描87,741个历史区间；仅使用本机 zer0share 快照20260727；不使用未来数据；
同一股票只保留一个区间。当前等待用户确认方向，不是封存评估结论。</p>
</header>{''.join(sections)}</main></body></html>"""
    (ROOT / "visual-shortlist.html").write_text(html, encoding="utf-8")

    CURRENT_ROOT.mkdir(parents=True, exist_ok=True)
    hub = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>形态V2 · 当前有效模子</title>
<style>body{font-family:system-ui;background:#f3f6f8;color:#152238}
main{max-width:800px;margin:60px auto;background:#fff;padding:32px;border-radius:18px}
li{font-size:22px;margin:18px}a{color:#087b5b}p{line-height:1.7}</style></head><body><main>
<h1>形态V2 · 当前有效模子</h1>
<p>健康上升趋势已获用户确认；刚突破已按“长整理/长阴跌后突然突破”修正；
回调转强已把浅、短回调后恢复纳入代表模子。</p><ul>
<li><a href="../template-discovery-v2/healthy-uptrend-segments/visual-shortlist.html">健康上升趋势</a></li>
<li><a href="../template-discovery-v4/fresh-breakout-segments/visual-shortlist.html">刚突破 v4</a></li>
<li><a href="../template-discovery-v3/pullback-strengthening-segments/visual-shortlist.html">回调转强</a></li>
</ul></main></body></html>"""
    (CURRENT_ROOT / "index.html").write_text(hub, encoding="utf-8")
    print(CURRENT_ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
