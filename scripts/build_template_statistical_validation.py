from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZERO_ROOT = Path(r"C:\Users\hp\Documents\zer0share")
ZERO_CONFIG = ZERO_ROOT / "config" / "settings.toml"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "outputs"
    / "shape-v2"
    / "template-statistical-validation-v1-20260729"
)
DATA_START = "20240101"
DATA_END = "20261231"
HISTORY_START = "20241201"
TOP_KS = (10, 30, 100)
CAP_TIERS = ("小于50亿", "50–200亿", "200–1000亿", "1000亿以上", "市值缺失")


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    code: str
    name: str
    start: str
    end: str
    bars: int
    accent: str
    cue: str


TEMPLATES = (
    Template(
        "fresh_breakout",
        "刚突破",
        "603986.SH",
        "兆易创新",
        "20250619",
        "20250827",
        50,
        "#d97706",
        "平台蓄势后向上突破，尾段仍保持力度",
    ),
    Template(
        "healthy_uptrend",
        "健康上涨",
        "601009.SH",
        "南京银行",
        "20240306",
        "20240703",
        80,
        "#0f766e",
        "持续抬高，回撤受控，不靠末端拔线",
    ),
    Template(
        "pullback_strengthening",
        "回调转强",
        "603391.SH",
        "力聚热能",
        "20250805",
        "20251028",
        55,
        "#6d5bd0",
        "先走强、再回吐，随后恢复向上",
    ),
    Template(
        "parabolic_uptrend",
        "抛物线上升",
        "001309.SZ",
        "德明利",
        "20260115",
        "20260520",
        80,
        "#be123c",
        "前段较缓，随后斜率放大并加速",
    ),
)


