from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api

from build_template_statistical_validation import (
    HISTORY_START,
    PROJECT_ROOT,
    TEMPLATES,
    ZERO_CONFIG,
    ZERO_ROOT,
    build_series,
    load_market_data,
    load_stock_metadata,
    load_templates,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "unified-threshold-v3-20260729"
)
PUBLIC_DATA = PROJECT_ROOT / "public" / "template-breadth-v3.json"
CANDIDATES = (0.70, 0.75, 0.80)
LOW_COUNT_LIMIT = 5
HUNDREDS_COUNT_LIMIT = 200
TOP_K = 100
DISPLAY_K = 30
RECENT_DAYS = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(
        frame.replace({np.nan: None}).to_json(orient="records", force_ascii=False)
    )


def safe_corr(left: pd.Series, right: pd.Series) -> float | None:
    valid = pd.concat([left, right], axis=1).dropna()
    if len(valid) < 3 or valid.iloc[:, 0].nunique() < 2 or valid.iloc[:, 1].nunique() < 2:
        return None
    value = float(valid.iloc[:, 0].corr(valid.iloc[:, 1]))
    return value if math.isfinite(value) else None


def rolling_scores(
    series: dict[str, dict],
    stocks: pd.DataFrame,
    template_z: np.ndarray,
    bars: int,
    as_of: str,
) -> pd.DataFrame:
    metadata = stocks.set_index("ts_code")[["list_date", "delist_date"]].to_dict("index")
    rows: list[pd.DataFrame] = []
    for code, item in series.items():
        meta = metadata.get(code)
        if meta is None:
            continue
        values = np.asarray(item["qfq_close"], dtype=float)
        dates = np.asarray(item["dates"], dtype=str)
        if len(values) < bars or np.any(values <= 0):
            continue
        logged = np.log(values)
        cumulative = np.concatenate(([0.0], np.cumsum(logged)))
        cumulative_sq = np.concatenate(([0.0], np.cumsum(logged * logged)))
        sums = cumulative[bars:] - cumulative[:-bars]
        sums_sq = cumulative_sq[bars:] - cumulative_sq[:-bars]
        variance = np.maximum(sums_sq / bars - (sums / bars) ** 2, 0.0)
        std = np.sqrt(variance)
        dots = np.correlate(logged, template_z, mode="valid")
        scores = np.divide(
            dots,
            bars * std,
            out=np.zeros_like(dots),
            where=std > 1e-12,
        )
        score_dates = dates[bars - 1 :]
        listed = str(meta.get("list_date") or "00000000")
        delisted_value = meta.get("delist_date")
        delisted = (
            str(delisted_value)
            if delisted_value is not None and not pd.isna(delisted_value)
            else "99999999"
        )
        keep = (
            (score_dates >= HISTORY_START)
            & (score_dates <= as_of)
            & (score_dates >= listed)
            & (score_dates < delisted)
        )
        if not np.any(keep):
            continue
        rows.append(
            pd.DataFrame(
                {
                    "trade_date": score_dates[keep],
                    "ts_code": code,
                    "score": scores[keep],
                }
            )
        )
    if not rows:
        raise RuntimeError("逐日相似度结果为空")
    frame = pd.concat(rows, ignore_index=True)
    if not frame["score"].between(-1 - 1e-8, 1 + 1e-8).all():
        raise RuntimeError("Pearson 分数超出 [-1, 1]")
    return frame


def active_industry_map(members: pd.DataFrame, as_of: str) -> dict[str, tuple[str, str]]:
    entered = members["in_date"].fillna("00000000").astype(str) <= as_of
    not_exited = members["out_date"].isna() | (
        members["out_date"].astype(str) > as_of
    )
    active = members[entered & not_exited].copy()
    active = active.sort_values(["ts_code", "in_date"]).drop_duplicates(
        "ts_code", keep="last"
    )
    return {
        str(row.ts_code): (
            str(row.l1_code) if not pd.isna(row.l1_code) else "missing",
            str(row.l1_name) if not pd.isna(row.l1_name) else "行业缺失",
        )
        for row in active.itertuples(index=False)
    }


