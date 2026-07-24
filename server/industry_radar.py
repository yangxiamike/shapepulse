"""Deterministic calculations for the A-share large active fund-flow radar.

This module deliberately has no database or PDF dependency.  Its input is the
stock-day panel produced from the research universe, an industry mapping, and
large-order active net flow.  Keeping calculation here makes the report
reproducible and prevents presentation code from silently changing a score.

Required columns are ``trade_date, ts_code, <level>_code, <level>_name,
inst_net_flow, amount, circ_mv, close``.  Amount, market value, and flow must
use a consistent monetary unit. ``inst_net_flow`` is retained as the upstream
field name for compatibility; semantically it is large-order plus
extra-large-order active buys minus active sells.  It is not an account
identity or a position measure.  Five-day and twenty-day radars use the same
formula independently, so a score always has one explicit horizon and never
blends short- and medium-term evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


LOOKBACKS = (1, 5, 20)
SCORING_HORIZONS = (5, 20)
ANOMALY_HISTORY_DAYS = 120
MINIMUM_TRADING_DAYS = ANOMALY_HISTORY_DAYS + max(LOOKBACKS)
PERSISTENCE_WEIGHT = 0.35
BREADTH_WEIGHT = 0.65
CONFIRMATION_DECAY = 0.30
COMPREHENSIVE_SCORE_SCALE = 10_000
SCORE_ROUND_DECIMALS = 12
FLOW_TIE_ROUND_DECIMALS = 6
MIN_L2_VALID_STOCKS = 10
Level = Literal["l1", "l2"]
Horizon = Literal[5, 20]


@dataclass(frozen=True)
class RadarResult:
    """Rankings, stock contributors, and auditable data-quality metadata."""

    rankings: pd.DataFrame
    contributors: pd.DataFrame
    daily_flows: pd.DataFrame
    quality: dict[str, int | str | float | bool]


def minimum_required_trading_days(
    history_days: int = ANOMALY_HISTORY_DAYS, lookback: int = 20
) -> int:
    """Days needed for ``history_days`` prior rolling observations plus today."""
    if history_days < 1 or lookback < 1:
        raise ValueError("history_days and lookback must be positive")
    return history_days + lookback


def _require_columns(frame: pd.DataFrame, level: Level) -> tuple[str, str]:
    code, name = f"{level}_code", f"{level}_name"
    required = {
        "trade_date", "ts_code", code, name, "inst_net_flow", "amount", "circ_mv", "close"
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"radar input is missing columns: {', '.join(sorted(missing))}")
    return code, name


def effective_stock_mask(frame: pd.DataFrame) -> pd.Series:
    """Return rows with normal trading and complete calculation inputs.

    ``amount > 0`` and ``close > 0`` are the portable normal-trading checks.
    When an upstream ``is_trading`` or ``trade_status`` field exists it is
    additionally respected.  Missing large active flow is never filled with
    zero.
    """
    numeric = {
        column: pd.to_numeric(frame[column], errors="coerce")
        for column in ("inst_net_flow", "amount", "circ_mv", "close")
    }
    mask = pd.Series(True, index=frame.index, dtype=bool)
    for values in numeric.values():
        mask &= np.isfinite(values)
    mask &= numeric["amount"].gt(0)
    mask &= numeric["circ_mv"].gt(0)
    mask &= numeric["close"].gt(0)
    if "is_trading" in frame:
        trading = frame["is_trading"]
        if trading.dtype == bool:
            mask &= trading.fillna(False)
        else:
            normalized = trading.astype(str).str.strip().str.lower()
            mask &= normalized.isin(
                {"1", "1.0", "true", "yes", "y", "正常", "交易", "交易中"}
            )
    elif "trade_status" in frame:
        normalized = frame["trade_status"].astype(str).str.strip().str.lower()
        mask &= normalized.isin(
            {
                "1",
                "1.0",
                "true",
                "yes",
                "y",
                "正常",
                "交易",
                "交易中",
                "trading",
                "normal",
            }
        )
    return mask


def _quantized_sign(value: float) -> int:
    """Return a deterministic sign at the documented source-money precision."""
    numeric = pd.to_numeric(value, errors="coerce")
    if not np.isfinite(numeric):
        return 0
    return int(np.sign(round(float(numeric), FLOW_TIE_ROUND_DECIMALS)))


def _deterministic_rank(
    rankings: pd.DataFrame, code_column: str, horizon: int
) -> pd.DataFrame:
    """Sort quantized scores by auditable signed keys, then stable code.

    The public score is quantized before sorting.  Mathematical ties then use
    the selected-window base strength, signed flow, five-day flow, one-day
    flow, and stable industry code.  Every numeric key has an explicit decimal
    precision, so machine epsilon never decides a published rank.
    """
    work = rankings.copy()
    work["score"] = pd.to_numeric(work["score"], errors="coerce").round(
        SCORE_ROUND_DECIMALS
    )
    work["_rank_base_strength"] = pd.to_numeric(
        work["base_strength"], errors="coerce"
    ).round(SCORE_ROUND_DECIMALS)
    tie_periods: list[int] = []
    for period in (horizon, 5, 1):
        if period not in tie_periods:
            tie_periods.append(period)
    sort_columns = ["score", "_rank_base_strength"]
    ascending = [False, False]
    temporary: list[str] = ["_rank_base_strength"]
    for period in tie_periods:
        key = f"_rank_flow_{period}d"
        work[key] = pd.to_numeric(
            work[f"flow_{period}d"], errors="coerce"
        ).round(FLOW_TIE_ROUND_DECIMALS)
        sort_columns.append(key)
        ascending.append(False)
        temporary.append(key)
    sort_columns.append(code_column)
    ascending.append(True)
    work = work.sort_values(
        sort_columns, ascending=ascending, kind="stable", na_position="last"
    ).reset_index(drop=True)
    work["rank"] = work.index + 1
    return work.drop(columns=temporary)


def _robust_z(current: float, historical: pd.Series) -> tuple[float, bool]:
    """Return a signed own-history robust z value and cold-start flag."""
    history = historical.replace([np.inf, -np.inf], np.nan).dropna()
    if len(history) < ANOMALY_HISTORY_DAYS:
        return 0.0, True
    median = float(history.median())
    mad = float((history - median).abs().median())
    scale = mad * 1.4826
    if scale <= 1e-12:
        scale = float(history.std(ddof=0))
    if scale <= 1e-12:
        return (3.0 if current > median else 0.0), False
    return float(np.clip((current - median) / scale, -3.0, 3.0)), False


def _weighted_return(group: pd.DataFrame, start_index: int) -> float:
    ordered_dates = sorted(group["trade_date"].unique())
    if len(ordered_dates) <= start_index:
        return float("nan")
    end_date, start_date = ordered_dates[-1], ordered_dates[-1 - start_index]
    start = group[group["trade_date"].eq(start_date)][["ts_code", "close", "circ_mv"]].rename(
        columns={"close": "start_close", "circ_mv": "start_mv"}
    )
    end = group[group["trade_date"].eq(end_date)][["ts_code", "close"]].rename(
        columns={"close": "end_close"}
    )
    merged = start.merge(end, on="ts_code", how="inner")
    merged = merged[(merged["start_close"] > 0) & (merged["start_mv"] > 0)].copy()
    if merged.empty:
        return float("nan")
    returns = merged["end_close"] / merged["start_close"] - 1.0
    return float(np.average(returns, weights=merged["start_mv"]))


def _industry_daily(work: pd.DataFrame, code_column: str, name_column: str) -> pd.DataFrame:
    return (
        work.groupby(["trade_date", code_column, name_column], as_index=False)
        .agg(
            inst_net_flow=("inst_net_flow", lambda values: values.sum(min_count=1)),
            amount=("amount", lambda values: values.sum(min_count=1)),
            valid_stock_count=("ts_code", "nunique"),
        )
        .sort_values([code_column, "trade_date"])
    )


def _direction_label(flow: float, period: int) -> tuple[str, int]:
    if not np.isfinite(flow):
        return f"{period}日数据缺失", 0
    sign = _quantized_sign(flow)
    suffix = "净流入" if sign > 0 else "净流出" if sign < 0 else "持平"
    return f"{period}日{suffix}", sign


def analyze_industries(
    frame: pd.DataFrame, level: Level = "l2", horizon: Horizon = 5
) -> RadarResult:
    """Calculate one independent 5- or 20-day SW level ranking.

    The latest common date in ``frame`` is the report date.  Rows with missing
    large active flow, amount, market value, or close are retained for coverage
    accounting but excluded from calculations.  For SW level 2, industries
    with fewer than ten effective report-date constituents are completely
    excluded from the ranking universe.  Zero is a real value; missing is
    never silently converted to it.
    """
    if horizon not in SCORING_HORIZONS:
        raise ValueError(f"horizon must be one of {SCORING_HORIZONS}")
    code_column, name_column = _require_columns(frame, level)
    if frame.empty:
        raise ValueError("radar input is empty")
    work = frame.copy()
    work["trade_date"] = work["trade_date"].astype(str)
    if work.duplicated(["trade_date", "ts_code"]).any():
        raise ValueError("radar input has duplicate stock-day rows")
    for column in ("inst_net_flow", "amount", "circ_mv", "close"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    mapped = work[work[code_column].notna() & work[name_column].notna()].copy()
    dates = sorted(mapped["trade_date"].unique())
    if not dates:
        raise ValueError("radar input has no mapped industry rows")
    as_of = dates[-1]
    available_days = len(dates)
    latest_mapped = mapped[mapped["trade_date"].eq(as_of)].copy()
    valid_mask = effective_stock_mask(mapped)
    valid_work = mapped[valid_mask].copy()
    latest_valid = valid_work[valid_work["trade_date"].eq(as_of)].copy()
    excluded_industries = pd.DataFrame(columns=[code_column, name_column, "valid_stock_count"])
    if level == "l2":
        counted = (
            latest_valid.groupby([code_column, name_column], as_index=False)["ts_code"]
            .nunique()
            .rename(columns={"ts_code": "valid_stock_count"})
        )
        latest_counts = (
            latest_mapped[[code_column, name_column]]
            .drop_duplicates()
            .merge(
                counted,
                on=[code_column, name_column],
                how="left",
                validate="one_to_one",
            )
        )
        latest_counts["valid_stock_count"] = (
            latest_counts["valid_stock_count"].fillna(0).astype(int)
        )
        excluded_industries = latest_counts[
            latest_counts["valid_stock_count"] < MIN_L2_VALID_STOCKS
        ].copy()
        eligible = latest_counts[
            latest_counts["valid_stock_count"] >= MIN_L2_VALID_STOCKS
        ][[code_column, name_column]]
        if eligible.empty:
            raise ValueError(
                "no l2 industries have at least "
                f"{MIN_L2_VALID_STOCKS} effective report-date stocks"
            )
        valid_work = valid_work.merge(
            eligible, on=[code_column, name_column], how="inner", validate="many_to_one"
        )
        latest_valid = valid_work[valid_work["trade_date"].eq(as_of)].copy()
    daily = _industry_daily(valid_work, code_column, name_column)
    records: list[dict] = []
    contributor_frames: list[pd.DataFrame] = []

    for (industry_code, industry_name), group in daily.groupby([code_column, name_column], sort=False):
        series = group.set_index("trade_date")["inst_net_flow"].reindex(dates)
        amount_series = group.set_index("trade_date")["amount"].reindex(dates)
        flows = {period: float(series.tail(period).sum(min_count=period)) for period in LOOKBACKS}
        amounts = {period: float(amount_series.tail(period).sum(min_count=period)) for period in LOOKBACKS}
        directions = {
            period: _direction_label(flows[period], period) for period in LOOKBACKS
        }
        direction, direction_sign = directions[horizon]
        z_values: dict[int, float] = {}
        cold_starts: dict[int, bool] = {}
        for period in LOOKBACKS:
            rolling = series.rolling(period, min_periods=period).sum()
            z_values[period], cold_starts[period] = _robust_z(
                flows[period], rolling.iloc[:-1].tail(ANOMALY_HISTORY_DAYS)
            )
        scoring_window = series.tail(horizon)
        selected_flow_quantized = round(
            flows[horizon], FLOW_TIE_ROUND_DECIMALS
        )
        if direction_sign == 0:
            # With no aggregate direction there is no proposition for either
            # days or stocks to confirm.  Both raw confirmation ratios are
            # therefore defined as zero.  The base strength and final score
            # are also exactly zero, so this convention cannot create NaN or
            # alter the zero-flow rank boundary.
            consistent_day_count = 0
        else:
            consistent_day_count = int(
                scoring_window.map(_quantized_sign).eq(direction_sign).sum()
            )
        persistence_ratio = consistent_day_count / horizon
        stock_window = valid_work[
            valid_work[code_column].eq(industry_code)
            & valid_work["trade_date"].isin(dates[-horizon:])
        ].groupby("ts_code", as_index=False).agg(
            inst_net_flow=("inst_net_flow", lambda values: values.sum(min_count=1)),
            amount=("amount", lambda values: values.sum(min_count=1)),
        )
        valid_stock_flows = stock_window["inst_net_flow"].dropna()
        breadth_stock_count = int(len(valid_stock_flows))
        if direction_sign == 0 or breadth_stock_count == 0:
            consistent_stock_count = 0
        else:
            consistent_stock_count = int(
                valid_stock_flows.map(_quantized_sign).eq(direction_sign).sum()
            )
        breadth_ratio = (
            consistent_stock_count / breadth_stock_count
            if breadth_stock_count
            else 0.0
        )
        selected_amount = amounts[horizon]
        if not np.isfinite(flows[horizon]):
            base_strength = float("nan")
        elif direction_sign == 0:
            base_strength = 0.0
        elif np.isfinite(selected_amount) and selected_amount > 0:
            base_strength = float(flows[horizon] / selected_amount)
        else:
            base_strength = float("nan")
        confirmation_score = (
            PERSISTENCE_WEIGHT * persistence_ratio
            + BREADTH_WEIGHT * breadth_ratio
        )
        confirmation_multiplier = float(
            np.exp(-CONFIRMATION_DECAY * (1.0 - confirmation_score))
        )
        score_unrounded = base_strength * confirmation_multiplier
        latest_industry = latest_valid[latest_valid[code_column].eq(industry_code)]
        latest_stock_flows = latest_industry[
            ["ts_code", "inst_net_flow"]
        ].copy()
        latest_stock_flows["inst_net_flow"] = pd.to_numeric(
            latest_stock_flows["inst_net_flow"], errors="coerce"
        )
        valid_stock_count = int(len(latest_stock_flows))
        net_inflow_stock_count = int(
            latest_stock_flows["inst_net_flow"].map(_quantized_sign).gt(0).sum()
        )
        net_inflow_stock_ratio = (
            net_inflow_stock_count / valid_stock_count if valid_stock_count else np.nan
        )
        day_sign = directions[1][1]
        directional_pool = (
            latest_stock_flows["inst_net_flow"] * day_sign
        ).clip(lower=0)
        directional_denominator = float(directional_pool.sum())

        def top_share(count: int) -> float:
            if day_sign == 0 or directional_denominator <= 0:
                return float("nan")
            share = directional_pool.nlargest(count).sum() / directional_denominator
            return float(np.clip(share, 0.0, 1.0))

        top1_share = top_share(1)
        top3_share = top_share(3)
        top5_share = top_share(5)
        if day_sign > 0:
            if net_inflow_stock_ratio >= 0.60 and top3_share <= 0.50:
                diffusion_label = "普遍扩散"
            elif top3_share >= 0.70 or (
                net_inflow_stock_ratio < 0.40 and top3_share >= 0.60
            ):
                diffusion_label = "少数个股驱动"
            else:
                diffusion_label = "结构性流入"
        elif day_sign < 0:
            outflow_ratio = 1.0 - net_inflow_stock_ratio
            if outflow_ratio >= 0.60 and top3_share <= 0.50:
                diffusion_label = "普遍流出"
            elif top3_share >= 0.70:
                diffusion_label = "少数个股拖累"
            else:
                diffusion_label = "结构性流出"
        else:
            diffusion_label = "方向持平"
        records.append({
            code_column: industry_code, name_column: industry_name, "as_of": as_of,
            "horizon": horizon, "horizon_label": f"{horizon}日",
            "direction": direction, "direction_sign": direction_sign,
            "direction_1d": directions[1][0], "direction_1d_sign": directions[1][1],
            "direction_5d": directions[5][0], "direction_5d_sign": directions[5][1],
            "direction_20d": directions[20][0], "direction_20d_sign": directions[20][1],
            "flow_1d": flows[1], "flow_5d": flows[5], "flow_20d": flows[20],
            "amount_1d": amounts[1], "amount_5d": amounts[5], "amount_20d": amounts[20],
            "anomaly_z_1d": z_values[1], "anomaly_z_5d": z_values[5], "anomaly_z_20d": z_values[20],
            "anomaly_cold_start": cold_starts[horizon],
            "selected_flow_quantized": selected_flow_quantized,
            f"consistent_day_count_{horizon}d": consistent_day_count,
            f"persistence_ratio_{horizon}d": persistence_ratio,
            f"breadth_stock_count_{horizon}d": breadth_stock_count,
            f"consistent_stock_count_{horizon}d": consistent_stock_count,
            f"breadth_ratio_{horizon}d": breadth_ratio,
            "consistent_day_count": consistent_day_count,
            "persistence_ratio": persistence_ratio,
            "breadth_stock_count": breadth_stock_count,
            "consistent_stock_count": consistent_stock_count,
            "breadth_ratio": breadth_ratio,
            "base_strength": base_strength,
            "confirmation_score": confirmation_score,
            "confirmation_multiplier": confirmation_multiplier,
            "score_unrounded": score_unrounded,
            "valid_stock_count_1d": valid_stock_count,
            "net_inflow_stock_count_1d": net_inflow_stock_count,
            "net_inflow_stock_ratio_1d": net_inflow_stock_ratio,
            "top1_direction_contribution_1d": top1_share,
            "top3_direction_contribution_1d": top3_share,
            "top5_direction_contribution_1d": top5_share,
            "direction_contribution_side_1d": (
                "inflow" if day_sign > 0 else "outflow" if day_sign < 0 else "flat"
            ),
            "diffusion_label_1d": diffusion_label,
            "return_5d": _weighted_return(
                valid_work[valid_work[code_column].eq(industry_code)], 5
            ),
            "return_20d": _weighted_return(
                valid_work[valid_work[code_column].eq(industry_code)], 20
            ),
        })
        contributor_window = valid_work[
            valid_work[code_column].eq(industry_code)
            & valid_work["trade_date"].isin(dates[-horizon:])
        ]
        stock_flows = contributor_window.groupby("ts_code", as_index=False).agg(
            inst_net_flow=("inst_net_flow", lambda values: values.sum(min_count=1)),
            **({"stock_name": ("stock_name", "last")} if "stock_name" in contributor_window else {}),
        )
        direction_contribution = stock_flows["inst_net_flow"] * direction_sign
        denominator = float(direction_contribution.clip(lower=0).sum())
        stock_flows = stock_flows.assign(
            _direction_contribution=direction_contribution
        ).sort_values(
            ["_direction_contribution", "ts_code"],
            ascending=[False, True],
            kind="stable",
        ).head(5)
        stock_flows["contribution_rank"] = np.arange(1, len(stock_flows) + 1)
        stock_flows["contribution_share"] = (
            stock_flows["_direction_contribution"].clip(lower=0) / denominator
            if denominator
            else np.nan
        )
        stock_flows["contribution_share"] = stock_flows[
            "contribution_share"
        ].clip(lower=0, upper=1)
        stock_flows[code_column] = industry_code
        stock_flows[name_column] = industry_name
        contributor_frames.append(
            stock_flows[
                [
                    code_column,
                    name_column,
                    *(["stock_name"] if "stock_name" in stock_flows else []),
                    "ts_code",
                    "inst_net_flow",
                    "contribution_rank",
                    "contribution_share",
                ]
            ]
        )

    rankings = pd.DataFrame(records)
    # Keep supporting ratios for auditability.  Only selected-window
    # flow/turnover enters the score; market value, returns, and anomaly z do
    # not enter the formula or rank.
    latest_mv = latest_valid.groupby(code_column)["circ_mv"].sum()
    for period in LOOKBACKS:
        turnover = rankings[f"flow_{period}d"] / rankings[f"amount_{period}d"].replace(0, np.nan)
        rankings[f"flow_to_turnover_{period}d"] = turnover
        rankings[f"flow_to_mv_{period}d"] = rankings[f"flow_{period}d"] / rankings[code_column].map(latest_mv).replace(0, np.nan)
    rankings["anomaly_raw"] = rankings[f"anomaly_z_{horizon}d"]
    rankings["score"] = rankings["score_unrounded"].round(SCORE_ROUND_DECIMALS)
    # User-facing linear display scale.  The raw signed score remains the
    # authoritative formula and sorting key; this field preserves its sign,
    # zero, and complete order exactly.
    rankings["comprehensive_score"] = (
        rankings["score"] * COMPREHENSIVE_SCORE_SCALE
    )
    rankings = _deterministic_rank(rankings, code_column, horizon)
    contributors = pd.concat(contributor_frames, ignore_index=True) if contributor_frames else pd.DataFrame()
    quality: dict[str, int | str | float | bool] = {
        "as_of": as_of,
        "horizon": horizon,
        "horizon_label": f"{horizon}日",
        "available_trading_days": available_days,
        "minimum_trading_days": minimum_required_trading_days(lookback=horizon),
        "has_full_anomaly_history": available_days >= minimum_required_trading_days(lookback=horizon),
        "input_rows": int(len(frame)),
        "mapped_rows": int(len(mapped)),
        "effective_rows": int(len(valid_work)),
        "latest_stock_rows": int(len(latest_mapped)),
        "latest_effective_stock_rows": int(len(latest_valid)),
        "latest_missing_flow_rate": float(
            latest_mapped["inst_net_flow"].isna().mean()
        ),
        "latest_missing_amount_rate": float(latest_mapped["amount"].isna().mean()),
        "latest_missing_market_value_rate": float(
            latest_mapped["circ_mv"].isna().mean()
        ),
        "minimum_l2_valid_stocks": MIN_L2_VALID_STOCKS,
        "eligible_industry_count": int(len(rankings)),
        "excluded_small_sample_industry_count": int(len(excluded_industries)),
        "excluded_small_sample_industries": (
            "|".join(
                f"{getattr(row, name_column)}({int(row.valid_stock_count)})"
                for row in excluded_industries.itertuples(index=False)
            )
            if level == "l2"
            else ""
        ),
        "market_flow_1d": float(rankings["flow_1d"].sum(min_count=1)),
        "market_flow_5d": float(rankings["flow_5d"].sum(min_count=1)),
        "market_flow_20d": float(rankings["flow_20d"].sum(min_count=1)),
        "positive_flow_5d_industry_count": int((rankings["direction_5d_sign"] > 0).sum()),
        "positive_flow_20d_industry_count": int((rankings["direction_20d_sign"] > 0).sum()),
        "positive_flow_industry_count": int((rankings["direction_sign"] > 0).sum()),
        "scoring_formula": "S_H=(flow_H/amount_H)*exp[-0.3*(1-(0.35*P_H+0.65*P_B))]",
        "persistence_weight": PERSISTENCE_WEIGHT,
        "breadth_weight": BREADTH_WEIGHT,
        "confirmation_decay": CONFIRMATION_DECAY,
        "comprehensive_score_scale": COMPREHENSIVE_SCORE_SCALE,
        "comprehensive_score_formula": "comprehensive_score=10000*S_H",
        "minimum_confirmation_multiplier": float(np.exp(-CONFIRMATION_DECAY)),
        "zero_direction_policy": "if quantized flow_H is zero, P_H=P_B=0 and S_H=0",
        "score_round_decimals": SCORE_ROUND_DECIMALS,
        "flow_tie_round_decimals": FLOW_TIE_ROUND_DECIMALS,
        "rank_tie_break": (
            "score, base_strength, selected-window flow, 5d flow, 1d flow, "
            "industry code; numeric keys quantized at documented decimals"
        ),
        "flow_semantics": (
            "large+extra-large active buy amount minus active sell amount; "
            "not real institution identity, holdings, or holding changes"
        ),
        "contribution_denominator": (
            "same-direction positive pool; never the net industry flow"
        ),
    }
    for source_key in ("source_window_start", "source_window_end", "source_request_count", "source_coverage_rate"):
        if source_key in frame.columns:
            supplied = frame[source_key].dropna()
            if not supplied.empty:
                value = supplied.iloc[-1]
                quality[source_key] = value.item() if hasattr(value, "item") else value
    return RadarResult(
        rankings=rankings,
        contributors=contributors,
        daily_flows=daily.copy(),
        quality=quality,
    )
