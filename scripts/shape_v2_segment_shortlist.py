from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "template-discovery-v2"
    / "healthy-uptrend-segments"
)


GROUPS = {
    "representative": [
        (
            "S-149153362198",
            3,
            "上升贯穿完整窗口，斜率稳定，回撤小，没有依赖尾端突击。",
        ),
        (
            "S-71CE133BA6D2",
            3,
            "高低点持续抬高，阶段回撤短而浅，趋势连续度高。",
        ),
        (
            "S-6E236E9910D9",
            3,
            "多阶段平稳抬升，整段最大回撤仅约4%，末端仍保持结构。",
        ),
        (
            "S-BD88FC73A830",
            3,
            "中前段已经建立上升基础，随后稳步创新高，没有深快回撤。",
        ),
        (
            "S-AA7C030FAB1E",
            3,
            "涨幅分布在完整窗口，回撤受控，量价没有明显失真。",
        ),
        (
            "S-FB4202871453",
            3,
            "阶梯式上升清楚，平台整理短，整段和近60日回撤都较小。",
        ),
        (
            "S-3DF1CFEA43CA",
            3,
            "前中后段均有抬升，整理不破坏主趋势，末端不过度陡峭。",
        ),
        (
            "S-ABC73DAEE88A",
            3,
            "上升基础形成较早，后段延续顺畅，回撤和波动均受控。",
        ),
        (
            "S-43FD3FE1FB79",
            3,
            "趋势由多个小台阶组成，最大回撤低，末端没有明显走弱。",
        ),
        (
            "S-3631281731DD",
            3,
            "高低点总体持续抬高，途中回撤短，随后能较快恢复。",
        ),
    ],
    "boundary": [
        (
            "S-C41F2469FC0B",
            2,
            "整段回撤很小，但后半段加速较明显，代表性略打折。",
        ),
        (
            "S-F3B9BD4B63F0",
            2,
            "总体健康，但中段台阶跳变较明显，不作为最标准的平滑模子。",
        ),
        (
            "S-EBF0D28AFEF6",
            2,
            "趋势成立，但后段波动放大，距离理想健康趋势有差距。",
        ),
        (
            "S-D38F37EA5835",
            2,
            "完整趋势成立，评分日处在回撤阶段，因此只作为边界。",
        ),
        (
            "S-4185514C8ED3",
            2,
            "上升结构清楚，但多次跳台阶，连续和平滑程度不足。",
        ),
    ],
    "reject_as_representative": [
        (
            "S-415433D1D2CB",
            1,
            "主要高度来自少数跳升阶段，不适合做标准健康趋势模子。",
        ),
        (
            "S-B812B3037E6C",
            0,
            "中途存在异常大跳变，虽然收盘路径回撤不大，视觉结构仍失真。",
        ),
        (
            "S-83861B36413E",
            1,
            "前段长期平缓、末端集中加速，完整窗口的代表性不足。",
        ),
        (
            "S-90FD356D7439",
            1,
            "主要涨幅集中在后段并伴随跳升，不是稳定贯穿的健康趋势。",
        ),
        (
            "S-6A826CA8B1A9",
            1,
            "途中多次单点脉冲，整体虽向上但连续性和自然度不足。",
        ),
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
    return f"""<article class="{escape(group)}">
<h2>{escape(sample_id)} · {rating}分</h2>
<p class="reason">{escape(reason)}</p>
<p class="facts">整段最大回撤 {d['max_drawdown_120']:.1%} · 最差10日 {d['worst_return_10']:.1%} ·
120日涨幅 {d['return_119']:.1%} · 趋势连续度 {d['trend_fit_120']:.3f}</p>
<img src="charts/{escape(sample_id)}.svg" alt="{escape(sample_id)}">
</article>"""


def main() -> int:
    rankings = json.loads((SOURCE_ROOT / "rankings.json").read_text(encoding="utf-8"))
    by_id = {item["sample_id"]: item for item in rankings}
    flat_ids = [sample_id for rows in GROUPS.values() for sample_id, _, _ in rows]
    missing = sorted(set(flat_ids).difference(by_id))
    if missing:
        raise ValueError("shortlist ids missing from rankings: " + ", ".join(missing))
    if len(flat_ids) != len(set(flat_ids)):
        raise ValueError("shortlist cannot reuse a sample")

    labels = {
        "representative": "✅ 代表模子",
        "boundary": "⚠️ 边界片段",
        "reject_as_representative": "❌ 明确不作为模子",
    }
    sections = []
    for group, rows in GROUPS.items():
        cards = "".join(
            _card(group, sample_id, rating, reason, by_id[sample_id])
            for sample_id, rating, reason in rows
        )
        sections.append(f"<section><h1>{labels[group]}</h1>{cards}</section>")

    payload = {
        "schema_version": "shape-v2-template-segment-shortlist/1",
        "category": "healthy_uptrend",
        "status": "ai_visual_provisional_after_user_drawdown_correction",
        "source_role": "template",
        "source_dataset": "shape-v2.0.0-template-segments2-healthy-uptrend",
        "review_rules": [
            "整段最大回撤优先于仅看末端形态",
            "排除依赖少数跳空或末端集中拉升的片段",
            "同一股票只保留一个历史区间",
            "本页不是封存评估集，也不作为成熟模型结论",
        ],
        "groups": {
            group: [
                {"sample_id": sample_id, "rating": rating, "reason": reason}
                for sample_id, rating, reason in rows
            ]
            for group, rows in GROUPS.items()
        },
    }
    _write_json(SOURCE_ROOT / "visual-shortlist.json", payload)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>健康上升趋势 · 真正历史区间模子</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f3f6f8;color:#152238}}
main{{max-width:1120px;margin:auto;padding:24px}}header,article{{background:#fff;border-radius:16px;padding:20px;margin:16px 0}}
header{{border-left:10px solid #178c66}}article{{border-left:9px solid #168d67}}
article.boundary{{border-left-color:#d29a18}}article.reject_as_representative{{border-left-color:#ba4545}}
h1,h2{{margin:.25em 0}}p{{line-height:1.65}}.notice{{background:#eef8f4;padding:14px;border-radius:12px}}
.facts{{color:#5c687b;font-size:14px}}img{{width:100%;display:block;margin-top:10px}}
</style></head><body><main><header>
<h1>健康上升趋势 · 历史区间模子 v2</h1>
<p class="notice">这次是真正从历史评分日滚动找到的120根K线区间。代表模子必须整段回撤小、
上升贯穿前中后段，并且不能主要靠大跳空或尾端突然拉升。</p>
<p>扫描 87,741 个历史区间；只使用本机 zer0share 快照 20260727；不使用未来数据；
同一股票只保留一个区间。这里仍是 AI 视觉校准后的暂定模子，不是封存测试结论。</p>
</header>{''.join(sections)}</main></body></html>"""
    (SOURCE_ROOT / "visual-shortlist.html").write_text(html, encoding="utf-8")
    print(SOURCE_ROOT / "visual-shortlist.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