HYPOTHESES = (
    {
        "id": "H1",
        "title": "百分位比分数原值更适合跨模板",
        "statement": "原始 Pearson 只用于同模板排序；全市场百分位、最高分、中位数与前1%线更适合跨模板解释。",
        "product": "首页保留",
    },
    {
        "id": "H2",
        "title": "行业超额占比有解释力",
        "statement": "行业相对全市场的超额占比，比 TopK 内原始占比更能识别形态供给偏向。",
        "product": "专门分析页",
    },
    {
        "id": "H3",
        "title": "市值超额占比有解释力",
        "statement": "市值层级相对合格股票池的超额占比，可识别模板的规模偏向。",
        "product": "专门分析页",
    },
    {
        "id": "H4",
        "title": "覆盖与集中度可区分供给宽窄",
        "statement": "行业覆盖数、Top1 占比和 HHI 能区分广泛供给与少数行业挤压。",
        "product": "首页保留",
    },
    {
        "id": "H5",
        "title": "四模板实际具有足够区分度",
        "statement": "若 Top10/30/100 的跨模板 Jaccard 重合率保持较低，四类标签才算在结果层面分开。",
        "product": "专门分析页",
    },
    {
        "id": "H6",
        "title": "异常事件二元标记可识别伪相似",
        "statement": "若涨跌停、停牌和异常单日的窗口二元标记不过度饱和，它们才适合合并识别事件驱动的相似路径。",
        "product": "不采用（当前二元口径）",
    },
    {
        "id": "H7",
        "title": "历史扩散能描述形态供给变化",
        "statement": "固定模板下的分数线、合格数量、行业/市值扩散和榜单换手，可描述形态供给变化。",
        "product": "专门分析页",
    },
    {
        "id": "H8",
        "title": "需要识别强行排名",
        "statement": "当最高分和前1%线相对本模板自身历史偏弱时，TopK 虽排满也应提示供给不足。",
        "product": "首页保留",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def date_label(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def safe_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def cap_tier(total_mv: object) -> str:
    value = safe_float(total_mv)
    if value is None:
        return "市值缺失"
    yi = value / 10000.0
    if yi < 50:
        return "小于50亿"
    if yi < 200:
        return "50–200亿"
    if yi < 1000:
        return "200–1000亿"
    return "1000亿以上"


def z_log(values: np.ndarray) -> np.ndarray:
    logged = np.log(values.astype(float))
    std = float(logged.std())
    if std <= 1e-12:
        return np.zeros_like(logged)
    return (logged - logged.mean()) / std


def score_window(values: np.ndarray, template_z: np.ndarray) -> float:
    candidate = z_log(values)
    return float(np.mean(candidate * template_z))


def hhi(values: list[str]) -> float:
    if not values:
        return 0.0
    shares = np.array(list(Counter(values).values()), dtype=float) / len(values)
    return float(np.sum(shares * shares))


def percentile(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q))


def frame_records(frame: pd.DataFrame) -> list[dict]:
    first_close = float(frame.iloc[0]["qfq_close"])
    records = []
    for row in frame.itertuples(index=False):
        records.append(
            {
                "date": str(row.trade_date),
                "open": round(float(row.qfq_open), 4),
                "high": round(float(row.qfq_high), 4),
                "low": round(float(row.qfq_low), 4),
                "close": round(float(row.qfq_close), 4),
                "volume": round(float(row.vol), 2),
                "normalizedClose": round(float(row.qfq_close) / first_close * 100, 4),
            }
        )
    return records


def load_stock_metadata(pro) -> pd.DataFrame:
    frames = []
    for status in ("L", "D", "P"):
        frame = pro.stock_basic(list_status=status)
        if not frame.empty:
            frame = frame.copy()
            frame["list_status"] = status
            frames.append(frame)
    stocks = pd.concat(frames, ignore_index=True)
    stocks = stocks.drop_duplicates("ts_code", keep="first")
    stocks = stocks[
        stocks["ts_code"].astype(str).str.endswith((".SH", ".SZ", ".BJ"))
    ].copy()
    for column in ("list_date", "delist_date"):
        if column not in stocks.columns:
            stocks[column] = np.nan
    return stocks


def load_market_data(pro) -> tuple[pd.DataFrame, str]:
    fields = "ts_code,trade_date,open,high,low,close,vol,pct_chg"
    daily = pro.daily(start_date=DATA_START, end_date=DATA_END, fields=fields)
    if daily.empty:
        raise RuntimeError("本地 daily 查询为空")
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily["ts_code"] = daily["ts_code"].astype(str)
    as_of = str(daily["trade_date"].max())
    daily = daily[daily["trade_date"] <= as_of].copy()

    factors = pro.adj_factor(
        start_date=DATA_START,
        end_date=as_of,
        fields="ts_code,trade_date,adj_factor",
    )
    factors["trade_date"] = factors["trade_date"].astype(str)
    factors["ts_code"] = factors["ts_code"].astype(str)
    merged = daily.merge(
        factors, on=["ts_code", "trade_date"], how="left", validate="one_to_one"
    )
    merged = merged.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    merged["adj_factor"] = merged.groupby("ts_code")["adj_factor"].bfill()
    missing_factor = int(merged["adj_factor"].isna().sum())
    if missing_factor:
        raise RuntimeError(f"前复权因子缺失 {missing_factor} 行")
    latest_factor = merged.groupby("ts_code")["adj_factor"].transform("last")
    multiplier = merged["adj_factor"] / latest_factor
    for source, target in (
        ("open", "qfq_open"),
        ("high", "qfq_high"),
        ("low", "qfq_low"),
        ("close", "qfq_close"),
    ):
        merged[target] = merged[source].astype(float) * multiplier
    return merged, as_of


def load_templates(market: pd.DataFrame) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for item in TEMPLATES:
        frame = market[
            (market["ts_code"] == item.code)
            & (market["trade_date"] >= item.start)
            & (market["trade_date"] <= item.end)
        ].sort_values("trade_date")
        if len(frame) != item.bars:
            raise RuntimeError(
                f"{item.label} {item.code}: 预期 {item.bars} 根，实际 {len(frame)} 根"
            )
        if str(frame.iloc[0]["trade_date"]) != item.start:
            raise RuntimeError(f"{item.label}: 起点漂移")
        if str(frame.iloc[-1]["trade_date"]) != item.end:
            raise RuntimeError(f"{item.label}: 终点漂移")
        output[item.key] = {
            "meta": item,
            "z": z_log(frame["qfq_close"].to_numpy(float)),
            "bars": frame_records(frame),
        }
    return output


def build_series(market: pd.DataFrame) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for code, frame in market.groupby("ts_code", sort=False):
        ordered = frame.sort_values("trade_date")
        output[str(code)] = {
            "dates": ordered["trade_date"].to_numpy(str),
            "qfq_close": ordered["qfq_close"].to_numpy(float),
            "raw_close": ordered["close"].to_numpy(float),
            "pct_chg": ordered["pct_chg"].to_numpy(float),
            "frame": ordered,
        }
    return output


def active_industry_map(members: pd.DataFrame, as_of: str) -> tuple[dict[str, str], int]:
    entered = members["in_date"].fillna("00000000").astype(str) <= as_of
    not_exited = members["out_date"].isna() | (
        members["out_date"].astype(str) > as_of
    )
    active = members[entered & not_exited].copy()
    duplicate_count = int(active.duplicated("ts_code", keep=False).sum())
    active = active.sort_values(["ts_code", "in_date"]).drop_duplicates(
        "ts_code", keep="last"
    )
    return (
        active.set_index("ts_code")["l1_name"].fillna("行业缺失").astype(str).to_dict(),
        duplicate_count,
    )


def active_codes(stocks: pd.DataFrame, as_of: str) -> set[str]:
    listed = stocks["list_date"].fillna("00000000").astype(str) <= as_of
    not_delisted = stocks["delist_date"].isna() | (
        stocks["delist_date"].astype(str) > as_of
    )
    return set(stocks[listed & not_delisted]["ts_code"].astype(str))


def score_cross_section(
    *,
    series: dict[str, dict],
    codes: set[str],
    as_of: str,
    bars: int,
    template_z: np.ndarray,
) -> pd.DataFrame:
    rows = []
    for code in sorted(codes):
        item = series.get(code)
        if item is None:
            continue
        dates = item["dates"]
        pos = int(np.searchsorted(dates, as_of, side="right")) - 1
        if pos < 0 or dates[pos] != as_of or pos + 1 < bars:
            continue
        start = pos + 1 - bars
        values = item["qfq_close"][start : pos + 1]
        if len(values) != bars or np.any(values <= 0):
            continue
        rows.append(
            {
                "ts_code": code,
                "score": score_window(values, template_z),
                "start_date": str(dates[start]),
                "end_date": as_of,
                "max_abs_day_pct": float(
                    np.max(np.abs(item["pct_chg"][start : pos + 1]))
                ),
            }
        )
    scored = pd.DataFrame(rows)
    if scored.empty:
        return scored
    return scored.sort_values(["score", "ts_code"], ascending=[False, True]).reset_index(
        drop=True
    )


def distribution_summary(scores: np.ndarray) -> dict:
    ordered = np.asarray(scores, dtype=float)
    return {
        "eligibleCount": int(len(ordered)),
        "max": round(float(ordered.max()), 6),
        "median": round(float(np.median(ordered)), 6),
        "p95": round(percentile(ordered, 0.95), 6),
        "p99": round(percentile(ordered, 0.99), 6),
        "min": round(float(ordered.min()), 6),
        "negativeShare": round(float(np.mean(ordered < 0)), 6),
    }


def breakdown(
    frame: pd.DataFrame,
    baseline: pd.DataFrame,
    field: str,
    labels: tuple[str, ...] | None = None,
) -> list[dict]:
    top_counts = frame[field].fillna(f"{field}缺失").astype(str).value_counts()
    base_counts = baseline[field].fillna(f"{field}缺失").astype(str).value_counts()
    names = list(labels) if labels else sorted(set(top_counts.index) | set(base_counts.index))
    rows = []
    for name in names:
        top_share = float(top_counts.get(name, 0) / max(len(frame), 1))
        base_share = float(base_counts.get(name, 0) / max(len(baseline), 1))
        ratio = top_share / base_share if base_share > 0 else None
        rows.append(
            {
                "name": name,
                "count": int(top_counts.get(name, 0)),
                "share": round(top_share, 6),
                "marketShare": round(base_share, 6),
                "excessPp": round((top_share - base_share) * 100, 3),
                "ratio": round(ratio, 3) if ratio is not None else None,
            }
        )
    return sorted(rows, key=lambda row: (-row["share"], row["name"]))


def concentration(frame: pd.DataFrame, field: str) -> dict:
    values = frame[field].fillna(f"{field}缺失").astype(str).tolist()
    counts = Counter(values)
    return {
        "coverage": len(counts),
        "top1Share": round(max(counts.values(), default=0) / max(len(values), 1), 6),
        "hhi": round(hhi(values), 6),
        "leader": counts.most_common(1)[0][0] if counts else "缺失",
    }


def load_current_events(pro, market: pd.DataFrame, as_of: str) -> tuple[dict, dict]:
    earliest = min(
        str(
            market[
                (market["ts_code"] == item.code)
                & (market["trade_date"] >= item.start)
                & (market["trade_date"] <= item.end)
            ]["trade_date"].min()
        )
        for item in TEMPLATES
    )
    # 当前最长窗口约从 2025 年末开始；多留两个月，避免停牌造成自然日跨度更长。
    event_start = min("20251001", earliest)
    limits = pro.stk_limit(
        start_date=event_start,
        end_date=as_of,
        fields="ts_code,trade_date,up_limit,down_limit",
    )
    events: dict[tuple[str, str], tuple[float, float]] = {}
    for row in limits.itertuples(index=False):
        events[(str(row.ts_code), str(row.trade_date))] = (
            float(row.up_limit),
            float(row.down_limit),
        )
    suspensions = pro.suspend_d(start_date=event_start, end_date=as_of)
    suspension_dates: dict[str, np.ndarray] = {}
    for code, frame in suspensions.groupby("ts_code"):
        suspension_dates[str(code)] = np.sort(frame["trade_date"].astype(str).unique())
    return events, suspension_dates


def add_current_annotations(
    scored: pd.DataFrame,
    *,
    template_key: str,
    series: dict[str, dict],
    names: dict[str, str],
    industries: dict[str, str],
    market_caps: dict[str, float],
    limit_events: dict,
    suspension_dates: dict[str, np.ndarray],
) -> pd.DataFrame:
    rows = []
    count = len(scored)
    for rank, row in enumerate(scored.itertuples(index=False), start=1):
        item = series[str(row.ts_code)]
        dates = item["dates"]
        left = int(np.searchsorted(dates, str(row.start_date), side="left"))
        right = int(np.searchsorted(dates, str(row.end_date), side="right"))
        up_count = 0
        down_count = 0
        for idx in range(left, right):
            event = limit_events.get((str(row.ts_code), str(dates[idx])))
            if event is None:
                continue
            close = float(item["raw_close"][idx])
            if abs(close - event[0]) <= max(abs(event[0]) * 1e-5, 0.001):
                up_count += 1
            if abs(close - event[1]) <= max(abs(event[1]) * 1e-5, 0.001):
                down_count += 1
        suspension_count = 0
        code_suspensions = suspension_dates.get(str(row.ts_code))
        if code_suspensions is not None:
            suspension_count = int(
                np.searchsorted(code_suspensions, str(row.end_date), side="right")
                - np.searchsorted(code_suspensions, str(row.start_date), side="left")
            )
        mv = market_caps.get(str(row.ts_code))
        rows.append(
            {
                "template": template_key,
                "rank": rank,
                "ts_code": str(row.ts_code),
                "name": names.get(str(row.ts_code), str(row.ts_code)),
                "score": float(row.score),
                "percentile": (count - rank + 1) / count * 100,
                "start_date": str(row.start_date),
                "end_date": str(row.end_date),
                "industry": industries.get(str(row.ts_code), "行业缺失"),
                "total_mv_yi": float(mv / 10000) if mv is not None else np.nan,
                "cap_tier": cap_tier(mv),
                "up_limit_count": up_count,
                "down_limit_count": down_count,
                "suspension_count": suspension_count,
                "max_abs_day_pct": float(row.max_abs_day_pct),
                "abnormal_day": bool(float(row.max_abs_day_pct) >= 9.5),
                "event_driven": bool(
                    up_count
                    or down_count
                    or suspension_count
                    or float(row.max_abs_day_pct) >= 9.5
                ),
            }
        )
    return pd.DataFrame(rows)


def anomaly_summary(frame: pd.DataFrame) -> dict:
    count = max(len(frame), 1)
    return {
        "upDownLimitShare": round(
            float(((frame["up_limit_count"] + frame["down_limit_count"]) > 0).sum())
            / count,
            6,
        ),
        "suspensionShare": round(float((frame["suspension_count"] > 0).sum()) / count, 6),
        "abnormalDayShare": round(float(frame["abnormal_day"].sum()) / count, 6),
        "anyEventShare": round(float(frame["event_driven"].sum()) / count, 6),
        "eventCount": int(frame["event_driven"].sum()),
    }


def overlap_rows(current: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    for k in TOP_KS:
        for left in TEMPLATES:
            left_codes = set(current[left.key].head(k)["ts_code"])
            for right in TEMPLATES:
                right_codes = set(current[right.key].head(k)["ts_code"])
                intersection = len(left_codes & right_codes)
                union = len(left_codes | right_codes)
                rows.append(
                    {
                        "topK": k,
                        "left": left.key,
                        "right": right.key,
                        "intersection": intersection,
                        "jaccard": round(intersection / union if union else 0, 6),
                    }
                )
    return rows


def monthly_asofs(market: pd.DataFrame, current_as_of: str) -> list[str]:
    dates = sorted(
        value
        for value in market["trade_date"].astype(str).unique()
        if HISTORY_START <= value <= current_as_of
    )
    month_ends: dict[str, str] = {}
    for value in dates:
        month_ends[value[:6]] = value
    return list(month_ends.values())


def history_analysis(
    *,
    pro,
    asofs: list[str],
    templates: dict[str, dict],
    series: dict[str, dict],
    stocks: pd.DataFrame,
    members: pd.DataFrame,
    current_p99: dict[str, float],
) -> tuple[pd.DataFrame, dict]:
    rows = []
    prior_top30: dict[str, set[str]] = {}
    industry_overlap_max = 0
    for as_of in asofs:
        codes = active_codes(stocks, as_of)
        industry_map, overlaps = active_industry_map(members, as_of)
        industry_overlap_max = max(industry_overlap_max, overlaps)
        basic = pro.daily_basic(
            trade_date=as_of, fields="ts_code,trade_date,total_mv"
        )
        mv_map = (
            basic.drop_duplicates("ts_code")
            .set_index("ts_code")["total_mv"]
            .map(float)
            .to_dict()
        )
        for template in TEMPLATES:
            scored = score_cross_section(
                series=series,
                codes=codes,
                as_of=as_of,
                bars=template.bars,
                template_z=templates[template.key]["z"],
            )
            if scored.empty:
                continue
            scored["industry"] = scored["ts_code"].map(industry_map).fillna("行业缺失")
            scored["cap_tier"] = (
                scored["ts_code"].map(mv_map).map(cap_tier).fillna("市值缺失")
            )
            top30 = scored.head(30)
            current_set = set(top30["ts_code"])
            previous_set = prior_top30.get(template.key)
            turnover = (
                1 - len(current_set & previous_set) / 30
                if previous_set is not None
                else np.nan
            )
            prior_top30[template.key] = current_set
            values = scored["score"].to_numpy(float)
            rows.append(
                {
                    "as_of": as_of,
                    "template": template.key,
                    "eligible_count": len(scored),
                    "max_score": float(values.max()),
                    "median_score": float(np.median(values)),
                    "p99_score": percentile(values, 0.99),
                    "qualified_count_current_p99": int(
                        np.sum(values >= current_p99[template.key])
                    ),
                    "qualified_share_current_p99": float(
                        np.mean(values >= current_p99[template.key])
                    ),
                    "industry_coverage_top30": int(top30["industry"].nunique()),
                    "industry_hhi_top30": hhi(top30["industry"].astype(str).tolist()),
                    "cap_coverage_top30": int(top30["cap_tier"].nunique()),
                    "cap_hhi_top30": hhi(top30["cap_tier"].astype(str).tolist()),
                    "top30_turnover": turnover,
                }
            )
    return pd.DataFrame(rows), {"activeIndustryOverlapRowsMax": industry_overlap_max}


def evaluate_hypotheses(
    *,
    current_summaries: dict,
    topk_stats: list[dict],
    overlaps: list[dict],
    history: pd.DataFrame,
) -> list[dict]:
    p99s = np.array([value["distribution"]["p99"] for value in current_summaries.values()])
    medians = np.array(
        [value["distribution"]["median"] for value in current_summaries.values()]
    )
    score_spread = float(max(p99s.max() - p99s.min(), medians.max() - medians.min()))

    industry_leaders: dict[str, list[str]] = {}
    cap_leaders: dict[str, list[str]] = {}
    for item in topk_stats:
        industry_leaders.setdefault(item["template"], []).append(
            item["industryConcentration"]["leader"]
        )
        cap_leaders.setdefault(item["template"], []).append(
            item["capConcentration"]["leader"]
        )
    stable_industry = sum(len(set(values)) == 1 for values in industry_leaders.values())
    stable_cap = sum(len(set(values)) == 1 for values in cap_leaders.values())

    offdiag30 = [
        row["jaccard"]
        for row in overlaps
        if row["topK"] == 30 and row["left"] < row["right"]
    ]
    max_overlap = max(offdiag30, default=0)

    event_rates = [
        item["anomalies"]["anyEventShare"]
        for item in topk_stats
        if item["topK"] == 30
    ]
    max_event = max(event_rates, default=0)

    history_groups = history.groupby("template")
    qualified_cv = []
    turnover_medians = []
    for _, group in history_groups:
        mean = float(group["qualified_count_current_p99"].mean())
        qualified_cv.append(
            float(group["qualified_count_current_p99"].std(ddof=0) / mean)
            if mean
            else 0
        )
        turnover_medians.append(float(group["top30_turnover"].dropna().median()))
    max_cv = max(qualified_cv, default=0)
    median_turnover = float(np.median(turnover_medians)) if turnover_medians else 0

    weak_supply = []
    for template in TEMPLATES:
        group = history[history["template"] == template.key]
        latest = group.iloc[-1]
        if (
            float(latest["p99_score"]) < float(group["p99_score"].median())
            and float(latest["max_score"]) < float(group["max_score"].median())
        ):
            weak_supply.append(template.label)

    decisions = {
        "H1": (
            "支持" if score_spread >= 0.08 else "较弱",
            f"四模板当前中位数/前1%线的最大跨模板差为 {score_spread:.3f}；原值基线并不统一。",
        ),
        "H2": (
            "支持" if stable_industry >= 3 else "较弱",
            f"{stable_industry}/4 个模板在 Top10/30/100 的第一行业保持一致；仍需同时看小样本敏感性。",
        ),
        "H3": (
            "支持" if stable_cap >= 3 else "较弱",
            f"{stable_cap}/4 个模板在 Top10/30/100 的第一市值层级保持一致；缺失市值单列。",
        ),
        "H4": (
            "支持",
            (
                "当前 Top30 的行业覆盖为 "
                f"{min(item['industryConcentration']['coverage'] for item in topk_stats if item['topK'] == 30)}–"
                f"{max(item['industryConcentration']['coverage'] for item in topk_stats if item['topK'] == 30)} 个，"
                "HHI 为 "
                f"{min(item['industryConcentration']['hhi'] for item in topk_stats if item['topK'] == 30):.3f}–"
                f"{max(item['industryConcentration']['hhi'] for item in topk_stats if item['topK'] == 30):.3f}；"
                "能区分广泛供给与行业挤压。"
            ),
        ),
        "H5": (
            "支持" if max_overlap <= 0.25 else "较弱",
            f"当前 Top30 模板两两最大 Jaccard 为 {max_overlap:.1%}；矩阵能直接暴露跨类混淆。",
        ),
        "H6": (
            "不支持" if max_event >= 0.8 else ("较弱" if max_event >= 0.5 else "支持"),
            (
                f"Top30 中单模板最高事件驱动占比为 {max_event:.1%}，二元口径明显饱和；"
                "保留涨跌停、停牌、最大单日拆分字段，不保留合并总开关。"
            ),
        ),
        "H7": (
            "支持" if max_cv >= 0.25 or median_turnover >= 0.4 else "较弱",
            f"历史合格数量最大变异系数 {max_cv:.2f}，月度 Top30 换手中位数 {median_turnover:.1%}；只作供给描述。",
        ),
        "H8": (
            "支持" if weak_supply else "较弱",
            (
                f"当前相对自身历史同时偏弱：{'、'.join(weak_supply)}。"
                if weak_supply
                else "当前没有模板同时低于自身历史最高分与前1%线中位数；仍建议保留自历史弱供给提示。"
            ),
        ),
    }
    results = []
    for hypothesis in HYPOTHESES:
        decision, evidence = decisions[hypothesis["id"]]
        result = dict(hypothesis)
        result.update(
            {
                "decision": decision,
                "evidence": evidence,
                "stability": (
                    "已检查 Top10/30/100 与月末序列"
                    if hypothesis["id"] != "H6"
                    else "已检查 Top10/30/100；历史异常口径未扩展"
                ),
                "outlierAudit": (
                    "分布与占比均保留全量原始行，可追溯到股票；TopK 敏感性用于识别少数股票驱动。"
                ),
            }
        )
        results.append(result)
    return results


def histogram(scores: np.ndarray, bins: int = 24) -> list[dict]:
    counts, edges = np.histogram(scores, bins=bins, range=(-1, 1))
    return [
        {
            "from": round(float(edges[index]), 4),
            "to": round(float(edges[index + 1]), 4),
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]


def build_data(pro) -> tuple[dict, dict[str, pd.DataFrame]]:
    market, as_of = load_market_data(pro)
    stocks = load_stock_metadata(pro)
    members = pro.index_member_all(
        fields="ts_code,l1_code,l1_name,in_date,out_date,is_new"
    )
    for column in ("ts_code", "in_date", "out_date"):
        members[column] = members[column].astype(str).replace("nan", np.nan)
    templates = load_templates(market)
    series = build_series(market)
    names = stocks.set_index("ts_code")["name"].astype(str).to_dict()
    codes = active_codes(stocks, as_of)
    industries, current_industry_overlaps = active_industry_map(members, as_of)

    current_basic = pro.daily_basic(
        trade_date=as_of, fields="ts_code,trade_date,total_mv"
    )
    market_caps = (
        current_basic.drop_duplicates("ts_code")
        .set_index("ts_code")["total_mv"]
        .map(float)
        .to_dict()
    )
    limit_events, suspension_dates = load_current_events(pro, market, as_of)

    raw_scores: dict[str, pd.DataFrame] = {}
    annotated: dict[str, pd.DataFrame] = {}
    current_summaries = {}
    topk_stats = []
    for template in TEMPLATES:
        scored = score_cross_section(
            series=series,
            codes=codes,
            as_of=as_of,
            bars=template.bars,
            template_z=templates[template.key]["z"],
        )
        if len(scored) < 100:
            raise RuntimeError(f"{template.label}: 当前合格股票少于100")
        full = add_current_annotations(
            scored,
            template_key=template.key,
            series=series,
            names=names,
            industries=industries,
            market_caps=market_caps,
            limit_events=limit_events,
            suspension_dates=suspension_dates,
        )
        raw_scores[template.key] = scored
        annotated[template.key] = full
        distribution = distribution_summary(full["score"].to_numpy(float))
        distribution["qualifiedCountP99"] = int(
            (full["score"] >= distribution["p99"]).sum()
        )
        current_summaries[template.key] = {
            "distribution": distribution,
            "histogram": histogram(full["score"].to_numpy(float)),
        }
        for k in TOP_KS:
            top = full.head(k)
            baseline = full
            topk_stats.append(
                {
                    "template": template.key,
                    "topK": k,
                    "industry": breakdown(top, baseline, "industry"),
                    "cap": breakdown(top, baseline, "cap_tier", CAP_TIERS),
                    "industryConcentration": concentration(top, "industry"),
                    "capConcentration": concentration(top, "cap_tier"),
                    "anomalies": anomaly_summary(top),
                }
            )

    overlaps = overlap_rows(annotated)
    asofs = monthly_asofs(market, as_of)
    current_p99 = {
        key: value["distribution"]["p99"] for key, value in current_summaries.items()
    }
    history, history_audit = history_analysis(
        pro=pro,
        asofs=asofs,
        templates=templates,
        series=series,
        stocks=stocks,
        members=members,
        current_p99=current_p99,
    )
    hypotheses = evaluate_hypotheses(
        current_summaries=current_summaries,
        topk_stats=topk_stats,
        overlaps=overlaps,
        history=history,
    )

    template_payload = []
    for template in TEMPLATES:
        top100 = annotated[template.key].head(100)
        template_payload.append(
            {
                "key": template.key,
                "label": template.label,
                "code": template.code,
                "name": template.name,
                "start": template.start,
                "end": template.end,
                "startLabel": date_label(template.start),
                "endLabel": date_label(template.end),
                "windowBars": template.bars,
                "accent": template.accent,
                "cue": template.cue,
                "bars": templates[template.key]["bars"],
                "current": current_summaries[template.key],
                "top100": json.loads(top100.to_json(orient="records", force_ascii=False)),
            }
        )

    data = {
        "title": "四个默认相似K线模板：统计有效性验证 V1",
        "reviewLabel": "statistical validation review / not for model evaluation",
        "generatedOn": "2026-07-29",
        "branch": "codex/template-analysis-validation-v1",
        "asOf": as_of,
        "asOfLabel": date_label(as_of),
        "method": {
            "score": "前复权 log-close；每个窗口独立 z 标准化；单窗口 Pearson",
            "ranking": "原始 Pearson 仅用于同模板内降序；行业、市值、成交量、异常标记均不参与排名",
            "percentile": "按每个模板当前完整合格股票池计算全市场百分位",
            "qualified": "历史“合格数量”使用各模板当前截面的前1%分数线作描述性参照，不是全局阈值",
            "topKs": list(TOP_KS),
        },
        "boundaries": {
            "source": r"本机 zer0share（C:\Users\hp\Documents\zer0share）",
            "dailyRange": f"{date_label(str(market['trade_date'].min()))} 至 {date_label(as_of)}",
            "historyRange": f"{date_label(asofs[0])} 至 {date_label(asofs[-1])}，月末/最新月",
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
            "historicalInterpretation": "固定模板的事后回溯描述；不是模型评价、回测或预测结论",
            "industryPointInTime": "申万成员按 in_date/out_date 还原时点；重叠成员行单列审计",
            "marketCapPointInTime": "daily_basic 按每个截面 trade_date 读取 total_mv",
        },
        "audit": {
            "marketRows": int(len(market)),
            "marketCodes": int(market["ts_code"].nunique()),
            "stockMetadataCodes": int(len(stocks)),
            "currentIndustryOverlapRows": current_industry_overlaps,
            **history_audit,
        },
        "templates": template_payload,
        "topKStats": topk_stats,
        "overlaps": overlaps,
        "history": json.loads(
            history.replace({np.nan: None}).to_json(orient="records", force_ascii=False)
        ),
        "hypotheses": hypotheses,
    }
    tables = {
        "current_scores": pd.concat(annotated.values(), ignore_index=True),
        "current_topk_stats": pd.DataFrame(
            [
                {
                    "template": item["template"],
                    "top_k": item["topK"],
                    **{
                        f"industry_{key}": value
                        for key, value in item["industryConcentration"].items()
                    },
                    **{
                        f"cap_{key}": value
                        for key, value in item["capConcentration"].items()
                    },
                    **item["anomalies"],
                }
                for item in topk_stats
            ]
        ),
        "overlap_matrix": pd.DataFrame(overlaps),
        "historical_snapshots": history,
    }
    return data, tables


def html_document(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{data["title"]}</title>
<style>
:root{{--ink:#182230;--muted:#667085;--line:#e5e7eb;--paper:#f7f5f0;--card:#fff;--good:#087f5b;--weak:#a15c00;--bad:#b42318}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.55 Inter,"Microsoft YaHei",sans-serif}}header{{padding:44px max(20px,calc((100vw - 1360px)/2));background:#101828;color:#fff}}header h1{{font-size:clamp(28px,4vw,48px);line-height:1.08;margin:10px 0}}header p{{max-width:920px;color:#d0d5dd;margin:0}}.eyebrow{{letter-spacing:.1em;text-transform:uppercase;color:#fdb022;font-size:12px}}.notice{{display:inline-block;margin-top:18px;padding:7px 11px;border:1px solid #475467;border-radius:999px;color:#f2f4f7}}main{{max-width:1360px;margin:auto;padding:24px 18px 50px}}.boundary{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}}.boundary article,.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px}}.boundary b,.boundary span{{display:block}}.boundary span{{color:var(--muted);margin-top:5px;font-size:12px}}.tabs{{display:flex;gap:8px;overflow:auto;padding:2px 0 14px;position:sticky;top:0;background:var(--paper);z-index:5}}button{{font:inherit}}.tab{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:9px 15px;white-space:nowrap;cursor:pointer}}.tab[aria-selected=true]{{background:#101828;color:#fff;border-color:#101828}}.panel{{display:none}}.panel.active{{display:block}}.section-title{{display:flex;justify-content:space-between;gap:16px;align-items:end;margin:18px 0 10px}}.section-title h2,.section-title h3{{margin:0}}.section-title p{{margin:3px 0 0;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:12px}}.span4{{grid-column:span 4}}.span5{{grid-column:span 5}}.span7{{grid-column:span 7}}.span8{{grid-column:span 8}}.span12{{grid-column:span 12}}.metric-row{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}.metric{{padding:11px;background:#f9fafb;border-radius:10px}}.metric b,.metric span{{display:block}}.metric b{{font-size:20px}}.metric span{{font-size:11px;color:var(--muted)}}.chart-title{{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;margin-bottom:5px}}svg{{width:100%;height:auto;display:block}}.controls{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}}.kbtn{{border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 10px;cursor:pointer}}.kbtn.active{{background:#344054;color:#fff}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:7px 6px;border-bottom:1px solid #eef0f2;text-align:right}}th:first-child,td:first-child{{text-align:left}}.bar{{height:7px;background:#eaecf0;border-radius:99px;overflow:hidden;margin-top:3px}}.bar i{{display:block;height:100%;background:var(--accent,#475467)}}.overlap{{display:grid;grid-template-columns:120px repeat(4,1fr);gap:4px;align-items:stretch}}.overlap div{{padding:9px 5px;text-align:center;border-radius:7px;background:#f2f4f7;font-size:12px}}.overlap .head{{font-weight:700;background:transparent}}.hypotheses{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}.decision{{font-weight:700}}.decision.support{{color:var(--good)}}.decision.weak{{color:var(--weak)}}.decision.no{{color:var(--bad)}}details{{border-top:1px solid var(--line);margin-top:10px;padding-top:10px}}summary{{cursor:pointer;font-weight:700}}.fine{{font-size:12px;color:var(--muted)}}.warning{{border-left:4px solid #f79009;background:#fffaeb;padding:10px 12px;border-radius:8px}}footer{{text-align:center;color:var(--muted);padding:20px}}@media(max-width:900px){{.boundary{{grid-template-columns:1fr 1fr}}.span4,.span5,.span7,.span8{{grid-column:span 12}}.hypotheses{{grid-template-columns:1fr}}}}@media(max-width:600px){{header{{padding:28px 16px}}main{{padding:14px 10px 40px}}.boundary{{grid-template-columns:1fr}}.metric-row{{grid-template-columns:1fr 1fr}}.metric:last-child{{grid-column:span 2}}.overlap{{grid-template-columns:78px repeat(4,minmax(48px,1fr));font-size:10px}}.card{{padding:12px}}}}
</style>
</head>
<body>
<header>
  <div class="eyebrow">Statistical validation review · V1</div>
  <h1>四个默认相似K线模板<br>统计有效性验证</h1>
  <p>只验证统计指标有没有解释力。固定算法、固定四模板，不评价模型，不预测收益，不连接正式产品。</p>
  <div class="notice">not for model evaluation</div>
</header>
<main>
  <section class="boundary">
    <article><b>本地数据</b><span>{data["boundaries"]["source"]}<br>{data["boundaries"]["dailyRange"]}</span></article>
    <article><b>冻结算法</b><span>前复权 log-close；窗口内独立 z 标准化；单窗口 Pearson</span></article>
    <article><b>历史解释</b><span>月末固定模板事后描述；不是回测、评价或预测</span></article>
    <article><b>泄漏审计</b><span>无未来收益、无 IC、无策略表现、未读 sealed final、未联网</span></article>
  </section>
  <nav class="tabs" id="tabs"></nav>
  <div id="panels"></div>
  <section class="section-title"><div><h2>四模板重合矩阵</h2><p>同一 TopK 股票集合的 Jaccard；越高越容易跨类混淆。</p></div><div class="controls" id="overlap-controls"></div></section>
  <section class="card"><div id="overlap"></div></section>
  <section class="section-title"><div><h2>假设结论</h2><p>支持 / 较弱 / 不支持，连同证据、稳定性和产品去向。</p></div></section>
  <section class="hypotheses" id="hypotheses"></section>
  <section class="section-title"><div><h2>方法、边界与审计</h2></div></section>
  <section class="card">
    <div class="warning">历史行业按申万成员 in_date/out_date 还原，历史市值按截面 daily_basic 读取。固定模板可能晚于部分历史截面，因此只能解释“当时有哪些窗口后来被这个固定模板匹配”，不能写成当时可用的模型表现。</div>
    <details open><summary>统计口径</summary><p class="fine">{data["method"]["ranking"]}。{data["method"]["percentile"]}。{data["method"]["qualified"]}。</p></details>
    <details><summary>数据完整性</summary><p class="fine">日线共 {data["audit"]["marketRows"].toLocaleString() if False else data["audit"]["marketRows"]} 行、{data["audit"]["marketCodes"]} 个代码；当前行业重叠成员行 {data["audit"]["currentIndustryOverlapRows"]}，历史截面最大重叠成员行 {data["audit"]["activeIndustryOverlapRowsMax"]}。重叠时保留最近 in_date，并在原始数据中留痕。</p></details>
  </section>
</main>
<footer>生成日期 2026-07-29 · 分支 codex/template-analysis-validation-v1 · 非正式本地统计验证页</footer>
<script>
const DATA={payload};
const labels=Object.fromEntries(DATA.templates.map(x=>[x.key,x.label]));
const esc=s=>String(s).replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
const pct=x=>(x*100).toFixed(1)+"%";
const score=x=>(x*100).toFixed(1);
function candleVolume(t){{
 const b=t.bars,W=650,H=260,p={{l:38,r:8,t:10,b:22}},priceH=165,volTop=190,volH=42,lo=Math.min(...b.map(x=>x.low)),hi=Math.max(...b.map(x=>x.high)),range=hi-lo||1,vm=Math.max(...b.map(x=>x.volume)),step=(W-p.l-p.r)/b.length,body=Math.max(1.2,step*.6),x=i=>p.l+(i+.5)*step,y=v=>p.t+(hi-v)*priceH/range,vy=v=>volTop+volH*(1-v/vm);
 const bars=b.map((d,i)=>{{const c=d.close>=d.open?"#d94f4f":"#139a78",yo=y(d.open),yc=y(d.close);return `<line x1="${{x(i)}}" x2="${{x(i)}}" y1="${{y(d.high)}}" y2="${{y(d.low)}}" stroke="${{c}}"/><rect x="${{x(i)-body/2}}" y="${{Math.min(yo,yc)}}" width="${{body}}" height="${{Math.max(1,Math.abs(yo-yc))}}" fill="${{c}}"><title>${{d.date}} O${{d.open}} H${{d.high}} L${{d.low}} C${{d.close}}</title></rect><rect x="${{x(i)-body/2}}" y="${{vy(d.volume)}}" width="${{body}}" height="${{volTop+volH-vy(d.volume)}}" fill="${{c}}" opacity=".55"/>`}}).join("");
 return `<div class="chart-title"><span>固定模板前复权 K 线 + 成交量</span><span>${{t.startLabel}} → ${{t.endLabel}}</span></div><svg viewBox="0 0 ${{W}} ${{H}}">${{[0,.5,1].map(r=>`<line x1="${{p.l}}" x2="${{W-p.r}}" y1="${{p.t+r*priceH}}" y2="${{p.t+r*priceH}}" stroke="#e5e7eb"/>`).join("")}}${{bars}}<text x="${{p.l}}" y="${{H-5}}" font-size="9" fill="#667085">${{t.startLabel}}</text><text x="${{W-p.r}}" y="${{H-5}}" text-anchor="end" font-size="9" fill="#667085">${{t.endLabel}}</text></svg>`;
}}
function histogram(t){{
 const bins=t.current.histogram,W=650,H=220,p={{l:36,r:8,t:10,b:25}},max=Math.max(...bins.map(x=>x.count)),bw=(W-p.l-p.r)/bins.length;
 return `<div class="chart-title"><span>完整合格股票池 Pearson 分布</span><span>灰线：中位数；橙线：前1%</span></div><svg viewBox="0 0 ${{W}} ${{H}}">${{bins.map((b,i)=>`<rect x="${{p.l+i*bw+1}}" y="${{p.t+(H-p.t-p.b)*(1-b.count/max)}}" width="${{Math.max(1,bw-2)}}" height="${{(H-p.t-p.b)*b.count/max}}" fill="${{t.accent}}" opacity=".72"/>`).join("")}}${{[t.current.distribution.median,t.current.distribution.p99].map((v,i)=>{{const x=p.l+(v+1)/2*(W-p.l-p.r);return `<line x1="${{x}}" x2="${{x}}" y1="${{p.t}}" y2="${{H-p.b}}" stroke="${{i?"#f79009":"#667085"}}" stroke-width="2"/>`}}).join("")}}<text x="${{p.l}}" y="${{H-6}}" font-size="9">-1</text><text x="${{W-p.r}}" y="${{H-6}}" text-anchor="end" font-size="9">+1</text></svg>`;
}}
function trend(t,key,label,color){{
 const rows=DATA.history.filter(x=>x.template===t.key),W=650,H=220,p={{l:40,r:8,t:12,b:28}},vals=rows.map(x=>x[key]),clean=vals.filter(x=>x!=null),lo=Math.min(...clean),hi=Math.max(...clean),range=hi-lo||1,x=i=>p.l+i*(W-p.l-p.r)/Math.max(rows.length-1,1),y=v=>p.t+(hi-v)*(H-p.t-p.b)/range,d=rows.map((r,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(r[key]).toFixed(1)).join(" ");
 return `<div class="chart-title"><span>${{label}}</span><span>${{rows[0].as_of.slice(0,6)}} → ${{rows.at(-1).as_of.slice(0,6)}}</span></div><svg viewBox="0 0 ${{W}} ${{H}}"><path d="${{d}}" fill="none" stroke="${{color}}" stroke-width="2.5"/><text x="${{p.l-4}}" y="${{p.t+4}}" text-anchor="end" font-size="9">${{hi.toFixed(key.includes("score")?2:0)}}</text><text x="${{p.l-4}}" y="${{H-p.b}}" text-anchor="end" font-size="9">${{lo.toFixed(key.includes("score")?2:0)}}</text>${{rows.map((r,i)=>i%3===0?`<text x="${{x(i)}}" y="${{H-7}}" text-anchor="middle" font-size="8" fill="#667085">${{r.as_of.slice(2,6)}}</text>`:"").join("")}}</svg>`;
}}
function distTable(rows,type){{
 const sorted=[...rows].sort((a,b)=>b.share-a.share).slice(0,type==="industry"?8:5);
 return `<table><thead><tr><th>${{type==="industry"?"行业":"市值层级"}}</th><th>Top占比</th><th>全市场</th><th>超额</th></tr></thead><tbody>${{sorted.map(r=>`<tr><td>${{esc(r.name)}}<div class="bar"><i style="width:${{Math.min(100,r.share*100)}}%"></i></div></td><td>${{pct(r.share)}}</td><td>${{pct(r.marketShare)}}</td><td>${{r.excessPp>0?"+":""}}${{r.excessPp.toFixed(1)}}pp</td></tr>`).join("")}}</tbody></table>`;
}}
function panel(t,index){{
 const d=t.current.distribution;
 return `<section class="panel${{index===0?" active":""}}" id="panel-${{t.key}}" style="--accent:${{t.accent}}"><div class="section-title"><div><h2>${{t.label}} · ${{t.name}} ${{t.code}}</h2><p>${{t.cue}} · ${{t.windowBars}} 根</p></div><b>截至 ${{DATA.asOfLabel}}</b></div><div class="grid"><article class="card span7">${{candleVolume(t)}}</article><article class="card span5"><div class="metric-row"><div class="metric"><b>${{score(d.max)}}</b><span>最高 Pearson ×100</span></div><div class="metric"><b>${{score(d.median)}}</b><span>全市场中位数</span></div><div class="metric"><b>${{score(d.p99)}}</b><span>前1%分数线</span></div><div class="metric"><b>${{d.qualifiedCountP99}}</b><span>前1%数量</span></div><div class="metric"><b>${{d.eligibleCount}}</b><span>完整合格股票</span></div></div>${{histogram(t)}}</article><article class="card span12"><div class="controls">${{DATA.method.topKs.map(k=>`<button class="kbtn${{k===30?" active":""}}" data-template="${{t.key}}" data-k="${{k}}">Top${{k}}</button>`).join("")}}</div><div class="grid"><div class="span7" id="industry-${{t.key}}"></div><div class="span5" id="cap-${{t.key}}"></div></div><div class="fine" id="concentration-${{t.key}}"></div></article><article class="card span7">${{trend(t,"qualified_count_current_p99","超过当前前1%线的历史数量",t.accent)}}</article><article class="card span5">${{trend(t,"top30_turnover","月度 Top30 换手率","#344054")}}</article><article class="card span12"><h3>当前 Top100 明细（默认收起）</h3><details><summary>展开股票、百分位与异常标记</summary><table><thead><tr><th>排名 / 股票</th><th>Pearson</th><th>百分位</th><th>行业</th><th>市值</th><th>异常</th></tr></thead><tbody>${{t.top100.map(x=>`<tr><td>#${{x.rank}} ${{esc(x.name)}} ${{x.ts_code}}</td><td>${{score(x.score)}}</td><td>${{x.percentile.toFixed(2)}}%</td><td>${{esc(x.industry)}}</td><td>${{esc(x.cap_tier)}}</td><td>${{x.event_driven?"有":"无"}}</td></tr>`).join("")}}</tbody></table></details></article></div></section>`;
}}
const tabs=document.querySelector("#tabs"),panels=document.querySelector("#panels");
DATA.templates.forEach((t,i)=>{{tabs.insertAdjacentHTML("beforeend",`<button class="tab" aria-selected="${{i===0}}" data-key="${{t.key}}">${{t.label}} · ${{t.windowBars}}根</button>`);panels.insertAdjacentHTML("beforeend",panel(t,i));}});
function renderBreakdown(key,k){{const s=DATA.topKStats.find(x=>x.template===key&&x.topK===k);document.querySelector("#industry-"+key).innerHTML=`<h3>行业分布与相对全市场超额</h3>${{distTable(s.industry,"industry")}}`;document.querySelector("#cap-"+key).innerHTML=`<h3>市值分布与相对全市场超额</h3>${{distTable(s.cap,"cap")}}`;document.querySelector("#concentration-"+key).innerHTML=`行业覆盖 ${{s.industryConcentration.coverage}} · Top1 ${{pct(s.industryConcentration.top1Share)}} · HHI ${{s.industryConcentration.hhi.toFixed(3)}}；异常事件 ${{pct(s.anomalies.anyEventShare)}}（涨跌停 ${{pct(s.anomalies.upDownLimitShare)}} / 停牌 ${{pct(s.anomalies.suspensionShare)}} / 异常单日 ${{pct(s.anomalies.abnormalDayShare)}}）`;}}
DATA.templates.forEach(t=>renderBreakdown(t.key,30));
document.addEventListener("click",e=>{{const tab=e.target.closest(".tab");if(tab){{document.querySelectorAll(".tab").forEach(x=>x.setAttribute("aria-selected",x===tab));document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+tab.dataset.key));}}const kb=e.target.closest(".kbtn[data-template]");if(kb){{document.querySelectorAll(`.kbtn[data-template="${{kb.dataset.template}}"]`).forEach(x=>x.classList.toggle("active",x===kb));renderBreakdown(kb.dataset.template,Number(kb.dataset.k));}}}});
function renderOverlap(k){{const rows=DATA.overlaps.filter(x=>x.topK===k),keys=DATA.templates.map(x=>x.key);document.querySelector("#overlap").innerHTML=`<div class="overlap"><div></div>${{keys.map(x=>`<div class="head">${{labels[x]}}</div>`).join("")}}${{keys.map(l=>`<div class="head">${{labels[l]}}</div>${{keys.map(r=>{{const x=rows.find(v=>v.left===l&&v.right===r);const a=l===r?1:x.jaccard;return `<div style="background:rgba(109,91,208,${{.08+a*.65}})">${{l===r?"—":pct(a)}}<br><small>${{l===r?k:x.intersection}}只</small></div>`}}).join("")}}`).join("")}}</div>`;}}
DATA.method.topKs.forEach(k=>document.querySelector("#overlap-controls").insertAdjacentHTML("beforeend",`<button class="kbtn overlap-btn${{k===30?" active":""}}" data-overlap="${{k}}">Top${{k}}</button>`));renderOverlap(30);
document.querySelector("#overlap-controls").addEventListener("click",e=>{{const b=e.target.closest("[data-overlap]");if(!b)return;document.querySelectorAll(".overlap-btn").forEach(x=>x.classList.toggle("active",x===b));renderOverlap(Number(b.dataset.overlap));}});
document.querySelector("#hypotheses").innerHTML=DATA.hypotheses.map(h=>`<article class="card"><div class="decision ${{h.decision==="支持"?"support":h.decision==="较弱"?"weak":"no"}}">${{h.id}} · ${{h.decision}} · ${{h.product}}</div><h3>${{esc(h.title)}}</h3><p>${{esc(h.evidence)}}</p><details><summary>稳定性与异常驱动审计</summary><p class="fine">${{esc(h.stability)}}。${{esc(h.outlierAudit)}}</p></details></article>`).join("");
</script>
</body>
</html>"""


def notes_document(data: dict) -> str:
    lines = [
        "# 四个默认相似K线模板：统计有效性验证 V1",
        "",
        f"- 截面：{data['asOfLabel']}",
        f"- 实际分支：{data['branch']}",
        f"- 标记：{data['reviewLabel']}",
        "",
        "## 先验假设与结论",
        "",
    ]
    for item in data["hypotheses"]:
        lines.extend(
            [
                f"### {item['id']} {item['title']}：{item['decision']}",
                "",
                f"- 先验：{item['statement']}",
                f"- 证据：{item['evidence']}",
                f"- 稳定性：{item['stability']}",
                f"- 少数异常股票审计：{item['outlierAudit']}",
                f"- 产品建议：{item['product']}",
                "",
            ]
        )
    lines.extend(
        [
            "## 方法与边界",
            "",
            f"- 核心算法：{data['method']['score']}。",
            f"- 排名：{data['method']['ranking']}。",
            f"- 历史：{data['boundaries']['historicalInterpretation']}。",
            "- 明确未使用：未来收益、IC、策略表现、sealed final、联网行情。",
            f"- 行业：{data['boundaries']['industryPointInTime']}。",
            f"- 市值：{data['boundaries']['marketCapPointInTime']}。",
            "",
            "## 产品总建议",
            "",
            "- 首页保留：全市场百分位、前1%线、最高分、合格数量、行业覆盖/集中度、弱供给提示。",
            "- 专门分析页：行业与市值超额占比、TopK 敏感性、跨模板重合矩阵、历史扩散与换手、涨跌停/停牌/最大单日拆分字段。",
            "- 不采用：统一“90分合格线”、用原始 Pearson 跨模板比较、合并异常事件二元总开关、把历史固定模板回看写成模型评价或预测。",
        ]
    )
    return "\n".join(lines) + "\n"


def validate(data: dict, tables: dict[str, pd.DataFrame]) -> None:
    boundaries = data["boundaries"]
    forbidden = (
        boundaries["networkUsed"],
        boundaries["sealedFinalRead"],
        boundaries["futureReturnUsed"],
        boundaries["icUsed"],
        boundaries["strategyPerformanceUsed"],
    )
    if any(forbidden):
        raise RuntimeError("泄漏审计失败")
    if data["branch"] != "codex/template-analysis-validation-v1":
        raise RuntimeError("输出分支标记错误")
    if len(data["templates"]) != 4 or len(data["hypotheses"]) != 8:
        raise RuntimeError("模板或假设数量不完整")
    for template in data["templates"]:
        if len(template["bars"]) != template["windowBars"]:
            raise RuntimeError(f"{template['label']}: 模板根数漂移")
        scores = tables["current_scores"]
        subset = scores[scores["template"] == template["key"]]
        if len(subset) != template["current"]["distribution"]["eligibleCount"]:
            raise RuntimeError(f"{template['label']}: 完整分布行数不一致")
        if not subset["score"].between(-1, 1).all():
            raise RuntimeError(f"{template['label']}: Pearson 越界")
        if subset["rank"].tolist() != list(range(1, len(subset) + 1)):
            raise RuntimeError(f"{template['label']}: 排名不连续")
        if not subset["score"].is_monotonic_decreasing:
            raise RuntimeError(f"{template['label']}: 分数未降序")
    if tables["historical_snapshots"]["as_of"].max() != data["asOf"]:
        raise RuntimeError("历史序列未覆盖当前截面")


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"输出必须位于工作区：{output}")
    if output.exists():
        raise RuntimeError(f"拒绝覆盖现有输出：{output}")
    if not ZERO_ROOT.exists() or not ZERO_CONFIG.exists():
        raise RuntimeError("本机 zer0share 或配置文件不存在")

    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        data, tables = build_data(pro)
    finally:
        os.chdir(previous_cwd)
    validate(data, tables)

    output.mkdir(parents=True)
    (output / "validation-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "hypothesis-conclusions.json").write_text(
        json.dumps(data["hypotheses"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "review-notes.md").write_text(
        notes_document(data), encoding="utf-8"
    )
    (output / "index.html").write_text(html_document(data), encoding="utf-8")
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
    data_qa = {
        "pass": True,
        "templateCount": len(data["templates"]),
        "hypothesisCount": len(data["hypotheses"]),
        "currentScoreRows": int(len(tables["current_scores"])),
        "currentEligibleByTemplate": {
            item["label"]: item["current"]["distribution"]["eligibleCount"]
            for item in data["templates"]
        },
        "topKSensitivityRows": int(len(tables["current_topk_stats"])),
        "overlapMatrixRows": int(len(tables["overlap_matrix"])),
        "historicalSnapshotRows": int(len(tables["historical_snapshots"])),
        "historicalAsOfCount": int(
            tables["historical_snapshots"]["as_of"].nunique()
        ),
        "scoreRangeValid": bool(
            tables["current_scores"]["score"].between(-1, 1).all()
        ),
        "rankSequencesValid": all(
            frame["rank"].tolist() == list(range(1, len(frame) + 1))
            for _, frame in tables["current_scores"].groupby("template")
        ),
        "leakageAudit": {
            "networkUsed": data["boundaries"]["networkUsed"],
            "sealedFinalRead": data["boundaries"]["sealedFinalRead"],
            "futureReturnUsed": data["boundaries"]["futureReturnUsed"],
            "icUsed": data["boundaries"]["icUsed"],
            "strategyPerformanceUsed": data["boundaries"][
                "strategyPerformanceUsed"
            ],
        },
    }
    (output / "qa-data-results.json").write_text(
        json.dumps(data_qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(output / "index.html")
    print(
        json.dumps(
            {
                "asOf": data["asOf"],
                "templates": {
                    item["label"]: item["current"]["distribution"]
                    for item in data["templates"]
                },
                "hypotheses": {
                    item["id"]: item["decision"] for item in data["hypotheses"]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