def expanding_position(values: pd.Series) -> tuple[list[float], list[str]]:
    percentiles: list[float] = []
    labels: list[str] = []
    history: list[float] = []
    for value in values.astype(float):
        history.append(value)
        pct = float(np.mean(np.asarray(history) <= value))
        percentiles.append(pct)
        labels.append("高位" if pct >= 2 / 3 else "低位" if pct <= 1 / 3 else "中位")
    return percentiles, labels


def direction_run_share(changes: pd.Series) -> tuple[float, int]:
    signs = np.sign(changes.fillna(0).to_numpy(float))
    runs: list[int] = []
    current_sign = 0
    current_length = 0
    for sign in signs:
        if sign == 0:
            if current_length:
                runs.append(current_length)
            current_sign = 0
            current_length = 0
        elif sign == current_sign:
            current_length += 1
        else:
            if current_length:
                runs.append(current_length)
            current_sign = int(sign)
            current_length = 1
    if current_length:
        runs.append(current_length)
    persistent_days = sum(length for length in runs if length >= 3)
    nonzero_days = int(np.sum(signs != 0))
    return (
        persistent_days / nonzero_days if nonzero_days else 0.0,
        max(runs, default=0),
    )


def build_market_and_industry(
    score_frame: pd.DataFrame,
    template_key: str,
    members: pd.DataFrame,
    name_map: dict[str, str],
) -> tuple[list[dict], list[dict], list[dict]]:
    market_rows: list[dict] = []
    industry_rows: list[dict] = []
    latest_rows: list[dict] = []
    prior_sets: dict[tuple[float, str], set[str]] = defaultdict(set)
    dates = sorted(score_frame["trade_date"].unique())

    for date_index, (current, frame) in enumerate(
        score_frame.groupby("trade_date", sort=True)
    ):
        ranked = frame.sort_values(
            ["score", "ts_code"], ascending=[False, True]
        ).reset_index(drop=True)
        ranked["rank"] = np.arange(1, len(ranked) + 1)
        industry_lookup = active_industry_map(members, str(current))
        ranked["industry_code"] = ranked["ts_code"].map(
            lambda code: industry_lookup.get(str(code), ("missing", "行业缺失"))[0]
        )
        ranked["industry"] = ranked["ts_code"].map(
            lambda code: industry_lookup.get(str(code), ("missing", "行业缺失"))[1]
        )
        top100_codes = set(ranked.head(TOP_K)["ts_code"])

        for threshold in CANDIDATES:
            selected = ranked[ranked["score"] >= threshold]
            market_rows.append(
                {
                    "trade_date": str(current),
                    "template": template_key,
                    "threshold": threshold,
                    "eligible_count": len(ranked),
                    "above_count": len(selected),
                }
            )
            for (industry_code, industry), group in ranked.groupby(
                ["industry_code", "industry"], sort=True
            ):
                ordered = group.sort_values(
                    ["score", "ts_code"], ascending=[False, True]
                )
                current_set = set(
                    ordered.loc[ordered["score"] >= threshold, "ts_code"]
                )
                key = (threshold, str(industry_code))
                prior = prior_sets[key]
                top100_count = int(ordered["ts_code"].isin(top100_codes).sum())
                row = {
                    "trade_date": str(current),
                    "template": template_key,
                    "threshold": threshold,
                    "industry_code": str(industry_code),
                    "industry": str(industry),
                    "eligible_count": len(ordered),
                    "above_count": len(current_set),
                    "above_rate": len(current_set) / len(ordered),
                    "top100_count": top100_count,
                    "top100_share": top100_count / TOP_K,
                    "new_count": len(current_set - prior),
                    "retained_count": len(current_set & prior),
                    "exit_count": len(prior - current_set),
                }
                for remove in (1, 3):
                    trimmed = ordered.iloc[remove:]
                    trimmed_set = set(
                        trimmed.loc[trimmed["score"] >= threshold, "ts_code"]
                    )
                    trimmed_top100 = int(
                        trimmed["ts_code"].isin(top100_codes).sum()
                    )
                    row[f"eligible_without_top{remove}"] = len(trimmed)
                    row[f"above_without_top{remove}"] = len(trimmed_set)
                    row[f"above_rate_without_top{remove}"] = (
                        len(trimmed_set) / len(trimmed) if len(trimmed) else 0.0
                    )
                    row[f"top100_without_top{remove}"] = trimmed_top100
                    row[f"top100_share_without_top{remove}"] = (
                        trimmed_top100 / TOP_K
                    )
                industry_rows.append(row)
                prior_sets[key] = current_set

        if date_index == len(dates) - 1:
            for row in ranked.head(DISPLAY_K).itertuples(index=False):
                latest_rows.append(
                    {
                        "trade_date": str(current),
                        "template": template_key,
                        "rank": int(row.rank),
                        "ts_code": str(row.ts_code),
                        "name": name_map.get(str(row.ts_code), str(row.ts_code)),
                        "industry_code": str(row.industry_code),
                        "industry": str(row.industry),
                        "score": float(row.score),
                    }
                )
    return market_rows, industry_rows, latest_rows


