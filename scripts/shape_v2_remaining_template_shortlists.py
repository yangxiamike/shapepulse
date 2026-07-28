from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "template-discovery-v3"
)


REVIEWS = {
    "fresh_breakout": {
        "label": "刚突破",
        "slug": "fresh-breakout-segments",
        "representative": [
            ("S-6B0894760DEA", 3, "突破后第2根，越过完整结构高位并继续守住，前段接近过程自然。"),
            ("S-0042D83CA3C4", 3, "突破后第1根，清晰越过平台压力，成交量配合且没有立刻回落。"),
            ("S-94DE8582694C", 3, "上升基础清楚，回调整理后突破前高，评分日仍保持强势。"),
            ("S-E3674B31F72A", 3, "多阶段抬高后突破整理高点，突破后没有跌回压力区。"),
            ("S-94F9615BB230", 3, "中期趋势向上，尾端突破清晰，确认阶段和量价较协调。"),
            ("S-DC54A0418DBC", 3, "趋势连续、压力位可辨认，突破后第2根仍在结构上方。"),
            ("S-DEB81E5E4FE7", 3, "前段蓄势后越过平台高点，突破不是普通区间内反弹。"),
            ("S-10328FA464CB", 3, "较长平台后分段抬升并突破新高，评分日处于早期确认。"),
            ("S-CA6E02D9620C", 3, "前高和整理区清楚，突破后延续且未出现高量回撤。"),
            ("S-49D0D8D02496", 3, "健康上升背景中的新高突破，位置、连续性和时效性都较好。"),
        ],
        "boundary": [
            ("S-FC05A8F5A41E", 2, "突破成立，但尾端加速较陡，容易和过度延伸混在一起。"),
            ("S-4213199A87C5", 2, "已越过近端压力，但完整窗口较杂，结构清晰度略弱。"),
            ("S-82A4D3DAC3F1", 2, "尾端突破幅度明显，但此前仍是较宽区间，只作边界。"),
            ("S-0780E151D059", 2, "打破60日压力成立，但长期背景偏弱，代表性需要打折。"),
            ("S-BDD85D675AD3", 2, "底部转强后突破清楚，但前段上升基础不足，不作为标准3分。"),
        ],
        "reject_as_representative": [
            ("S-9DE9CE054153", 1, "完整窗口仍较混乱，尾端冲高不足以代表标准刚突破。"),
            ("S-428B632E5608", 1, "大区间内部波动占主导，压力结构和接近过程不够干净。"),
            ("S-5A27DD7D7279", 1, "末端上涨过度集中，较像快速拉升而不是有序突破确认。"),
            ("S-82A910694D5D", 1, "此前宽幅震荡和异常下影较多，局部新高的质量不足。"),
            ("S-BE087632F430", 1, "仍带有明显大区间属性，尾端突破不够代表标准模子。"),
        ],
    },
    "pullback_strengthening": {
        "label": "回调转强",
        "slug": "pullback-strengthening-segments",
        "representative": [
            ("S-1216434156E4", 3, "前段上升清楚，近期回调约9%，低点后连续收复并接近前高。"),
            ("S-B0FD9125DF06", 3, "上升基础完整，回调深度适中，低点后6根内恢复约八成。"),
            ("S-79457207DE3A", 3, "阶梯上升后出现可辨认回调，评分日前3根迅速转强。"),
            ("S-2E033C022FEA", 3, "中期趋势向上，近期回调受控，低点后重新站回强势区。"),
            ("S-DA9E59F6D983", 3, "前段涨幅充分，回调没有破坏主结构，评分日出现明确收复。"),
            ("S-316727B7BF35", 3, "高低点总体抬高，近期回调约10%，随后有序恢复而非单日反抽。"),
            ("S-5BF82CD54A43", 3, "持续上升后回调，低点距今3根，转强过程清楚且仍未失真。"),
            ("S-3F1136639E61", 3, "长期趋势连续，近期回调后逐步收复，节奏和深度都较合理。"),
            ("S-DA76939A59DB", 3, "前段上升稳定，近期回撤后低点很近，评分日已有明确转强。"),
            ("S-4D176CB8583F", 3, "上升基础、真实回调和恢复三段结构完整，适合作为代表模子。"),
        ],
        "boundary": [
            ("S-1CA52568C346", 2, "回调和恢复成立，但此前跳升较明显，趋势自然度略弱。"),
            ("S-E662E20EEC5A", 2, "近期回调转强可见，但完整窗口波动偏大，只作边界。"),
            ("S-2758A61A7403", 2, "低点后恢复较清楚，但中段来回较多，结构不够标准。"),
            ("S-CBEEFED5430A", 2, "上升后回调成立，但恢复已接近完成，时点略偏晚。"),
            ("S-C1D01378BCB2", 2, "回调深度适中且评分日强力收复，但确认主要集中在单根K线。"),
        ],
        "reject_as_representative": [
            ("S-721FAFB8A48D", 1, "完整窗口宽幅震荡，前段上升基础不够连续。"),
            ("S-ABCEC7C1DE97", 1, "大区间波动占主导，局部回调恢复不足以代表标准结构。"),
            ("S-39C4767997B1", 1, "多次剧烈来回，回调和转强边界难以清晰分段。"),
            ("S-F97A62ABB1CF", 1, "旧尖峰和大区间影响明显，当前恢复缺少稳定上升基础。"),
            ("S-BA6BDD717D6E", 0, "主要结构由一次大跳升形成，不是健康上涨后的受控回调。"),
        ],
    },
}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _fact_line(category: str, diagnostics: dict[str, float]) -> str:
    if category == "fresh_breakout":
        return (
            f"突破后第 {diagnostics['breakout_age']:.0f} 根 · "
            f"高于压力 {diagnostics['breakout_current_margin']:.1%} · "
            f"相对60日高点 {diagnostics['breakout_vs_prior_60']:.1%} · "
            f"完整区间位置 {diagnostics['range_position_120']:.0%}"
        )
    return (
        f"前段涨幅 {diagnostics['prior_advance_before_peak']:.1%} · "
        f"近期真实回调 {diagnostics['recent_pullback_depth_40']:.1%} · "
        f"低点距今 {diagnostics['recent_pullback_low_age']:.0f} 根 · "
        f"已收复 {diagnostics['recent_recovery_fraction']:.0%}"
    )


