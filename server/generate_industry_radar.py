"""Generate the auditable A-share industry large active fund-flow radar.

The command accepts only an explicit existing panel.  It never downloads,
extends, fills, or fabricates source data, and the historical path pages are
descriptive report-date checks rather than a backtest or forecast.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .industry_radar import (
    MIN_L2_VALID_STOCKS,
    RadarResult,
    analyze_industries,
    effective_stock_mask,
)


PAGE_WIDTH, PAGE_HEIGHT = 841.89, 595.28
MARGIN = 34
PAGE_COUNT = 11
RED = (0.78, 0.12, 0.14)
GREEN = (0.08, 0.43, 0.20)
NAVY = (0.07, 0.15, 0.27)
BLUE = (0.20, 0.37, 0.62)
ROSE = (0.66, 0.34, 0.42)
ORANGE = (0.90, 0.50, 0.10)
PURPLE = (0.38, 0.35, 0.65)
MUTED = (0.35, 0.39, 0.45)
PALE = (0.94, 0.96, 0.98)
REPORT_FONT = "RadarChinese"
REPORT_FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
HORIZON_SLUGS = {5: "5d_short_term", 20: "20d_trend"}
HORIZON_TITLES = {5: "5日短线雷达", 20: "20日趋势雷达"}
STATE_ORDER = ("双窗净流入", "短线转入", "趋势仍流入", "双窗净流出")
STATE_CRITERIA = {
    "双窗净流入": "5日正 / 20日正",
    "短线转入": "5日正 / 20日负或零",
    "趋势仍流入": "5日负或零 / 20日正",
    "双窗净流出": "5日负或零 / 20日负或零",
}
LINE_COLORS = (RED, BLUE, ORANGE, PURPLE, GREEN)
MARKET_FLOW_DISPLAY_DAYS = 60
MARKET_FLOW_MINIMUM_DAYS = MARKET_FLOW_DISPLAY_DAYS
ROTATION_STRENGTH_5D_WEIGHT = 0.60
ROTATION_STRENGTH_20D_WEIGHT = 0.40


def load_panel(path: Path) -> pd.DataFrame:
    """Read a real upstream extract without changing values or dates."""
    if not path.is_file():
        raise FileNotFoundError(f"input extract not found: {path}")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path, dtype={"trade_date": str, "ts_code": str})
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    raise ValueError("input must be Parquet, CSV, JSON, or JSONL")


def _ranked(rankings: pd.DataFrame) -> pd.DataFrame:
    """Return the published deterministic final-score order."""
    code = "l2_code" if "l2_code" in rankings else "l1_code"
    if "rank" in rankings:
        return rankings.sort_values(["rank", code], kind="stable")
    return rankings.sort_values(
        ["score", f"flow_{int(rankings['horizon'].iloc[0])}d", code],
        ascending=[False, False, True],
        kind="stable",
    )


def _comparison_frame(report: dict[str, Any], level: str = "l2") -> pd.DataFrame:
    """Join the two independent rankings without changing either order."""
    code, name = f"{level}_code", f"{level}_name"
    five = report["horizons"][5][level].rankings
    twenty = report["horizons"][20][level].rankings
    five_columns = [
        code,
        name,
        "rank",
        "score",
        "comprehensive_score",
        "flow_5d",
    ]
    twenty_columns = [
        code,
        "rank",
        "score",
        "comprehensive_score",
        "flow_20d",
    ]
    return five[five_columns].merge(
        twenty[twenty_columns],
        on=code,
        how="inner",
        suffixes=("_5d", "_20d"),
        validate="one_to_one",
    )


def _state_name(flow_5d: float, flow_20d: float) -> str:
    """Classify an industry from actual signed window flows."""
    five_positive = float(pd.to_numeric(flow_5d, errors="coerce")) > 0
    twenty_positive = float(pd.to_numeric(flow_20d, errors="coerce")) > 0
    if five_positive and twenty_positive:
        return "双窗净流入"
    if five_positive:
        return "短线转入"
    if twenty_positive:
        return "趋势仍流入"
    return "双窗净流出"


def _rotation_history(frame: pd.DataFrame) -> dict[str, Any]:
    """Build comparable daily L2 strength, rank, migration, and streak data."""
    required = {
        "trade_date",
        "ts_code",
        "l2_code",
        "l2_name",
        "inst_net_flow",
        "amount",
        "circ_mv",
        "close",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            "rotation history is missing columns: " + ", ".join(sorted(missing))
        )
    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    for column in ("inst_net_flow", "amount", "circ_mv", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work[
        work["l2_code"].notna()
        & work["l2_name"].notna()
        & effective_stock_mask(work)
    ].copy()
    daily = (
        work.groupby(["trade_date", "l2_code", "l2_name"], as_index=False)
        .agg(
            flow_1d=("inst_net_flow", lambda values: values.sum(min_count=1)),
            amount_1d=("amount", lambda values: values.sum(min_count=1)),
            valid_stock_count=("ts_code", "nunique"),
        )
        .sort_values(["l2_code", "trade_date"], kind="stable")
    )
    dates = sorted(daily["trade_date"].unique())
    if len(dates) < 20:
        raise ValueError(
            f"rotation history requires at least 20 trading days, found {len(dates)}"
        )
    records: list[pd.DataFrame] = []
    for (industry_code, industry_name), group in daily.groupby(
        ["l2_code", "l2_name"], sort=False
    ):
        indexed = group.set_index("trade_date").reindex(dates)
        flow = pd.to_numeric(indexed["flow_1d"], errors="coerce")
        amount = pd.to_numeric(indexed["amount_1d"], errors="coerce")
        count = pd.to_numeric(indexed["valid_stock_count"], errors="coerce").fillna(0)
        flow_5d = flow.rolling(5, min_periods=5).sum()
        flow_20d = flow.rolling(20, min_periods=20).sum()
        amount_5d = amount.rolling(5, min_periods=5).sum()
        amount_20d = amount.rolling(20, min_periods=20).sum()
        intensity_5d = 10_000 * flow_5d / amount_5d.replace(0, np.nan)
        intensity_20d = 10_000 * flow_20d / amount_20d.replace(0, np.nan)
        strength = (
            ROTATION_STRENGTH_5D_WEIGHT * intensity_5d
            + ROTATION_STRENGTH_20D_WEIGHT * intensity_20d
        )
        eligible = count.ge(MIN_L2_VALID_STOCKS)
        state = pd.Series(index=dates, dtype="object")
        complete = eligible & flow_5d.notna() & flow_20d.notna()
        state.loc[complete] = [
            _state_name(five, twenty)
            for five, twenty in zip(flow_5d.loc[complete], flow_20d.loc[complete])
        ]
        records.append(
            pd.DataFrame(
                {
                    "trade_date": dates,
                    "l2_code": str(industry_code),
                    "l2_name": str(industry_name),
                    "valid_stock_count": count.to_numpy(dtype=int),
                    "eligible": eligible.to_numpy(dtype=bool),
                    "flow_1d": flow.to_numpy(dtype=float),
                    "flow_5d": flow_5d.to_numpy(dtype=float),
                    "flow_20d": flow_20d.to_numpy(dtype=float),
                    "amount_5d": amount_5d.to_numpy(dtype=float),
                    "amount_20d": amount_20d.to_numpy(dtype=float),
                    "intensity_5d_bps": intensity_5d.to_numpy(dtype=float),
                    "intensity_20d_bps": intensity_20d.to_numpy(dtype=float),
                    "rotation_strength_bps": strength.to_numpy(dtype=float),
                    "state": state.to_numpy(),
                }
            )
        )
    history = pd.concat(records, ignore_index=True)
    history["rotation_rank"] = np.nan
    for date, indexes in history.groupby("trade_date").groups.items():
        day = history.loc[indexes]
        publishable = day[
            day["eligible"] & day["rotation_strength_bps"].notna()
        ].sort_values(
            ["rotation_strength_bps", "flow_5d", "l2_code"],
            ascending=[False, False, True],
            kind="stable",
        )
        history.loc[publishable.index, "rotation_rank"] = np.arange(
            1, len(publishable) + 1
        )

    as_of = dates[-1]
    prior_date = dates[-2]
    five_days_ago = dates[-6] if len(dates) >= 6 else None
    current = history[
        history["trade_date"].eq(as_of) & history["eligible"]
    ].copy()
    previous = history[history["trade_date"].eq(prior_date)].set_index("l2_code")
    previous_five = (
        history[history["trade_date"].eq(five_days_ago)].set_index("l2_code")
        if five_days_ago
        else pd.DataFrame()
    )

    def historical_value(
        code: str, source: pd.DataFrame, column: str
    ) -> Any:
        if source.empty or code not in source.index:
            return np.nan
        value = source.loc[code, column]
        return value.iloc[0] if isinstance(value, pd.Series) else value

    for index, row in current.iterrows():
        code = str(row["l2_code"])
        rank_now = float(row["rotation_rank"])
        rank_prev = historical_value(code, previous, "rotation_rank")
        rank_5d = historical_value(code, previous_five, "rotation_rank")
        strength_now = float(row["rotation_strength_bps"])
        strength_prev = historical_value(code, previous, "rotation_strength_bps")
        strength_5d = historical_value(
            code, previous_five, "rotation_strength_bps"
        )
        state_prev = historical_value(code, previous, "state")
        state_5d = historical_value(code, previous_five, "state")
        flow_5d_prev = historical_value(code, previous, "flow_5d")
        current.loc[index, "rank_previous"] = rank_prev
        current.loc[index, "rank_5d_ago"] = rank_5d
        current.loc[index, "rank_change_1d"] = (
            rank_prev - rank_now
            if np.isfinite(rank_now) and np.isfinite(rank_prev)
            else np.nan
        )
        current.loc[index, "rank_change_5d"] = (
            rank_5d - rank_now
            if np.isfinite(rank_now) and np.isfinite(rank_5d)
            else np.nan
        )
        current.loc[index, "strength_previous_bps"] = strength_prev
        current.loc[index, "strength_5d_ago_bps"] = strength_5d
        current.loc[index, "strength_change_1d_bps"] = (
            strength_now - strength_prev
            if np.isfinite(strength_now) and np.isfinite(strength_prev)
            else np.nan
        )
        current.loc[index, "strength_change_5d_per_day_bps"] = (
            (strength_now - strength_5d) / 5
            if np.isfinite(strength_now) and np.isfinite(strength_5d)
            else np.nan
        )
        current.loc[index, "improvement_speed_bps"] = (
            0.40 * current.loc[index, "strength_change_1d_bps"]
            + 0.60 * current.loc[index, "strength_change_5d_per_day_bps"]
        )
        current.loc[index, "state_previous"] = state_prev
        current.loc[index, "state_5d_ago"] = state_5d
        current.loc[index, "flow_5d_previous"] = flow_5d_prev
        current.loc[index, "transition_previous"] = (
            f"{state_prev}→{row['state']}"
            if isinstance(state_prev, str)
            else "数据不足"
        )
        current.loc[index, "transition_5d"] = (
            f"{state_5d}→{row['state']}"
            if isinstance(state_5d, str)
            else "数据不足"
        )
        streak = 0
        industry_history = history[
            history["l2_code"].astype(str).eq(code)
        ].sort_values("trade_date", ascending=False)
        for historical_state in industry_history["state"]:
            if not isinstance(historical_state, str) or historical_state != row["state"]:
                break
            streak += 1
        current.loc[index, "state_streak_days"] = streak

    return {
        "as_of": as_of,
        "previous_date": prior_date,
        "five_days_ago": five_days_ago,
        "strength_formula": (
            "rotation_strength_bps=0.60*(10000*flow_5d/amount_5d)"
            "+0.40*(10000*flow_20d/amount_20d)"
        ),
        "improvement_formula": (
            "0.40*1d_strength_change+0.60*(5d_strength_change/5)"
        ),
        "current": current.to_dict("records"),
        "series": history.to_dict("records"),
    }


def _market_concentration(rankings: pd.DataFrame) -> dict[str, Any]:
    """Measure current positive industry-flow concentration without netting."""
    positive = rankings[pd.to_numeric(rankings["flow_1d"], errors="coerce") > 0].copy()
    positive = positive.sort_values(
        ["flow_1d", "l2_code"], ascending=[False, True], kind="stable"
    )
    total_positive = float(positive["flow_1d"].sum())
    if total_positive <= 0:
        return {
            "positive_industry_count": 0,
            "eligible_industry_count": int(len(rankings)),
            "top3_share": np.nan,
            "top5_share": np.nan,
            "hhi": np.nan,
            "normalized_hhi": np.nan,
            "effective_industry_count": np.nan,
            "label": "当日无净流入行业",
        }
    shares = positive["flow_1d"].astype(float) / total_positive
    hhi = float((shares**2).sum())
    count = len(positive)
    normalized_hhi = (
        1.0 if count == 1 else float((hhi - 1 / count) / (1 - 1 / count))
    )
    top3 = float(shares.head(3).sum())
    top5 = float(shares.head(5).sum())
    if count <= 3 or top3 >= 0.60 or normalized_hhi >= 0.25:
        label = "集中于少数行业"
    elif top3 < 0.45 and normalized_hhi < 0.15:
        label = "较为分散"
    else:
        label = "中等集中"
    return {
        "positive_industry_count": int(count),
        "eligible_industry_count": int(len(rankings)),
        "positive_flow_pool": total_positive,
        "top3_share": top3,
        "top5_share": top5,
        "hhi": hhi,
        "normalized_hhi": normalized_hhi,
        "effective_industry_count": float(1 / hhi),
        "label": label,
        "top_industries": positive[
            ["l2_code", "l2_name", "flow_1d"]
        ].head(5).to_dict("records"),
        "denominator": "sum(max(industry_flow_1d,0)) over eligible L2 industries",
    }


def _state_frame(report: dict[str, Any]) -> pd.DataFrame:
    frame = _comparison_frame(report, "l2")
    frame["state"] = [
        _state_name(five, twenty)
        for five, twenty in zip(frame["flow_5d"], frame["flow_20d"])
    ]
    frame["score_change"] = (
        frame["comprehensive_score_5d"] - frame["comprehensive_score_20d"]
    )
    frame["joint_strength"] = frame[
        ["comprehensive_score_5d", "comprehensive_score_20d"]
    ].min(axis=1)
    frame["deepest_score"] = frame[
        ["comprehensive_score_5d", "comprehensive_score_20d"]
    ].min(axis=1)
    rotation = pd.DataFrame(report.get("rotation_history", {}).get("current", []))
    if not rotation.empty:
        dynamic_columns = [
            "l2_code",
            "rotation_rank",
            "rank_previous",
            "rank_5d_ago",
            "rank_change_1d",
            "rank_change_5d",
            "rotation_strength_bps",
            "strength_change_1d_bps",
            "strength_change_5d_per_day_bps",
            "improvement_speed_bps",
            "state_previous",
            "state_5d_ago",
            "transition_previous",
            "transition_5d",
            "state_streak_days",
            "flow_5d_previous",
        ]
        available = [column for column in dynamic_columns if column in rotation]
        frame = frame.merge(
            rotation[available],
            on="l2_code",
            how="left",
            validate="one_to_one",
        )
    return frame


def _state_groups(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Return deterministic complete memberships and representatives."""
    groups: dict[str, dict[str, Any]] = {}
    total = len(frame)
    for state in STATE_ORDER:
        group = frame[frame["state"].eq(state)].copy()
        if state == "双窗净流入":
            ordered = group.sort_values(
                ["joint_strength", "rank_20d", "l2_code"],
                ascending=[False, True, True],
                kind="stable",
            )
            representatives = {"代表": ordered.head(4)}
            metric = "两窗综合分较弱者优先，识别共同强势"
        elif state == "短线转入":
            ordered = group.sort_values(
                ["score_change", "comprehensive_score_5d", "l2_code"],
                ascending=[False, False, True],
                kind="stable",
            )
            representatives = {"代表": ordered.head(4)}
            metric = "5日相对20日综合分改善最大"
        elif state == "趋势仍流入":
            ordered = group.sort_values(
                ["score_change", "comprehensive_score_20d", "l2_code"],
                ascending=[True, False, True],
                kind="stable",
            )
            representatives = {"代表": ordered.head(4)}
            metric = "20日综合分相对5日领先最大"
        else:
            ordered = group.sort_values(
                ["rank_20d", "rank_5d", "l2_code"], kind="stable"
            )
            near = group.sort_values(
                ["score_change", "comprehensive_score_5d", "l2_code"],
                ascending=[False, False, True],
                kind="stable",
            ).head(4)
            deep = group.sort_values(
                ["deepest_score", "comprehensive_score_20d", "l2_code"],
                ascending=[True, True, True],
                kind="stable",
            ).head(4)
            representatives = {"接近改善": near, "流出最深": deep}
            metric = "分别列5日改善最大与两窗流出最深"
        groups[state] = {
            "count": int(len(group)),
            "share": float(len(group) / total) if total else 0.0,
            "criterion": STATE_CRITERIA[state],
            "selection_metric": metric,
            "industries": ordered,
            "representatives": representatives,
        }
    return groups


