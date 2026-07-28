from __future__ import annotations

from typing import Any


TOP_N = 100
LOOKBACK_TRADING_DAYS = 120
SAMPLE_EVERY = 5
SAMPLE_COUNT = 24
DEFAULT_VISIBLE_INDUSTRIES = 12
RECENT_WINDOW_POINTS = 4
MIN_DIRECTIONAL_SLOTS = 4
RAPID_START_DELTA = 3
SLOPE_EPSILON = 0.25


def fixed_sample_dates(trade_dates: list[str]) -> list[str]:
    """Return the 24 fixed five-trading-day samples ending at the latest date."""
    dates = sorted(dict.fromkeys(str(value) for value in trade_dates if value))
    window = dates[-LOOKBACK_TRADING_DAYS:]
    return window[4::SAMPLE_EVERY]


def latest_first(values: list[Any]) -> list[Any]:
    """Return a copy ordered newest-to-oldest for the heatmap reading direction."""
    return list(reversed(values))


def heat_level(percent: float) -> int:
    """Map the visible heat scale to the frozen 0/1-2/3-4/5-7/8-10/>10 bands."""
    if percent <= 0:
        return 0
    if percent <= 2:
        return 1
    if percent <= 4:
        return 2
    if percent <= 7:
        return 3
    if percent <= 10:
        return 4
    return 5


def recent_slope(counts: list[int]) -> float:
    """Return the least-squares slope of the latest four sample points."""
    values = [float(value) for value in counts[-RECENT_WINDOW_POINTS:]]
    if len(values) < 2:
        return 0.0
    x_mean = (len(values) - 1) / 2
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    if denominator == 0:
        return 0.0
    y_mean = sum(values) / len(values)
    slope = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in enumerate(values)
    ) / denominator
    return round(slope, 2)


def recent_persistence(counts: list[int], slope: float | None = None) -> float:
    """Share of recent intervals moving in the same direction as the slope."""
    values = counts[-RECENT_WINDOW_POINTS:]
    if len(values) < 2:
        return 0.0
    resolved_slope = recent_slope(values) if slope is None else slope
    if abs(resolved_slope) < SLOPE_EPSILON:
        return 0.0
    deltas = [current - previous for previous, current in zip(values, values[1:])]
    matching = sum(
        delta > 0 if resolved_slope > 0 else delta < 0
        for delta in deltas
    )
    return round(matching / len(deltas), 2)


def _latest_effective_count(row: dict[str, Any]) -> int:
    return next(
        (
            int(value)
            for value in reversed(row["counts"][-RECENT_WINDOW_POINTS:])
            if int(value) > 0
        ),
        0,
    )


