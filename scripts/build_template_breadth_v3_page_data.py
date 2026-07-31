from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "unified-threshold-v3-20260729"
)
DEFAULT_PUBLIC = PROJECT_ROOT / "public" / "template-breadth-v3.json"
DISPLAY_THRESHOLD = 0.80
RECENT_DAYS = 60


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    cue: str
    accent: str


TEMPLATES = (
    Template(
        "fresh_breakout",
        "刚突破",
        "平台蓄势后向上突破，尾段仍保持力度",
        "#d97706",
    ),
    Template(
        "healthy_uptrend",
        "健康上涨",
        "持续抬高，回撤受控，不靠末端拔线",
        "#0f766e",
    ),
    Template(
        "pullback_strengthening",
        "回调转强",
        "先走强、再回吐，随后恢复向上",
        "#6d5bd0",
    ),
    Template(
        "parabolic_uptrend",
        "抛物线上升",
        "前段较缓，随后斜率放大并加速",
        "#be123c",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--public", type=Path, default=DEFAULT_PUBLIC)
    return parser.parse_args()


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(
        frame.replace({np.nan: None}).to_json(orient="records", force_ascii=False)
    )


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    public = args.public.resolve()
    if PROJECT_ROOT not in source.parents or PROJECT_ROOT not in public.parents:
        raise RuntimeError("输入与输出必须位于工作区")
    if public.exists():
        raise RuntimeError(f"拒绝覆盖现有页面数据：{public}")

    market = pd.read_csv(source / "daily_threshold_counts.csv")
    industry = pd.read_csv(source / "industry_daily.csv")
    top30 = pd.read_csv(source / "latest_top30.csv")
    candidate_decisions = json.loads(
        (source / "candidate_evaluation.json").read_text(encoding="utf-8")
    )

    market = market[np.isclose(market["threshold"], DISPLAY_THRESHOLD)].copy()
    industry = industry[
        np.isclose(industry["threshold"], DISPLAY_THRESHOLD)
    ].copy()
    as_of = str(int(market["trade_date"].max()))

    page_templates = []
    for template in TEMPLATES:
        template_market = market[
            market["template"] == template.key
        ].sort_values("trade_date")
        recent_market = template_market.tail(RECENT_DAYS)
        latest = recent_market.iloc[-1]

        template_top30 = top30[top30["template"] == template.key].copy()
        template_top30["above_threshold"] = (
            template_top30["score"] >= DISPLAY_THRESHOLD
        )

        template_industry = industry[
            industry["template"] == template.key
        ].sort_values(["industry_code", "trade_date"])
        template_industry["change_5d"] = template_industry.groupby(
            "industry_code"
        )["above_count"].diff(5)
        current_industries = template_industry[
            template_industry["trade_date"] == int(as_of)
        ].copy()
        current_industries["change_5d"] = (
            current_industries["change_5d"].fillna(0).astype(int)
        )
        industry_series = []
        for (industry_code, industry_name), group in template_industry.groupby(
            ["industry_code", "industry"], sort=True
        ):
            points = group.sort_values("trade_date").tail(RECENT_DAYS)
            industry_series.append(
                {
                    "industryCode": str(industry_code),
                    "industry": str(industry_name),
                    "points": [
                        {
                            "date": str(int(row.trade_date)),
                            "count": int(row.above_count),
                        }
                        for row in points.itertuples(index=False)
                    ],
                }
            )

        page_templates.append(
            {
                "key": template.key,
                "label": template.label,
                "cue": template.cue,
                "accent": template.accent,
                "summary": {
                    "count": int(latest["above_count"]),
                    "change1d": int(latest["change_1d"]),
                    "change5d": int(latest["change_5d"]),
                    "ma5": round(float(latest["ma5"]), 1),
                    "position": str(latest["historical_position"]),
                    "historicalPercentile": round(
                        float(latest["historical_percentile"]) * 100, 1
                    ),
                },
                "marketSeries": [
                    {
                        "date": str(int(row.trade_date)),
                        "count": int(row.above_count),
                        "ma5": round(float(row.ma5), 2),
                    }
                    for row in recent_market.itertuples(index=False)
                ],
                "top30": records(
                    template_top30[
                        [
                            "rank",
                            "ts_code",
                            "name",
                            "industry",
                            "score",
                            "above_threshold",
                        ]
                    ]
                ),
                "industries": records(
                    current_industries[
                        [
                            "industry_code",
                            "industry",
                            "above_count",
                            "top100_count",
                            "top100_share",
                            "new_count",
                            "retained_count",
                            "exit_count",
                            "change_5d",
                        ]
                    ].sort_values(
                        ["above_count", "top100_count", "industry"],
                        ascending=[False, False, True],
                    )
                ),
                "industrySeries": industry_series,
            }
        )

    payload = {
        "version": "template-breadth-v3-exploratory-080",
        "asOf": as_of,
        "historyStart": str(int(market["trade_date"].min())),
        "displayThreshold": DISPLAY_THRESHOLD,
        "warning": (
            "0.80 是用户指定的试用观察线。实验显示它不适合作为四模板统一常态基准；"
            "页面用于先观察数量和变化，不代表该线已验证有效。"
        ),
        "candidateDecisions": candidate_decisions,
        "templates": page_templates,
        "boundaries": {
            "dataSource": r"C:\Users\hp\Documents\zer0share",
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
            "algorithm": "前复权 log-close；窗口内独立 z；单窗口 Pearson",
        },
    }

    if len(payload["templates"]) != 4:
        raise RuntimeError("页面模板数量错误")
    for template in payload["templates"]:
        if len(template["marketSeries"]) != RECENT_DAYS:
            raise RuntimeError(f"{template['label']} 近60日序列不完整")
        if len(template["top30"]) != 30:
            raise RuntimeError(f"{template['label']} Top30 不完整")
        if not template["industries"]:
            raise RuntimeError(f"{template['label']} 行业数据为空")

    public.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (source / "app-data-080.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(public)


if __name__ == "__main__":
    main()