def _state_payload(report: dict[str, Any]) -> dict[str, Any]:
    groups = _state_groups(_state_frame(report))
    payload: dict[str, Any] = {}
    columns = [
        "l2_code",
        "l2_name",
        "rank_5d",
        "rank_20d",
        "flow_5d",
        "flow_20d",
        "score_5d",
        "score_20d",
        "comprehensive_score_5d",
        "comprehensive_score_20d",
        "rotation_rank",
        "rank_previous",
        "rank_5d_ago",
        "rank_change_1d",
        "rank_change_5d",
        "rotation_strength_bps",
        "strength_change_1d_bps",
        "strength_change_5d_per_day_bps",
        "improvement_speed_bps",
        "state_previous",
        "state_5d_ago",
        "transition_previous",
        "transition_5d",
        "state_streak_days",
    ]
    state_frame = _state_frame(report)
    columns = [column for column in columns if column in state_frame.columns]
    for state, details in groups.items():
        representatives = {
            label: rows[columns].to_dict("records")
            for label, rows in details["representatives"].items()
        }
        payload[state] = {
            "count": details["count"],
            "share": details["share"],
            "criterion": details["criterion"],
            "selection_metric": details["selection_metric"],
            "industries": details["industries"][columns].to_dict("records"),
            "representatives": representatives,
        }
    return payload