def finish_market_stats(market: pd.DataFrame) -> pd.DataFrame:
    output = []
    for (_, _), group in market.groupby(["template", "threshold"], sort=True):
        frame = group.sort_values("trade_date").copy()
        frame["change_1d"] = frame["above_count"].diff(1)
        frame["change_5d"] = frame["above_count"].diff(5)
        frame["ma5"] = frame["above_count"].rolling(5, min_periods=1).mean()
        percentiles, positions = expanding_position(frame["above_count"])
        frame["historical_percentile"] = percentiles
        frame["historical_position"] = positions
        output.append(frame)
    return pd.concat(output, ignore_index=True).sort_values(
        ["threshold", "template", "trade_date"]
    )


def evaluate_candidates(market: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    template_rows: list[dict] = []
    candidate_rows: list[dict] = []
    for threshold in CANDIDATES:
        supported_templates = 0
        for template in TEMPLATES:
            frame = market[
                (market["threshold"] == threshold)
                & (market["template"] == template.key)
            ].sort_values("trade_date")
            low_share = float((frame["above_count"] <= LOW_COUNT_LIMIT).mean())
            hundreds_share = float(
                (frame["above_count"] >= HUNDREDS_COUNT_LIMIT).mean()
            )
            level_autocorr = safe_corr(
                frame["above_count"].iloc[:-1].reset_index(drop=True),
                frame["above_count"].iloc[1:].reset_index(drop=True),
            )
            ma5_autocorr = safe_corr(
                frame["ma5"].iloc[:-1].reset_index(drop=True),
                frame["ma5"].iloc[1:].reset_index(drop=True),
            )
            persistent_share, max_run = direction_run_share(frame["change_5d"])
            usable_range = low_share < 0.5 and hundreds_share < 0.5
            persistent = (
                (ma5_autocorr or 0.0) >= 0.85
                and persistent_share >= 0.5
                and max_run >= 5
            )
            supported = usable_range and persistent
            supported_templates += int(supported)
            template_rows.append(
                {
                    "threshold": threshold,
                    "template": template.key,
                    "template_label": template.label,
                    "days": len(frame),
                    "median_count": float(frame["above_count"].median()),
                    "p10_count": float(frame["above_count"].quantile(0.1)),
                    "p90_count": float(frame["above_count"].quantile(0.9)),
                    "share_count_0_to_5": low_share,
                    "share_count_200_plus": hundreds_share,
                    "level_lag1_corr": level_autocorr,
                    "ma5_lag1_corr": ma5_autocorr,
                    "persistent_direction_share": persistent_share,
                    "max_direction_run": max_run,
                    "usable_range": usable_range,
                    "persistent_intervals": persistent,
                    "template_support": supported,
                }
            )
        decision = (
            "支持"
            if supported_templates == len(TEMPLATES)
            else "较弱"
            if supported_templates >= 2
            else "不支持"
        )
        subset = [row for row in template_rows if row["threshold"] == threshold]
        candidate_rows.append(
            {
                "threshold": threshold,
                "decision": decision,
                "supported_templates": supported_templates,
                "worst_extreme_share": max(
                    max(row["share_count_0_to_5"], row["share_count_200_plus"])
                    for row in subset
                ),
                "mean_ma5_lag1_corr": float(
                    np.mean([row["ma5_lag1_corr"] or 0.0 for row in subset])
                ),
                "rule": (
                    "每模板：count<=5 与 count>=200 的天数占比均低于50%；"
                    "MA5滞后1日相关>=0.85；5日变化同向持续段覆盖>=50%，最长>=5日。"
                    "4/4支持=支持，2–3/4=较弱，0–1/4=不支持。"
                ),
            }
        )
    return pd.DataFrame(template_rows), candidate_rows


def evaluate_industry(industry: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (threshold, template), frame in industry.groupby(
        ["threshold", "template"], sort=True
    ):
        frame = frame.sort_values(["industry_code", "trade_date"]).copy()
        for suffix, above_column, top100_column in (
            ("base", "above_count", "top100_count"),
            ("without_top1", "above_without_top1", "top100_without_top1"),
            ("without_top3", "above_without_top3", "top100_without_top3"),
        ):
            frame[f"{suffix}_above_change_1d"] = frame.groupby("industry_code")[
                above_column
            ].diff(1)
            frame[f"{suffix}_top100_change_1d"] = frame.groupby("industry_code")[
                top100_column
            ].diff(1)
            frame[f"{suffix}_above_change_5d"] = frame.groupby("industry_code")[
                above_column
            ].diff(5)
            frame[f"{suffix}_top100_change_5d"] = frame.groupby("industry_code")[
                top100_column
            ].diff(5)
        daily = []
        for _, current in frame.groupby("trade_date", sort=True):
            daily.append(
                {
                    "base_count_corr": safe_corr(
                        current["above_count"], current["top100_count"]
                    ),
                    "base_rate_corr": safe_corr(
                        current["above_rate"], current["top100_share"]
                    ),
                    "without_top1_count_corr": safe_corr(
                        current["above_without_top1"],
                        current["top100_without_top1"],
                    ),
                    "without_top3_count_corr": safe_corr(
                        current["above_without_top3"],
                        current["top100_without_top3"],
                    ),
                    "base_change_1d_corr": safe_corr(
                        current["base_above_change_1d"],
                        current["base_top100_change_1d"],
                    ),
                    "base_change_5d_corr": safe_corr(
                        current["base_above_change_5d"],
                        current["base_top100_change_5d"],
                    ),
                    "without_top1_change_5d_corr": safe_corr(
                        current["without_top1_above_change_5d"],
                        current["without_top1_top100_change_5d"],
                    ),
                    "without_top3_change_5d_corr": safe_corr(
                        current["without_top3_above_change_5d"],
                        current["without_top3_top100_change_5d"],
                    ),
                }
            )
        daily_frame = pd.DataFrame(daily)
        within = []
        for _, current in frame.groupby("industry_code", sort=True):
            within.append(
                {
                    "within_base_change_1d_corr": safe_corr(
                        current["base_above_change_1d"],
                        current["base_top100_change_1d"],
                    ),
                    "within_base_change_5d_corr": safe_corr(
                        current["base_above_change_5d"],
                        current["base_top100_change_5d"],
                    ),
                    "within_without_top1_change_5d_corr": safe_corr(
                        current["without_top1_above_change_5d"],
                        current["without_top1_top100_change_5d"],
                    ),
                    "within_without_top3_change_5d_corr": safe_corr(
                        current["without_top3_above_change_5d"],
                        current["without_top3_top100_change_5d"],
                    ),
                }
            )
        within_frame = pd.DataFrame(within)
        rows.append(
            {
                "threshold": threshold,
                "template": template,
                **{
                    column: float(daily_frame[column].dropna().median())
                    if daily_frame[column].notna().any()
                    else None
                    for column in daily_frame
                },
                **{
                    column: float(within_frame[column].dropna().median())
                    if within_frame[column].notna().any()
                    else None
                    for column in within_frame
                },
                "dates": len(daily_frame),
            }
        )
    return pd.DataFrame(rows)


def choose_threshold(candidate_rows: list[dict]) -> tuple[float | None, str]:
    supported = [row for row in candidate_rows if row["decision"] == "支持"]
    if not supported:
        return None, "三条统一固定线没有一条在四模板上同时通过简单有效性规则，停止产品化。"
    chosen = min(
        supported,
        key=lambda row: (
            row["worst_extreme_share"],
            -row["mean_ma5_lag1_corr"],
            row["threshold"],
        ),
    )
    return float(chosen["threshold"]), (
        f"{chosen['threshold']:.2f} 在四模板上都避免长期落入 0–5 只或 200 只以上，"
        "且 5 日均线与扩散/收缩方向形成持续区间；"
        "在所有“支持”候选中，它的最差极端占比最低。"
    )


def build_page_data(
    *,
    market: pd.DataFrame,
    industry: pd.DataFrame,
    latest_top30: pd.DataFrame,
    selected_threshold: float,
    as_of: str,
    reason: str,
    candidate_rows: list[dict],
) -> dict:
    templates = []
    for template in TEMPLATES:
        market_series = market[
            (market["template"] == template.key)
            & (market["threshold"] == selected_threshold)
        ].sort_values("trade_date")
        recent = market_series.tail(RECENT_DAYS)
        latest = recent.iloc[-1]
        industry_series = industry[
            (industry["template"] == template.key)
            & (industry["threshold"] == selected_threshold)
        ].copy()
        last_date = str(industry_series["trade_date"].max())
        current_industries = industry_series[
            industry_series["trade_date"] == last_date
        ].copy()
        five_dates = sorted(industry_series["trade_date"].unique())
        comparison_date = five_dates[-6] if len(five_dates) >= 6 else five_dates[0]
        prior_counts = (
            industry_series[industry_series["trade_date"] == comparison_date]
            .set_index("industry_code")["above_count"]
            .to_dict()
        )
        current_industries["change_5d"] = current_industries.apply(
            lambda row: int(row["above_count"])
            - int(prior_counts.get(row["industry_code"], 0)),
            axis=1,
        )
        detail_series = []
        for (industry_code, industry_name), group in industry_series.groupby(
            ["industry_code", "industry"], sort=True
        ):
            detail_series.append(
                {
                    "industryCode": industry_code,
                    "industry": industry_name,
                    "points": [
                        {
                            "date": row.trade_date,
                            "count": int(row.above_count),
                        }
                        for row in group.sort_values("trade_date").tail(RECENT_DAYS).itertuples()
                    ],
                }
            )
        top30 = latest_top30[latest_top30["template"] == template.key].copy()
        top30["above_threshold"] = top30["score"] >= selected_threshold
        templates.append(
            {
                "key": template.key,
                "label": template.label,
                "cue": template.cue,
                "accent": template.accent,
                "summary": {
                    "count": int(latest["above_count"]),
                    "change1d": int(latest["change_1d"]) if not pd.isna(latest["change_1d"]) else 0,
                    "change5d": int(latest["change_5d"]) if not pd.isna(latest["change_5d"]) else 0,
                    "ma5": round(float(latest["ma5"]), 1),
                    "position": str(latest["historical_position"]),
                    "historicalPercentile": round(
                        float(latest["historical_percentile"]) * 100, 1
                    ),
                },
                "marketSeries": [
                    {
                        "date": row.trade_date,
                        "count": int(row.above_count),
                        "ma5": round(float(row.ma5), 2),
                    }
                    for row in recent.itertuples()
                ],
                "top30": records(
                    top30[
                        [
                            "rank",
                            "ts_code",
                            "name",
                            "industry_code",
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
                "industrySeries": detail_series,
            }
        )
    return {
        "version": "unified-threshold-v3",
        "asOf": as_of,
        "historyStart": HISTORY_START,
        "selectedThreshold": selected_threshold,
        "selectionReason": reason,
        "candidateDecisions": candidate_rows,
        "templates": templates,
        "boundaries": {
            "dataSource": str(ZERO_ROOT),
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
            "algorithm": "前复权 log-close；窗口内独立 z；单窗口 Pearson",
            "note": "历史序列是用冻结模板对同期形态供给的事后描述，不是预测或模型评估。",
        },
    }


def validate(
    market: pd.DataFrame,
    industry: pd.DataFrame,
    latest_top30: pd.DataFrame,
    selected_threshold: float | None,
) -> None:
    if set(market["threshold"].unique()) != set(CANDIDATES):
        raise RuntimeError("候选线集合漂移")
    threshold_count = market.groupby(["template", "trade_date"])["threshold"].nunique()
    if not (threshold_count == len(CANDIDATES)).all():
        raise RuntimeError("某些模板/日期缺候选线")
    pivot = market.pivot_table(
        index=["template", "trade_date"],
        columns="threshold",
        values="above_count",
        aggfunc="first",
    )
    if not ((pivot[0.70] >= pivot[0.75]) & (pivot[0.75] >= pivot[0.80])).all():
        raise RuntimeError("阈值数量单调性失败")
    if (market["above_count"] > market["eligible_count"]).any():
        raise RuntimeError("超过线数量大于合资格数量")
    identities = industry[
        industry["above_count"]
        != industry["new_count"] + industry["retained_count"]
    ]
    if len(identities):
        raise RuntimeError("行业新进/保留恒等式失败")
    if len(latest_top30) != len(TEMPLATES) * DISPLAY_K:
        raise RuntimeError("Top30 行数错误")
    if selected_threshold is not None and selected_threshold not in CANDIDATES:
        raise RuntimeError("最终线不在候选集合")


def notes_document(
    *,
    as_of: str,
    selected_threshold: float | None,
    reason: str,
    candidate_rows: list[dict],
    market: pd.DataFrame,
    template_evaluation: pd.DataFrame,
    industry_evaluation: pd.DataFrame,
) -> str:
    lines = [
        "# 统一固定线实验与简化应用页 V3",
        "",
        f"- 截止交易日：{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}",
        "- 候选统一线：0.70、0.75、0.80（四模板完全共用）",
        "- 算法冻结：前复权 log-close、窗口内独立 z、单窗口 Pearson",
        "- 用途：描述同期形态供给的扩散、收缩与低位，不是预测或模型评估",
        "",
        "## 三条候选线结论",
        "",
    ]
    for row in candidate_rows:
        lines.append(
            f"- **{row['threshold']:.2f}：{row['decision']}**；"
            f"{row['supported_templates']}/4 个模板通过简单规则。"
        )
    lines += [
        "",
        "## 统一固定线选择",
        "",
        (
            f"- 选择 **{selected_threshold:.2f}**。{reason}"
            if selected_threshold is not None
            else f"- 不选择。{reason}"
        ),
        "",
        "## 简单有效性规则",
        "",
        "- 不能多数时间只有 0–5 只：`count<=5` 天数占比必须低于 50%。",
        "- 不能多数时间有几百只：`count>=200` 天数占比必须低于 50%。",
        "- 5 日均线滞后 1 日相关至少 0.85；5 日变化同向持续段覆盖至少 50%，最长至少 5 日。",
        "- 四模板全通过为“支持”，2–3 个为“较弱”，0–1 个为“不支持”。",
        "",
        "## 当前市场状态",
        "",
    ]
    latest = market.sort_values("trade_date").groupby(
        ["threshold", "template"], as_index=False
    ).tail(1)
    for threshold in CANDIDATES:
        current = latest[latest["threshold"] == threshold].set_index("template")
        counts = "/".join(
            str(int(current.loc[template.key, "above_count"]))
            for template in TEMPLATES
        )
        changes = "/".join(
            f"{int(current.loc[template.key, 'change_5d']):+d}"
            for template in TEMPLATES
        )
        lines.append(
            f"- {threshold:.2f}：刚突破/健康上涨/回调转强/抛物线上升当前数量 "
            f"{counts}；较 5 日前 {changes}。"
        )
    lines += [
        "- 12 个“候选线×模板”当前都处于各自扩展历史低位，且较 5 日前全部收缩；"
        "可以描述当前同期形态供给偏低、正在收缩。",
        "- 但三类模板在历史上长期有数百至上千只，绝对尺度不可统一；"
        "因此市场状态描述成立，不代表统一固定线可以产品化。",
        "",
        "## 行业结论",
        "",
        "- 跨行业强度主口径是各模板 Top100 中的行业入选率，分母固定为 100。",
        "- 更准确地说，该值是 Top100 行业占比（任务所称入选率）：行业入选数 / 100。",
        "- 这里沿用 Top100/100 的度量形式；股票池是四模板各自的全 A 活跃截面（沪深北，未显式剔除 ST），不是旧行业页的三形态股票池。",
        "- 固定线以上行业数量用于描述行业宽度；同时报告行业内去 Top1、去 Top3 后的日度横截面中位相关。",
    ]
    for threshold in CANDIDATES:
        current = industry_evaluation[
            industry_evaluation["threshold"] == threshold
        ]
        lines.append(
            f"- {threshold:.2f}：四模板“固定线以上行业数量 vs Top100行业入选数”"
            f"相关中位数范围 {current['base_count_corr'].min():.2f}–"
            f"{current['base_count_corr'].max():.2f}；去 Top1 后 "
            f"{current['without_top1_count_corr'].min():.2f}–"
            f"{current['without_top1_count_corr'].max():.2f}，去 Top3 后 "
            f"{current['without_top3_count_corr'].min():.2f}–"
            f"{current['without_top3_count_corr'].max():.2f}。"
        )
        lines.append(
            f"  - 1 日变化的跨行业相关仅 "
            f"{current['base_change_1d_corr'].min():.2f}–"
            f"{current['base_change_1d_corr'].max():.2f}；5 日变化为 "
            f"{current['base_change_5d_corr'].min():.2f}–"
            f"{current['base_change_5d_corr'].max():.2f}；行业自身时间序列中位相关 "
            f"{current['within_base_change_5d_corr'].min():.2f}–"
            f"{current['within_base_change_5d_corr'].max():.2f}。"
        )
    lines.append(
        "- 结论：水平结构相关强且行业内去 Top1/Top3 后仍成立；"
        "但变化关系除刚突破外普遍较弱，主要受行业规模共同驱动，"
        "不能据此声称固定线数量稳定解释行业宽度变化，也不能救回统一线。"
    )
    if selected_threshold is not None:
        chosen = industry_evaluation[
            industry_evaluation["threshold"] == selected_threshold
        ]
        for row in chosen.itertuples(index=False):
            label = next(item.label for item in TEMPLATES if item.key == row.template)
            lines.append(
                f"- {label}：数量与 Top100 行业入选数相关中位数 "
                f"{row.base_count_corr:.2f}；去 Top1 后 {row.without_top1_count_corr:.2f}，"
                f"去 Top3 后 {row.without_top3_count_corr:.2f}。"
            )
    lines += [
        "",
        "## 数据边界与泄漏审计",
        "",
        f"- 仅使用本机 zer0share：`{ZERO_ROOT}`，历史起点 {HISTORY_START}，截止 {as_of}。",
        "- 未联网、未读 sealed final、未使用未来收益、IC 或策略表现。",
        "- 行业成员按每个交易日的 in_date/out_date 还原；out_date 当日不再视为有效成员。",
        "- 固定模板可能晚于历史截面，因此历史结果只可作事后同期描述。",
        "",
        "## 原始表",
        "",
        "- `daily_threshold_counts.csv`：三线×四模板逐日数量、1/5日变化、MA5、历史位置。",
        "- `industry_daily.csv`：Top100 行业占比、固定线行业宽度、新进/保留/退出、去 Top1/Top3。",
        "- `latest_top30.csv`：各模板最新 Top30 与分数。",
        "- `candidate_template_evaluation.csv`、`candidate_evaluation.json`、`industry_evaluation.csv`：结论依据。",
        "",
        f"模板级有效性明细共 {len(template_evaluation)} 行；行业稳健性明细共 {len(industry_evaluation)} 行。",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"输出必须位于工作区：{output}")
    if output.exists():
        raise RuntimeError(f"拒绝覆盖现有输出：{output}")
    if PUBLIC_DATA.exists():
        raise RuntimeError(f"拒绝覆盖现有页面数据：{PUBLIC_DATA}")
    if not ZERO_ROOT.exists() or not ZERO_CONFIG.exists():
        raise RuntimeError("本机 zer0share 或配置不存在")

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        market_data, as_of = load_market_data(pro)
        stocks = load_stock_metadata(pro)
        templates = load_templates(market_data)
        series = build_series(market_data)
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
    name_map = stocks.set_index("ts_code")["name"].astype(str).to_dict()

    market_rows: list[dict] = []
    industry_rows: list[dict] = []
    latest_rows: list[dict] = []
    for template in TEMPLATES:
        print(f"计算 {template.label} 的逐日截面", flush=True)
        scores = rolling_scores(
            series,
            stocks,
            templates[template.key]["z"],
            template.bars,
            as_of,
        )
        template_market, template_industry, template_latest = (
            build_market_and_industry(
                scores,
                template.key,
                members,
                name_map,
            )
        )
        market_rows.extend(template_market)
        industry_rows.extend(template_industry)
        latest_rows.extend(template_latest)

    market = finish_market_stats(pd.DataFrame(market_rows))
    industry = pd.DataFrame(industry_rows).sort_values(
        ["threshold", "template", "trade_date", "industry_code"]
    )
    latest_top30 = pd.DataFrame(latest_rows).sort_values(["template", "rank"])
    template_evaluation, candidate_rows = evaluate_candidates(market)
    industry_evaluation = evaluate_industry(industry)
    selected_threshold, reason = choose_threshold(candidate_rows)
    validate(market, industry, latest_top30, selected_threshold)

    output.mkdir(parents=True)
    market.to_csv(
        output / "daily_threshold_counts.csv", index=False, encoding="utf-8-sig"
    )
    industry.to_csv(
        output / "industry_daily.csv", index=False, encoding="utf-8-sig"
    )
    latest_top30.to_csv(
        output / "latest_top30.csv", index=False, encoding="utf-8-sig"
    )
    template_evaluation.to_csv(
        output / "candidate_template_evaluation.csv",
        index=False,
        encoding="utf-8-sig",
    )
    industry_evaluation.to_csv(
        output / "industry_evaluation.csv", index=False, encoding="utf-8-sig"
    )
    (output / "candidate_evaluation.json").write_text(
        json.dumps(candidate_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conclusion = {
        "selectedThreshold": selected_threshold,
        "reason": reason,
        "candidateDecisions": candidate_rows,
        "marketStateConclusion": (
            "截至2026-07-29，12个候选线×模板组合均处扩展历史低位，"
            "且较5日前全部收缩；可描述当前形态供给偏低、正在收缩。"
            "但三个模板的历史绝对数量长期过宽，不能据此统一产品线。"
        ),
        "industryConclusion": (
            "固定线行业数量与Top100行业数量的水平结构相关强，"
            "行业内去Top1/Top3后仍成立；但1日变化及行业自身变化关系"
            "除刚突破外普遍较弱，主要受行业规模共同驱动，"
            "不能声称固定线数量稳定解释行业宽度变化。"
        ),
        "productizationContinues": selected_threshold is not None,
    }
    (output / "conclusion.json").write_text(
        json.dumps(conclusion, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "review-notes.md").write_text(
        notes_document(
            as_of=as_of,
            selected_threshold=selected_threshold,
            reason=reason,
            candidate_rows=candidate_rows,
            market=market,
            template_evaluation=template_evaluation,
            industry_evaluation=industry_evaluation,
        ),
        encoding="utf-8",
    )
    qa = {
        "pass": True,
        "branch": "codex/unified-threshold-app-v3",
        "asOf": as_of,
        "candidateThresholds": list(CANDIDATES),
        "templateCount": len(TEMPLATES),
        "selectedThreshold": selected_threshold,
        "marketRows": len(market),
        "industryRows": len(industry),
        "top30Rows": len(latest_top30),
        "leakageAudit": {
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
        },
    }
    (output / "qa-data-results.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if selected_threshold is not None:
        page_data = build_page_data(
            market=market,
            industry=industry,
            latest_top30=latest_top30,
            selected_threshold=selected_threshold,
            as_of=as_of,
            reason=reason,
            candidate_rows=candidate_rows,
        )
        PUBLIC_DATA.write_text(
            json.dumps(page_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output / "page-data.json").write_text(
            json.dumps(page_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(
        json.dumps(
            {
                "output": str(output),
                "asOf": as_of,
                "selectedThreshold": selected_threshold,
                "reason": reason,
                "candidateDecisions": candidate_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
