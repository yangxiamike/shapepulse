from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHAPE_ROOT = PROJECT_ROOT / "outputs" / "shape-v2"
CURRENT_ROOT = SHAPE_ROOT / "template-current"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the user-facing gallery of accepted 3-point shape templates."
    )
    parser.add_argument("--breakout-version", type=int, default=7)
    parser.add_argument("--breakout-count", type=int, default=10)
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _approved_rows(
    version: int,
) -> list[dict[str, str]]:
    sources = [
        (
            "healthy_uptrend",
            "健康上升趋势",
            SHAPE_ROOT
            / "template-discovery-v2"
            / "healthy-uptrend-segments",
        ),
        (
            "pullback_strengthening",
            "回调转强",
            SHAPE_ROOT
            / "template-discovery-v3"
            / "pullback-strengthening-segments",
        ),
    ]
    rows: list[dict[str, str]] = []
    for category, label, root in sources:
        shortlist = _read_json(root / "visual-shortlist.json")
        for item in shortlist["groups"]["representative"]:
            rows.append(
                {
                    "category": category,
                    "label": label,
                    "sample_id": item["sample_id"],
                    "reason": item["reason"],
                    "chart": str(
                        Path("..")
                        / root.relative_to(SHAPE_ROOT)
                        / "charts"
                        / f"{item['sample_id']}.svg"
                    ).replace("\\", "/"),
                }
            )
    return rows


def _breakout_reason(diagnostics: dict[str, float]) -> str:
    return_100 = float(diagnostics["pre_breakout_return_100"])
    slope_100 = float(diagnostics["pre_breakout_trend_slope_100"])
    position_100 = float(diagnostics["pre_breakout_range_position_100"])
    if return_100 < -0.04 or slope_100 < -0.04:
        setup = "较长阴跌或走弱后"
    elif position_100 < 0.58:
        setup = "区间低位或底部震荡后"
    else:
        setup = "较长横盘、原趋势已重置后"
    age = int(round(float(diagnostics["breakout_age"])))
    return (
        f"{setup}突然拉升并打破局部结构；突破后第{age}根仍守住，"
        "不是上涨趋势中的再次创新高。"
    )


def _breakout_rows(version: int, count: int) -> list[dict[str, str]]:
    root = (
        SHAPE_ROOT
        / f"template-discovery-v{version}"
        / "fresh-breakout-segments"
    )
    rankings = _read_json(root / "rankings.json")
    eligible = [item for item in rankings if not item["hard_findings"]]
    selected = eligible[:count]
    if len(selected) < count:
        raise ValueError(
            f"only {len(selected)} eligible breakout rows, expected {count}"
        )
    return [
        {
            "category": "fresh_breakout",
            "label": "刚突破",
            "sample_id": item["sample_id"],
            "reason": _breakout_reason(item["diagnostics"]),
            "chart": str(
                Path("..")
                / root.relative_to(SHAPE_ROOT)
                / "charts"
                / f"{item['sample_id']}.svg"
            ).replace("\\", "/"),
        }
        for item in selected
    ]


def _card(item: dict[str, str]) -> str:
    return f"""<article>
<h2>{escape(item["sample_id"])} · 3分</h2>
<p>{escape(item["reason"])}</p>
<img src="{escape(item["chart"])}" alt="{escape(item["sample_id"])}">
</article>"""


def main() -> int:
    args = parse_args()
    if args.breakout_version < 1 or args.breakout_count < 1:
        raise ValueError("version and count must be positive")
    rows = _approved_rows(args.breakout_version)
    rows.extend(_breakout_rows(args.breakout_version, args.breakout_count))
    categories = [
        ("healthy_uptrend", "健康上升趋势", "一直涨得健康"),
        (
            "pullback_strengthening",
            "回调转强",
            "涨过、回调了、现在重新转强",
        ),
        ("fresh_breakout", "刚突破", "原来没在涨，现在突然开始涨"),
    ]
    sections = []
    for category, label, definition in categories:
        cards = "".join(
            _card(item) for item in rows if item["category"] == category
        )
        sections.append(
            f"""<section id="{escape(category)}">
<header><h1>{escape(label)}</h1><p>{escape(definition)}</p></header>
{cards}</section>"""
        )
    CURRENT_ROOT.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>形态V2 · 只看认可的3分模子</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f2f5f7;color:#152238}}
main{{max-width:1120px;margin:auto;padding:24px}}nav{{position:sticky;top:0;background:#f2f5f7ee;padding:12px 0;z-index:2}}
nav a{{display:inline-block;margin:4px 10px 4px 0;padding:10px 16px;border-radius:999px;background:#fff;color:#087b5b;text-decoration:none}}
.intro,header,article{{background:#fff;border-radius:16px;padding:20px;margin:16px 0}}
.intro{{border-left:10px solid #178c66}}header{{border-left:9px solid #178c66}}
article{{border-left:9px solid #178c66}}h1,h2{{margin:.25em 0}}p{{line-height:1.65}}
img{{width:100%;display:block;margin-top:10px}}.scope{{color:#5c687b}}
</style></head><body><main>
<div class="intro"><h1>只看认可的3分模子</h1>
<p>1分和2分继续留作算法内部的反例与边界材料，不再要求逐条复核。</p>
<p class="scope">只使用评分日及以前120根K线和成交量；匿名、归一化、不含未来信息。</p></div>
<nav><a href="#healthy_uptrend">健康上升趋势</a>
<a href="#pullback_strengthening">回调转强</a>
<a href="#fresh_breakout">刚突破</a></nav>
{''.join(sections)}</main></body></html>"""
    (CURRENT_ROOT / "index.html").write_text(html, encoding="utf-8")
    _write_json(
        CURRENT_ROOT / "three-point-gallery.json",
        {
            "schema_version": "shape-v2-three-point-gallery/1",
            "status": "user_definition_confirmed_ai_visual_provisional",
            "breakout_version": args.breakout_version,
            "rows": rows,
        },
    )
    print(CURRENT_ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