def _daily_answers(report: dict[str, Any]) -> dict[str, Any]:
    """Answer the nine required daily rotation questions with auditable rows."""
    states = _state_frame(report)
    rotation = pd.DataFrame(report["rotation_history"]["series"])
    current_date = str(report["rotation_history"]["as_of"])
    previous_date = str(report["rotation_history"]["previous_date"])
    current_daily = rotation[
        rotation["trade_date"].astype(str).eq(current_date) & rotation["eligible"]
    ]
    previous_daily = rotation[
        rotation["trade_date"].astype(str).eq(previous_date) & rotation["eligible"]
    ]

    def inflow_share(rows: pd.DataFrame) -> float:
        if rows.empty:
            return float("nan")
        return float((pd.to_numeric(rows["flow_1d"], errors="coerce") > 0).mean())

    current_share = inflow_share(current_daily)
    previous_share = inflow_share(previous_daily)
    share_change = (
        current_share - previous_share
        if np.isfinite(current_share) and np.isfinite(previous_share)
        else np.nan
    )
    if not np.isfinite(share_change) or abs(share_change) < 0.01:
        share_direction = "基本持平"
    elif share_change > 0:
        share_direction = "扩大"
    else:
        share_direction = "收缩"

    def industry_names(rows: pd.DataFrame, maximum: int = 4) -> list[str]:
        if rows.empty:
            return []
        return rows["l2_name"].astype(str).head(maximum).tolist()

    def names_text(names: list[str]) -> str:
        return "、".join(names) if names else "无符合条件行业"

    persistent_inflow = states[
        states["state"].eq("双窗净流入")
        & pd.to_numeric(states.get("state_streak_days"), errors="coerce").ge(3)
    ].sort_values(
        ["rotation_strength_bps", "l2_code"],
        ascending=[False, True],
        kind="stable",
    )
    recently_turned = states[
        pd.to_numeric(states["flow_5d"], errors="coerce").gt(0)
        & pd.to_numeric(states.get("flow_5d_previous"), errors="coerce").le(0)
    ].sort_values(
        ["improvement_speed_bps", "l2_code"],
        ascending=[False, True],
        kind="stable",
    )
    cooling = states[states["state"].eq("趋势仍流入")].sort_values(
        ["comprehensive_score_20d", "l2_code"],
        ascending=[False, True],
        kind="stable",
    )
    persistent_outflow = states[
        states["state"].eq("双窗净流出")
        & pd.to_numeric(states.get("state_streak_days"), errors="coerce").ge(3)
    ].sort_values(
        ["rotation_strength_bps", "l2_code"],
        ascending=[True, True],
        kind="stable",
    )
    improved = states.dropna(subset=["improvement_speed_bps"]).sort_values(
        ["improvement_speed_bps", "rank_change_1d", "l2_code"],
        ascending=[False, False, True],
        kind="stable",
    ).head(5)
    worsened = states.dropna(subset=["improvement_speed_bps"]).sort_values(
        ["improvement_speed_bps", "rank_change_1d", "l2_code"],
        ascending=[True, True, True],
        kind="stable",
    ).head(5)
    latest_rankings = report["horizons"][5]["l2"].rankings
    inflow_quality = latest_rankings[
        pd.to_numeric(latest_rankings["flow_1d"], errors="coerce") > 0
    ]
    broad = inflow_quality[
        inflow_quality["diffusion_label_1d"].eq("普遍扩散")
    ].sort_values(["flow_1d", "l2_code"], ascending=[False, True])
    narrow = inflow_quality[
        inflow_quality["diffusion_label_1d"].eq("少数个股驱动")
    ].sort_values(["flow_1d", "l2_code"], ascending=[False, True])
    concentration = report["market_concentration"]

    persistent_inflow_names = industry_names(persistent_inflow)
    recently_turned_names = industry_names(recently_turned)
    cooling_names = industry_names(cooling)
    persistent_outflow_names = industry_names(persistent_outflow)
    improved_names = industry_names(improved)
    worsened_names = industry_names(worsened)
    broad_names = industry_names(broad)
    narrow_names = industry_names(narrow)
    return {
        "inflow_industry_share": {
            "current": current_share,
            "previous": previous_share,
            "change_percentage_points": (
                share_change * 100 if np.isfinite(share_change) else np.nan
            ),
            "direction": share_direction,
            "text": (
                f"净流入行业占比{share_direction}：{current_share:.1%}，"
                f"较前一日{share_change:+.1%}。"
            ),
        },
        "market_concentration": {
            **concentration,
            "text": (
                f"流入{concentration['label']}：Top3 "
                f"{concentration['top3_share']:.0%} · Top5 "
                f"{concentration['top5_share']:.0%} · HHI "
                f"{concentration['normalized_hhi']:.2f}。"
                if np.isfinite(concentration["top3_share"])
                else "当日无净流入行业，集中度不适用。"
            ),
        },
        "persistent_inflow": {
            "industries": persistent_inflow_names,
            "text": f"持续流入：{names_text(persistent_inflow_names)}。",
        },
        "recently_turned_in": {
            "industries": recently_turned_names,
            "text": f"最近刚转入：{names_text(recently_turned_names)}。",
        },
        "medium_strong_short_cooling": {
            "industries": cooling_names,
            "text": f"中期强势但短期降温：{names_text(cooling_names)}。",
        },
        "persistent_outflow": {
            "industries": persistent_outflow_names,
            "text": f"持续流出：{names_text(persistent_outflow_names)}。",
        },
        "inflow_diffusion": {
            "broad_diffusion": broad_names,
            "few_stocks_driven": narrow_names,
            "text": (
                f"普遍扩散：{names_text(broad_names)}；"
                f"少数个股驱动：{names_text(narrow_names)}。"
            ),
        },
        "fastest_improving": {
            "industries": improved_names,
            "rows": improved[
                [
                    "l2_code",
                    "l2_name",
                    "improvement_speed_bps",
                    "rank_change_1d",
                    "rank_change_5d",
                    "transition_previous",
                    "state_streak_days",
                ]
            ].to_dict("records"),
            "text": f"改善最快：{names_text(improved_names)}。",
        },
        "fastest_worsening": {
            "industries": worsened_names,
            "rows": worsened[
                [
                    "l2_code",
                    "l2_name",
                    "improvement_speed_bps",
                    "rank_change_1d",
                    "rank_change_5d",
                    "transition_previous",
                    "state_streak_days",
                ]
            ].to_dict("records"),
            "text": f"恶化最快：{names_text(worsened_names)}。",
        },
    }


def _history_payload(report: dict[str, Any], level: str) -> dict[str, Any]:
    """Build report-date Top/Bottom 5 cumulative paths from the final 40 dates."""
    code, name = f"{level}_code", f"{level}_name"
    result: RadarResult = report["horizons"][20][level]
    ranked = _ranked(result.rankings)
    selections = {"top": ranked.head(5), "bottom": ranked.tail(5)}
    daily = result.daily_flows.copy()
    dates = sorted(daily["trade_date"].astype(str).unique())[-40:]
    if len(dates) != 40:
        raise ValueError(
            f"{level} history requires 40 existing trading days, found {len(dates)}"
        )
    payload: dict[str, Any] = {
        "selection_basis": "report-date 20-day final rank",
        "window_dates": dates,
        "highlight_dates": dates[-20:],
    }
    for side, rows in selections.items():
        paths: list[dict[str, Any]] = []
        for row in rows.itertuples(index=False):
            industry_code = str(getattr(row, code))
            industry_name = str(getattr(row, name))
            industry_daily = (
                daily[daily[code].astype(str).eq(industry_code)]
                .set_index("trade_date")["inst_net_flow"]
                .reindex(dates)
            )
            if industry_daily.isna().any():
                missing = industry_daily[industry_daily.isna()].index.tolist()
                raise ValueError(
                    f"{level} {industry_code} is missing history dates: {missing}"
                )
            cumulative = industry_daily.astype(float).cumsum()
            cumulative = cumulative - float(cumulative.iloc[0])
            paths.append(
                {
                    "industry_code": industry_code,
                    "industry_name": industry_name,
                    "rank_20d": int(getattr(row, "rank")),
                    "score_20d": float(getattr(row, "score")),
                    "comprehensive_score_20d": float(
                        getattr(row, "comprehensive_score")
                    ),
                    "dates": dates,
                    "daily_flow": industry_daily.astype(float).tolist(),
                    "cumulative_flow": cumulative.astype(float).tolist(),
                }
            )
        payload[side] = paths
    return payload


