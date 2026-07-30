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
SIMILARITY_ALGORITHM = (
    "qfq_log_close_independent_z_single_window_pearson"
)
CHANGE_WINDOWS = (10, 20)
DEFAULT_CHANGE_WINDOW = 10
DISPLAY_DAYS = 60
CALCULATION_DAYS = DISPLAY_DAYS + max(CHANGE_WINDOWS)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "top100-breadth-20260730"
)
DEFAULT_PUBLIC = PROJECT_ROOT / "public" / "template-breadth-v3.json"
DEFAULT_PUBLIC_DETAILS = PROJECT_ROOT / "public" / "template-breadth-v3-details"
DEFAULT_PUBLIC_RANKINGS = PROJECT_ROOT / "public" / "template-rankings"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--public", type=Path, default=DEFAULT_PUBLIC)
    parser.add_argument(
        "--public-details",
        type=Path,
        default=DEFAULT_PUBLIC_DETAILS,
    )
    parser.add_argument(
        "--public-rankings",
        type=Path,
        default=DEFAULT_PUBLIC_RANKINGS,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="完成计算和全部校验，但不写文件。",
    )
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
    date_positions = {date: index for index, date in enumerate(dates)}
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
            security_dates = np.asarray(series[str(code)]["dates"], dtype=str)
            positions = np.flatnonzero(security_dates == current)
            if not len(positions) or positions[-1] + 1 < template_bars:
                raise RuntimeError(f"{code} {current} 缺少候选窗口日期")
            return str(security_dates[positions[-1] - template_bars + 1])

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

        current_groups = {
            str(code): group
            for code, group in frame.groupby("industry_code", sort=True)
        }
        current_names = (
            frame.set_index("industry_code")["industry"].astype(str).to_dict()
        )
        current_codes = set(top["ts_code"])
        current_position = date_positions[current]
        for comparison_days in CHANGE_WINDOWS:
            comparison_date = (
                dates[current_position - comparison_days]
                if current_position >= comparison_days
                else ""
            )
            prior = (
                daily_top[comparison_date]
                if comparison_date
                else top.iloc[0:0]
            )
            prior_codes = set(prior["ts_code"])
            new_codes = current_codes - prior_codes
            retained_codes = current_codes & prior_codes
            exit_codes = prior_codes - current_codes
            prior_names = (
                prior.set_index("industry_code")["industry"]
                .astype(str)
                .to_dict()
            )
            industry_codes = sorted(
                set(current_groups)
                | set(
                    prior.loc[
                        prior["ts_code"].isin(exit_codes),
                        "industry_code",
                    ]
                )
            )
            for industry_code in industry_codes:
                eligible = current_groups.get(
                    industry_code, frame.iloc[0:0]
                )
                current_industry = top[
                    top["industry_code"] == industry_code
                ]
                prior_industry = prior[
                    prior["industry_code"] == industry_code
                ]
                industry_rows.append(
                    {
                        "trade_date": current,
                        "template": template_key,
                        "comparison_trading_days": comparison_days,
                        "comparison_trade_date": comparison_date,
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
                            current_industry["ts_code"]
                            .isin(new_codes)
                            .sum()
                        ),
                        "retained_count": int(
                            current_industry["ts_code"]
                            .isin(retained_codes)
                            .sum()
                        ),
                        "exit_count": int(
                            prior_industry["ts_code"]
                            .isin(exit_codes)
                            .sum()
                        ),
                    }
                )

    membership = pd.DataFrame(memberships)
    industry = pd.DataFrame(industry_rows)
    return membership, industry


def sorted_stock_records(frame: pd.DataFrame) -> list[dict]:
    return [
        stock_record(row)
        for _, row in frame.sort_values("rank").iterrows()
    ]


def lightweight_industry(
    *,
    code: str,
    name: str,
    eligible_count: int,
    top100_count: int,
    changes: dict[str, dict],
) -> dict:
    return {
        "industry_code": code,
        "industry": name,
        "eligible_count": eligible_count,
        "top100_count": top100_count,
        "selection_rate": round(
            top100_count / eligible_count if eligible_count else 0.0,
            8,
        ),
        "top100_share": round(top100_count / TOP_K, 8),
        "changes": changes,
    }


