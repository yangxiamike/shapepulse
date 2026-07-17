from __future__ import annotations

from typing import Any


TOP_N = 100
LOOKBACK_TRADING_DAYS = 120
SAMPLE_EVERY = 5
SAMPLE_COUNT = 24
DEFAULT_VISIBLE_INDUSTRIES = 16
RAPID_START_DELTA = 3


def fixed_sample_dates(trade_dates: list[str]) -> list[str]:
    """Return the 24 fixed five-trading-day samples ending at the latest date."""
    dates = sorted(dict.fromkeys(str(value) for value in trade_dates if value))
    window = dates[-LOOKBACK_TRADING_DAYS:]
    return window[4::SAMPLE_EVERY]


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


def industry_status(counts: list[int], current_rank: int) -> str:
    if not counts:
        return "暂无数据"
    current = counts[-1]
    previous = counts[-2] if len(counts) > 1 else 0
    if previous == 0 and current >= RAPID_START_DELTA:
        return "新进入行业"
    if len(counts) >= 4 and counts[-4] < counts[-3] < counts[-2] < counts[-1]:
        return "持续增强"
    if len(counts) >= 3 and counts[-3] < counts[-2] < counts[-1]:
        return "正在增强"
    if current - previous >= RAPID_START_DELTA:
        return "快速启动"
    if (
        current_rank <= 5
        and len(counts) >= 3
        and counts[-3] > counts[-2] > counts[-1]
    ):
        return "高位退潮"
    if len(counts) >= 3 and counts[-3] > counts[-2] > counts[-1]:
        return "正在走弱"
    return "相对稳定"


def _forced_visible_codes(
    ordered_rows: list[dict[str, Any]], current_top_codes: list[str]
) -> list[str]:
    visible = [row["code"] for row in ordered_rows[:DEFAULT_VISIBLE_INDUSTRIES]]
    protected = set(current_top_codes)
    for code in current_top_codes:
        if code in visible:
            continue
        replacement = next(
            (
                candidate
                for candidate in reversed(visible)
                if candidate not in protected
            ),
            None,
        )
        if replacement is None:
            break
        visible[visible.index(replacement)] = code
    order = {row["code"]: index for index, row in enumerate(ordered_rows)}
    return sorted(dict.fromkeys(visible), key=lambda code: order[code])


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
    four_back_date = sample_dates[-5] if len(sample_dates) >= 5 else sample_dates[0]
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
        rows.append(
            {
                **item,
                "points": points,
                "counts": counts,
                "current_count": len(by_industry[code][latest_date]),
                "current_percent": float(len(by_industry[code][latest_date])),
                "change_previous": len(by_industry[code][latest_date])
                - len(by_industry[code][previous_date]),
                "change_four_samples": len(by_industry[code][latest_date])
                - len(by_industry[code][four_back_date]),
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
    for rank, row in enumerate(current_sorted, 1):
        row["rank"] = rank
        row["status"] = industry_status(row["counts"], rank)

    heatmap_rows = sorted(
        rows,
        key=lambda row: (-row["cumulative_count"], -row["current_count"], row["code"]),
    )
    current_top_codes = [row["code"] for row in current_sorted[:10]]
    default_visible_codes = _forced_visible_codes(heatmap_rows, current_top_codes)
    visible_set = set(default_visible_codes)
    folded_rows = [row for row in heatmap_rows if row["code"] not in visible_set]
    folded_current_count = sum(row["current_count"] for row in folded_rows)

    active = [row for row in current_sorted if row["current_count"] > 0]
    strongest = active[0] if active else None
    strongest_gain = max(
        active, key=lambda row: (row["change_four_samples"], row["current_count"])
    ) if active else None
    weakening = [row for row in rows if row["change_four_samples"] < 0]
    strongest_loss = min(
        weakening,
        key=lambda row: (row["change_four_samples"], -row["current_count"]),
    ) if weakening else None
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
    four_back_top_three = sorted(
        (
            next(point["count"] for point in row["points"] if point["date"] == four_back_date)
            for row in rows
        ),
        reverse=True,
    )[:3]
    concentration_delta = top_three_share - float(sum(four_back_top_three))
    concentration_state = (
        "集中"
        if concentration_delta >= 5
        else "扩散"
        if concentration_delta <= -5
        else "大体稳定"
    )

    summary: list[str] = []
    if strongest:
        summary.append(
            f"当前最强为{strongest['name']}，占 Top 100 的 {strongest['current_percent']:.0f}%."
        )
    persistent = [row for row in current_sorted if row["status"] == "持续增强"]
    if persistent:
        summary.append(
            f"{'、'.join(row['name'] for row in persistent[:3])}连续 3 个采样间隔上升，处于持续增强。"
        )
    rapid = [
        row
        for row in current_sorted
        if row["change_previous"] >= RAPID_START_DELTA
        or row["status"] == "新进入行业"
    ]
    if rapid:
        summary.append(
            f"{'、'.join(row['name'] for row in rapid[:3])}单次增加至少 {RAPID_START_DELTA} 只，属于快速启动。"
        )
    retreat = [row for row in current_sorted if row["status"] == "高位退潮"]
    if retreat:
        summary.append(
            f"{'、'.join(row['name'] for row in retreat[:3])}仍居前五但连续回落，呈现高位退潮。"
        )
    summary.append(
        f"前三行业合计 {top_three_share:.0f}%，较 4 个采样点前"
        f"{abs(concentration_delta):.0f} 个百分点，行业分布{concentration_state}。"
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
            else strongest_gain["change_four_samples"],
            "fastest_weakening": None
            if not strongest_loss
            else strongest_loss["name"],
            "fastest_weakening_change": 0
            if not strongest_loss
            else strongest_loss["change_four_samples"],
            "top_three_percent": top_three_share,
            "new_top_ten_count": len(new_top_ten),
            "concentration_state": concentration_state,
            "concentration_change": concentration_delta,
        },
        "analysis": summary,
        "rules": {
            "rapid_start_delta": RAPID_START_DELTA,
            "rapid_start_explanation": "单个 5 交易日采样间隔增加至少 3 只（3 个百分点）",
            "high_rank_cutoff": 5,
        },
        "display": {
            "default_visible_count": min(DEFAULT_VISIBLE_INDUSTRIES, len(rows)),
            "default_visible_codes": default_visible_codes,
            "folded_count": len(folded_rows),
            "folded_current_count": folded_current_count,
            "folded_current_percent": float(folded_current_count),
        },
        "industries": heatmap_rows,
        "ranking": current_sorted,
        "actual_top_by_date": actual_top_by_date,
        "missing_industry_by_date": missing_industry_by_date,
        "warnings": output_warnings,
    }