def _market_flow_history(
    daily_flows: pd.DataFrame,
    market_flow_5d: float,
    market_flow_20d: float,
) -> dict[str, Any]:
    """Return a 60-date first-day-zero cumulative market flow series."""
    required = {
        "trade_date",
        "l2_code",
        "l2_name",
        "inst_net_flow",
    }
    missing = required.difference(daily_flows.columns)
    if missing:
        raise ValueError(
            "market flow history is missing columns: "
            + ", ".join(sorted(missing))
        )
    work = daily_flows.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    work["inst_net_flow"] = pd.to_numeric(
        work["inst_net_flow"], errors="coerce"
    )
    work = work[
        work["l2_code"].notna() & work["l2_name"].notna()
    ].copy()
    dates = sorted(work["trade_date"].unique())
    if len(dates) < MARKET_FLOW_MINIMUM_DAYS:
        raise ValueError(
            "market flow history requires at least "
            f"{MARKET_FLOW_MINIMUM_DAYS} existing trading days, found "
            f"{len(dates)}"
        )
    market_daily = (
        work.groupby("trade_date")["inst_net_flow"]
        .sum(min_count=1)
        .reindex(dates)
        .astype(float)
    )
    history = pd.DataFrame(
        {
            "trade_date": dates,
            "market_large_active_flow_daily": market_daily.to_numpy(),
        }
    ).tail(MARKET_FLOW_DISPLAY_DAYS).reset_index(drop=True)
    if len(history) != MARKET_FLOW_DISPLAY_DAYS or history[
        "market_large_active_flow_daily"
    ].isna().any():
        raise ValueError("market flow history could not produce 60 full points")
    cumulative = history["market_large_active_flow_daily"].cumsum()
    history["market_large_active_flow_cumulative"] = (
        cumulative - float(cumulative.iloc[0])
    )
    raw_last_5d = float(
        history.iloc[-1]["market_large_active_flow_cumulative"]
        - history.iloc[-6]["market_large_active_flow_cumulative"]
    )
    raw_last_20d = float(
        history.iloc[-1]["market_large_active_flow_cumulative"]
        - history.iloc[-21]["market_large_active_flow_cumulative"]
    )
    matches = bool(
        np.isclose(raw_last_5d, market_flow_5d, rtol=0, atol=1e-6)
        and np.isclose(raw_last_20d, market_flow_20d, rtol=0, atol=1e-6)
    )
    if not matches:
        raise ValueError("market cumulative recent changes do not match cards")
    return {
        "unit": "source_thousand_yuan",
        "display_unit": "亿元",
        "window_definition": "last 60 existing trading days; first point reset to zero",
        "frozen_universe": (
            "same report-date eligible L2 industry universe as 5d/20d cards"
        ),
        "flow_semantics": (
            "large+extra-large active buy amount minus active sell amount"
        ),
        "display_points": MARKET_FLOW_DISPLAY_DAYS,
        "minimum_input_trading_days": MARKET_FLOW_MINIMUM_DAYS,
        "available_input_trading_days": len(dates),
        "endpoint_matches_cards": matches,
        "recent_5d_change": market_flow_5d,
        "recent_20d_change": market_flow_20d,
        "endpoint_raw_delta_5d": raw_last_5d - market_flow_5d,
        "endpoint_raw_delta_20d": raw_last_20d - market_flow_20d,
        "series": history.to_dict("records"),
    }


def build_report_data(
    frame: pd.DataFrame, source_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build symmetric rankings plus deterministic report-only views."""
    horizons: dict[int, dict[str, RadarResult]] = {}
    report_dates: set[str] = set()
    for horizon in (5, 20):
        l1 = analyze_industries(frame, "l1", horizon=horizon)
        l2 = analyze_industries(frame, "l2", horizon=horizon)
        report_dates.update((str(l1.quality["as_of"]), str(l2.quality["as_of"])))
        if source_metadata:
            for result in (l1, l2):
                for key in (
                    "source_window_start",
                    "source_window_end",
                    "source_request_count",
                    "source_coverage_rate",
                ):
                    if key in source_metadata:
                        result.quality[key] = source_metadata[key]
        horizons[horizon] = {"l1": l1, "l2": l2}
    if len(report_dates) != 1:
        raise ValueError("industry levels and horizons do not share a report date")
    report: dict[str, Any] = {
        "as_of": report_dates.pop(),
        "horizons": horizons,
        "l1": horizons[5]["l1"],
        "l2": horizons[5]["l2"],
    }
    report["market_flow_history"] = _market_flow_history(
        horizons[20]["l2"].daily_flows,
        float(horizons[5]["l2"].quality["market_flow_5d"]),
        float(horizons[20]["l2"].quality["market_flow_20d"]),
    )
    report["rotation_history"] = _rotation_history(frame)
    report["market_concentration"] = _market_concentration(
        horizons[5]["l2"].rankings
    )
    report["fund_states"] = _state_payload(report)
    report["daily_answers"] = _daily_answers(report)
    report["history"] = {
        "l1": _history_payload(report, "l1"),
        "l2": _history_payload(report, "l2"),
    }
    return report


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _result_payload(result: RadarResult) -> dict[str, Any]:
    return {
        "quality": result.quality,
        "rankings": result.rankings.to_dict("records"),
        "contributors": result.contributors.to_dict("records"),
        "daily_flows": result.daily_flows.to_dict("records"),
    }


def _state_csv(report: dict[str, Any]) -> pd.DataFrame:
    frame = _state_frame(report)
    frame["state_criterion"] = frame["state"].map(STATE_CRITERIA)
    return frame.sort_values(
        ["state", "rank_20d", "rank_5d", "l2_code"], kind="stable"
    )


def _history_csv(report: dict[str, Any], level: str) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for side in ("top", "bottom"):
        for path in report["history"][level][side]:
            for date, daily, cumulative in zip(
                path["dates"], path["daily_flow"], path["cumulative_flow"]
            ):
                records.append(
                    {
                        "level": level,
                        "selection": side,
                        "selection_basis": "report-date 20-day final rank",
                        "industry_code": path["industry_code"],
                        "industry_name": path["industry_name"],
                        "rank_20d": path["rank_20d"],
                        "score_20d": path["score_20d"],
                        "comprehensive_score_20d": path[
                            "comprehensive_score_20d"
                        ],
                        "trade_date": date,
                        "daily_flow": daily,
                        "cumulative_flow_first_day_zero": cumulative,
                    }
                )
    return pd.DataFrame(records)


def write_datasets(
    report: dict[str, Any], output_dir: Path
) -> tuple[list[Path], Path]:
    """Write score, state, path, and manifest audit artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = str(report["as_of"])
    paths: list[Path] = []
    combined: dict[str, Any] = {
        "as_of": as_of,
        "comprehensive_score_formula": "comprehensive_score=10000*S_H",
        "fund_label": "大额主动资金",
        "fund_definition": (
            "大单+特大单主动买入额−主动卖出额；反映大额主动成交方向，"
            "不代表真实机构账户身份、实际持仓或持仓变化"
        ),
        "fund_states": report["fund_states"],
        "daily_answers": report["daily_answers"],
        "market_concentration": report["market_concentration"],
        "rotation_history": report["rotation_history"],
        "history": report["history"],
        "market_flow_history": report["market_flow_history"],
        "horizons": {},
    }
    for horizon, slug in HORIZON_SLUGS.items():
        bundle = report["horizons"][horizon]
        l1, l2 = bundle["l1"], bundle["l2"]
        l1_path = output_dir / f"industry_radar_l1_{slug}_{as_of}.csv"
        l2_path = output_dir / f"industry_radar_l2_{slug}_{as_of}.csv"
        horizon_manifest = output_dir / f"industry_radar_{slug}_{as_of}.json"
        l1.rankings.to_csv(l1_path, index=False, encoding="utf-8-sig")
        l2.rankings.to_csv(l2_path, index=False, encoding="utf-8-sig")
        horizon_payload = {
            "as_of": as_of,
            "horizon": horizon,
            "horizon_title": HORIZON_TITLES[horizon],
            "l1": _result_payload(l1),
            "l2": _result_payload(l2),
        }
        horizon_manifest.write_text(
            json.dumps(
                horizon_payload,
                ensure_ascii=False,
                indent=2,
                default=_jsonable,
            ),
            encoding="utf-8",
        )
        paths.extend((l1_path, l2_path, horizon_manifest))
        combined["horizons"][str(horizon)] = horizon_payload

    state_path = output_dir / f"industry_radar_l2_fund_states_{as_of}.csv"
    _state_csv(report).to_csv(state_path, index=False, encoding="utf-8-sig")
    paths.append(state_path)
    for level in ("l1", "l2"):
        history_path = (
            output_dir / f"industry_radar_{level}_40d_cumulative_paths_{as_of}.csv"
        )
        _history_csv(report, level).to_csv(
            history_path, index=False, encoding="utf-8-sig"
        )
        paths.append(history_path)

    rotation_path = (
        output_dir / f"industry_radar_l2_rotation_changes_{as_of}.csv"
    )
    pd.DataFrame(report["rotation_history"]["current"]).to_csv(
        rotation_path, index=False, encoding="utf-8-sig"
    )
    paths.append(rotation_path)

    market_history_path = (
        output_dir / f"industry_radar_market_large_active_flow_60d_{as_of}.csv"
    )
    pd.DataFrame(report["market_flow_history"]["series"]).to_csv(
        market_history_path, index=False, encoding="utf-8-sig"
    )
    paths.append(market_history_path)

    manifest_path = output_dir / f"industry_radar_{as_of}.json"
    manifest_path.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2, default=_jsonable),
        encoding="utf-8",
    )
    return paths, manifest_path