def build_page_data(
    memberships: pd.DataFrame,
    industries: pd.DataFrame,
    eligible_counts: pd.DataFrame,
    as_of: str,
) -> tuple[dict, dict[str, dict], dict[str, dict]]:
    templates: list[dict] = []
    detail_payloads: dict[str, dict] = {}
    ranking_payloads: dict[str, dict] = {}
    history_starts: list[str] = []

    for template in TEMPLATES:
        membership = memberships[
            memberships["template"] == template.key
        ].copy()
        industry = industries[
            industries["template"] == template.key
        ].copy()
        current = membership[
            membership["trade_date"] == as_of
        ].sort_values("rank")
        current_industry = industry[
            industry["trade_date"] == as_of
        ].copy()
        base_current = current_industry[
            current_industry["comparison_trading_days"]
            == DEFAULT_CHANGE_WINDOW
        ].copy()
        by_date = (
            eligible_counts[
                eligible_counts["template"] == template.key
            ]
            .sort_values("trade_date")
            .tail(DISPLAY_DAYS)
        )
        display_dates = tuple(by_date["trade_date"].astype(str))
        history_starts.append(display_dates[0])
        current_codes = set(current["ts_code"])

        contexts: dict[int, dict[str, object]] = {}
        for comparison_days in CHANGE_WINDOWS:
            current_rows = current_industry[
                current_industry["comparison_trading_days"]
                == comparison_days
            ]
            comparison_dates = set(
                current_rows["comparison_trade_date"].astype(str)
            )
            if len(comparison_dates) != 1:
                raise RuntimeError(
                    f"{template.label} {comparison_days} 日比较日期不唯一"
                )
            comparison_date = comparison_dates.pop()
            prior = membership[
                membership["trade_date"] == comparison_date
            ].copy()
            prior_codes = set(prior["ts_code"])
            contexts[comparison_days] = {
                "comparison_date": comparison_date,
                "prior": prior,
                "new_codes": current_codes - prior_codes,
                "retained_codes": current_codes & prior_codes,
                "exit_codes": prior_codes - current_codes,
            }

        summary_items: list[dict] = []
        detail_items: list[dict] = []
        for row in base_current.sort_values(
            ["top100_count", "selection_rate", "industry"],
            ascending=[False, False, True],
        ).itertuples(index=False):
            code = str(row.industry_code)
            name = str(row.industry)
            current_stocks = current[current["industry_code"] == code]
            changes: dict[str, dict] = {}
            detail_changes: dict[str, dict] = {}
            for comparison_days in CHANGE_WINDOWS:
                context = contexts[comparison_days]
                prior = context["prior"]
                assert isinstance(prior, pd.DataFrame)
                change_row = current_industry[
                    (
                        current_industry["comparison_trading_days"]
                        == comparison_days
                    )
                    & (current_industry["industry_code"].astype(str) == code)
                ]
                if len(change_row) != 1:
                    raise RuntimeError(
                        f"{template.label} {code} {comparison_days} 日行数错误"
                    )
                change = change_row.iloc[0]
                prior_stocks = prior[
                    prior["industry_code"].astype(str) == code
                ]
                new_codes = context["new_codes"]
                retained_codes = context["retained_codes"]
                exit_codes = context["exit_codes"]
                assert isinstance(new_codes, set)
                assert isinstance(retained_codes, set)
                assert isinstance(exit_codes, set)
                summary_change = {
                    "comparison_date": str(
                        context["comparison_date"]
                    ),
                    "new_count": int(change["new_count"]),
                    "retained_count": int(change["retained_count"]),
                    "exit_count": int(change["exit_count"]),
                    "net_change": int(change["new_count"])
                    - int(change["exit_count"]),
                }
                changes[str(comparison_days)] = summary_change
                detail_changes[str(comparison_days)] = {
                    **summary_change,
                    "new_stocks": sorted_stock_records(
                        current_stocks[
                            current_stocks["ts_code"].isin(new_codes)
                        ]
                    ),
                    "retained_stocks": sorted_stock_records(
                        current_stocks[
                            current_stocks["ts_code"].isin(retained_codes)
                        ]
                    ),
                    "exit_stocks": sorted_stock_records(
                        prior_stocks[
                            prior_stocks["ts_code"].isin(exit_codes)
                        ]
                    ),
                }

            summary_item = lightweight_industry(
                code=code,
                name=name,
                eligible_count=int(row.eligible_count),
                top100_count=int(row.top100_count),
                changes=changes,
            )
            series_rows = industry[
                (
                    industry["comparison_trading_days"]
                    == DEFAULT_CHANGE_WINDOW
                )
                & (industry["industry_code"].astype(str) == code)
                & (industry["trade_date"].astype(str).isin(display_dates))
            ].sort_values("trade_date")
            points_by_date = {
                str(item.trade_date): item
                for item in series_rows.itertuples(index=False)
            }
            series = []
            for current_date in display_dates:
                point = points_by_date.get(current_date)
                eligible_count = (
                    int(point.eligible_count) if point is not None else 0
                )
                top100_count = (
                    int(point.top100_count) if point is not None else 0
                )
                series.append(
                    {
                        "date": current_date,
                        "top100_count": top100_count,
                        "eligible_count": eligible_count,
                        "selection_rate": round(
                            top100_count / eligible_count
                            if eligible_count
                            else 0.0,
                            8,
                        ),
                    }
                )
            summary_items.append(summary_item)
            detail_items.append(
                {
                    **summary_item,
                    "current_stocks": sorted_stock_records(current_stocks),
                    "changes": detail_changes,
                    "series": series,
                }
            )

        low_summary = [
            item
            for item in summary_items
            if item["top100_count"] in (1, 2)
        ]
        low_codes = {
            str(item["industry_code"]) for item in low_summary
        }
        normal_treemap = [
            item
            for item in summary_items
            if int(item["top100_count"]) >= 3
        ]
        other_summary: dict | None = None
        other_detail: dict | None = None
        if low_summary:
            other_changes: dict[str, dict] = {}
            for comparison_days in CHANGE_WINDOWS:
                window = str(comparison_days)
                other_changes[window] = {
                    "comparison_date": low_summary[0]["changes"][window][
                        "comparison_date"
                    ],
                    "new_count": sum(
                        int(item["changes"][window]["new_count"])
                        for item in low_summary
                    ),
                    "retained_count": sum(
                        int(item["changes"][window]["retained_count"])
                        for item in low_summary
                    ),
                    "exit_count": sum(
                        int(item["changes"][window]["exit_count"])
                        for item in low_summary
                    ),
                }
                other_changes[window]["net_change"] = (
                    other_changes[window]["new_count"]
                    - other_changes[window]["exit_count"]
                )
            other_summary = lightweight_industry(
                code="other",
                name="其他行业",
                eligible_count=sum(
                    int(item["eligible_count"]) for item in low_summary
                ),
                top100_count=sum(
                    int(item["top100_count"]) for item in low_summary
                ),
                changes=other_changes,
            )
            other_summary.update(
                {
                    "neutral": True,
                    "component_industry_count": len(low_summary),
                    "component_industry_codes": sorted(low_codes),
                }
            )
            low_details = [
                item
                for item in detail_items
                if str(item["industry_code"]) in low_codes
            ]
            other_detail_changes: dict[str, dict] = {}
            for comparison_days in CHANGE_WINDOWS:
                window = str(comparison_days)
                other_detail_changes[window] = {
                    **other_changes[window],
                    "new_stocks": sorted(
                        [
                            stock
                            for item in low_details
                            for stock in item["changes"][window][
                                "new_stocks"
                            ]
                        ],
                        key=lambda stock: stock["rank"],
                    ),
                    "retained_stocks": sorted(
                        [
                            stock
                            for item in low_details
                            for stock in item["changes"][window][
                                "retained_stocks"
                            ]
                        ],
                        key=lambda stock: stock["rank"],
                    ),
                    "exit_stocks": sorted(
                        [
                            stock
                            for item in low_details
                            for stock in item["changes"][window][
                                "exit_stocks"
                            ]
                        ],
                        key=lambda stock: stock["rank"],
                    ),
                }
            other_series = []
            default_industry = industry[
                (
                    industry["comparison_trading_days"]
                    == DEFAULT_CHANGE_WINDOW
                )
                & (industry["industry_code"].astype(str).isin(low_codes))
            ]
            for current_date in display_dates:
                point_rows = default_industry[
                    default_industry["trade_date"].astype(str)
                    == current_date
                ]
                eligible_count = int(point_rows["eligible_count"].sum())
                top100_count = int(point_rows["top100_count"].sum())
                other_series.append(
                    {
                        "date": current_date,
                        "top100_count": top100_count,
                        "eligible_count": eligible_count,
                        "selection_rate": round(
                            top100_count / eligible_count
                            if eligible_count
                            else 0.0,
                            8,
                        ),
                    }
                )
            other_detail = {
                **other_summary,
                "current_stocks": sorted(
                    [
                        stock
                        for item in low_details
                        for stock in item["current_stocks"]
                    ],
                    key=lambda stock: stock["rank"],
                ),
                "changes": other_detail_changes,
                "series": other_series,
                "components": low_details,
            }
            normal_treemap.append(other_summary)

        summary_items.sort(
            key=lambda item: (
                -int(item["top100_count"]),
                str(item["industry"]),
            )
        )
        detail_items.sort(
            key=lambda item: (
                -int(item["top100_count"]),
                str(item["industry"]),
            )
        )
        normal_treemap.sort(
            key=lambda item: (
                -int(item["top100_count"]),
                str(item["industry"]),
            )
        )
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
                    "otherCount": (
                        int(other_summary["top100_count"])
                        if other_summary
                        else 0
                    ),
                    "otherIndustryCount": len(low_summary),
                },
                "detail_url": (
                    f"/template-breadth-v3-details/{template.key}.json"
                ),
                "industries": summary_items,
                "treemap_industries": normal_treemap,
            }
        )
        detail_payloads[template.key] = {
            "version": "template-top100-breadth-detail-v2",
            "as_of": as_of,
            "template_id": template.key,
            "default_change_window": DEFAULT_CHANGE_WINDOW,
            "change_windows": list(CHANGE_WINDOWS),
            "industries": detail_items,
            "other": other_detail,
        }
        ranking_payloads[template.key] = {
            "as_of": as_of,
            "template_id": template.key,
            "algorithm": SIMILARITY_ALGORITHM,
            "template": {
                "source_ts_code": template.code,
                "start_date": template.start,
                "end_date": template.end,
                "window_bars": template.bars,
            },
            "total_eligible": int(by_date.iloc[-1]["eligible_count"]),
            "items": [
                {
                    "rank": int(row.rank),
                    "ts_code": str(row.ts_code),
                    "code": str(row.ts_code).split(".")[0],
                    "name": str(row.name),
                    "industry": str(row.industry),
                    "score": round(float(row.score), 8),
                    "start_date": str(row.window_start),
                    "end_date": str(row.trade_date),
                    "window_bars": int(template.bars),
                }
                for row in current.itertuples(index=False)
            ],
        }

    payload = {
        "version": "template-top100-breadth-v2",
        "asOf": as_of,
        "historyStart": min(history_starts),
        "defaultChangeWindow": DEFAULT_CHANGE_WINDOW,
        "changeWindows": list(CHANGE_WINDOWS),
        "selection": {
            "method": "每个模板每日按单窗口 Pearson 降序固定取 Top100",
            "topK": TOP_K,
            "comparisonTradingDays": list(CHANGE_WINDOWS),
            "industryRateDenominator": "行业当日有完整候选窗口且处于上市期的股票数",
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
    return payload, detail_payloads, ranking_payloads


def validate(
    memberships: pd.DataFrame,
    industries: pd.DataFrame,
    payload: dict,
    detail_payloads: dict[str, dict],
    ranking_payloads: dict[str, dict],
) -> dict:
    def all_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                key
                for child in value.values()
                for key in all_keys(child)
            }
        if isinstance(value, list):
            return {
                key for child in value for key in all_keys(child)
            }
        return set()

    forbidden_initial_keys = {
        "current_stocks",
        "new_stocks",
        "retained_stocks",
        "exit_stocks",
        "series",
        "bars",
        "displayThreshold",
        "selectedThreshold",
    }
    assert not (all_keys(payload) & forbidden_initial_keys)
    assert payload["defaultChangeWindow"] == DEFAULT_CHANGE_WINDOW
    assert payload["changeWindows"] == list(CHANGE_WINDOWS)
    assert payload["selection"]["topK"] == TOP_K
    assert payload["selection"]["comparisonTradingDays"] == list(
        CHANGE_WINDOWS
    )

    checks = []
    for template in TEMPLATES:
        membership = memberships[memberships["template"] == template.key]
        industry = industries[industries["template"] == template.key]
        daily_members = membership.groupby("trade_date")["ts_code"].agg(
            ["count", "nunique"]
        )
        assert (daily_members["count"] == TOP_K).all()
        assert (daily_members["nunique"] == TOP_K).all()
        totals = industry.groupby(
            ["comparison_trading_days", "trade_date"]
        ).agg(
            top100_count=("top100_count", "sum"),
            new_count=("new_count", "sum"),
            retained_count=("retained_count", "sum"),
            exit_count=("exit_count", "sum"),
        )
        assert (totals["top100_count"] == TOP_K).all()
        comparable = (
            industry[industry["comparison_trade_date"].astype(str) != ""]
            .groupby(["comparison_trading_days", "trade_date"])
            .agg(
                top100_count=("top100_count", "sum"),
                new_count=("new_count", "sum"),
                retained_count=("retained_count", "sum"),
                exit_count=("exit_count", "sum"),
            )
        )
        assert (
            comparable["new_count"] + comparable["retained_count"] == TOP_K
        ).all()
        assert (
            comparable["exit_count"] + comparable["retained_count"] == TOP_K
        ).all()
        assert (
            industry["top100_count"] <= industry["eligible_count"]
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
        assert sum(
            item["top100_count"]
            for item in page_template["treemap_industries"]
        ) == TOP_K
        low_items = [
            item
            for item in page_template["industries"]
            if item["top100_count"] in (1, 2)
        ]
        other_items = [
            item
            for item in page_template["treemap_industries"]
            if item["industry_code"] == "other"
        ]
        assert len(other_items) == (1 if low_items else 0)
        if low_items:
            other = other_items[0]
            assert other["neutral"] is True
            assert other["top100_count"] == sum(
                item["top100_count"] for item in low_items
            )
            assert other["component_industry_count"] == len(low_items)
            assert set(other["component_industry_codes"]) == {
                item["industry_code"] for item in low_items
            }

        detail = detail_payloads[template.key]
        detail_by_code = {
            item["industry_code"]: item
            for item in detail["industries"]
        }
        latest_members = membership[
            membership["trade_date"] == payload["asOf"]
        ]
        assert len(latest_members) == TOP_K
        for item in page_template["industries"]:
            code = item["industry_code"]
            actual = detail_by_code[code]
            assert len(actual["current_stocks"]) == item["top100_count"]
            assert len(actual["series"]) == DISPLAY_DAYS
            for comparison_days in CHANGE_WINDOWS:
                window = str(comparison_days)
                summary_change = item["changes"][window]
                detail_change = actual["changes"][window]
                for field in (
                    "comparison_date",
                    "new_count",
                    "retained_count",
                    "exit_count",
                    "net_change",
                ):
                    assert detail_change[field] == summary_change[field]
                assert len(detail_change["new_stocks"]) == int(
                    summary_change["new_count"]
                )
                assert len(detail_change["retained_stocks"]) == int(
                    summary_change["retained_count"]
                )
                assert len(detail_change["exit_stocks"]) == int(
                    summary_change["exit_count"]
                )

        detail_other = detail["other"]
        assert (detail_other is not None) == bool(low_items)
        if detail_other is not None:
            assert len(detail_other["components"]) == len(low_items)
            assert len(detail_other["current_stocks"]) == int(
                detail_other["top100_count"]
            )
            assert len(detail_other["series"]) == DISPLAY_DAYS

        ranking = ranking_payloads[template.key]
        assert ranking["as_of"] == payload["asOf"]
        assert ranking["template_id"] == template.key
        assert ranking["algorithm"] == SIMILARITY_ALGORITHM
        assert ranking["template"] == {
            "source_ts_code": template.code,
            "start_date": template.start,
            "end_date": template.end,
            "window_bars": template.bars,
        }
        assert len(ranking["items"]) == TOP_K
        assert len(
            {item["ts_code"] for item in ranking["items"]}
        ) == TOP_K
        assert [item["rank"] for item in ranking["items"]] == list(
            range(1, TOP_K + 1)
        )
        assert {
            item["window_bars"] for item in ranking["items"]
        } == {template.bars}
        expected = latest_members.sort_values("rank")
        for actual, row in zip(
            ranking["items"],
            expected.itertuples(index=False),
            strict=True,
        ):
            assert actual["ts_code"] == str(row.ts_code)
            assert actual["start_date"] == str(row.window_start)
            assert actual["end_date"] == str(row.trade_date)
            assert np.isclose(actual["score"], float(row.score))

        checks.append(
            {
                "template": template.key,
                "dates": int(membership["trade_date"].nunique()),
                "latestEligible": page_template["summary"]["eligibleCount"],
                "latestTop100": len(ranking["items"]),
                "industryCount": len(page_template["industries"]),
                "otherTop100Count": (
                    other_items[0]["top100_count"]
                    if other_items
                    else 0
                ),
                "otherIndustryCount": len(low_items),
                "comparisonIdentities": {
                    str(window): True for window in CHANGE_WINDOWS
                },
                "detailBytes": len(
                    json.dumps(
                        detail,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ),
                "rankingBytes": len(
                    json.dumps(
                        ranking,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ),
            }
        )
    manifest_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert manifest_bytes < 200_000
    return {
        "pass": True,
        "asOf": payload["asOf"],
        "topK": TOP_K,
        "defaultChangeWindow": DEFAULT_CHANGE_WINDOW,
        "comparisonTradingDays": list(CHANGE_WINDOWS),
        "initialPayloadBytes": manifest_bytes,
        "initialPayloadHasStockLists": False,
        "initialPayloadHasKlineBars": False,
        "templates": checks,
        "leakageAudit": payload["boundaries"],
    }


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    public = args.public.resolve()
    public_details = args.public_details.resolve()
    public_rankings = args.public_rankings.resolve()
    workspace_targets = (
        output,
        public,
        public_details,
        public_rankings,
    )
    if any(PROJECT_ROOT not in path.parents for path in workspace_targets):
        raise RuntimeError("输出必须位于工作区")
    if not args.dry_run and output.exists():
        raise RuntimeError(f"拒绝覆盖现有原始输出：{output}")
    if not args.dry_run and public_details.exists():
        raise RuntimeError(
            f"拒绝覆盖现有行业明细目录：{public_details}"
        )
    if not args.dry_run and public_rankings.exists():
        raise RuntimeError(
            f"拒绝覆盖现有冻结排名目录：{public_rankings}"
        )

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
    payload, detail_payloads, ranking_payloads = build_page_data(
        memberships, industries, eligible, as_of
    )
    qa = validate(
        memberships,
        industries,
        payload,
        detail_payloads,
        ranking_payloads,
    )
    if args.dry_run:
        print(json.dumps(qa, ensure_ascii=False, indent=2))
        return

    output.mkdir(parents=True)
    output_details = output / "details"
    output_rankings = output / "rankings"
    output_details.mkdir()
    output_rankings.mkdir()
    public_details.mkdir(parents=True)
    public_rankings.mkdir(parents=True)
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
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    for template_key, detail in detail_payloads.items():
        pretty_detail = json.dumps(
            detail, ensure_ascii=False, indent=2
        )
        compact_detail = json.dumps(
            detail,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        (output_details / f"{template_key}.json").write_text(
            pretty_detail, encoding="utf-8"
        )
        (public_details / f"{template_key}.json").write_text(
            compact_detail, encoding="utf-8"
        )
    for template_key, ranking in ranking_payloads.items():
        pretty_ranking = json.dumps(
            ranking, ensure_ascii=False, indent=2
        )
        compact_ranking = json.dumps(
            ranking,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        (output_rankings / f"{template_key}.json").write_text(
            pretty_ranking, encoding="utf-8"
        )
        (public_rankings / f"{template_key}.json").write_text(
            compact_ranking, encoding="utf-8"
        )
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
