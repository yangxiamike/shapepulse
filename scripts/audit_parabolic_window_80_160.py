from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api

from build_template_statistical_validation import (
    PROJECT_ROOT,
    ZERO_CONFIG,
    ZERO_ROOT,
    build_series,
    load_market_data,
    load_stock_metadata,
    z_log,
)


SOURCE_TS_CODE = "001309.SZ"
SOURCE_NAME = "德明利"
ORIGINAL_START = "20251031"
ORIGINAL_END = "20260630"
ORIGINAL_BARS = 160
AUDIT_BARS = 80
EXPECTED_SELECTED_START = "20260115"
EXPECTED_SELECTED_END = "20260520"
TOP_KS = (30, 100)
RECENT_DAYS = 60
STABILITY_LAGS = (1, 5, 10)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "parabolic-window-audit-20260730"
)


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    start: str
    end: str
    bars: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="完成计算和校验，但不写文件。",
    )
    return parser.parse_args()


def safe_number(value: object, digits: int = 8) -> float | None:
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def shape_metrics(
    frame: pd.DataFrame,
    *,
    label: str,
    key: str,
) -> dict[str, object]:
    ordered = frame.sort_values("trade_date").reset_index(drop=True)
    close = ordered["qfq_close"].to_numpy(dtype=float)
    if len(close) < 4 or np.any(close <= 0):
        raise ValueError(f"{label} 没有足够的正价格")
    logged = np.log(close)
    x = np.linspace(-1.0, 1.0, len(logged))
    quadratic = np.polyfit(x, logged, 2)
    fitted = np.polyval(quadratic, x)
    total_variation = float(np.sum((logged - logged.mean()) ** 2))
    quadratic_r2 = (
        1.0 - float(np.sum((logged - fitted) ** 2)) / total_variation
        if total_variation > 1e-16
        else 0.0
    )
    split = len(logged) // 2
    first_slope = float(
        np.polyfit(np.arange(split, dtype=float), logged[:split], 1)[0]
    )
    second_slope = float(
        np.polyfit(
            np.arange(len(logged) - split, dtype=float),
            logged[split:],
            1,
        )[0]
    )
    peak = np.maximum.accumulate(close)
    drawdown = close / peak - 1.0
    return {
        "key": key,
        "label": label,
        "start_date": str(ordered.iloc[0]["trade_date"]),
        "end_date": str(ordered.iloc[-1]["trade_date"]),
        "bars": int(len(ordered)),
        "return_pct": safe_number((close[-1] / close[0] - 1.0) * 100.0, 6),
        "quadratic_coefficient": safe_number(quadratic[0], 10),
        "quadratic_fit_r2": safe_number(quadratic_r2, 10),
        "first_half_log_slope_bp_per_bar": safe_number(
            first_slope * 10_000.0, 6
        ),
        "second_half_log_slope_bp_per_bar": safe_number(
            second_slope * 10_000.0, 6
        ),
        "slope_delta_bp_per_bar": safe_number(
            (second_slope - first_slope) * 10_000.0, 6
        ),
        "max_drawdown_pct": safe_number(float(drawdown.min()) * 100.0, 6),
        "positive_bar_share": safe_number(
            float(np.mean(np.diff(logged) > 0.0)), 8
        ),
    }


