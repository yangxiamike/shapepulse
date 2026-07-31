from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from zer0share import pro_api

from build_template_statistical_validation import (
    TEMPLATES,
    ZERO_CONFIG,
    ZERO_ROOT,
    active_codes,
    active_industry_map,
    build_series,
    cap_tier,
    date_label,
    hhi,
    load_market_data,
    load_stock_metadata,
    load_templates,
    score_cross_section,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "template-dynamics-validation-v2-20260729"
)
HISTORY_START = "20241201"
TOP_KS = (5, 10, 30, 100)
STATES = (
    "刚突破",
    "健康上涨",
    "回调转强",
    "抛物线上升",
    "混合",
    "无状态",
)
CAP_TIERS = ("小于50亿", "50–200亿", "200–1000亿", "1000亿以上", "市值缺失")
SEED = 20260729


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def safe(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(
        frame.replace({np.nan: None}).to_json(orient="records", force_ascii=False)
    )


def snapshot_dates(market: pd.DataFrame, as_of: str) -> dict[str, list[str]]:
    dates = sorted(
        d
        for d in market["trade_date"].astype(str).unique()
        if HISTORY_START <= d <= as_of
    )
    weeks: dict[str, str] = {}
    months: dict[str, str] = {}
    for d in dates:
        stamp = pd.Timestamp(d)
        iso = stamp.isocalendar()
        weeks[f"{iso.year}-{iso.week:02d}"] = d
        months[d[:6]] = d
    return {"weekly": list(weeks.values()), "monthly": list(months.values())}


def percentile_group(values: pd.Series) -> pd.Series:
    ranks = values.rank(method="first", pct=True)
    return pd.cut(
        ranks,
        bins=[0, 0.2, 0.4, 0.6, 0.8, 1],
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        include_lowest=True,
    ).astype(str)


def annotate(
    scored: pd.DataFrame, industry_map: dict[str, str], mv_map: dict[str, float]
) -> pd.DataFrame:
    frame = scored[["ts_code", "score"]].copy()
    n = len(frame)
    frame["rank"] = np.arange(1, n + 1)
    frame["percentile"] = (n - frame["rank"] + 1) / n * 100
    frame["industry"] = frame["ts_code"].map(industry_map).fillna("行业缺失")
    frame["total_mv"] = frame["ts_code"].map(mv_map)
    frame["cap_tier"] = frame["total_mv"].map(cap_tier)
    available = frame["total_mv"].notna()
    frame["cap_percentile"] = "市值缺失"
    if available.any():
        frame.loc[available, "cap_percentile"] = percentile_group(
            frame.loc[available, "total_mv"]
        )
    return frame


def control_summary(template_z: np.ndarray, bars: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)

    def batch(kind: str) -> np.ndarray:
        if kind == "random":
            increments = rng.normal(0.0, 0.018, size=(5000, bars))
        else:
            slopes = rng.uniform(0.00025, 0.0018, size=(5000, 1))
            increments = slopes + rng.normal(0.0, 0.011, size=(5000, bars))
        paths = np.cumsum(increments, axis=1)
        paths -= paths.mean(axis=1, keepdims=True)
        std = paths.std(axis=1, keepdims=True)
        paths /= np.where(std <= 1e-12, 1.0, std)
        return np.mean(paths * template_z[None, :], axis=1)

    output = {}
    for kind in ("random", "ordinary_up"):
        values = batch(kind)
        output[kind] = {
            "count": len(values),
            "p95": float(np.quantile(values, 0.95)),
            "p99": float(np.quantile(values, 0.99)),
            "max": float(values.max()),
        }
    return output


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return max(0.0, center - half), min(1.0, center + half)


def corr(left: pd.Series, right: pd.Series) -> float | None:
    if len(left) < 3 or left.nunique() < 2 or right.nunique() < 2:
        return None
    return safe(np.corrcoef(left.to_numpy(float), right.to_numpy(float))[0, 1])


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def classify_state(labels: list[str]) -> str:
    if not labels:
        return "无状态"
    if len(labels) > 1:
        return "混合"
    return labels[0]


def build_raw(pro):
    market, as_of = load_market_data(pro)
    stocks = load_stock_metadata(pro)
    members = pro.index_member_all(
        fields="ts_code,l1_code,l1_name,in_date,out_date,is_new"
    )
    for column in ("ts_code", "in_date", "out_date"):
        members[column] = members[column].astype(str).replace("nan", np.nan)
    templates = load_templates(market)
    series = build_series(market)
    frequencies = snapshot_dates(market, as_of)
    all_dates = sorted(set(frequencies["weekly"]) | set(frequencies["monthly"]))
    scores: dict[str, dict[str, pd.DataFrame]] = {}
    industry_maps: dict[str, dict[str, str]] = {}
    mv_maps: dict[str, dict[str, float]] = {}
    overlap_max = 0

    for idx, current in enumerate(all_dates, start=1):
        codes = active_codes(stocks, current)
        industry_map, overlap = active_industry_map(members, current)
        overlap_max = max(overlap_max, overlap)
        basic = pro.daily_basic(
            trade_date=current, fields="ts_code,trade_date,total_mv"
        )
        mv_map = (
            basic.drop_duplicates("ts_code")
            .set_index("ts_code")["total_mv"]
            .map(float)
            .to_dict()
        )
        industry_maps[current] = industry_map
        mv_maps[current] = mv_map
        scores[current] = {}
        for template in TEMPLATES:
            scored = score_cross_section(
                series=series,
                codes=codes,
                as_of=current,
                bars=template.bars,
                template_z=templates[template.key]["z"],
            )
            scores[current][template.key] = annotate(scored, industry_map, mv_map)
        if idx % 10 == 0 or idx == len(all_dates):
            print(f"scored {idx}/{len(all_dates)} snapshots", flush=True)
    return {
        "market": market,
        "stocks": stocks,
        "templates": templates,
        "series": series,
        "as_of": as_of,
        "frequencies": frequencies,
        "scores": scores,
        "industry_maps": industry_maps,
        "mv_maps": mv_maps,
        "overlap_max": overlap_max,
    }


def build_thresholds(raw) -> tuple[pd.DataFrame, dict[str, float]]:
    monthly = raw["frequencies"]["monthly"]
    calibration = monthly[: min(12, len(monthly))]
    rows = []
    values = {}
    for pos, template in enumerate(TEMPLATES):
        p99s = [
            float(np.quantile(raw["scores"][d][template.key]["score"], 0.99))
            for d in calibration
        ]
        controls = control_summary(
            raw["templates"][template.key]["z"], template.bars, SEED + pos
        )
        threshold = float(np.quantile(p99s, 0.75))
        values[template.key] = threshold
        latest = raw["scores"][raw["as_of"]][template.key]
        latest_max = float(latest["score"].max())
        random_extreme = controls["random"]["max"]
        ordinary_extreme = controls["ordinary_up"]["max"]
        risk = (
            "高"
            if threshold <= min(random_extreme, ordinary_extreme)
            else "中"
            if threshold <= max(random_extreme, ordinary_extreme)
            else "较低"
        )
        rows.append(
            {
                "template": template.key,
                "label": template.label,
                "window_bars": template.bars,
                "calibration_start": calibration[0],
                "calibration_end": calibration[-1],
                "calibration_months": len(calibration),
                "calibration_p99_median": float(np.median(p99s)),
                "calibration_p99_q75": threshold,
                "frozen_threshold": threshold,
                "random_p99": controls["random"]["p99"],
                "random_max_5000": random_extreme,
                "ordinary_up_p99": controls["ordinary_up"]["p99"],
                "ordinary_up_max_5000": ordinary_extreme,
                "latest_max": latest_max,
                "latest_above_random_max": latest_max > random_extreme,
                "latest_above_ordinary_max": latest_max > ordinary_extreme,
                "false_positive_risk": risk,
                "purpose": "供给筛选下限；不是预测阈值、真值标签或固定Top1%",
            }
        )
    return pd.DataFrame(rows), values


def build_distributions(raw, thresholds):
    rows = []
    consistency = []
    for freq, dates in raw["frequencies"].items():
        for template in TEMPLATES:
            p99_history = []
            prior_qualified: list[set[str]] = []
            template_rows = []
            for current in dates:
                frame = raw["scores"][current][template.key]
                values = frame["score"].to_numpy(float)
                threshold = thresholds[template.key]
                qualified = set(frame.loc[frame["score"] >= threshold, "ts_code"])
                rolling = (
                    float(np.quantile(p99_history[-26:], 0.75))
                    if p99_history
                    else None
                )
                q_counts = frame.loc[frame["score"] >= threshold, "industry"].value_counts()
                template_rows.append(
                    {
                        "frequency": freq,
                        "as_of": current,
                        "template": template.key,
                        "eligible_count": len(frame),
                        "max_score": float(values.max()),
                        "median_score": float(np.median(values)),
                        "p05_score": float(np.quantile(values, 0.05)),
                        "p95_score": float(np.quantile(values, 0.95)),
                        "p99_score": float(np.quantile(values, 0.99)),
                        "distribution_width_p95_p05": float(
                            np.quantile(values, 0.95) - np.quantile(values, 0.05)
                        ),
                        "frozen_threshold": threshold,
                        "rolling_reference": rolling,
                        "qualified_count": len(qualified),
                        "qualified_share": len(qualified) / len(frame),
                        "industry_width": int(len(q_counts)),
                        "industry_hhi": (
                            float(np.sum((q_counts / q_counts.sum()) ** 2))
                            if len(q_counts)
                            else 0.0
                        ),
                    }
                )
                consistency.append(
                    {
                        "frequency": freq,
                        "as_of": current,
                        "template": template.key,
                        "qualified_count": len(qualified),
                        "consistent_2_count": (
                            len(qualified & prior_qualified[-1])
                            if len(prior_qualified) >= 1
                            else 0
                        ),
                        "consistent_3_count": (
                            len(qualified & prior_qualified[-1] & prior_qualified[-2])
                            if len(prior_qualified) >= 2
                            else 0
                        ),
                    }
                )
                prior_qualified.append(qualified)
                p99_history.append(float(np.quantile(values, 0.99)))
            p99_values = np.array([row["p99_score"] for row in template_rows])
            for row in template_rows:
                pct = float(np.mean(p99_values <= row["p99_score"]))
                row["historical_percentile"] = pct
                row["historical_position"] = (
                    "高" if pct >= 2 / 3 else "低" if pct <= 1 / 3 else "中"
                )
            rows.extend(template_rows)
    return pd.DataFrame(rows), pd.DataFrame(consistency)


def build_memberships_and_stability(raw, thresholds):
    stability_rows = []
    member_rows = []
    qualified_rows = []
    streaks: dict[tuple[str, str, int, str], int] = {}
    for freq, dates in raw["frequencies"].items():
        for template in TEMPLATES:
            previous = None
            for current in dates:
                frame = raw["scores"][current][template.key]
                lookup = frame.set_index("ts_code")[["rank", "percentile"]]
                threshold = thresholds[template.key]
                q = frame[frame["score"] >= threshold]
                for row in q.itertuples(index=False):
                    qualified_rows.append(
                        {
                            "frequency": freq,
                            "as_of": current,
                            "template": template.key,
                            "ts_code": row.ts_code,
                            "score": row.score,
                            "percentile": row.percentile,
                            "exceedance": row.score - threshold,
                            "industry": row.industry,
                            "cap_tier": row.cap_tier,
                            "cap_percentile": row.cap_percentile,
                        }
                    )
                for k in TOP_KS:
                    current_set = set(frame.head(k)["ts_code"])
                    for code in current_set:
                        key = (freq, template.key, k, code)
                        streaks[key] = streaks.get(key, 0) + 1
                        row = lookup.loc[code]
                        member_rows.append(
                            {
                                "frequency": freq,
                                "as_of": current,
                                "template": template.key,
                                "top_k": k,
                                "ts_code": code,
                                "rank": int(row["rank"]),
                                "percentile": float(row["percentile"]),
                                "streak": streaks[key],
                            }
                        )
                    absent = [
                        key
                        for key in list(streaks)
                        if key[:3] == (freq, template.key, k) and key[3] not in current_set
                    ]
                    for key in absent:
                        streaks[key] = 0
                if previous is not None:
                    merged = previous.merge(
                        frame,
                        on="ts_code",
                        suffixes=("_prev", "_curr"),
                        how="inner",
                    )
                    top_union = set(previous.head(100)["ts_code"]) | set(
                        frame.head(100)["ts_code"]
                    )
                    rank_pair = pd.DataFrame({"ts_code": list(top_union)})
                    rank_pair = rank_pair.merge(
                        previous[["ts_code", "rank"]].rename(
                            columns={"rank": "rank_prev"}
                        ),
                        on="ts_code",
                        how="left",
                    ).merge(
                        frame[["ts_code", "rank"]].rename(columns={"rank": "rank_curr"}),
                        on="ts_code",
                        how="left",
                    )
                    rank_pair[["rank_prev", "rank_curr"]] = (
                        rank_pair[["rank_prev", "rank_curr"]]
                        .fillna(101)
                        .clip(upper=101)
                    )
                    for k in TOP_KS:
                        left = set(previous.head(k)["ts_code"])
                        right = set(frame.head(k)["ts_code"])
                        changed = left ^ right
                        boundary = 0
                        for code in changed:
                            rp = previous.loc[previous["ts_code"] == code, "rank"]
                            rc = frame.loc[frame["ts_code"] == code, "rank"]
                            if (
                                (len(rp) and 25 <= int(rp.iloc[0]) <= 35)
                                or (len(rc) and 25 <= int(rc.iloc[0]) <= 35)
                            ):
                                boundary += 1
                        stability_rows.append(
                            {
                                "frequency": freq,
                                "as_of": current,
                                "previous_as_of": str(
                                    previous.attrs.get("as_of", "")
                                ),
                                "template": template.key,
                                "top_k": k,
                                "retention": len(left & right) / k,
                                "turnover": 1 - len(left & right) / k,
                                "random_retention_baseline": k
                                / max(len(frame), len(previous)),
                                "all_percentile_corr": corr(
                                    merged["percentile_prev"],
                                    merged["percentile_curr"],
                                ),
                                "all_percentile_mae": float(
                                    np.mean(
                                        np.abs(
                                            merged["percentile_prev"]
                                            - merged["percentile_curr"]
                                        )
                                    )
                                ),
                                "top100_rank_corr": corr(
                                    rank_pair["rank_prev"], rank_pair["rank_curr"]
                                ),
                                "boundary_25_35_change_share": (
                                    boundary / len(changed) if changed else 0.0
                                ),
                                "common_eligible": len(merged),
                            }
                        )
                frame.attrs["as_of"] = current
                previous = frame
    return (
        pd.DataFrame(stability_rows),
        pd.DataFrame(member_rows),
        pd.DataFrame(qualified_rows),
    )


def build_jaccard(raw, thresholds):
    rows = []
    for freq, dates in raw["frequencies"].items():
        for current in dates:
            for left, right in combinations(TEMPLATES, 2):
                lf = raw["scores"][current][left.key]
                rf = raw["scores"][current][right.key]
                lq = set(lf.loc[lf["score"] >= thresholds[left.key], "ts_code"])
                rq = set(rf.loc[rf["score"] >= thresholds[right.key], "ts_code"])
                rows.append(
                    {
                        "frequency": freq,
                        "as_of": current,
                        "left": left.key,
                        "right": right.key,
                        "pair": f"{left.label}×{right.label}",
                        "top30_jaccard": jaccard(
                            set(lf.head(30)["ts_code"]), set(rf.head(30)["ts_code"])
                        ),
                        "qualified_jaccard": jaccard(lq, rq),
                        "qualified_intersection": len(lq & rq),
                    }
                )
    return pd.DataFrame(rows)


def build_states(raw, thresholds):
    state_rows = []
    transition_counts: dict[tuple[str, str, str], int] = Counter()
    dwell_values: dict[tuple[str, str], list[int]] = defaultdict(list)
    for freq, dates in raw["frequencies"].items():
        previous_states: dict[str, str] | None = None
        runs: dict[str, tuple[str, int]] = {}
        for current in dates:
            codes = set()
            qualified_by_template = {}
            for template in TEMPLATES:
                frame = raw["scores"][current][template.key]
                codes.update(frame["ts_code"])
                qualified_by_template[template.key] = set(
                    frame.loc[
                        frame["score"] >= thresholds[template.key], "ts_code"
                    ]
                )
            current_states = {}
            label_counter = Counter()
            for code in codes:
                labels = [
                    template.label
                    for template in TEMPLATES
                    if code in qualified_by_template[template.key]
                ]
                state = classify_state(labels)
                current_states[code] = state
                label_counter["+".join(labels) if labels else "无标签"] += 1
                old_state, run = runs.get(code, (state, 0))
                if old_state == state:
                    runs[code] = (state, run + 1)
                else:
                    dwell_values[(freq, old_state)].append(run)
                    runs[code] = (state, 1)
            counts = Counter(current_states.values())
            for state in STATES:
                state_rows.append(
                    {
                        "frequency": freq,
                        "as_of": current,
                        "state": state,
                        "count": counts.get(state, 0),
                        "share": counts.get(state, 0) / max(len(codes), 1),
                        "multi_label_detail": json.dumps(
                            label_counter, ensure_ascii=False, sort_keys=True
                        ),
                    }
                )
            if previous_states is not None:
                for code in set(previous_states) & set(current_states):
                    transition_counts[
                        (freq, previous_states[code], current_states[code])
                    ] += 1
            previous_states = current_states
        for _, (state, run) in runs.items():
            dwell_values[(freq, state)].append(run)

    transition_rows = []
    for freq in raw["frequencies"]:
        total_to = Counter()
        row_total = Counter()
        grand = 0
        for (f, old, new), count in transition_counts.items():
            if f == freq:
                row_total[old] += count
                total_to[new] += count
                grand += count
        for old in STATES:
            for new in STATES:
                count = transition_counts.get((freq, old, new), 0)
                rate = count / row_total[old] if row_total[old] else 0.0
                expected = (
                    row_total[old] * total_to[new] / grand if grand else 0.0
                )
                reverse_count = transition_counts.get((freq, new, old), 0)
                reverse_rate = (
                    reverse_count / row_total[new] if row_total[new] else 0.0
                )
                transition_rows.append(
                    {
                        "frequency": freq,
                        "from_state": old,
                        "to_state": new,
                        "count": count,
                        "row_rate": rate,
                        "random_expected_count": expected,
                        "lift_vs_random": count / expected if expected else None,
                        "reverse_row_rate": reverse_rate,
                        "asymmetry_pp": (rate - reverse_rate) * 100,
                    }
                )
    dwell_rows = []
    transition_frame = pd.DataFrame(transition_rows)
    for (freq, state), values in dwell_values.items():
        row = transition_frame[
            (transition_frame["frequency"] == freq)
            & (transition_frame["from_state"] == state)
            & (transition_frame["to_state"] == state)
        ]
        stay = float(row.iloc[0]["row_rate"]) if len(row) else 0.0
        dwell_rows.append(
            {
                "frequency": freq,
                "state": state,
                "run_count": len(values),
                "mean_duration": float(np.mean(values)) if values else 0.0,
                "median_duration": float(np.median(values)) if values else 0.0,
                "max_duration": int(max(values, default=0)),
                "exit_rate": 1 - stay,
            }
        )
    return pd.DataFrame(state_rows), transition_frame, pd.DataFrame(dwell_rows)


def build_industry(raw, thresholds):
    rows = []
    previous_sets: dict[tuple[str, str, str], set[str]] = {}
    previous_rates: dict[tuple[str, str, str], float] = {}
    for freq, dates in raw["frequencies"].items():
        for current in dates:
            for template in TEMPLATES:
                frame = raw["scores"][current][template.key]
                threshold = thresholds[template.key]
                qualified = frame[frame["score"] >= threshold]
                market_rate = len(qualified) / len(frame)
                total_q = max(len(qualified), 1)
                for industry, group in frame.groupby("industry"):
                    q = group[group["score"] >= threshold]
                    n = len(group)
                    qn = len(q)
                    low, high = wilson(qn, n)
                    current_set = set(q["ts_code"])
                    key = (freq, template.key, str(industry))
                    prior = previous_sets.get(key, set())
                    rate = qn / n
                    prior_rate = previous_rates.get(key)
                    strong = rate > market_rate
                    improving = prior_rate is not None and rate > prior_rate
                    status = (
                        "强且增强"
                        if strong and improving
                        else "强但走弱"
                        if strong
                        else "弱但改善"
                        if improving
                        else "弱且走弱"
                    )
                    rows.append(
                        {
                            "frequency": freq,
                            "as_of": current,
                            "template": template.key,
                            "industry": industry,
                            "eligible_count": n,
                            "qualified_count": qn,
                            "qualified_rate": rate,
                            "market_qualified_rate": market_rate,
                            "rate_excess_pp": (rate - market_rate) * 100,
                            "qualified_share": qn / total_q,
                            "market_member_share": n / len(frame),
                            "share_excess_pp": (qn / total_q - n / len(frame)) * 100,
                            "wilson_low": low,
                            "wilson_high": high,
                            "new_count": len(current_set - prior),
                            "retained_count": len(current_set & prior),
                            "exit_count": len(prior - current_set),
                            "status": status,
                            "small_sample": n < 30,
                        }
                    )
                    previous_sets[key] = current_set
                    previous_rates[key] = rate
    industry = pd.DataFrame(rows)
    industry["rate_percentile"] = industry.groupby(
        ["frequency", "as_of", "template"]
    )["qualified_rate"].rank(pct=True, method="average")

    migration_counts = Counter()
    for freq, dates in raw["frequencies"].items():
        previous = {}
        for current in dates:
            snap = industry[
                (industry["frequency"] == freq) & (industry["as_of"] == current)
            ]
            leaders = (
                snap.sort_values(
                    ["industry", "rate_percentile", "template"],
                    ascending=[True, False, True],
                )
                .drop_duplicates("industry")
                .set_index("industry")["template"]
                .to_dict()
            )
            for name in set(previous) & set(leaders):
                migration_counts[(freq, previous[name], leaders[name])] += 1
            previous = leaders
    migration = pd.DataFrame(
        [
            {
                "frequency": f,
                "from_template": old,
                "to_template": new,
                "count": count,
            }
            for (f, old, new), count in migration_counts.items()
        ]
    )
    return industry, migration


def build_electronics_audit(raw, thresholds, industry):
    rows = []
    current = raw["as_of"]
    for template in TEMPLATES:
        frame = raw["scores"][current][template.key]
        threshold = thresholds[template.key]
        group = frame[frame["industry"] == "电子"].sort_values("score", ascending=False)
        qn = int((group["score"] >= threshold).sum())
        rate = qn / max(len(group), 1)
        latest = industry[
            (industry["frequency"] == "monthly")
            & (industry["as_of"] == current)
            & (industry["template"] == template.key)
            & (industry["industry"] == "电子")
        ]
        all_latest = industry[
            (industry["frequency"] == "monthly")
            & (industry["as_of"] == current)
            & (industry["template"] == template.key)
            & (~industry["small_sample"])
        ].sort_values("qualified_rate", ascending=False)
        rank = (
            int(np.where(all_latest["industry"].to_numpy() == "电子")[0][0] + 1)
            if "电子" in set(all_latest["industry"])
            else None
        )
        positive = np.maximum(group["score"].to_numpy(float) - threshold, 0)
        total_excess = float(positive.sum())
        rows.append(
            {
                "template": template.key,
                "label": template.label,
                "eligible_count": len(group),
                "qualified_count": qn,
                "qualified_rate": rate,
                "industry_rank_min30": rank,
                "status": latest.iloc[0]["status"] if len(latest) else "缺失",
                "rate_excess_pp": (
                    float(latest.iloc[0]["rate_excess_pp"]) if len(latest) else None
                ),
                "top1_code": group.iloc[0]["ts_code"] if len(group) else None,
                "top3_exceedance_share": (
                    float(positive[:3].sum() / total_excess) if total_excess else 0.0
                ),
                "rate_without_top1": (
                    max(qn - int(group.iloc[0]["score"] >= threshold), 0)
                    / max(len(group) - 1, 1)
                    if len(group)
                    else 0.0
                ),
                "rate_without_top3": (
                    max(qn - int((group.head(3)["score"] >= threshold).sum()), 0)
                    / max(len(group) - min(3, len(group)), 1)
                ),
            }
        )
    return pd.DataFrame(rows)


def build_cap(raw, thresholds):
    rows = []
    shift_rows = []
    for freq, dates in raw["frequencies"].items():
        previous = None
        for current in dates:
            for template in TEMPLATES:
                frame = raw["scores"][current][template.key]
                threshold = thresholds[template.key]
                market_rate = float(np.mean(frame["score"] >= threshold))
                for dimension in ("cap_tier", "cap_percentile"):
                    for group_name, group in frame.groupby(dimension):
                        qn = int((group["score"] >= threshold).sum())
                        rows.append(
                            {
                                "frequency": freq,
                                "as_of": current,
                                "template": template.key,
                                "dimension": dimension,
                                "group": group_name,
                                "eligible_count": len(group),
                                "qualified_count": qn,
                                "qualified_rate": qn / len(group),
                                "rate_excess_pp": (qn / len(group) - market_rate) * 100,
                            }
                        )
            current_map = pd.DataFrame(
                {
                    "ts_code": list(raw["mv_maps"][current]),
                    "total_mv": list(raw["mv_maps"][current].values()),
                }
            )
            current_map["cap_tier"] = current_map["total_mv"].map(cap_tier)
            current_map["cap_percentile"] = percentile_group(current_map["total_mv"])
            if previous is not None:
                merged = previous.merge(
                    current_map, on="ts_code", suffixes=("_prev", "_curr")
                )
                shift_rows.append(
                    {
                        "frequency": freq,
                        "as_of": current,
                        "common_codes": len(merged),
                        "fixed_tier_shift_rate": float(
                            np.mean(merged["cap_tier_prev"] != merged["cap_tier_curr"])
                        ),
                        "percentile_group_shift_rate": float(
                            np.mean(
                                merged["cap_percentile_prev"]
                                != merged["cap_percentile_curr"]
                            )
                        ),
                    }
                )
            previous = current_map
    return pd.DataFrame(rows), pd.DataFrame(shift_rows)


def resample_template(values: np.ndarray, length: int) -> np.ndarray:
    output = np.interp(
        np.linspace(0, 1, length), np.linspace(0, 1, len(values)), values
    )
    return (output - output.mean()) / output.std()


def build_window_sensitivity(raw):
    rows = []
    current = raw["as_of"]
    codes = active_codes(raw["stocks"], current)
    for template in TEMPLATES:
        base = raw["scores"][current][template.key]
        base_set = set(base.head(30)["ts_code"])
        for factor in (0.9, 1.1):
            bars = max(10, int(round(template.bars * factor)))
            z = resample_template(raw["templates"][template.key]["z"], bars)
            alt = score_cross_section(
                series=raw["series"],
                codes=codes,
                as_of=current,
                bars=bars,
                template_z=z,
            )
            rows.append(
                {
                    "template": template.key,
                    "variant": f"{factor:.1f}x",
                    "original_bars": template.bars,
                    "variant_bars": bars,
                    "top30_jaccard": jaccard(
                        base_set, set(alt.head(30)["ts_code"])
                    ),
                    "use": "仅稳健性扰动，不替换冻结模板，不做多窗口组合",
                }
            )
    return pd.DataFrame(rows)


def build_exclusion_robustness(raw, thresholds):
    rows = []
    current = raw["as_of"]
    for template in TEMPLATES:
        frame = raw["scores"][current][template.key]
        threshold = thresholds[template.key]
        base_rate = float(np.mean(frame["score"] >= threshold))
        variants = {"基准": frame, "去掉电子": frame[frame["industry"] != "电子"]}
        for count in (1, 3):
            kept = (
                frame.sort_values(["industry", "score"], ascending=[True, False])
                .groupby("industry", group_keys=False)
                .apply(lambda group: group.iloc[min(count, len(group)) :])
            )
            variants[f"每行业去Top{count}"] = kept
        for name, subset in variants.items():
            qualified_count = int((subset["score"] >= threshold).sum())
            rate = qualified_count / max(len(subset), 1)
            rows.append(
                {
                    "template": template.key,
                    "variant": name,
                    "eligible_count": len(subset),
                    "qualified_count": qualified_count,
                    "qualified_rate": rate,
                    "change_vs_base_pp": (rate - base_rate) * 100,
                }
            )
    return pd.DataFrame(rows)


def conclusions(
    thresholds,
    distribution,
    stability,
    jaccards,
    transitions,
    electronics,
    window_sensitivity,
    exclusion_robustness,
):
    threshold_range = float(
        thresholds["frozen_threshold"].max() - thresholds["frozen_threshold"].min()
    )
    cvs = distribution.groupby(["frequency", "template"])["qualified_count"].agg(
        lambda x: float(x.std(ddof=0) / x.mean()) if x.mean() else 0.0
    )
    max_cv = float(cvs.max())
    controls_hit = int(
        (
            (~thresholds["latest_above_random_max"])
            | (~thresholds["latest_above_ordinary_max"])
        ).sum()
    )
    monthly30 = stability[
        (stability["frequency"] == "monthly") & (stability["top_k"] == 30)
    ]
    boundary = float(monthly30["boundary_25_35_change_share"].median())
    whole_corr = float(monthly30["all_percentile_corr"].median())
    top100_turnover = float(
        stability[
            (stability["frequency"] == "monthly") & (stability["top_k"] == 100)
        ]["turnover"].median()
    )
    jaccard_spread = float(
        jaccards.groupby("pair")["top30_jaccard"].median().max()
        - jaccards.groupby("pair")["top30_jaccard"].median().min()
    )
    transition_lift = transitions[
        (transitions["from_state"] != "无状态")
        & (transitions["to_state"] != "无状态")
    ]["lift_vs_random"].replace([np.inf, -np.inf], np.nan)
    max_lift = float(transition_lift.max()) if transition_lift.notna().any() else 0.0
    electronic_weak = int(electronics["status"].isin(["强但走弱", "弱且走弱"]).sum())
    window_median = float(window_sensitivity["top30_jaccard"].median())
    exclusion_max_change = float(
        exclusion_robustness[
            exclusion_robustness["variant"] != "基准"
        ]["change_vs_base_pp"].abs().max()
    )

    return [
        {
            "id": "A1",
            "decision": "支持" if threshold_range >= 0.03 else "较弱",
            "evidence": f"四模板冻结阈值跨度 {threshold_range:.3f}；统一90分会混淆各模板自身尾部。",
            "stability": "校准期前12个月冻结；另列26周滚动历史参照。",
            "outlierAudit": f"{controls_hit}/4 个模板当前最高分未同时越过两类5000路径自然极值。",
            "product": "首页保留每模板冻结阈值与真实合格数",
        },
        {
            "id": "A2",
            "decision": "支持" if max_cv >= 0.25 else "较弱",
            "evidence": f"真实合格数量最大变异系数 {max_cv:.2f}，固定Top1%不能代表动态供应。",
            "stability": "周频与月末均复算，不补足TopK。",
            "outlierAudit": "零或不足TopK均原样保留。",
            "product": "首页保留",
        },
        {
            "id": "A3",
            "decision": "支持" if controls_hit >= 2 else "较弱",
            "evidence": f"{controls_hit}/4 个模板的当前最高分未同时战胜随机与普通上涨的5000路径最大值。",
            "stability": "长度匹配、固定随机种子、每模板独立对照。",
            "outlierAudit": "对照只审计自然极值，不参与排序。",
            "product": "阈值专页警示",
        },
        {
            "id": "B1",
            "decision": "支持" if max_cv >= 0.25 else "较弱",
            "evidence": f"最高分、P99、宽度与合格数共同显示供给位置；合格数最大CV {max_cv:.2f}。",
            "stability": "周频/月频与历史高中低位置一致展示。",
            "outlierAudit": "同时列中位数、P95/P99，避免只看最大值。",
            "product": "首页简卡＋专页时间序列",
        },
        {
            "id": "C1",
            "decision": (
                "支持"
                if boundary >= 0.35
                and whole_corr >= 0.7
                and top100_turnover <= 0.6
                else "较弱"
                if boundary >= 0.25
                and whole_corr >= 0.7
                and top100_turnover <= 0.8
                else "不支持"
            ),
            "evidence": f"月末Top30变动中25–35名边界占比中位数 {boundary:.1%}；全截面百分位相关 {whole_corr:.2f}，Top100换手 {top100_turnover:.1%}。",
            "stability": "Top5/10/30/100、周频/月频分别统计。",
            "outlierAudit": "若全截面相关也低，则明确归为整体失稳。",
            "product": "专页保留换手拆解",
        },
        {
            "id": "D1",
            "decision": "支持" if jaccard_spread >= 0.05 and max_lift >= 1.2 else "较弱",
            "evidence": f"六组Top30 Jaccard中位数跨度 {jaccard_spread:.1%}；非空状态迁移相对随机最大lift {max_lift:.2f}。",
            "stability": "周频/月频、Top30与真实合格集合并列。",
            "outlierAudit": "多标签保留；原始Pearson不跨模板比较。",
            "product": "专页保留，禁止预测措辞",
        },
        {
            "id": "E1",
            "decision": "支持" if electronic_weak >= 2 else "较弱",
            "evidence": f"电子在4模板中有 {electronic_weak} 个处于走弱象限；去Top1/Top3结果另列。",
            "stability": "使用时点申万成员、合格率与Wilson区间。",
            "outlierAudit": "同时审计Top3超过阈值程度占比。",
            "product": "行业专页，不用绝对数量下结论",
        },
        {
            "id": "E2/E3",
            "decision": "支持",
            "evidence": "行业使用合格率/超额占比；市值同时使用固定亿元层级与截面五分位。",
            "stability": "周频/月频、成员与daily_basic均按时点读取。",
            "outlierAudit": "小行业标记n<30并给95% Wilson区间。",
            "product": "专页保留双口径",
        },
        {
            "id": "F1",
            "decision": "支持" if window_median >= 0.25 else "较弱",
            "evidence": f"窗口±10%扰动Top30 Jaccard中位数 {window_median:.1%}；去电子/每行业去Top1/Top3后合格率最大变化 {exclusion_max_change:.2f}pp。",
            "stability": "TopK、频率、去龙头、去电子、随机基线、连续2–3期均有证据。",
            "outlierAudit": "多重比较只作探索性验证，不挑选显著结果。",
            "product": "仅跨稳健性成立的指标进入产品",
        },
    ]


def build_payload(raw, tables, conclusion_rows):
    thresholds = tables["thresholds"]
    latest_distribution = tables["distribution_snapshots"][
        (tables["distribution_snapshots"]["frequency"] == "monthly")
        & (tables["distribution_snapshots"]["as_of"] == raw["as_of"])
    ]
    template_payload = []
    for template in TEMPLATES:
        template_payload.append(
            {
                "key": template.key,
                "label": template.label,
                "bars": template.bars,
                "accent": template.accent,
                "threshold": records(
                    thresholds[thresholds["template"] == template.key]
                )[0],
                "latest": records(
                    latest_distribution[
                        latest_distribution["template"] == template.key
                    ]
                )[0],
            }
        )
    monthly_stability = tables["stability_pairs"][
        tables["stability_pairs"]["frequency"] == "monthly"
    ]
    stability_summary = (
        monthly_stability.groupby(["template", "top_k"], as_index=False)
        .agg(
            median_retention=("retention", "median"),
            median_turnover=("turnover", "median"),
            median_percentile_corr=("all_percentile_corr", "median"),
            median_boundary_share=("boundary_25_35_change_share", "median"),
        )
    )
    latest_industry = tables["industry_dynamic"][
        (tables["industry_dynamic"]["frequency"] == "monthly")
        & (tables["industry_dynamic"]["as_of"] == raw["as_of"])
        & (~tables["industry_dynamic"]["small_sample"])
    ].copy()
    latest_industry = (
        latest_industry.sort_values(
            ["template", "qualified_rate", "eligible_count"],
            ascending=[True, False, False],
        )
        .groupby("template")
        .head(8)
    )
    return {
        "title": "四模板动态供给、阈值与状态迁移验证 V2",
        "reviewLabel": "statistical validation review / not for model evaluation",
        "branch": "codex/template-dynamics-validation-v2",
        "generatedOn": "2026-07-29",
        "asOf": raw["as_of"],
        "asOfLabel": date_label(raw["as_of"]),
        "templates": template_payload,
        "distribution": records(tables["distribution_snapshots"]),
        "stabilitySummary": records(stability_summary),
        "jaccard": records(tables["dynamic_jaccard"]),
        "transitions": records(
            tables["state_transitions"][
                tables["state_transitions"]["frequency"] == "monthly"
            ]
        ),
        "dwell": records(tables["state_dwell"]),
        "industryLatest": records(latest_industry),
        "electronics": records(tables["electronics_audit"]),
        "capLatest": records(
            tables["cap_dynamic"][
                (tables["cap_dynamic"]["frequency"] == "monthly")
                & (tables["cap_dynamic"]["as_of"] == raw["as_of"])
            ]
        ),
        "windowSensitivity": records(tables["window_sensitivity"]),
        "exclusionRobustness": records(tables["exclusion_robustness"]),
        "conclusions": conclusion_rows,
        "boundaries": {
            "source": r"本机 zer0share（C:\Users\hp\Documents\zer0share）",
            "dailyRange": f"{date_label(str(raw['market']['trade_date'].min()))} 至 {date_label(raw['as_of'])}",
            "historyRange": f"{date_label(raw['frequencies']['weekly'][0])} 至 {date_label(raw['as_of'])}",
            "networkUsed": False,
            "sealedFinalRead": False,
            "futureReturnUsed": False,
            "icUsed": False,
            "strategyPerformanceUsed": False,
            "industryPointInTime": "申万成员按 in_date/out_date 还原",
            "marketCapPointInTime": "daily_basic 按截面 trade_date 读取 total_mv",
            "historicalInterpretation": "固定模板可能晚于历史截面，只能作事后描述，不能作预测或模型评价",
        },
        "audit": {
            "marketRows": len(raw["market"]),
            "marketCodes": raw["market"]["ts_code"].nunique(),
            "weeklyAsOfs": len(raw["frequencies"]["weekly"]),
            "monthlyAsOfs": len(raw["frequencies"]["monthly"]),
            "activeIndustryOverlapRowsMax": raw["overlap_max"],
        },
    }


def html_document(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{data["title"]}</title>
<style>
:root{{--ink:#17212b;--muted:#64717e;--line:#d8dee4;--paper:#f5f7f8;--card:#fff;--blue:#295f8d;--warn:#a85d16}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}}
header{{padding:34px max(18px,calc((100vw - 1280px)/2));background:#162533;color:#fff}}header h1{{margin:5px 0 8px;font-size:clamp(25px,4vw,42px)}}header p{{max-width:900px;color:#c7d5df}}.eyebrow{{color:#84c5e8;font-size:12px;letter-spacing:.12em;text-transform:uppercase}}.notice{{display:inline-block;padding:5px 9px;border:1px solid #688293;border-radius:5px;font-size:11px}}
main{{max-width:1280px;margin:auto;padding:18px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.card,details{{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 8px #2233440a}}.card{{padding:15px}}.card b{{display:block;font-size:20px}}.card span,.muted{{color:var(--muted);font-size:12px}}h2{{margin:26px 0 10px}}.tabs{{display:flex;gap:7px;overflow:auto;margin:18px 0 10px}}button{{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 13px;white-space:nowrap;cursor:pointer}}button[aria-selected=true]{{background:#17344b;color:#fff;border-color:#17344b}}.panel{{display:none}}.panel.active{{display:block}}.threshold{{border-top:4px solid var(--accent)}}.warn{{color:var(--warn)}}.chart{{width:100%;height:230px;background:#fbfcfd;border:1px solid #e3e8ec;border-radius:8px}}svg{{width:100%;height:100%}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{padding:8px;border-bottom:1px solid #e6eaed;text-align:right}}th:first-child,td:first-child{{text-align:left}}.scroll{{overflow:auto}}details{{margin:10px 0}}summary{{padding:14px;cursor:pointer;font-weight:700}}details>div{{padding:0 14px 14px}}.matrix{{display:grid;grid-template-columns:100px repeat(6,minmax(68px,1fr));gap:2px;min-width:620px}}.matrix div{{padding:7px;background:#f2f5f7;text-align:center;font-size:11px}}.matrix .head{{background:#20384c;color:#fff}}.conclusion{{border-left:4px solid #2c769f}}footer{{padding:28px;text-align:center;color:var(--muted);font-size:11px}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:560px){{main{{padding:10px}}.grid{{grid-template-columns:1fr}}header{{padding:24px 14px}}.card{{padding:12px}}}}
</style></head><body>
<header><div class="eyebrow">Template dynamics validation · V2</div><h1>{data["title"]}</h1>
<p>只描述固定模板在同期市场里的形态供给。阈值、稳定性、迁移、行业和市值均不使用未来收益、IC或策略表现。</p><div class="notice">{data["reviewLabel"]}</div></header>
<main>
<section class="grid" id="overview">
<article class="card"><b>{data["asOfLabel"]}</b><span>本地最新交易日</span></article>
<article class="card"><b>{data["audit"]["weeklyAsOfs"]} / {data["audit"]["monthlyAsOfs"]}</b><span>周频 / 月末截面</span></article>
<article class="card"><b>4 个独立阈值</b><span>不统一90分，不固定Top1%</span></article>
<article class="card"><b>事后描述</b><span>固定模板可能晚于历史截面</span></article></section>
<nav class="tabs" id="tabs"></nav><section id="panels"></section>
<h2>📊 榜单稳定性与换手拆解</h2><div class="card scroll"><table id="stability"></table></div>
<details open><summary>动态 Jaccard：六组时间关系</summary><div><div class="tabs" id="freqTabs"><button aria-selected="true" data-freq="weekly">周频</button><button aria-selected="false" data-freq="monthly">月末</button></div><div class="chart" id="jaccardChart"></div></div></details>
<details><summary>状态迁移矩阵（月末，描述性）</summary><div class="scroll"><div class="matrix" id="matrix"></div><p class="muted">保留多标签；矩阵含“混合”和“无状态”。随机基线保持下一期状态频率，不代表预测。</p></div></details>
<details open><summary>行业 × 模板 × 当前截面</summary><div><div class="card scroll"><table id="industry"></table></div><h3>电子行业专项审计</h3><div class="card scroll"><table id="electronics"></table></div></div></details>
<details><summary>市值动态双口径</summary><div class="card scroll"><table id="cap"></table><p class="muted">固定亿元层级与截面市值五分位并列，避免仅由股价上涨造成机械换档。</p></div></details>
<details><summary>稳健性：窗口、去电子与去行业龙头</summary><div><div class="card scroll"><table id="robustness"></table></div><p class="muted">窗口±10%只作单窗口扰动，不替换冻结模板、不做多窗口组合。每行业去Top1/Top3按当期本模板分数处理。</p></div></details>
<h2>📌 假设结论与产品取舍</h2><section class="grid" id="conclusions"></section>
<details><summary>方法、数据边界与泄漏审计</summary><div><ul>
<li>冻结算法：前复权 log-close；窗口内独立 z 标准化；单窗口 Pearson。</li>
<li>跨模板只比较百分位、Jaccard或超过自身阈值程度，不比较原始 Pearson。</li>
<li>来源：{data["boundaries"]["source"]}；范围 {data["boundaries"]["dailyRange"]}。</li>
<li>{data["boundaries"]["industryPointInTime"]}；{data["boundaries"]["marketCapPointInTime"]}。</li>
<li class="warn">{data["boundaries"]["historicalInterpretation"]}。</li>
<li>未联网、未读 sealed final、未用未来收益、IC或策略表现。</li></ul></div></details>
</main><footer>非正式本地增强统计验证页 · 分支 {data["branch"]}</footer>
<script>
const D={payload}, labels=Object.fromEntries(D.templates.map(x=>[x.key,x.label]));
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
const pct=n=>(Number(n)*100).toFixed(1)+"%", num=n=>Number(n).toLocaleString("zh-CN",{{maximumFractionDigits:3}});
const tabs=document.querySelector("#tabs"),panels=document.querySelector("#panels");
function lineChart(rows,fields,colors){{if(!rows.length)return"";const W=900,H=220,p=30,vals=rows.flatMap(r=>fields.map(f=>+r[f])).filter(Number.isFinite),lo=Math.min(...vals),hi=Math.max(...vals),x=i=>p+i*(W-2*p)/Math.max(rows.length-1,1),y=v=>H-p-(v-lo)*(H-2*p)/Math.max(hi-lo,.0001);return `<svg viewBox="0 0 ${{W}} ${{H}}"><line x1="${{p}}" x2="${{W-p}}" y1="${{H-p}}" y2="${{H-p}}" stroke="#bcc7cf"/>${{fields.map((f,j)=>`<path d="${{rows.map((r,i)=>(i?"L":"M")+x(i)+","+y(+r[f])).join(" ")}}" fill="none" stroke="${{colors[j]}}" stroke-width="2"><title>${{f}}</title></path>`).join("")}}<text x="${{p}}" y="16" font-size="11" fill="#64717e">${{hi.toFixed(3)}}</text><text x="${{p}}" y="${{H-7}}" font-size="11" fill="#64717e">${{rows[0].as_of}} → ${{rows.at(-1).as_of}}</text></svg>`}}
D.templates.forEach((t,i)=>{{tabs.insertAdjacentHTML("beforeend",`<button aria-selected="${{i===0}}" data-key="${{t.key}}">${{esc(t.label)}} · ${{t.bars}}根</button>`);const rows=D.distribution.filter(x=>x.frequency==="weekly"&&x.template===t.key);panels.insertAdjacentHTML("beforeend",`<article class="panel ${{i===0?"active":""}}" id="p-${{t.key}}"><section class="grid"><div class="card threshold" style="--accent:${{t.accent}}"><b>${{t.threshold.frozen_threshold.toFixed(3)}}</b><span>冻结阈值 · ${{t.threshold.false_positive_risk}}误判风险</span></div><div class="card"><b>${{t.latest.qualified_count}}</b><span>真实合格数量 / ${{t.latest.eligible_count}}</span></div><div class="card"><b>${{t.latest.historical_position}}</b><span>P99历史位置 · ${{pct(t.latest.historical_percentile)}}</span></div><div class="card"><b>${{t.threshold.random_max_5000.toFixed(3)}} / ${{t.threshold.ordinary_up_max_5000.toFixed(3)}}</b><span>随机 / 普通上涨 5000路径最大值</span></div></section><h2>${{esc(t.label)}}动态分布</h2><div class="chart">${{lineChart(rows,["max_score","p99_score","median_score","frozen_threshold"],[t.accent,"#2c769f","#7d8790","#a85d16"])}}</div><p class="muted">线条：最高分、P99、中位数、冻结阈值。合格数不足TopK时不补足。</p></article>`);}});
tabs.onclick=e=>{{const b=e.target.closest("button");if(!b)return;tabs.querySelectorAll("button").forEach(x=>x.setAttribute("aria-selected",x===b));document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="p-"+b.dataset.key));}};
const stab=D.stabilitySummary.filter(x=>x.top_k===5||x.top_k===30||x.top_k===100);document.querySelector("#stability").innerHTML="<tr><th>模板 / K</th><th>留存</th><th>换手</th><th>全截面百分位相关</th><th>25–35边界占变动</th></tr>"+stab.map(x=>`<tr><td>${{labels[x.template]}} / ${{x.top_k}}</td><td>${{pct(x.median_retention)}}</td><td>${{pct(x.median_turnover)}}</td><td>${{num(x.median_percentile_corr)}}</td><td>${{pct(x.median_boundary_share)}}</td></tr>`).join("");
function drawJ(freq){{const rows=D.jaccard.filter(x=>x.frequency===freq),pairs=[...new Set(rows.map(x=>x.pair))],dates=[...new Set(rows.map(x=>x.as_of))],wide=dates.map(d=>Object.assign({{as_of:d}},Object.fromEntries(rows.filter(x=>x.as_of===d).map(x=>[x.pair,x.top30_jaccard]))));document.querySelector("#jaccardChart").innerHTML=lineChart(wide,pairs,["#295f8d","#a85d16","#238067","#784a9b","#b33e52","#61717d"]);}}
drawJ("weekly");document.querySelector("#freqTabs").onclick=e=>{{const b=e.target.closest("button");if(!b)return;document.querySelectorAll("#freqTabs button").forEach(x=>x.setAttribute("aria-selected",x===b));drawJ(b.dataset.freq);}};
const states={json.dumps(list(STATES), ensure_ascii=False)},m=document.querySelector("#matrix");m.innerHTML=`<div class="head">从 \\ 到</div>${{states.map(x=>`<div class="head">${{x}}</div>`).join("")}}`+states.map(a=>`<div class="head">${{a}}</div>`+states.map(b=>{{const r=D.transitions.find(x=>x.from_state===a&&x.to_state===b);return `<div title="随机基线lift ${{r?.lift_vs_random?.toFixed?.(2)??"—"}}">${{r?pct(r.row_rate):"—"}}</div>`}}).join("")).join("");
function tbl(id,heads,rows){{document.querySelector(id).innerHTML="<tr>"+heads.map(x=>`<th>${{x}}</th>`).join("")+"</tr>"+rows.join("");}}
tbl("#industry",["模板 / 行业","合格率","超额","样本","状态"],D.industryLatest.map(x=>`<tr><td>${{labels[x.template]}} / ${{esc(x.industry)}}</td><td>${{pct(x.qualified_rate)}}</td><td>${{num(x.rate_excess_pp)}}pp</td><td>${{x.qualified_count}} / ${{x.eligible_count}}</td><td>${{x.status}}</td></tr>`));
tbl("#electronics",["模板","行业名次","合格率","去Top1","去Top3","Top3驱动","状态"],D.electronics.map(x=>`<tr><td>${{x.label}}</td><td>${{x.industry_rank_min30??"—"}}</td><td>${{pct(x.qualified_rate)}}</td><td>${{pct(x.rate_without_top1)}}</td><td>${{pct(x.rate_without_top3)}}</td><td>${{pct(x.top3_exceedance_share)}}</td><td>${{x.status}}</td></tr>`));
tbl("#cap",["模板 / 口径 / 组","合格率","超额","样本"],D.capLatest.map(x=>`<tr><td>${{labels[x.template]}} / ${{x.dimension==="cap_tier"?"亿元层级":"截面五分位"}} / ${{x.group}}</td><td>${{pct(x.qualified_rate)}}</td><td>${{num(x.rate_excess_pp)}}pp</td><td>${{x.qualified_count}} / ${{x.eligible_count}}</td></tr>`));
tbl("#robustness",["模板 / 实验","合格率或Top30 Jaccard","相对基准"],D.exclusionRobustness.map(x=>`<tr><td>${{labels[x.template]}} / ${{x.variant}}</td><td>${{pct(x.qualified_rate)}}</td><td>${{num(x.change_vs_base_pp)}}pp</td></tr>`).concat(D.windowSensitivity.map(x=>`<tr><td>${{labels[x.template]}} / 窗口${{x.variant}}</td><td>${{pct(x.top30_jaccard)}}</td><td>仅敏感性</td></tr>`)));
document.querySelector("#conclusions").innerHTML=D.conclusions.map(x=>`<article class="card conclusion"><b>${{x.id}} · ${{x.decision}}</b><p>${{esc(x.evidence)}}</p><span>${{esc(x.product)}}<br>${{esc(x.outlierAudit)}}</span></article>`).join("");
</script></body></html>"""


def notes_document(data: dict) -> str:
    lines = [
        f"# {data['title']}",
        "",
        f"- 实际分支：`{data['branch']}`",
        f"- 截止日：{data['asOfLabel']}",
        f"- 标记：{data['reviewLabel']}",
        "",
        "## 阈值建议",
        "",
    ]
    for item in data["templates"]:
        t = item["threshold"]
        lines.append(
            f"- {item['label']}：冻结阈值 `{t['frozen_threshold']:.4f}`；当前真实合格 "
            f"{item['latest']['qualified_count']} 只；对照误判风险 `{t['false_positive_risk']}`。"
        )
    lines += ["", "## 假设结论", ""]
    for item in data["conclusions"]:
        lines += [
            f"### {item['id']} · {item['decision']}",
            "",
            item["evidence"],
            "",
            f"- 稳定性：{item['stability']}",
            f"- 异常驱动：{item['outlierAudit']}",
            f"- 产品建议：{item['product']}",
            "",
        ]
    lines += [
        "## 数据边界与口径限制",
        "",
        f"- {data['boundaries']['source']}。",
        f"- 日线范围：{data['boundaries']['dailyRange']}。",
        "- 未联网、未读 sealed final、未使用未来收益、IC或策略表现。",
        "- 固定模板可能晚于历史截面；历史序列只能事后描述同期形态供给。",
        "- 阈值是筛选下限，不是预测阈值、真值标签或固定Top1%。",
        "- 小行业使用 n<30 标记和 Wilson 95% 区间；多重比较仅作探索性审计。",
    ]
    return "\n".join(lines) + "\n"


def validate(raw, tables, data):
    if data["branch"] != "codex/template-dynamics-validation-v2":
        raise RuntimeError("分支标记错误")
    if any(
        data["boundaries"][key]
        for key in (
            "networkUsed",
            "sealedFinalRead",
            "futureReturnUsed",
            "icUsed",
            "strategyPerformanceUsed",
        )
    ):
        raise RuntimeError("泄漏审计失败")
    if len(tables["thresholds"]) != 4:
        raise RuntimeError("模板阈值数量错误")
    if tables["distribution_snapshots"]["as_of"].max() != raw["as_of"]:
        raise RuntimeError("动态分布未覆盖当前")
    if not tables["distribution_snapshots"]["qualified_share"].between(0, 1).all():
        raise RuntimeError("合格率越界")
    if not tables["stability_pairs"]["retention"].between(0, 1).all():
        raise RuntimeError("留存率越界")
    expected_pairs = len(list(combinations(TEMPLATES, 2)))
    if tables["dynamic_jaccard"]["pair"].nunique() != expected_pairs:
        raise RuntimeError("Jaccard组合不完整")
    if set(tables["state_transitions"]["from_state"]) != set(STATES):
        raise RuntimeError("状态迁移不完整")
    if not all(
        frame["score"].between(-1 - 1e-9, 1 + 1e-9).all()
        for frames in raw["scores"].values()
        for frame in frames.values()
    ):
        raise RuntimeError("Pearson 分数超出数值容差")


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError(f"输出必须位于工作区：{output}")
    if output.exists():
        raise RuntimeError(f"拒绝覆盖现有输出：{output}")
    previous_cwd = Path.cwd()
    os.chdir(ZERO_ROOT)
    try:
        pro = pro_api(str(ZERO_CONFIG))
        raw = build_raw(pro)
    finally:
        os.chdir(previous_cwd)

    thresholds_frame, thresholds = build_thresholds(raw)
    distributions, consistency = build_distributions(raw, thresholds)
    stability, topk_members, qualified = build_memberships_and_stability(
        raw, thresholds
    )
    dynamic_jaccard = build_jaccard(raw, thresholds)
    state_counts, state_transitions, state_dwell = build_states(raw, thresholds)
    industry, industry_migration = build_industry(raw, thresholds)
    electronics = build_electronics_audit(raw, thresholds, industry)
    cap_dynamic, cap_shifts = build_cap(raw, thresholds)
    window_sensitivity = build_window_sensitivity(raw)
    exclusion_robustness = build_exclusion_robustness(raw, thresholds)
    tables = {
        "thresholds": thresholds_frame,
        "distribution_snapshots": distributions,
        "qualified_consistency": consistency,
        "stability_pairs": stability,
        "topk_memberships": topk_members,
        "qualified_memberships": qualified,
        "dynamic_jaccard": dynamic_jaccard,
        "state_counts": state_counts,
        "state_transitions": state_transitions,
        "state_dwell": state_dwell,
        "industry_dynamic": industry,
        "industry_template_migration": industry_migration,
        "electronics_audit": electronics,
        "cap_dynamic": cap_dynamic,
        "cap_group_shifts": cap_shifts,
        "window_sensitivity": window_sensitivity,
        "exclusion_robustness": exclusion_robustness,
    }
    conclusion_rows = conclusions(
        thresholds_frame,
        distributions,
        stability,
        dynamic_jaccard,
        state_transitions,
        electronics,
        window_sensitivity,
        exclusion_robustness,
    )
    data = build_payload(raw, tables, conclusion_rows)
    validate(raw, tables, data)

    output.mkdir(parents=True)
    for name, frame in tables.items():
        frame.to_csv(output / f"{name}.csv", index=False, encoding="utf-8-sig")
    (output / "validation-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "hypothesis-conclusions.json").write_text(
        json.dumps(conclusion_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "review-notes.md").write_text(
        notes_document(data), encoding="utf-8"
    )
    (output / "index.html").write_text(html_document(data), encoding="utf-8")
    score_range_valid = all(
        frame["score"].between(-1 - 1e-9, 1 + 1e-9).all()
        for frames in raw["scores"].values()
        for frame in frames.values()
    )
    qa = {
        "pass": score_range_valid,
        "branch": data["branch"],
        "asOf": data["asOf"],
        "templateCount": 4,
        "thresholdRows": len(thresholds_frame),
        "weeklyAsOfs": data["audit"]["weeklyAsOfs"],
        "monthlyAsOfs": data["audit"]["monthlyAsOfs"],
        "distributionRows": len(distributions),
        "stabilityRows": len(stability),
        "jaccardRows": len(dynamic_jaccard),
        "transitionRows": len(state_transitions),
        "industryRows": len(industry),
        "capRows": len(cap_dynamic),
        "scoreRangeValid": score_range_valid,
        "scoreTolerance": 1e-9,
        "leakageAudit": data["boundaries"],
    }
    (output / "qa-data-results.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(output / "index.html")
    print(json.dumps({"thresholds": records(thresholds_frame), "electronics": records(electronics), "conclusions": conclusion_rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