def _pdf_canvas(path: Path):
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab_unavailable") from exc
    if REPORT_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(REPORT_FONT, REPORT_FONT_PATH))
    return canvas.Canvas(str(path), pagesize=landscape(A4))


def _draw_text(
    c,
    x: float,
    y: float,
    value: str,
    size: float = 9,
    color: tuple[float, float, float] = NAVY,
) -> None:
    c.setFillColorRGB(*color)
    c.setFont(REPORT_FONT, size)
    c.drawString(x, y, str(value))


def _right_text(
    c,
    x: float,
    y: float,
    value: str,
    size: float = 8,
    color: tuple[float, float, float] = NAVY,
) -> None:
    c.setFillColorRGB(*color)
    c.setFont(REPORT_FONT, size)
    c.drawRightString(x, y, str(value))


def _center_text(
    c,
    x: float,
    y: float,
    value: str,
    size: float = 8,
    color: tuple[float, float, float] = NAVY,
) -> None:
    c.setFillColorRGB(*color)
    c.setFont(REPORT_FONT, size)
    c.drawCentredString(x, y, str(value))


def _box(
    c,
    x: float,
    y: float,
    width: float,
    height: float,
    fill: tuple[float, float, float] = (0.98, 0.99, 1.0),
    stroke: tuple[float, float, float] = (0.82, 0.86, 0.91),
    radius: float = 7,
) -> None:
    c.setFillColorRGB(*fill)
    c.setStrokeColorRGB(*stroke)
    c.roundRect(x, y, width, height, radius, fill=1, stroke=1)


def _flow_color(value: float) -> tuple[float, float, float]:
    numeric = pd.to_numeric(value, errors="coerce")
    return RED if numeric > 0 else GREEN if numeric < 0 else MUTED


def _money(value: float, digits: int = 1) -> str:
    """Format source thousand-yuan values as familiar Chinese money units."""
    numeric = float(pd.to_numeric(value, errors="coerce"))
    if not np.isfinite(numeric):
        return "--"
    if abs(numeric) >= 100_000:
        return f"{numeric / 100_000:+,.{digits}f}亿"
    if abs(numeric) >= 10:
        return f"{numeric / 10:+,.0f}万"
    return f"{numeric * 1_000:+,.0f}元"


def _comprehensive(value: float, digits: int = 2) -> str:
    numeric = float(pd.to_numeric(value, errors="coerce"))
    return "--" if not np.isfinite(numeric) else f"{numeric:+.{digits}f}"


def _percent(value: float) -> str:
    numeric = float(pd.to_numeric(value, errors="coerce"))
    return "--" if not np.isfinite(numeric) else f"{numeric:+.2%}"


def _short_date(value: str) -> str:
    raw = str(value).replace("-", "")
    return f"{raw[4:6]}/{raw[6:8]}" if len(raw) == 8 else raw


def _header(c, as_of: str, page: int, title: str) -> None:
    c.setFillColorRGB(*NAVY)
    c.rect(0, PAGE_HEIGHT - 42, PAGE_WIDTH, 42, fill=1, stroke=0)
    _draw_text(
        c, MARGIN, PAGE_HEIGHT - 27, "A股行业大额主动资金雷达", 14.5, (1, 1, 1)
    )
    _draw_text(c, MARGIN + 218, PAGE_HEIGHT - 25, title, 10, (0.86, 0.90, 0.95))
    _right_text(
        c,
        PAGE_WIDTH - MARGIN,
        PAGE_HEIGHT - 25,
        f"报告日 {as_of}  |  {page}/{PAGE_COUNT}",
        9,
        (0.86, 0.90, 0.95),
    )


def _footer(c, text: str | None = None) -> None:
    message = text or "综合分仅为 10,000×S_H 的线性展示尺度；收益率与异常度不参与评分或排名。"
    _draw_text(c, MARGIN, 17, message, 7.2, MUTED)


def _ranking_rows(result: RadarResult, tail: bool = False) -> pd.DataFrame:
    ordered = _ranked(result.rankings)
    return ordered.tail(15) if tail else ordered.head(15)


def _draw_ranking_panel(
    c,
    x: float,
    title: str,
    result: RadarResult,
    level: str,
    horizon: int,
    tail: bool,
    accent: tuple[float, float, float],
) -> None:
    code, name = f"{level}_code", f"{level}_name"
    del code
    _box(c, x, 59, 383, 463)
    _draw_text(c, x + 14, 493, title, 12, accent)
    headers = [
        (x + 12, "名次", "left"),
        (x + 43, "行业", "left"),
        (x + 155, "综合分", "right"),
        (x + 226, "净流入", "right"),
        (x + 275, "同向天数", "right"),
        (x + 338, "同向个股", "right"),
        (x + 374, "涨跌", "right"),
    ]
    for hx, label, align in headers:
        if align == "right":
            _right_text(c, hx, 468, label, 5.7, MUTED)
        else:
            _draw_text(c, hx, 468, label, 5.7, MUTED)
    rows = _ranking_rows(result, tail)
    return_column = f"return_{horizon}d"
    flow_column = f"flow_{horizon}d"
    for index, row in enumerate(rows.itertuples(index=False)):
        y = 443 - index * 25.1
        if index % 2 == 0:
            c.setFillColorRGB(0.958, 0.972, 0.988)
            c.rect(x + 8, y - 8, 367, 21, fill=1, stroke=0)
        score = float(getattr(row, "comprehensive_score"))
        flow = float(getattr(row, flow_column))
        return_value = float(getattr(row, return_column))
        _draw_text(c, x + 13, y, str(int(getattr(row, "rank"))), 6.5, accent)
        _draw_text(c, x + 43, y, str(getattr(row, name))[:10], 6.5)
        _right_text(c, x + 155, y, _comprehensive(score), 6.2, _flow_color(score))
        _right_text(c, x + 226, y, _money(flow), 6.2, _flow_color(flow))
        _right_text(
            c,
            x + 275,
            y,
            f"{int(getattr(row, 'consistent_day_count'))}/{horizon}天",
            6.0,
        )
        _right_text(
            c,
            x + 338,
            y,
            (
                f"{int(getattr(row, 'consistent_stock_count'))}/"
                f"{int(getattr(row, 'breadth_stock_count'))}只"
            ),
            6.0,
        )
        _right_text(
            c,
            x + 374,
            y,
            _percent(return_value),
            6.0,
            _flow_color(return_value),
        )


def _representative_text(rows: pd.DataFrame, maximum: int = 4) -> str:
    parts = []
    for row in rows.head(maximum).itertuples(index=False):
        parts.append(
            f"{row.l2_name} {_comprehensive(row.comprehensive_score_5d, 1)}/"
            f"{_comprehensive(row.comprehensive_score_20d, 1)}"
        )
    return "、".join(parts) if parts else "无"