def select_eighty_bar_window(
    original: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for start in range(len(original) - AUDIT_BARS + 1):
        frame = original.iloc[start : start + AUDIT_BARS].copy()
        metric = shape_metrics(
            frame,
            label=f"80 根候选 {start + 1}",
            key=f"candidate_{start:03d}",
        )
        metric["offset_in_160"] = start
        metric["eligible_stage_window"] = bool(
            float(metric["quadratic_coefficient"]) > 0.0
            and float(metric["first_half_log_slope_bp_per_bar"]) > 0.0
            and float(metric["second_half_log_slope_bp_per_bar"])
            > float(metric["first_half_log_slope_bp_per_bar"])
        )
        rows.append(metric)
    candidates = pd.DataFrame(rows)
    eligible = candidates[candidates["eligible_stage_window"]].copy()
    if eligible.empty:
        raise RuntimeError("160 根源窗口内没有满足正斜率、正曲率和斜率放大的 80 根窗口")
    chosen_row = eligible.sort_values(
        ["quadratic_fit_r2", "quadratic_coefficient", "start_date"],
        ascending=[False, False, True],
    ).iloc[0]
    chosen_start = str(chosen_row["start_date"])
    chosen_end = str(chosen_row["end_date"])
    if (
        chosen_start != EXPECTED_SELECTED_START
        or chosen_end != EXPECTED_SELECTED_END
    ):
        raise RuntimeError(
            "80 根选择结果漂移："
            f"{chosen_start}–{chosen_end}，"
            f"预期 {EXPECTED_SELECTED_START}–{EXPECTED_SELECTED_END}"
        )
    candidates["selected"] = (
        (candidates["start_date"] == chosen_start)
        & (candidates["end_date"] == chosen_end)
    )
    chosen = original[
        (original["trade_date"].astype(str) >= chosen_start)
        & (original["trade_date"].astype(str) <= chosen_end)
    ].copy()
    if len(chosen) != AUDIT_BARS:
        raise RuntimeError(f"选定窗口应有 {AUDIT_BARS} 根，实际 {len(chosen)} 根")
    return chosen, candidates


def rolling_scores_recent(
    *,
    series: dict[str, dict],
    stocks: pd.DataFrame,
    template_z: np.ndarray,
    bars: int,
    target_dates: tuple[str, ...],
) -> pd.DataFrame:
    metadata = stocks.set_index("ts_code")[
        ["list_date", "delist_date"]
    ].to_dict("index")
    target = np.asarray(target_dates, dtype=str)
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
        standard_deviation = np.sqrt(variance)
        dots = np.correlate(logged, template_z, mode="valid")
        scores = np.divide(
            dots,
            bars * standard_deviation,
            out=np.zeros_like(dots),
            where=standard_deviation > 1e-12,
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
            np.isin(score_dates, target)
            & (score_dates >= listed)
            & (score_dates < delisted)
        )
        if np.any(keep):
            rows.append(
                pd.DataFrame(
                    {
                        "trade_date": score_dates[keep],
                        "ts_code": str(code),
                        "score": scores[keep],
                    }
                )
            )
    if not rows:
        raise RuntimeError(f"{bars} 根逐日相似度为空")
    result = pd.concat(rows, ignore_index=True)
    if not result["score"].between(-1 - 1e-8, 1 + 1e-8).all():
        raise RuntimeError(f"{bars} 根 Pearson 分数超出 [-1, 1]")
    return result


def ranked_by_date(scores: pd.DataFrame) -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for current, frame in scores.groupby("trade_date", sort=True):
        ranked = frame.sort_values(
            ["score", "ts_code"], ascending=[False, True]
        ).reset_index(drop=True)
        ranked["rank"] = np.arange(1, len(ranked) + 1)
        output[str(current)] = ranked
    return output


def rank_correlation(
    left: pd.DataFrame,
    right: pd.DataFrame,
    codes: set[str],
) -> float | None:
    if len(codes) < 3:
        return None
    left_rank = left[left["ts_code"].isin(codes)].set_index("ts_code")["rank"]
    right_rank = right[right["ts_code"].isin(codes)].set_index("ts_code")["rank"]
    joined = pd.concat(
        [left_rank.rename("left"), right_rank.rename("right")],
        axis=1,
        join="inner",
    )
    if len(joined) < 3:
        return None
    left_order = joined["left"].rank(method="average").to_numpy(dtype=float)
    right_order = joined["right"].rank(method="average").to_numpy(dtype=float)
    value = float(np.corrcoef(left_order, right_order)[0, 1])
    return value if math.isfinite(value) else None


def compare_variants_daily(
    rankings: dict[str, dict[str, pd.DataFrame]],
    dates: tuple[str, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for current in dates:
        left = rankings["selected_80"][current]
        right = rankings["original_160"][current]
        row: dict[str, object] = {
            "trade_date": current,
            "eligible_80": int(len(left)),
            "eligible_160": int(len(right)),
        }
        all_common = set(left["ts_code"]) & set(right["ts_code"])
        row["all_eligible_rank_spearman"] = rank_correlation(
            left, right, all_common
        )
        for top_k in TOP_KS:
            left_codes = set(left.head(top_k)["ts_code"])
            right_codes = set(right.head(top_k)["ts_code"])
            common = left_codes & right_codes
            union = left_codes | right_codes
            row[f"top{top_k}_overlap_count"] = int(len(common))
            row[f"top{top_k}_overlap_share"] = len(common) / top_k
            row[f"top{top_k}_jaccard"] = (
                len(common) / len(union) if union else 0.0
            )
            row[f"top{top_k}_common_rank_spearman"] = rank_correlation(
                left, right, common
            )
        rows.append(row)
    return pd.DataFrame(rows)


def temporal_stability(
    rankings: dict[str, dict[str, pd.DataFrame]],
    dates: tuple[str, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations: list[dict[str, object]] = []
    for variant, by_date in rankings.items():
        for lag in STABILITY_LAGS:
            for index in range(lag, len(dates)):
                previous_date = dates[index - lag]
                current_date = dates[index]
                previous = by_date[previous_date]
                current = by_date[current_date]
                previous_codes = set(previous.head(100)["ts_code"])
                current_codes = set(current.head(100)["ts_code"])
                common = previous_codes & current_codes
                union = previous_codes | current_codes
                observations.append(
                    {
                        "variant": variant,
                        "lag_trading_days": lag,
                        "previous_date": previous_date,
                        "current_date": current_date,
                        "top100_overlap_count": len(common),
                        "top100_jaccard": (
                            len(common) / len(union) if union else 0.0
                        ),
                        "common_rank_spearman": rank_correlation(
                            previous, current, common
                        ),
                    }
                )
    detail = pd.DataFrame(observations)
    summary = (
        detail.groupby(["variant", "lag_trading_days"], sort=True)
        .agg(
            observations=("current_date", "size"),
            overlap_mean=("top100_overlap_count", "mean"),
            overlap_median=("top100_overlap_count", "median"),
            overlap_min=("top100_overlap_count", "min"),
            jaccard_mean=("top100_jaccard", "mean"),
            jaccard_median=("top100_jaccard", "median"),
            jaccard_min=("top100_jaccard", "min"),
            common_rank_spearman_mean=("common_rank_spearman", "mean"),
            common_rank_spearman_median=("common_rank_spearman", "median"),
        )
        .reset_index()
    )
    return detail, summary


def candidate_window(
    item: dict,
    *,
    as_of: str,
    bars: int,
) -> pd.DataFrame:
    dates = np.asarray(item["dates"], dtype=str)
    positions = np.flatnonzero(dates == as_of)
    if not len(positions):
        raise RuntimeError(f"{as_of} 没有候选 K 线")
    end = int(positions[-1])
    start = end - bars + 1
    if start < 0:
        raise RuntimeError(f"{as_of} 候选窗口不足 {bars} 根")
    return item["frame"].iloc[start : end + 1].copy()


def latest_candidate_metrics(
    *,
    rankings: dict[str, dict[str, pd.DataFrame]],
    variants: dict[str, Variant],
    series: dict[str, dict],
    names: dict[str, str],
    as_of: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for variant_key, variant in variants.items():
        ranked = rankings[variant_key][as_of].head(100)
        for row in ranked.itertuples(index=False):
            code = str(row.ts_code)
            frame = candidate_window(
                series[code], as_of=as_of, bars=variant.bars
            )
            metric = shape_metrics(
                frame,
                label=names.get(code, code),
                key=code,
            )
            rows.append(
                {
                    "variant": variant_key,
                    "window_bars": variant.bars,
                    "rank": int(row.rank),
                    "ts_code": code,
                    "name": names.get(code, code),
                    "score": float(row.score),
                    "window_start": str(frame.iloc[0]["trade_date"]),
                    "window_end": str(frame.iloc[-1]["trade_date"]),
                    "return_pct": metric["return_pct"],
                    "quadratic_coefficient": metric[
                        "quadratic_coefficient"
                    ],
                    "quadratic_fit_r2": metric["quadratic_fit_r2"],
                    "first_half_log_slope_bp_per_bar": metric[
                        "first_half_log_slope_bp_per_bar"
                    ],
                    "second_half_log_slope_bp_per_bar": metric[
                        "second_half_log_slope_bp_per_bar"
                    ],
                    "slope_delta_bp_per_bar": metric[
                        "slope_delta_bp_per_bar"
                    ],
                    "max_drawdown_pct": metric["max_drawdown_pct"],
                }
            )
    return pd.DataFrame(rows)


def summarize_latest_candidate_shapes(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for variant, group in frame.groupby("variant", sort=True):
        rows.append(
            {
                "variant": str(variant),
                "rows": int(len(group)),
                "score_median": float(group["score"].median()),
                "score_min": float(group["score"].min()),
                "return_pct_median": float(group["return_pct"].median()),
                "quadratic_coefficient_median": float(
                    group["quadratic_coefficient"].median()
                ),
                "quadratic_fit_r2_median": float(
                    group["quadratic_fit_r2"].median()
                ),
                "positive_acceleration_share": float(
                    (
                        group["slope_delta_bp_per_bar"].astype(float) > 0.0
                    ).mean()
                ),
                "positive_both_halves_and_acceleration_share": float(
                    (
                        (
                            group[
                                "first_half_log_slope_bp_per_bar"
                            ].astype(float)
                            > 0.0
                        )
                        & (
                            group[
                                "second_half_log_slope_bp_per_bar"
                            ].astype(float)
                            > group[
                                "first_half_log_slope_bp_per_bar"
                            ].astype(float)
                        )
                    ).mean()
                ),
                "max_drawdown_pct_median": float(
                    group["max_drawdown_pct"].median()
                ),
            }
        )
    return pd.DataFrame(rows)


def to_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return json.loads(
        frame.replace({np.nan: None}).to_json(
            orient="records", force_ascii=False
        )
    )


def build_report(summary: dict[str, object]) -> str:
    shape = {
        row["key"]: row
        for row in summary["templateShapeMetrics"]  # type: ignore[index]
    }
    original = shape["original_160"]
    last = shape["mechanical_last_80"]
    selected = shape["selected_80"]
    latest = summary["latestCrossWindow"]  # type: ignore[index]
    stability = summary["temporalStability"]  # type: ignore[index]
    candidate_shapes = {
        row["variant"]: row
        for row in summary["latestCandidateShapeSummary"]  # type: ignore[index]
    }

    def stability_row(variant: str, lag: int) -> dict[str, object]:
        return next(
            row
            for row in stability
            if row["variant"] == variant
            and int(row["lag_trading_days"]) == lag
        )

    lines = [
        "# 抛物线上升模板 80/160 根形态口径审计",
        "",
        "## 结论",
        "",
        (
            f"- 支持把冻结模板从 160 根收敛到真实 80 根 "
            f"`{EXPECTED_SELECTED_START}`–`{EXPECTED_SELECTED_END}`。"
            "选择只使用德明利原冻结窗口内部 K 线的阶段形态，不使用候选股票后续收益、"
            "IC、策略表现或跨模板综合排名。"
        ),
        (
            f"- 原 160 根中，最大回撤为 {original['max_drawdown_pct']:.2f}%，"
            f"两半段 log 斜率为 "
            f"{original['first_half_log_slope_bp_per_bar']:.2f}→"
            f"{original['second_half_log_slope_bp_per_bar']:.2f} bp/根；"
            "它能表达“长平台后加速”，但把较长非加速阶段一起纳入相似度。"
        ),
        (
            f"- 机械截取截至 20260630 的末 80 根并不合适：两半段斜率 "
            f"{last['first_half_log_slope_bp_per_bar']:.2f}→"
            f"{last['second_half_log_slope_bp_per_bar']:.2f} bp/根，"
            f"二次项 {last['quadratic_coefficient']:.4f}，表现为高速后减速。"
        ),
        (
            f"- 选定 80 根两半段斜率 "
            f"{selected['first_half_log_slope_bp_per_bar']:.2f}→"
            f"{selected['second_half_log_slope_bp_per_bar']:.2f} bp/根，"
            f"正二次项 {selected['quadratic_coefficient']:.4f}，"
            f"二次拟合 R^2 {selected['quadratic_fit_r2']:.3f}；"
            "更集中表达斜率放大的加速阶段。"
        ),
        "",
        "## 候选窗口与排名差异",
        "",
        (
            f"- 最新截面 Top30 重合 {latest['top30_overlap_count']} 只"
            f"（{latest['top30_overlap_share']:.1%}），Top100 重合 "
            f"{latest['top100_overlap_count']} 只"
            f"（{latest['top100_overlap_share']:.1%}）。"
        ),
        (
            "- 这只说明窗口长度改变了当前形态检索对象，不能解释未来有效性，"
            "也不能推导市场是否存在抛物线行情。"
        ),
        (
            "- 最新 Top100 中，满足“两半段斜率均正且后半段更快”的候选占比："
            f"选定 80 根 {candidate_shapes['selected_80']['positive_both_halves_and_acceleration_share']:.1%}，"
            f"原 160 根 {candidate_shapes['original_160']['positive_both_halves_and_acceleration_share']:.1%}。"
            "固定 Top100 会在供给偏弱时仍排满，短窗当前榜单的严格加速形态更少；"
            "这是窗口内形态描述和口径局限，不是后续表现。"
        ),
        "",
        "## Top100 跨日稳定性",
        "",
        "| 窗口 | 间隔 | 平均重合只数 | 平均 Jaccard |",
        "| --- | ---: | ---: | ---: |",
    ]
    for lag in STABILITY_LAGS:
        for variant in ("selected_80", "original_160"):
            row = stability_row(variant, lag)
            label = "选定 80 根" if variant == "selected_80" else "原 160 根"
            lines.append(
                f"| {label} | {lag} 日 | {row['overlap_mean']:.2f} | "
                f"{row['jaccard_mean']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## 冻结口径与泄漏边界",
            "",
            "- 前复权 `log(close)`；模板与候选窗口各自独立 z；单窗口 Pearson。",
            "- 每个窗口方案独立排序，不跨模板综合。",
            "- 80 根选择规则：在原 160 根内枚举连续 80 根；要求二次项为正、"
            "前半段斜率为正、后半段斜率大于前半段；再按窗口内二次拟合 R^2、"
            "二次项和起始日确定唯一结果。",
            "- 未读取 sealed final，未联网，未使用未来收益、IC 或策略表现。",
            "",
            "## 局限",
            "",
            "- 这是形态阶段与排名敏感性审计，不是预测有效性检验。",
            "- 80 根来自单一真实样本，仍保留该样本自身约 20% 的窗口内回撤。",
            "- 80 根 Top100 的 1/5/10 日成员稳定性都低于 160 根，说明短窗更敏感；"
            "排名稳定性只描述相邻截面的成员变化，不代表策略稳定性或收益。",
            "- 最新固定 Top100 中，80 根严格加速形态占比低于 160 根；"
            "因此交付仍须展示真实候选 K 线，不能只凭名次宣称匹配纯度更高。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError("输出必须位于工作区")
    if not args.dry_run and output.exists():
        raise RuntimeError(f"拒绝覆盖现有审计输出：{output}")

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        market, as_of = load_market_data(pro)
        stocks = load_stock_metadata(pro)
    finally:
        os.chdir(previous_cwd)

    source = market[
        (market["ts_code"] == SOURCE_TS_CODE)
        & (market["trade_date"] >= ORIGINAL_START)
        & (market["trade_date"] <= ORIGINAL_END)
    ].sort_values("trade_date")
    if (
        len(source) != ORIGINAL_BARS
        or str(source.iloc[0]["trade_date"]) != ORIGINAL_START
        or str(source.iloc[-1]["trade_date"]) != ORIGINAL_END
    ):
        raise RuntimeError("原 160 根冻结窗口与本地真实 K 线不一致")

    selected, candidates = select_eighty_bar_window(source)
    variants = {
        "selected_80": Variant(
            "selected_80",
            "选定 80 根",
            EXPECTED_SELECTED_START,
            EXPECTED_SELECTED_END,
            AUDIT_BARS,
        ),
        "original_160": Variant(
            "original_160",
            "原 160 根",
            ORIGINAL_START,
            ORIGINAL_END,
            ORIGINAL_BARS,
        ),
    }
    shape_frames = [
        shape_metrics(
            source,
            label="原 160 根",
            key="original_160",
        ),
        shape_metrics(
            source.head(AUDIT_BARS),
            label="原窗口前 80 根",
            key="mechanical_first_80",
        ),
        shape_metrics(
            source.tail(AUDIT_BARS),
            label="原窗口末 80 根",
            key="mechanical_last_80",
        ),
        shape_metrics(
            selected,
            label="选定加速阶段 80 根",
            key="selected_80",
        ),
    ]

    all_dates = tuple(sorted(market["trade_date"].astype(str).unique()))
    needed_days = RECENT_DAYS + max(STABILITY_LAGS)
    target_dates = all_dates[-needed_days:]
    report_dates = target_dates[-RECENT_DAYS:]
    series = build_series(market)
    rankings: dict[str, dict[str, pd.DataFrame]] = {}
    for key, variant in variants.items():
        template_frame = market[
            (market["ts_code"] == SOURCE_TS_CODE)
            & (market["trade_date"] >= variant.start)
            & (market["trade_date"] <= variant.end)
        ].sort_values("trade_date")
        if len(template_frame) != variant.bars:
            raise RuntimeError(
                f"{variant.label} 预期 {variant.bars} 根，实际 {len(template_frame)}"
            )
        scores = rolling_scores_recent(
            series=series,
            stocks=stocks,
            template_z=z_log(template_frame["qfq_close"].to_numpy(float)),
            bars=variant.bars,
            target_dates=target_dates,
        )
        rankings[key] = ranked_by_date(scores)
        missing_dates = set(target_dates) - set(rankings[key])
        if missing_dates:
            raise RuntimeError(
                f"{variant.label} 缺少截面：{sorted(missing_dates)}"
            )

    cross_window = compare_variants_daily(rankings, report_dates)
    stability_detail, stability_summary = temporal_stability(
        rankings, target_dates
    )
    names = stocks.set_index("ts_code")["name"].astype(str).to_dict()
    candidates_latest = latest_candidate_metrics(
        rankings=rankings,
        variants=variants,
        series=series,
        names=names,
        as_of=as_of,
    )
    candidate_shape_summary = summarize_latest_candidate_shapes(
        candidates_latest
    )

    latest_cross = cross_window[
        cross_window["trade_date"] == as_of
    ].iloc[0].to_dict()
    selection_rule = (
        "在原160根内枚举连续80根；要求二次项>0、前半段log斜率>0、"
        "后半段log斜率>前半段；再按窗口内二次拟合R^2、二次项、起始日排序。"
    )
    leakage_audit = {
        "data_source": str(ZERO_ROOT),
        "local_interfaces": ["daily", "adj_factor", "stock_basic"],
        "network_used": False,
        "sealed_final_read": False,
        "future_return_used": False,
        "ic_used": False,
        "strategy_performance_used": False,
        "post_window_return_used_for_selection": False,
        "selection_uses_only_in_window_bars": True,
        "algorithm": "前复权 log-close；窗口内独立 z；单窗口 Pearson",
        "cross_template_ranking_used": False,
    }
    summary = {
        "pass": True,
        "asOf": as_of,
        "source": {
            "ts_code": SOURCE_TS_CODE,
            "name": SOURCE_NAME,
            "original_start": ORIGINAL_START,
            "original_end": ORIGINAL_END,
            "original_bars": ORIGINAL_BARS,
        },
        "selected": asdict(variants["selected_80"]),
        "selectionRule": selection_rule,
        "templateShapeMetrics": shape_frames,
        "latestCrossWindow": {
            key: safe_number(value, 10)
            if isinstance(value, (float, np.floating))
            else value
            for key, value in latest_cross.items()
        },
        "crossWindowDailySummary": {
            column: safe_number(cross_window[column].mean(), 10)
            for column in (
                "top30_overlap_count",
                "top30_overlap_share",
                "top30_jaccard",
                "top100_overlap_count",
                "top100_overlap_share",
                "top100_jaccard",
                "all_eligible_rank_spearman",
            )
        },
        "temporalStability": to_records(stability_summary),
        "latestCandidateShapeSummary": to_records(candidate_shape_summary),
        "latestCandidateRows": int(len(candidates_latest)),
        "leakageAudit": leakage_audit,
    }
    report = build_report(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.dry_run:
        return

    output.mkdir(parents=True)
    pd.DataFrame(shape_frames).to_csv(
        output / "template_shape_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    candidates.to_csv(
        output / "eighty_bar_window_scan.csv",
        index=False,
        encoding="utf-8-sig",
    )
    cross_window.to_csv(
        output / "cross_window_ranking_daily.csv",
        index=False,
        encoding="utf-8-sig",
    )
    stability_detail.to_csv(
        output / "top100_temporal_stability_daily.csv",
        index=False,
        encoding="utf-8-sig",
    )
    stability_summary.to_csv(
        output / "top100_temporal_stability_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    candidates_latest.to_csv(
        output / "latest_top100_candidate_shape_metrics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    candidate_shape_summary.to_csv(
        output / "latest_top100_candidate_shape_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output / "audit-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "leakage-audit.json").write_text(
        json.dumps(leakage_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "audit-report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