def rotation_observation_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Stable activity order: speed, persistence, effective level, then code."""
    return (
        -abs(float(row["recent_slope"])),
        -float(row["recent_persistence"]),
        -_latest_effective_count(row),
        str(row["code"]),
    )


def select_active_industries(
    rows: list[dict[str, Any]],
    limit: int = DEFAULT_VISIBLE_INDUSTRIES,
) -> list[dict[str, Any]]:
    """Choose active rows while reserving both rising and falling observations."""
    eligible = [
        row
        for row in rows
        if any(int(value) != 0 for value in row["counts"][-RECENT_WINDOW_POINTS:])
    ]
    rising = sorted(
        (row for row in eligible if row["recent_slope"] >= SLOPE_EPSILON),
        key=rotation_observation_key,
    )
    falling = sorted(
        (row for row in eligible if row["recent_slope"] <= -SLOPE_EPSILON),
        key=rotation_observation_key,
    )
    selected: list[dict[str, Any]] = []
    selected_codes: set[str] = set()

    def append(row: dict[str, Any]) -> None:
        if row["code"] not in selected_codes and len(selected) < limit:
            selected.append(row)
            selected_codes.add(row["code"])

    for row in rising[:MIN_DIRECTIONAL_SLOTS]:
        append(row)
    for row in falling[:MIN_DIRECTIONAL_SLOTS]:
        append(row)
    for row in sorted(eligible, key=rotation_observation_key):
        append(row)

    return sorted(
        selected,
        key=lambda row: (
            -float(row["recent_slope"]),
            -float(row["recent_persistence"]),
            -_latest_effective_count(row),
            str(row["code"]),
        ),
    )


def industry_status(
    counts: list[int],
    current_rank: int,
    slope: float | None = None,
    persistence: float | None = None,
) -> str:
    if not counts:
        return "暂无数据"
    current = counts[-1]
    previous = counts[-2] if len(counts) > 1 else 0
    resolved_slope = recent_slope(counts) if slope is None else slope
    resolved_persistence = (
        recent_persistence(counts, resolved_slope)
        if persistence is None
        else persistence
    )
    if (
        resolved_slope >= SLOPE_EPSILON
        and previous <= 1
        and current - previous >= RAPID_START_DELTA
    ):
        return "↗ 快速启动"
    if resolved_slope >= SLOPE_EPSILON and resolved_persistence >= 0.66:
        return "↑ 持续增强"
    if resolved_slope >= SLOPE_EPSILON:
        return "↑ 正在增强"
    if (
        current_rank <= 5
        and resolved_slope <= -SLOPE_EPSILON
        and max(counts[-RECENT_WINDOW_POINTS:]) > current
    ):
        return "⇣ 高位退潮"
    if resolved_slope <= -SLOPE_EPSILON:
        return "↓ 正在走弱"
    return "→ 变化不大"


def build_industry_strength(
    *,
    pattern: str,
    pattern_label: str,
    requested_end_date: str | None,
    sample_dates: list[str],
    industries: list[dict[str, str]],
    top_by_date: dict[str, list[dict[str, Any]]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    if not sample_dates:
        raise ValueError("没有足够的真实交易日可生成行业强弱截面")

    catalog = {
        str(item["code"]): {
            "code": str(item["code"]),
            "name": str(item["name"]),
        }
        for item in industries
    }
    by_industry: dict[str, dict[str, list[dict[str, Any]]]] = {
        code: {date: [] for date in sample_dates} for code in catalog
    }
    missing_industry_by_date: dict[str, int] = {}
    actual_top_by_date: dict[str, int] = {}

    for date in sample_dates:
        selected = list(top_by_date.get(date, []))[:TOP_N]
        actual_top_by_date[date] = len(selected)
        missing = 0
        for stock in selected:
            industry_code = str(stock.get("industry_code") or "")
            if industry_code not in catalog:
                missing += 1
                continue
            by_industry[industry_code][date].append(
                {
                    "ts_code": str(stock.get("ts_code") or ""),
                    "code": str(stock.get("ts_code") or "").split(".")[0],
                    "name": str(stock.get("name") or stock.get("ts_code") or ""),
                    "score": round(float(stock.get("score") or 0), 2),
                }
            )
        missing_industry_by_date[date] = missing

    rows: list[dict[str, Any]] = []
    latest_date = sample_dates[-1]
    previous_date = sample_dates[-2] if len(sample_dates) > 1 else latest_date
    recent_start_date = (
        sample_dates[-RECENT_WINDOW_POINTS]
        if len(sample_dates) >= RECENT_WINDOW_POINTS
        else sample_dates[0]
    )
    for code, item in catalog.items():
        points = []
        counts: list[int] = []
        for date_index, date in enumerate(sample_dates):
            stocks = by_industry[code][date]
            count = len(stocks)
            counts.append(count)
            points.append(
                {
                    "date": date,
                    "count": count,
                    "percent": float(count),
                    "heat_level": heat_level(float(count)),
                    "change": count - (
                        len(by_industry[code][sample_dates[date_index - 1]])
                        if date_index > 0
                        else 0
                    ),
                    "stocks": stocks,
                }
            )
        slope = recent_slope(counts)
        persistence = recent_persistence(counts, slope)
        current_count = len(by_industry[code][latest_date])
        recent_change = current_count - len(by_industry[code][recent_start_date])
        rows.append(
            {
                **item,
                "points": points,
                "counts": counts,
                "current_count": current_count,
                "current_percent": float(current_count),
                "change_previous": current_count
                - len(by_industry[code][previous_date]),
                "change_four_samples": recent_change,
                "recent_change": recent_change,
                "recent_slope": slope,
                "recent_persistence": persistence,
                "latest_effective_percent": float(
                    next((value for value in reversed(counts[-RECENT_WINDOW_POINTS:]) if value > 0), 0)
                ),
                "cumulative_count": sum(counts),
                "stocks": by_industry[code][latest_date],
            }
        )

    current_sorted = sorted(
        rows,
        key=lambda row: (
            -row["current_count"],
            -row["cumulative_count"],
            row["code"],
        ),
    )
    for current_rank, row in enumerate(current_sorted, 1):
        row["rank"] = current_rank
        row["current_rank"] = current_rank
        row["status"] = industry_status(
            row["counts"],
            current_rank,
            row["recent_slope"],
            row["recent_persistence"],
        )
        row["status_detail"] = (
            f"{row['recent_slope']:+.2f} 只/采样点 · "
            f"{round(row['recent_persistence'] * 3):.0f}/3 个间隔同向"
        )

    rotation_ranking = sorted(rows, key=rotation_observation_key)
    for rotation_rank, row in enumerate(rotation_ranking, 1):
        row["rotation_rank"] = rotation_rank

    all_heatmap_rows = sorted(
        rows,
        key=lambda row: (
            -float(row["recent_slope"]),
            -float(row["recent_persistence"]),
            -_latest_effective_count(row),
            str(row["code"]),
        ),
    )
    selected_rows = select_active_industries(rows)
    default_visible_codes = [row["code"] for row in selected_rows]
    visible_set = set(default_visible_codes)
    hidden_rows = [row for row in rows if row["code"] not in visible_set]

    active = [row for row in current_sorted if row["current_count"] > 0]
    strongest = active[0] if active else None
    rising = [row for row in rows if row["recent_slope"] >= SLOPE_EPSILON]
    falling = [row for row in rows if row["recent_slope"] <= -SLOPE_EPSILON]
    strongest_gain = min(rising, key=rotation_observation_key) if rising else None
    strongest_loss = min(falling, key=rotation_observation_key) if falling else None
    top_three_share = float(sum(row["current_count"] for row in current_sorted[:3]))
    previous_order = sorted(
        rows,
        key=lambda row: (
            -next(point["count"] for point in row["points"] if point["date"] == previous_date),
            row["code"],
        ),
    )
    previous_top_ten = {row["code"] for row in previous_order[:10]}
    new_top_ten = [
        row for row in current_sorted[:10] if row["code"] not in previous_top_ten
    ]
    recent_start_top_three = sorted(
        (
            next(
                point["count"]
                for point in row["points"]
                if point["date"] == recent_start_date
            )
            for row in rows
        ),
        reverse=True,
    )[:3]
    concentration_delta = top_three_share - float(sum(recent_start_top_three))
    concentration_state = (
        "集中"
        if concentration_delta >= 5
        else "扩散"
        if concentration_delta <= -5
        else "大体稳定"
    )

    summary: list[str] = []
    if strongest_gain:
        summary.append(
            f"{strongest_gain['name']}上升最快，近 4 个节点斜率"
            f" {strongest_gain['recent_slope']:+.2f} 只/采样点，"
            f"合计变化 {strongest_gain['recent_change']:+d} 只。"
        )
    if strongest_loss:
        summary.append(
            f"{strongest_loss['name']}下降最快，近 4 个节点斜率"
            f" {strongest_loss['recent_slope']:+.2f} 只/采样点，"
            f"合计变化 {strongest_loss['recent_change']:+d} 只。"
        )
    persistent = [row for row in rows if row["status"] == "↑ 持续增强"]
    if persistent:
        summary.append(
            f"{'、'.join(row['name'] for row in sorted(persistent, key=rotation_observation_key)[:3])}"
            f"近 3 个间隔至少 2 次同向上升，共 {len(persistent)} 个行业持续增强。"
        )
    rapid = [row for row in rows if row["status"] == "↗ 快速启动"]
    if rapid:
        summary.append(
            f"{'、'.join(row['name'] for row in sorted(rapid, key=rotation_observation_key)[:3])}"
            f"从低位单次增加至少 {RAPID_START_DELTA} 只，属于刚启动。"
        )
    summary.append(
        f"近 4 个节点有 {len(rising)} 个行业上升、{len(falling)} 个行业下降；"
        f"前三行业合计 {top_three_share:.0f}%，较窗口起点"
        f"{concentration_delta:+.0f} 个百分点，行业分布{concentration_state}。"
    )
    if strongest:
        summary.append(
            f"绝对水平次要参考：当前数量最多的是{strongest['name']}，"
            f"占 Top 100 的 {strongest['current_percent']:.0f}%。"
        )

    output_warnings = list(warnings or [])
    incomplete_dates = [
        date for date, count in actual_top_by_date.items() if count < TOP_N
    ]
    if incomplete_dates:
        output_warnings.append(
            f"{len(incomplete_dates)} 个采样节点的有效形态股票不足 Top 100；占比仍固定以 100 为分母。"
        )
    missing_total = sum(missing_industry_by_date.values())
    if missing_total:
        output_warnings.append(
            f"24 个截面合计有 {missing_total} 条入选记录缺少可追溯的一级行业，未伪造归类。"
        )
    if len(sample_dates) != SAMPLE_COUNT:
        output_warnings.append(
            f"本地历史只能形成 {len(sample_dates)} 个完整的 5 交易日采样节点，少于冻结口径 24 个。"
        )

    return {
        "pattern": pattern,
        "pattern_label": pattern_label,
        "requested_end_date": requested_end_date,
        "resolved_end_date": latest_date,
        "sampling": {
            "top_n": TOP_N,
            "industry_level": 1,
            "lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "sample_every_trading_days": SAMPLE_EVERY,
            "sample_count": len(sample_dates),
            "dates": sample_dates,
            "denominator": TOP_N,
        },
        "scope": {
            "board": "主板",
            "exclude_st": True,
            "industry_count": len(catalog),
            "industry_source": "申万一级行业（本地 zer0share）",
        },
        "metrics": {
            "covered_industries": len(active),
            "strongest_industry": None if not strongest else strongest["name"],
            "strongest_count": 0 if not strongest else strongest["current_count"],
            "fastest_strengthening": None
            if not strongest_gain
            else strongest_gain["name"],
            "fastest_strengthening_change": 0
            if not strongest_gain
            else strongest_gain["recent_change"],
            "fastest_strengthening_speed": 0
            if not strongest_gain
            else strongest_gain["recent_slope"],
            "fastest_weakening": None
            if not strongest_loss
            else strongest_loss["name"],
            "fastest_weakening_change": 0
            if not strongest_loss
            else strongest_loss["recent_change"],
            "fastest_weakening_speed": 0
            if not strongest_loss
            else strongest_loss["recent_slope"],
            "just_started_industry": None if not rapid else rapid[0]["name"],
            "just_started_count": len(rapid),
            "persistent_strengthening_count": len(persistent),
            "rising_industry_count": len(rising),
            "falling_industry_count": len(falling),
            "top_three_percent": top_three_share,
            "new_top_ten_count": len(new_top_ten),
            "concentration_state": concentration_state,
            "concentration_change": concentration_delta,
        },
        "analysis": summary,
        "rules": {
            "rapid_start_delta": RAPID_START_DELTA,
            "rapid_start_explanation": "从低位单个 5 交易日采样间隔增加至少 3 只（3 个百分点）",
            "high_rank_cutoff": 5,
            "recent_window_points": RECENT_WINDOW_POINTS,
            "slope_explanation": "最近 4 个采样点做线性回归；斜率单位为只/采样点，正数上升、负数下降",
            "stable_sort_explanation": "同速时依次按方向持续性、最新有效占比、行业代码排序",
            "directional_slots": MIN_DIRECTIONAL_SLOTS,
        },
        "display": {
            "default_visible_count": len(default_visible_codes),
            "default_visible_codes": default_visible_codes,
            "latest_first_dates": latest_first(sample_dates),
            "hidden_count": len(hidden_rows),
            "folded_count": 0,
            "folded_current_count": 0,
            "folded_current_percent": 0.0,
        },
        "industries": all_heatmap_rows,
        "ranking": rotation_ranking,
        "actual_top_by_date": actual_top_by_date,
        "missing_industry_by_date": missing_industry_by_date,
        "warnings": output_warnings,
    }