def _draw_state_card(
    c,
    x: float,
    y: float,
    width: float,
    height: float,
    state: str,
    details: dict[str, Any],
    accent: tuple[float, float, float],
) -> None:
    _box(c, x, y, width, height)
    _draw_text(
        c,
        x + 14,
        y + height - 25,
        f"{state}  {details['count']}个 / {details['share']:.1%}",
        11,
        accent,
    )
    _right_text(
        c,
        x + width - 13,
        y + height - 23,
        details["criterion"],
        6.4,
        MUTED,
    )
    representatives = details["representatives"]
    rep_y = y + height - 47
    if state == "双窗净流出":
        for label in ("接近改善", "流出最深"):
            _draw_text(
                c,
                x + 14,
                rep_y,
                f"{label}：{_representative_text(representatives[label])}",
                5.7,
                MUTED,
            )
            rep_y -= 14
    else:
        _draw_text(
            c,
            x + 14,
            rep_y,
            f"代表：{_representative_text(representatives['代表'])}",
            5.8,
            MUTED,
        )
        rep_y -= 14
    _draw_text(c, x + 14, rep_y - 1, "完整行业清单（按确定顺序）：", 5.8, MUTED)
    names = details["industries"]["l2_name"].astype(str).tolist()
    list_top = rep_y - 16
    available_height = list_top - (y + 12)
    rows_per_column = max(1, int(available_height // 8.0))
    columns = max(1, int(np.ceil(len(names) / rows_per_column)))
    columns = min(7, columns)
    rows_per_column = max(1, int(np.ceil(len(names) / columns)))
    column_width = (width - 28) / columns
    font_size = 5.0 if columns <= 4 else 4.5
    line_height = min(8.0, available_height / max(rows_per_column, 1))
    for index, industry_name in enumerate(names):
        column = index // rows_per_column
        row = index % rows_per_column
        if column >= columns:
            break
        _draw_text(
            c,
            x + 14 + column * column_width,
            list_top - row * line_height,
            industry_name[:8],
            font_size,
        )


def _draw_daily_answers(
    c, x: float, y: float, width: float, height: float, answers: dict[str, Any]
) -> None:
    """Draw the nine required daily conclusions in three compact columns."""
    _box(c, x, y, width, height, (0.985, 0.99, 1.0))
    columns = (
        (
            "市场扩散",
            [
                answers["inflow_industry_share"]["text"],
                answers["market_concentration"]["text"],
                answers["persistent_inflow"]["text"],
            ],
        ),
        (
            "状态轮动",
            [
                answers["recently_turned_in"]["text"],
                answers["medium_strong_short_cooling"]["text"],
                answers["persistent_outflow"]["text"],
            ],
        ),
        (
            "质量变化",
            [
                answers["inflow_diffusion"]["text"],
                answers["fastest_improving"]["text"],
                answers["fastest_worsening"]["text"],
            ],
        ),
    )
    column_width = (width - 28) / 3
    for column_index, (title, lines) in enumerate(columns):
        left = x + 12 + column_index * column_width
        _draw_text(c, left, y + height - 17, title, 7.2, BLUE)
        for line_index, line in enumerate(lines):
            compact = str(line).replace("。", "")
            _draw_text(
                c,
                left,
                y + height - 34 - line_index * 14,
                compact[:39],
                5.2,
                MUTED,
            )


def _history_bounds(paths: list[dict[str, Any]]) -> tuple[float, float]:
    values = [
        float(value)
        for path in paths
        for value in path["cumulative_flow"]
        if np.isfinite(value)
    ]
    low = min(values + [0.0])
    high = max(values + [0.0])
    span = max(high - low, max(abs(low), abs(high)) * 0.12, 1.0)
    return low - span * 0.08, high + span * 0.08


def _spread_label_positions(
    values: list[float], minimum: float, maximum: float, gap: float
) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    placed: dict[int, float] = {}
    cursor = minimum
    for original, value in indexed:
        cursor = max(cursor, value)
        placed[original] = cursor
        cursor += gap
    overflow = cursor - gap - maximum
    if overflow > 0:
        for original in placed:
            placed[original] -= overflow
    ordered = [placed[index] for index in range(len(values))]
    return [min(max(value, minimum), maximum) for value in ordered]


def _draw_history_chart(
    c,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    payload: dict[str, Any],
) -> None:
    _box(c, x, y, width, height)
    _draw_text(c, x + 14, y + height - 25, title, 11)
    _draw_text(
        c,
        x + 14,
        y + height - 43,
        "大额主动资金净流入逐日累计，首日归零；阴影为最后20个交易日",
        6.2,
        MUTED,
    )
    paths = payload
    dates = paths[0]["dates"]
    plot_x = x + 43
    plot_y = y + 42
    plot_width = width - 145
    plot_height = height - 102
    label_x = plot_x + plot_width + 10
    low, high = _history_bounds(paths)

    def px(index: int) -> float:
        return plot_x + index / (len(dates) - 1) * plot_width

    def py(value: float) -> float:
        return plot_y + (value - low) / (high - low) * plot_height

    c.setFillColorRGB(1.0, 0.975, 0.90)
    c.rect(px(len(dates) - 20), plot_y, px(len(dates) - 1) - px(len(dates) - 20), plot_height, fill=1, stroke=0)
    c.setStrokeColorRGB(0.83, 0.86, 0.90)
    c.setLineWidth(0.5)
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        grid_y = plot_y + fraction * plot_height
        c.line(plot_x, grid_y, plot_x + plot_width, grid_y)
        value = low + fraction * (high - low)
        _right_text(c, plot_x - 5, grid_y - 2, _money(value, 0), 5.4, MUTED)
    zero_y = py(0.0)
    c.setStrokeColorRGB(0.37, 0.42, 0.49)
    c.setLineWidth(0.9)
    c.line(plot_x, zero_y, plot_x + plot_width, zero_y)

    endpoint_ys: list[float] = []
    for index, path in enumerate(paths):
        color = LINE_COLORS[index % len(LINE_COLORS)]
        values = [float(value) for value in path["cumulative_flow"]]
        c.setStrokeColorRGB(*color)
        c.setLineWidth(1.25)
        line = c.beginPath()
        line.moveTo(px(0), py(values[0]))
        for point_index, value in enumerate(values[1:], 1):
            line.lineTo(px(point_index), py(value))
        c.drawPath(line, fill=0, stroke=1)
        c.setFillColorRGB(*color)
        c.circle(px(len(values) - 1), py(values[-1]), 2.2, fill=1, stroke=0)
        endpoint_ys.append(py(values[-1]))

    label_ys = _spread_label_positions(
        endpoint_ys, plot_y + 4, plot_y + plot_height - 4, 13
    )
    for index, (path, endpoint_y, label_y) in enumerate(
        zip(paths, endpoint_ys, label_ys)
    ):
        color = LINE_COLORS[index % len(LINE_COLORS)]
        final_value = float(path["cumulative_flow"][-1])
        c.setStrokeColorRGB(*color)
        c.setLineWidth(0.6)
        c.line(plot_x + plot_width, endpoint_y, label_x - 3, label_y)
        _draw_text(
            c,
            label_x,
            label_y - 2,
            (
                f"{path['industry_name'][:7]} 第{path['rank_20d']}名 "
                f"{_money(final_value)}"
            ),
            5.6,
            color,
        )
    _draw_text(c, plot_x, y + 24, _short_date(dates[0]), 5.8, MUTED)
    _center_text(c, px(len(dates) - 20), y + 24, _short_date(dates[-20]), 5.8, MUTED)
    _right_text(c, plot_x + plot_width, y + 24, _short_date(dates[-1]), 5.8, MUTED)


def _draw_market_flow_chart(
    c, x: float, y: float, width: float, height: float, payload: dict[str, Any]
) -> None:
    """Draw the 60-date first-day-zero cumulative large active flow."""
    _box(c, x, y, width, height)
    _draw_text(
        c,
        x + 14,
        y + height - 20,
        "市场大额主动资金：近60个交易日累计净流入",
        10.5,
    )
    _draw_text(
        c,
        x + 14,
        y + height - 38,
        "近60个交易日 · 首日归零 · 单位：亿元 · 上升=净流入 / 下降=净流出 · 斜率=强弱",
        6.2,
        MUTED,
    )
    series = pd.DataFrame(payload["series"])
    dates = series["trade_date"].astype(str).tolist()
    cumulative = (
        series["market_large_active_flow_cumulative"].astype(float).to_numpy()
        / 100_000
    )
    values = np.concatenate((cumulative, np.array([0.0])))
    low, high = float(np.nanmin(values)), float(np.nanmax(values))
    span = high - low
    padding = max(span * 0.10, max(abs(low), abs(high)) * 0.05, 1.0)
    low -= padding
    high += padding
    chart_x, chart_y = x + 50, y + 25
    chart_w, chart_h = width - 78, height - 72

    def px(index: int) -> float:
        return chart_x + chart_w * index / (len(dates) - 1)

    def py(value: float) -> float:
        return chart_y + chart_h * (value - low) / (high - low)

    zero_y = py(0.0)
    c.setFillColorRGB(1.0, 0.965, 0.965)
    c.rect(chart_x, zero_y, chart_w, chart_y + chart_h - zero_y, fill=1, stroke=0)
    c.setFillColorRGB(0.96, 0.985, 0.965)
    c.rect(chart_x, chart_y, chart_w, zero_y - chart_y, fill=1, stroke=0)
    c.setLineWidth(0.35)
    for value in np.linspace(low, high, 5):
        position = py(float(value))
        c.setStrokeColorRGB(0.86, 0.88, 0.91)
        c.line(chart_x, position, chart_x + chart_w, position)
        _right_text(c, chart_x - 5, position - 2, f"{value:+.0f}", 5.4, MUTED)
    c.setStrokeColorRGB(*MUTED)
    c.setLineWidth(1.0)
    c.line(chart_x, zero_y, chart_x + chart_w, zero_y)
    c.setStrokeColorRGB(*BLUE)
    c.setLineWidth(1.55)
    path = c.beginPath()
    path.moveTo(px(0), py(float(cumulative[0])))
    for index, value in enumerate(cumulative[1:], 1):
        path.lineTo(px(index), py(float(value)))
    c.drawPath(path, stroke=1, fill=0)
    tick_indexes = (0, 14, 29, 44, 59)
    for index in tick_indexes:
        _center_text(c, px(index), chart_y - 13, _short_date(dates[index]), 5.4, MUTED)
    _right_text(
        c,
        x + width - 15,
        y + height - 21,
        (
            f"近5日 {_money(payload['recent_5d_change'])} · "
            f"近20日 {_money(payload['recent_20d_change'])}"
        ),
        6.0,
        MUTED,
    )
    end_x = px(59)
    endpoint_y = py(float(cumulative[-1]))
    endpoint_color = RED if cumulative[-1] >= 0 else GREEN
    c.setFillColorRGB(*endpoint_color)
    c.circle(end_x, endpoint_y, 2.5, fill=1, stroke=0)
    _right_text(
        c,
        end_x - 5,
        min(endpoint_y + 4, chart_y + chart_h - 5),
        f"累计 {cumulative[-1]:+.1f}亿",
        5.9,
        endpoint_color,
    )


def _focus_rows(report: dict[str, Any]) -> list[pd.Series]:
    groups = _state_groups(_state_frame(report))
    rows: list[pd.Series] = []
    for state in STATE_ORDER:
        representatives = groups[state]["representatives"]
        key = "接近改善" if state == "双窗净流出" else "代表"
        selected = representatives[key]
        if not selected.empty:
            rows.append(selected.iloc[0])
    if len(rows) < 4:
        used = {str(row["l2_code"]) for row in rows}
        for _, row in _state_frame(report).sort_values(
            ["rank_20d", "rank_5d", "l2_code"], kind="stable"
        ).iterrows():
            if str(row["l2_code"]) not in used:
                rows.append(row)
            if len(rows) == 4:
                break
    return rows[:4]


def _draw_rotation_table(
    c,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    rows: pd.DataFrame,
    accent: tuple[float, float, float],
) -> None:
    """Draw one improvement/deterioration table with migration evidence."""
    _box(c, x, y, width, height)
    _draw_text(c, x + 14, y + height - 24, title, 11, accent)
    headers = (
        (x + 14, "行业", "left"),
        (x + 145, "可比强度", "right"),
        (x + 244, "Δ1日 / Δ5日均", "right"),
        (x + 350, "当前名次 / Δ1 / Δ5", "right"),
        (x + 503, "昨日→今日", "left"),
        (x + 639, "连续", "right"),
        (x + width - 14, "内部流入质量", "right"),
    )
    for hx, label, align in headers:
        if align == "right":
            _right_text(c, hx, y + height - 47, label, 5.7, MUTED)
        else:
            _draw_text(c, hx, y + height - 47, label, 5.7, MUTED)
    for row_index, row in enumerate(rows.head(5).itertuples(index=False)):
        row_y = y + height - 78 - row_index * 33
        if row_index % 2 == 0:
            c.setFillColorRGB(0.958, 0.972, 0.988)
            c.rect(x + 8, row_y - 9, width - 16, 24, fill=1, stroke=0)
        _draw_text(c, x + 14, row_y, str(row.l2_name)[:10], 7.0)
        _right_text(
            c,
            x + 145,
            row_y,
            f"{float(row.rotation_strength_bps):+.1f}bp",
            6.3,
            _flow_color(row.rotation_strength_bps),
        )
        _right_text(
            c,
            x + 244,
            row_y,
            (
                f"{float(row.strength_change_1d_bps):+.1f} / "
                f"{float(row.strength_change_5d_per_day_bps):+.1f}bp"
            ),
            6.0,
            accent,
        )
        _right_text(
            c,
            x + 350,
            row_y,
            (
                f"{int(row.rotation_rank)} / "
                f"{float(row.rank_change_1d):+g} / "
                f"{float(row.rank_change_5d):+g}"
            ),
            6.0,
        )
        _draw_text(c, x + 503, row_y, str(row.transition_previous)[:18], 5.8)
        _right_text(
            c,
            x + 639,
            row_y,
            f"{int(row.state_streak_days)}日",
            6.0,
        )
        _right_text(
            c,
            x + width - 14,
            row_y,
            (
                f"净流入股{float(row.net_inflow_stock_ratio_1d):.0%} · "
                f"Top3 {float(row.top3_direction_contribution_1d):.0%} · "
                f"{row.diffusion_label_1d}"
            ),
            5.7,
            MUTED,
        )


def _rotation_change_frame(report: dict[str, Any]) -> pd.DataFrame:
    dynamic = _state_frame(report)
    quality = report["horizons"][5]["l2"].rankings[
        [
            "l2_code",
            "net_inflow_stock_ratio_1d",
            "top3_direction_contribution_1d",
            "diffusion_label_1d",
        ]
    ]
    return dynamic.merge(quality, on="l2_code", how="left", validate="one_to_one")


def _merged_detail(report: dict[str, Any]) -> pd.DataFrame:
    five = report["horizons"][5]["l2"].rankings
    twenty = report["horizons"][20]["l2"].rankings
    common = [
        "rank",
        "base_strength",
        "consistent_day_count",
        "consistent_stock_count",
        "breadth_stock_count",
        "confirmation_score",
        "confirmation_multiplier",
        "score",
        "comprehensive_score",
    ]
    five_columns = [
        "l2_code",
        "l2_name",
        "flow_5d",
        "net_inflow_stock_ratio_1d",
        "top1_direction_contribution_1d",
        "top3_direction_contribution_1d",
        "top5_direction_contribution_1d",
        "diffusion_label_1d",
        *common,
    ]
    twenty_columns = ["l2_code", "flow_20d", *common]
    return five[five_columns].merge(
        twenty[twenty_columns],
        on="l2_code",
        suffixes=("_5d", "_20d"),
        validate="one_to_one",
    ).set_index("l2_code")


def _write_pdf_reportlab(report: dict[str, Any], path: Path) -> None:
    """Render the final eleven-page report using only ReportLab primitives."""
    c = _pdf_canvas(path)
    as_of = str(report["as_of"])
    five_l1: RadarResult = report["horizons"][5]["l1"]
    five_l2: RadarResult = report["horizons"][5]["l2"]
    twenty_l1: RadarResult = report["horizons"][20]["l1"]
    twenty_l2: RadarResult = report["horizons"][20]["l2"]

    def page(number: int, title: str) -> None:
        _header(c, as_of, number, title)

    def finish(footer: str | None = None) -> None:
        _footer(c, footer)
        c.showPage()

    # 1. Market overview.
    page(1, "市场总览")
    market_history = report["market_flow_history"]
    market5 = float(market_history["recent_5d_change"])
    market20 = float(market_history["recent_20d_change"])
    for x, label, value, subtitle in (
        (MARGIN, "5日市场大额主动资金", market5, "短线资金底色"),
        (PAGE_WIDTH / 2 + 8, "20日市场大额主动资金", market20, "趋势资金底色"),
    ):
        _box(c, x, 455, 383, 66)
        _draw_text(c, x + 18, 494, label, 9, MUTED)
        _draw_text(c, x + 18, 466, _money(value), 18, _flow_color(value))
        direction = "净流入" if value > 0 else "净流出" if value < 0 else "持平"
        _right_text(c, x + 365, 476, f"{direction} · {subtitle}", 8, _flow_color(value))
    _draw_market_flow_chart(
        c, MARGIN, 292, PAGE_WIDTH - 2 * MARGIN, 147, market_history
    )
    for x, title, result, horizon, accent in (
        (MARGIN, "5日二级行业前5", five_l2, 5, BLUE),
        (PAGE_WIDTH / 2 + 8, "20日二级行业前5", twenty_l2, 20, ROSE),
    ):
        _box(c, x, 45, 383, 230)
        _draw_text(c, x + 16, 252, title, 11, accent)
        _draw_text(c, x + 17, 232, "名次  行业", 6.0, MUTED)
        _right_text(c, x + 250, 232, "综合分", 6.0, MUTED)
        _right_text(c, x + 365, 232, "净流入 / 同期涨跌", 6.0, MUTED)
        for index, row in enumerate(_ranked(result.rankings).head(5).itertuples()):
            y = 206 - index * 31
            _draw_text(c, x + 18, y, str(int(row.rank)), 8, accent)
            _draw_text(c, x + 46, y, str(row.l2_name), 8)
            _right_text(c, x + 250, y, _comprehensive(row.comprehensive_score), 7.5, _flow_color(row.comprehensive_score))
            flow = getattr(row, f"flow_{horizon}d")
            return_value = getattr(row, f"return_{horizon}d")
            _right_text(c, x + 365, y, f"{_money(flow)} / {_percent(return_value)}", 7, _flow_color(flow))
            _draw_text(
                c,
                x + 46,
                y - 13,
                (
                    f"同向天数 {row.consistent_day_count}/{horizon}天 · "
                    f"净流入股 {row.net_inflow_stock_ratio_1d:.0%} · "
                    f"Top3贡献 {row.top3_direction_contribution_1d:.0%}"
                ),
                6.1,
                MUTED,
            )
    finish(
        "大额主动资金=大单+特大单主动买入额−主动卖出额；仅反映大额主动成交方向，"
        "不代表真实机构账户身份、实际持仓或持仓变化。"
    )

    # 2. Complete four-state list.
    page(2, "每日结论与四类资金状态")
    state_groups = _state_groups(_state_frame(report))
    _draw_daily_answers(
        c, MARGIN, 447, PAGE_WIDTH - 2 * MARGIN, 74, report["daily_answers"]
    )
    positions = {
        "双窗净流入": (MARGIN, 278),
        "短线转入": (PAGE_WIDTH / 2 + 8, 278),
        "趋势仍流入": (MARGIN, 65),
        "双窗净流出": (PAGE_WIDTH / 2 + 8, 65),
    }
    heights = {
        "双窗净流入": 155,
        "短线转入": 155,
        "趋势仍流入": 199,
        "双窗净流出": 199,
    }
    accents = {
        "双窗净流入": RED,
        "短线转入": ORANGE,
        "趋势仍流入": PURPLE,
        "双窗净流出": GREEN,
    }
    for state in STATE_ORDER:
        x, y = positions[state]
        _draw_state_card(
            c, x, y, 383, heights[state], state, state_groups[state], accents[state]
        )
    finish(
        "分类与占比仅使用报告日有效成分股不少于10只的申万二级行业；"
        "状态迁移、连续天数及改善/恶化明细见导出数据。"
    )

    # 3-6. Symmetric ranking pages.
    ranking_pages = (
        (3, "申万一级前15", five_l1, twenty_l1, "前15", False),
        (4, "申万一级后15", five_l1, twenty_l1, "后15", True),
        (5, "申万二级前15", five_l2, twenty_l2, "前15", False),
        (6, "申万二级后15", five_l2, twenty_l2, "后15", True),
    )
    for number, title, result5, result20, suffix, tail in ranking_pages:
        level = "l1" if number in (3, 4) else "l2"
        page(number, title)
        _draw_ranking_panel(c, MARGIN, f"5日短线{suffix}", result5, level, 5, tail, BLUE)
        _draw_ranking_panel(c, PAGE_WIDTH / 2 + 8, f"20日趋势{suffix}", result20, level, 20, tail, ROSE)
        finish(
            "同期涨跌为该窗口行业成分股流通市值加权涨跌，仅供参考，不参与综合分或排名。"
        )

    # 7-8. Historical cumulative fund paths.
    for number, level, title in (
        (7, "l1", "申万一级：20日Top/Bottom 5最近40日累计资金"),
        (8, "l2", "申万二级：20日Top/Bottom 5最近40日累计资金"),
    ):
        page(number, title)
        history = report["history"][level]
        _draw_history_chart(c, MARGIN, 66, 383, 454, "报告日20日排名 Top 5", history["top"])
        _draw_history_chart(c, PAGE_WIDTH / 2 + 8, 66, 383, 454, "报告日20日排名 Bottom 5", history["bottom"])
        finish(
            "选择基于报告日20日最终排名；仅复核截至报告日的最近40个现有交易日历史路径，不是回测、预测或投资建议。"
        )

    # 9. Comparable strength changes, rank changes, migrations, and quality.
    page(9, "资金状态变化：改善与恶化")
    rotation_changes = _rotation_change_frame(report)
    improving = rotation_changes.dropna(
        subset=["improvement_speed_bps"]
    ).sort_values(
        ["improvement_speed_bps", "rank_change_1d", "l2_code"],
        ascending=[False, False, True],
        kind="stable",
    )
    worsening = rotation_changes.dropna(
        subset=["improvement_speed_bps"]
    ).sort_values(
        ["improvement_speed_bps", "rank_change_1d", "l2_code"],
        ascending=[True, True, True],
        kind="stable",
    )
    _draw_rotation_table(
        c,
        MARGIN,
        294,
        PAGE_WIDTH - 2 * MARGIN,
        226,
        "改善最快 Top 5",
        improving,
        RED,
    )
    _draw_rotation_table(
        c,
        MARGIN,
        55,
        PAGE_WIDTH - 2 * MARGIN,
        226,
        "恶化最快 Top 5",
        worsening,
        GREEN,
    )
    finish(
        "改善/恶化按可比资金强度变化排序，排名变化仅作辅助；"
        "排名变化=历史名次−当前名次，正数表示上升。"
    )

    # 10. Representative calculation chains.
    page(10, "代表行业完整计算链")
    detail = _merged_detail(report)
    cards = [(34, 302), (430, 302), (34, 65), (430, 65)]
    for focus, (x, y) in zip(_focus_rows(report), cards):
        row = detail.loc[str(focus["l2_code"])]
        state = _state_name(row["flow_5d"], row["flow_20d"])
        _box(c, x, y, 378, 217)
        _draw_text(c, x + 14, y + 188, f"{state} · {row['l2_name']}", 11)
        for horizon, top, accent in ((5, 157, BLUE), (20, 91, ROSE)):
            _draw_text(
                c,
                x + 14,
                y + top,
                (
                    f"{horizon}日 第{int(row[f'rank_{horizon}d'])}名 · "
                    f"综合分 {_comprehensive(row[f'comprehensive_score_{horizon}d'])} · "
                    f"净流入 {_money(row[f'flow_{horizon}d'])}"
                ),
                7.4,
                accent,
            )
            _draw_text(
                c,
                x + 14,
                y + top - 23,
                (
                    f"基础强度 I={row[f'base_strength_{horizon}d']:+.6f} · "
                    f"同向天数 {int(row[f'consistent_day_count_{horizon}d'])}/{horizon}天 · "
                    f"同向个股 {int(row[f'consistent_stock_count_{horizon}d'])}/"
                    f"{int(row[f'breadth_stock_count_{horizon}d'])}只"
                ),
                6.2,
            )
            _draw_text(
                c,
                x + 14,
                y + top - 43,
                (
                    f"确认度 {row[f'confirmation_score_{horizon}d']:.3f} · "
                    f"确认乘数 {row[f'confirmation_multiplier_{horizon}d']:.3f} · "
                    f"原始 S_H={row[f'score_{horizon}d']:+.9f}"
                ),
                6.1,
                MUTED,
            )
        _draw_text(
            c,
            x + 14,
            y + 22,
            (
                f"当日净流入股 {row['net_inflow_stock_ratio_1d']:.0%} · "
                f"Top1/3/5方向贡献 "
                f"{row['top1_direction_contribution_1d']:.0%}/"
                f"{row['top3_direction_contribution_1d']:.0%}/"
                f"{row['top5_direction_contribution_1d']:.0%} · "
                f"{row['diffusion_label_1d']}"
            ),
            5.7,
            MUTED,
        )
    finish()

    # 11. Formula, semantics, coverage, and reproducibility.
    page(11, "公式、数据覆盖与复核说明")
    _draw_text(c, MARGIN, 516, "唯一、对称、有符号公式", 16)
    _box(c, MARGIN, 337, PAGE_WIDTH - 2 * MARGIN, 151)
    method_lines = [
        "I_H = H日净流入 / H日成交额",
        "P_H（同向天数比例）= 同向天数 / H",
        "P_B（同向个股比例）= 同向个股数 / 有效个股数",
        "C_H = 0.35 × P_H（同向天数比例） + 0.65 × P_B（同向个股比例）",
        "S_H = I_H × exp[-0.3 × (1 - C_H)]",
        "综合分 = 10,000 × S_H（仅线性展示，符号、零点、顺序完全不变）",
    ]
    for index, line in enumerate(method_lines):
        _draw_text(c, MARGIN + 20, 459 - index * 22, line, 8.7)
    _box(c, MARGIN, 174, PAGE_WIDTH - 2 * MARGIN, 137, (1.0, 0.985, 0.95))
    quality = five_l2.quality
    semantic_lines = [
        "确认乘数恒正，范围 exp(-0.3)≈0.741 到 1；没有流入/流出分支，也不会翻转原始资金方向。",
        "净流入为正、净流出为负、零流量为零；零流量时同向天数与同向个股比例均明确定义为0。",
        f"申万二级仅纳入报告日有效成分股不少于{quality['minimum_l2_valid_stocks']}只的行业；停牌、成交额≤0或关键字段缺失不计。",
        "Top1/3/5方向贡献以行业同方向股票资金池为分母，不以正负抵消后的行业净额为分母，比例范围0–100%。",
        "可比资金强度=0.60×5日净额/成交额+0.40×20日净额/成交额；改善榜看强度变化，排名变化仅辅助。",
    ]
    for index, line in enumerate(semantic_lines):
        _draw_text(c, MARGIN + 18, 281 - index * 23, line, 7.4, MUTED)
    _draw_text(c, MARGIN, 140, "数据覆盖", 11)
    _draw_text(
        c,
        MARGIN,
        116,
        (
            f"报告日 {quality['as_of']} · 交易日 {quality['available_trading_days']} · "
            f"输入 {quality['input_rows']:,} 行 · 映射后 {quality['mapped_rows']:,} 行 · "
            f"报告日样本股 {quality['latest_stock_rows']:,}"
        ),
        7.2,
        MUTED,
    )
    _draw_text(
        c,
        MARGIN,
        92,
        (
            f"报告日缺失率：大额主动资金 {quality['latest_missing_flow_rate']:.2%} · "
            f"成交额 {quality['latest_missing_amount_rate']:.2%} · "
            f"流通市值 {quality['latest_missing_market_value_rate']:.2%} · "
            f"二级行业纳入 {quality['eligible_industry_count']} / "
            f"小样本剔除 {quality['excluded_small_sample_industry_count']}"
        ),
        7.2,
        MUTED,
    )
    finish(
        "大额主动资金反映大单+特大单主动成交方向，不代表真实机构账户身份、"
        "实际持仓或持仓变化；本报告不构成投资建议。"
    )
    c.save()


def write_pdf(report: dict[str, Any], path: Path) -> None:
    """Write the single combined eleven-page report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_pdf_reportlab(report, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从同一真实行业资金面板生成5日短线×20日趋势合刊PDF"
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="上游ZeroShare/Tushare真实数据提取文件"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output/pdf")
    )
    parser.add_argument(
        "--metadata", type=Path, help="上游最小窗口、请求量与覆盖率JSON"
    )
    parser.add_argument(
        "--no-pdf", action="store_true", help="仅导出排名数据和数据质量清单"
    )
    args = parser.parse_args(argv)
    metadata = (
        json.loads(args.metadata.read_text(encoding="utf-8"))
        if args.metadata
        else None
    )
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object")
    report = build_report_data(load_panel(args.input), metadata)
    _, manifest = write_datasets(report, args.output_dir)
    if not args.no_pdf:
        pdf_path = args.output_dir / f"industry_fund_radar_{report['as_of']}.pdf"
        write_pdf(report, pdf_path)
        print(pdf_path.resolve())
    print(manifest.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
