from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api

from build_template_statistical_validation import (
    PROJECT_ROOT,
    TEMPLATES,
    ZERO_CONFIG,
    ZERO_ROOT,
    build_series,
    load_market_data,
    load_stock_metadata,
    load_templates,
)
from build_unified_threshold_v3 import active_industry_map, rolling_scores


TOP_K = 100
COMPARISON_DAYS = 5
DISPLAY_DAYS = 60
CALCULATION_DAYS = DISPLAY_DAYS + COMPARISON_DAYS
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "top100-breadth-20260729"
)
DEFAULT_PUBLIC = PROJECT_ROOT / "public" / "template-breadth-v3.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--public", type=Path, default=DEFAULT_PUBLIC)
    return parser.parse_args()


def stock_record(row: pd.Series) -> dict:
    return {
        "ts_code": str(row["ts_code"]),
        "code": str(row["ts_code"]).split(".")[0],
        "name": str(row["name"]),
        "industry": str(row["industry"]),
        "industry_code": str(row["industry_code"]),
        "score": round(float(row["score"]), 8),
        "rank": int(row["rank"]),
        "window_start": str(row["window_start"]),
        "window_end": str(row["trade_date"]),
    }


def build_template_frames(
    *,
    scores: pd.DataFrame,
    template_key: str,
    template_bars: int,
    series: dict[str, dict],
    members: pd.DataFrame,
    names: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(scores["trade_date"].astype(str).unique())[-CALCULATION_DAYS:]
    memberships: list[dict] = []
    industry_rows: list[dict] = []
    daily_top: dict[str, pd.DataFrame] = {}

    for current in dates:
        frame = scores[scores["trade_date"].astype(str) == current].sort_values(
            ["score", "ts_code"], ascending=[False, True]
        ).reset_index(drop=True)
        frame["rank"] = np.arange(1, len(frame) + 1)
        lookup = active_industry_map(members, current)
        frame["industry_code"] = frame["ts_code"].map(
            lambda code: lookup.get(str(code), ("missing", "行业缺失"))[0]
        )
        frame["industry"] = frame["ts_code"].map(
            lambda code: lookup.get(str(code), ("missing", "行业缺失"))[1]
        )
        frame["name"] = frame["ts_code"].map(
            lambda code: names.get(str(code), str(code))
        )
        def window_start(code: str) -> str:
            dates = np.asarray(series[str(code)]["dates"], dtype=str)
            positions = np.flatnonzero(dates == current)
            if not len(positions) or positions[-1] + 1 < template_bars:
                raise RuntimeError(f"{code} {current} 缺少候选窗口日期")
            return str(dates[positions[-1] - template_bars + 1])

        frame["window_start"] = frame["ts_code"].map(window_start)
        top = frame.head(TOP_K).copy()
        daily_top[current] = top
        for row in top.itertuples(index=False):
            memberships.append(
                {
                    "trade_date": current,
                    "template": template_key,
                    "rank": int(row.rank),
                    "ts_code": str(row.ts_code),
                    "name": str(row.name),
                    "industry_code": str(row.industry_code),
                    "industry": str(row.industry),
                    "score": float(row.score),
                    "window_start": str(row.window_start),
                    "window_end": current,
                }
            )

        prior = (
            daily_top[dates[dates.index(current) - COMPARISON_DAYS]]
            if dates.index(current) >= COMPARISON_DAYS
            else top.iloc[0:0]
        )
        current_codes = set(top["ts_code"])
        prior_codes = set(prior["ts_code"])
        new_codes = current_codes - prior_codes
        retained_codes = current_codes & prior_codes
        exit_codes = prior_codes - current_codes
        current_groups = {
            str(code): group
            for code, group in frame.groupby("industry_code", sort=True)
        }
        current_names = (
            frame.set_index("industry_code")["industry"].astype(str).to_dict()
        )
        prior_names = (
            prior.set_index("industry_code")["industry"].astype(str).to_dict()
        )
        industry_codes = sorted(
            set(current_groups)
            | set(prior.loc[prior["ts_code"].isin(exit_codes), "industry_code"])
        )
        for industry_code in industry_codes:
            eligible = current_groups.get(industry_code, frame.iloc[0:0])
            current_industry = top[top["industry_code"] == industry_code]
            prior_industry = prior[prior["industry_code"] == industry_code]
            industry_rows.append(
                {
                    "trade_date": current,
                    "template": template_key,
                    "industry_code": industry_code,
                    "industry": current_names.get(
                        industry_code,
                        prior_names.get(industry_code, "行业缺失"),
                    ),
                    "eligible_count": int(len(eligible)),
                    "top100_count": int(len(current_industry)),
                    "selection_rate": (
                        float(len(current_industry) / len(eligible))
                        if len(eligible)
                        else 0.0
                    ),
                    "top100_share": float(len(current_industry) / TOP_K),
                    "new_count": int(
                        current_industry["ts_code"].isin(new_codes).sum()
                    ),
                    "retained_count": int(
                        current_industry["ts_code"].isin(retained_codes).sum()
                    ),
                    "exit_count": int(
                        prior_industry["ts_code"].isin(exit_codes).sum()
                    ),
                    "comparison_trade_date": (
                        dates[dates.index(current) - COMPARISON_DAYS]
                        if dates.index(current) >= COMPARISON_DAYS
                        else ""
                    ),
                }
            )

    membership = pd.DataFrame(memberships)
    industry = pd.DataFrame(industry_rows)
    return membership, industry


def build_page_data(
    memberships: pd.DataFrame,
    industries: pd.DataFrame,
    eligible_counts: pd.DataFrame,
    as_of: str,
) -> dict:
    templates = []
    for template in TEMPLATES:
        membership = memberships[memberships["template"] == template.key].copy()
        industry = industries[industries["template"] == template.key].copy()
        current = membership[membership["trade_date"] == as_of].sort_values("rank")
        current_industry = industry[industry["trade_date"] == as_of].copy()
        comparison_date = str(current_industry["comparison_trade_date"].iloc[0])
        prior = membership[membership["trade_date"] == comparison_date].copy()
        current_codes = set(current["ts_code"])
        prior_codes = set(prior["ts_code"])
        new_codes = current_codes - prior_codes
        retained_codes = current_codes & prior_codes
        exit_codes = prior_codes - current_codes
        by_date = (
            eligible_counts[eligible_counts["template"] == template.key]
            .sort_values("trade_date")
            .tail(DISPLAY_DAYS)
        )

        industry_items = []
        for row in current_industry.sort_values(
            ["top100_count", "selection_rate", "industry"],
            ascending=[False, False, True],
        ).itertuples(index=False):
            code = str(row.industry_code)
            current_stocks = current[current["industry_code"] == code]
            prior_stocks = prior[prior["industry_code"] == code]
            industry_items.append(
                {
                    "industry_code": code,
                    "industry": str(row.industry),
                    "eligible_count": int(row.eligible_count),
                    "top100_count": int(row.top100_count),
                    "selection_rate": round(float(row.selection_rate), 8),
                    "top100_share": round(float(row.top100_share), 8),
                    "new_count": int(row.new_count),
                    "retained_count": int(row.retained_count),
                    "exit_count": int(row.exit_count),
                    "change_5d": int(row.top100_count)
                    - int(len(prior_stocks)),
                    "current_stocks": [
                        stock_record(item)
                        for _, item in current_stocks.sort_values("rank").iterrows()
                    ],
                    "new_stocks": [
                        stock_record(item)
                        for _, item in current_stocks[
                            current_stocks["ts_code"].isin(new_codes)
                        ]
                        .sort_values("rank")
                        .iterrows()
                    ],
                    "retained_stocks": [
                        stock_record(item)
                        for _, item in current_stocks[
                            current_stocks["ts_code"].isin(retained_codes)
                        ]
                        .sort_values("rank")
                        .iterrows()
                    ],
                    "exit_stocks": [
                        stock_record(item)
                        for _, item in prior_stocks[
                            prior_stocks["ts_code"].isin(exit_codes)
                        ]
                        .sort_values("rank")
                        .iterrows()
                    ],
                }
            )

        detail_series = []
        for (code, name), group in industry.groupby(
            ["industry_code", "industry"], sort=True
        ):
            detail_series.append(
                {
                    "industryCode": str(code),
                    "industry": str(name),
                    "points": [
                        {
                            "date": str(row.trade_date),
                            "count": int(row.top100_count),
                            "top100_count": int(row.top100_count),
                            "eligible_count": int(row.eligible_count),
                            "selection_rate": round(
                                float(row.selection_rate), 8
                            ),
                        }
                        for row in group.sort_values("trade_date")
                        .tail(DISPLAY_DAYS)
                        .itertuples(index=False)
                    ],
                }
            )

        top_records = [stock_record(row) for _, row in current.iterrows()]
        templates.append(
            {
                "key": template.key,
                "label": template.label,
                "cue": template.cue,
                "accent": template.accent,
                "summary": {
                    "count": TOP_K,
                    "eligibleCount": int(
                        by_date.iloc[-1]["eligible_count"]
                    ),
                    "comparisonDate": comparison_date,
                    "newCount": int(len(new_codes)),
                    "retainedCount": int(len(retained_codes)),
                    "exitCount": int(len(exit_codes)),
                },
                "marketSeries": [
                    {
                        "date": str(row.trade_date),
                        "count": TOP_K,
                        "eligibleCount": int(row.eligible_count),
                    }
                    for row in by_date.itertuples(index=False)
                ],
                "top30": top_records[:30],
                "top100": top_records,
                "industries": industry_items,
                "industrySeries": detail_series,
            }
        )

    return {
        "version": "template-top100-breadth-v1",
        "asOf": as_of,
        "historyStart": min(
            point["date"]
            for template in templates
            for point in template["marketSeries"]
        ),
        "selection": {
            "method": "每个模板每日按单窗口 Pearson 降序固定取 Top100",
            "topK": TOP_K,
            "comparisonTradingDays": COMPARISON_DAYS,
            "industryRateDenominator": "行业当日可选股票数",
            "selectionRateUnit": "比例（页面显示为百分比）",
        },
        "templates": templates,
        "boundaries": {
            "dataSource": str(ZERO_ROOT),
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
            "algorithm": "前复权 log-close；窗口内独立 z；单窗口 Pearson",
            "crossTemplateRankingUsed": False,
        },
    }


def validate(
    memberships: pd.DataFrame,
    industries: pd.DataFrame,
    payload: dict,
) -> dict:
    checks = []
    for template in TEMPLATES:
        membership = memberships[memberships["template"] == template.key]
        industry = industries[industries["template"] == template.key]
        daily_members = membership.groupby("trade_date")["ts_code"].agg(
            ["count", "nunique"]
        )
        assert (daily_members["count"] == TOP_K).all()
        assert (daily_members["nunique"] == TOP_K).all()
        totals = industry.groupby("trade_date").agg(
            top100_count=("top100_count", "sum"),
            new_count=("new_count", "sum"),
            retained_count=("retained_count", "sum"),
            exit_count=("exit_count", "sum"),
        )
        assert (totals["top100_count"] == TOP_K).all()
        comparable = totals.iloc[COMPARISON_DAYS:]
        assert (
            comparable["new_count"] + comparable["retained_count"] == TOP_K
        ).all()
        assert (
            comparable["exit_count"] + comparable["retained_count"] == TOP_K
        ).all()
        assert (
            (industry["top100_count"] <= industry["eligible_count"])
            | (industry["eligible_count"] == 0)
        ).all()
        expected_rate = np.divide(
            industry["top100_count"],
            industry["eligible_count"],
            out=np.zeros(len(industry), dtype=float),
            where=industry["eligible_count"].to_numpy() > 0,
        )
        assert np.allclose(industry["selection_rate"], expected_rate)
        page_template = next(
            item for item in payload["templates"] if item["key"] == template.key
        )
        assert sum(
            item["top100_count"] for item in page_template["industries"]
        ) == TOP_K
        checks.append(
            {
                "template": template.key,
                "dates": int(membership["trade_date"].nunique()),
                "latestEligible": page_template["summary"]["eligibleCount"],
                "latestTop100": len(page_template["top100"]),
                "industryCount": len(page_template["industries"]),
                "fiveDayIdentity": True,
            }
        )
    return {
        "pass": True,
        "asOf": payload["asOf"],
        "topK": TOP_K,
        "comparisonTradingDays": COMPARISON_DAYS,
        "templates": checks,
        "leakageAudit": payload["boundaries"],
    }


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    public = args.public.resolve()
    if PROJECT_ROOT not in output.parents or PROJECT_ROOT not in public.parents:
        raise RuntimeError("输出必须位于工作区")
    if output.exists():
        raise RuntimeError(f"拒绝覆盖现有原始输出：{output}")

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        market, as_of = load_market_data(pro)
        stocks = load_stock_metadata(pro)
        templates = load_templates(market)
        series = build_series(market)
        members = pro.index_member_all(
            fields="ts_code,l1_code,l1_name,in_date,out_date,is_new"
        )
    finally:
        os.chdir(previous_cwd)

    for column in ("ts_code", "l1_code", "l1_name", "in_date", "out_date"):
        if column not in members:
            members[column] = np.nan
    members["ts_code"] = members["ts_code"].astype(str)
    members["in_date"] = members["in_date"].astype(str).replace("nan", np.nan)
    members["out_date"] = members["out_date"].astype(str).replace("nan", np.nan)
    names = stocks.set_index("ts_code")["name"].astype(str).to_dict()

    all_memberships = []
    all_industries = []
    eligible_rows = []
    for template in TEMPLATES:
        print(f"计算 {template.label} Top100", flush=True)
        scores = rolling_scores(
            series, stocks, templates[template.key]["z"], template.bars, as_of
        )
        recent_dates = sorted(scores["trade_date"].unique())[-CALCULATION_DAYS:]
        recent_scores = scores[scores["trade_date"].isin(recent_dates)].copy()
        membership, industry = build_template_frames(
            scores=recent_scores,
            template_key=template.key,
            template_bars=template.bars,
            series=series,
            members=members,
            names=names,
        )
        all_memberships.append(membership)
        all_industries.append(industry)
        eligible_rows.extend(
            {
                "trade_date": str(date),
                "template": template.key,
                "eligible_count": int(len(frame)),
            }
            for date, frame in recent_scores.groupby("trade_date", sort=True)
        )

    memberships = pd.concat(all_memberships, ignore_index=True)
    industries = pd.concat(all_industries, ignore_index=True)
    eligible = pd.DataFrame(eligible_rows)
    payload = build_page_data(memberships, industries, eligible, as_of)
    qa = validate(memberships, industries, payload)

    output.mkdir(parents=True)
    memberships.to_csv(
        output / "top100_membership_daily.csv",
        index=False,
        encoding="utf-8-sig",
    )
    industries.to_csv(
        output / "top100_industry_daily.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output / "page-data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "qa-data-results.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    public.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