def _render_category(
    category: str, spec: dict[str, Any], rankings: dict[str, dict[str, Any]]
) -> str:
    labels = {
        "representative": "✅ 代表模子",
        "boundary": "⚠️ 边界片段",
        "reject_as_representative": "❌ 明确不作为模子",
    }
    sections = []
    for group in ("representative", "boundary", "reject_as_representative"):
        cards = []
        for sample_id, rating, reason in spec[group]:
            item = rankings[sample_id]
            cards.append(
                f"""<article class="{group}">
<h2>{escape(sample_id)} · {rating}分</h2>
<p>{escape(reason)}</p>
<p class="facts">{escape(_fact_line(category, item['diagnostics']))}</p>
<img src="charts/{escape(sample_id)}.svg" alt="{escape(sample_id)}">
</article>"""
            )
        sections.append(f"<section><h1>{labels[group]}</h1>{''.join(cards)}</section>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>{spec['label']} · 历史区间模子</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f3f6f8;color:#152238}}
main{{max-width:1120px;margin:auto;padding:24px}}header,article{{background:#fff;border-radius:16px;padding:20px;margin:16px 0}}
header{{border-left:10px solid #178c66}}article{{border-left:9px solid #168d67}}
article.boundary{{border-left-color:#d29a18}}article.reject_as_representative{{border-left-color:#ba4545}}
h1,h2{{margin:.25em 0}}p{{line-height:1.65}}.notice{{background:#eef8f4;padding:14px;border-radius:12px}}
.facts{{color:#5c687b;font-size:14px}}img{{width:100%;display:block;margin-top:10px}}
</style></head><body><main><header>
<h1>{spec['label']} · 历史区间模子 v3</h1>
<p class="notice">从87,741个历史评分日区间中滚动寻找；本类拥有独立评分器和视觉标准，
不复用另外两类的门槛。</p>
<p>仅使用本机 zer0share 快照20260727；不使用未来数据；同一股票只留一个区间。
当前是AI视觉短名单，等待用户确认方向，不是封存评估结论。</p>
</header>{''.join(sections)}</main></body></html>"""


def main() -> int:
    links = []
    for category, spec in REVIEWS.items():
        root = OUTPUT_ROOT / spec["slug"]
        rows = json.loads((root / "rankings.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        by_id = {item["sample_id"]: item for item in rows}
        selected_ids = [
            sample_id
            for group in ("representative", "boundary", "reject_as_representative")
            for sample_id, _, _ in spec[group]
        ]
        missing = sorted(set(selected_ids).difference(by_id))
        if missing:
            raise ValueError(f"{category}: shortlist ids missing: {', '.join(missing)}")
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError(f"{category}: shortlist cannot reuse a sample")
        payload = {
            "schema_version": "shape-v2-template-segment-shortlist/1",
            "category": category,
            "status": "ai_visual_provisional",
            "source_role": "template",
            "source_dataset": manifest["dataset_version"],
            "review_rules": [
                "只使用评分日及以前120根K线",
                "同一股票只保留一个历史区间",
                "代表、边界和剔除均由本类独立语义判断",
                "本页不是封存评估集",
            ],
            "groups": {
                group: [
                    {"sample_id": sample_id, "rating": rating, "reason": reason}
                    for sample_id, rating, reason in spec[group]
                ]
                for group in (
                    "representative",
                    "boundary",
                    "reject_as_representative",
                )
            },
        }
        _write_json(root / "visual-shortlist.json", payload)
        (root / "visual-shortlist.html").write_text(
            _render_category(category, spec, by_id), encoding="utf-8"
        )
        links.append(
            f'<li><a href="{escape(spec["slug"])}/visual-shortlist.html">'
            f'{escape(spec["label"])}模子页</a></li>'
        )
    hub = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>形态V2 · 另外两类模子</title>
<style>body{{font-family:system-ui;background:#f3f6f8;color:#152238}}
main{{max-width:760px;margin:60px auto;background:#fff;padding:32px;border-radius:18px}}
li{{font-size:22px;margin:18px}}a{{color:#087b5b}}</style></head><body><main>
<h1>形态V2 · 另外两类历史模子</h1>
<p>先看每页的“代表模子”即可；边界和剔除用于解释算法边界。</p>
<ul>{''.join(links)}</ul></main></body></html>"""
    (OUTPUT_ROOT / "index.html").write_text(hub, encoding="utf-8")
    print(OUTPUT_ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
