from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "unified-threshold-v3-20260729"
)
CANDIDATES = (0.70, 0.75, 0.80)
TEMPLATES = (
    "fresh_breakout",
    "healthy_uptrend",
    "pullback_strengthening",
    "parabolic_uptrend",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)


def check_market(frame: pd.DataFrame) -> dict:
    assert set(frame["threshold"].unique()) == set(CANDIDATES)
    assert set(frame["template"].unique()) == set(TEMPLATES)
    assert (frame["above_count"] <= frame["eligible_count"]).all()
    assert (frame["above_count"] >= 0).all()

    pivot = frame.pivot_table(
        index=["template", "trade_date"],
        columns="threshold",
        values="above_count",
        aggfunc="first",
    )
    assert ((pivot[0.70] >= pivot[0.75]) & (pivot[0.75] >= pivot[0.80])).all()

    checked_rows = 0
    for _, group in frame.groupby(["template", "threshold"], sort=True):
        ordered = group.sort_values("trade_date").reset_index(drop=True)
        expected_1d = ordered["above_count"].diff(1)
        expected_5d = ordered["above_count"].diff(5)
        expected_ma5 = ordered["above_count"].rolling(5, min_periods=1).mean()
        assert np.allclose(
            ordered["change_1d"].fillna(0), expected_1d.fillna(0)
        )
        assert np.allclose(
            ordered["change_5d"].fillna(0), expected_5d.fillna(0)
        )
        assert np.allclose(ordered["ma5"], expected_ma5)
        history: list[float] = []
        for row in ordered.itertuples(index=False):
            history.append(float(row.above_count))
            percentile = float(np.mean(np.asarray(history) <= row.above_count))
            position = (
                "高位"
                if percentile >= 2 / 3
                else "低位"
                if percentile <= 1 / 3
                else "中位"
            )
            assert close(row.historical_percentile, percentile)
            assert row.historical_position == position
            checked_rows += 1
    return {
        "rowsChecked": checked_rows,
        "thresholdMonotonic": True,
        "changesAndMa5Exact": True,
        "expandingPositionExact": True,
    }


def check_industry(frame: pd.DataFrame) -> dict:
    assert (
        frame["above_count"] == frame["new_count"] + frame["retained_count"]
    ).all()
    assert (frame["above_count"] >= frame["above_without_top1"]).all()
    assert (frame["above_without_top1"] >= frame["above_without_top3"]).all()
    assert (frame["eligible_count"] >= frame["eligible_without_top1"]).all()
    assert (frame["eligible_without_top1"] >= frame["eligible_without_top3"]).all()
    assert (
        frame["eligible_count"] - frame["eligible_without_top1"]
        == frame["eligible_count"].clip(upper=1)
    ).all()
    assert (
        frame["eligible_count"] - frame["eligible_without_top3"]
        == frame["eligible_count"].clip(upper=3)
    ).all()
    assert (frame["above_count"] - frame["above_without_top1"]).between(0, 1).all()
    assert (frame["above_count"] - frame["above_without_top3"]).between(0, 3).all()
    ordered = frame.sort_values(
        ["threshold", "template", "industry_code", "trade_date"]
    ).copy()
    previous = ordered.groupby(
        ["threshold", "template", "industry_code"]
    )["above_count"].shift(1)
    comparable = previous.notna()
    assert (
        previous[comparable]
        == (
            ordered.loc[comparable, "retained_count"]
            + ordered.loc[comparable, "exit_count"]
        )
    ).all()
    top100_sums = frame.groupby(["threshold", "template", "trade_date"])[
        "top100_count"
    ].sum()
    assert (top100_sums == 100).all()
    rate_sums = frame.groupby(["threshold", "template", "trade_date"])[
        "top100_share"
    ].sum()
    assert np.allclose(rate_sums, 1.0)
    market_sums = frame.groupby(["threshold", "template", "trade_date"])[
        ["above_count", "eligible_count"]
    ].sum()
    return {
        "rowsChecked": len(frame),
        "membershipIdentityExact": True,
        "previousMembershipIdentityExact": True,
        "leaderRemovalMonotonic": True,
        "leaderRemovalBoundsExact": True,
        "top100DenominatorExact": True,
        "marketSums": market_sums,
    }


def canonical_crosscheck(market: pd.DataFrame) -> dict:
    canonical_path = (
        PROJECT_ROOT
        / "outputs"
        / "shape-v2"
        / "template-statistical-validation-v1-20260729"
        / "current_scores.csv"
    )
    canonical = pd.read_csv(canonical_path)
    date = str(canonical["end_date"].astype(str).max())
    assert date == "20260728"
    current = market[market["trade_date"].astype(str) == date]
    rows = []
    for template in TEMPLATES:
        scores = canonical[canonical["template"] == template]["score"]
        for threshold in CANDIDATES:
            expected = int((scores >= threshold).sum())
            actual_row = current[
                (current["template"] == template)
                & np.isclose(current["threshold"], threshold)
            ]
            assert len(actual_row) == 1
            actual = int(actual_row.iloc[0]["above_count"])
            assert actual == expected
            rows.append(
                {
                    "date": date,
                    "template": template,
                    "threshold": threshold,
                    "canonicalCount": expected,
                    "dailyRollingCount": actual,
                }
            )
    return {"date": date, "rows": rows, "allExact": True}


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
    nonzero_days = int(np.sum(signs != 0))
    persistent_days = sum(length for length in runs if length >= 3)
    return (
        persistent_days / nonzero_days if nonzero_days else 0.0,
        max(runs, default=0),
    )


def check_conclusion(
    output: Path, market: pd.DataFrame, template_eval: pd.DataFrame
) -> dict:
    candidate = json.loads(
        (output / "candidate_evaluation.json").read_text(encoding="utf-8")
    )
    conclusion = json.loads(
        (output / "conclusion.json").read_text(encoding="utf-8")
    )
    assert [row["threshold"] for row in candidate] == list(CANDIDATES)
    assert all(row["decision"] in {"支持", "较弱", "不支持"} for row in candidate)
    recomputed = {}
    detail_rows = []
    for threshold in CANDIDATES:
        supported = 0
        for template in TEMPLATES:
            current = market[
                np.isclose(market["threshold"], threshold)
                & (market["template"] == template)
            ].sort_values("trade_date")
            low_share = float((current["above_count"] <= 5).mean())
            hundreds_share = float((current["above_count"] >= 200).mean())
            ma5_corr = float(current["ma5"].autocorr(lag=1))
            persistent_share, max_run = direction_run_share(current["change_5d"])
            usable = low_share < 0.5 and hundreds_share < 0.5
            persistent = (
                ma5_corr >= 0.85 and persistent_share >= 0.5 and max_run >= 5
            )
            template_support = usable and persistent
            supported += int(template_support)
            stored = template_eval[
                np.isclose(template_eval["threshold"], threshold)
                & (template_eval["template"] == template)
            ]
            assert len(stored) == 1
            stored_row = stored.iloc[0]
            assert close(stored_row["share_count_0_to_5"], low_share)
            assert close(stored_row["share_count_200_plus"], hundreds_share)
            assert close(stored_row["ma5_lag1_corr"], ma5_corr)
            assert close(
                stored_row["persistent_direction_share"], persistent_share
            )
            assert int(stored_row["max_direction_run"]) == max_run
            assert bool(stored_row["template_support"]) == template_support
            detail_rows.append(
                {
                    "threshold": threshold,
                    "template": template,
                    "lowShare": low_share,
                    "hundredsShare": hundreds_share,
                    "support": template_support,
                }
            )
        decision = "支持" if supported == 4 else "较弱" if supported >= 2 else "不支持"
        recomputed[threshold] = decision
        row = next(item for item in candidate if close(item["threshold"], threshold))
        assert row["supported_templates"] == supported
        assert row["decision"] == decision
    assert conclusion["selectedThreshold"] is None
    assert conclusion["productizationContinues"] is False
    assert all(value == "不支持" for value in recomputed.values())
    return {
        "candidateDecisions": {f"{key:.2f}": value for key, value in recomputed.items()},
        "recomputedTemplateRows": detail_rows,
        "selectionIsNull": True,
        "productizationStopped": True,
    }


def check_boundaries(output: Path) -> dict:
    qa = json.loads((output / "qa-data-results.json").read_text(encoding="utf-8"))
    audit = qa["leakageAudit"]
    expected_false = (
        "networkUsed",
        "sealedFinalRead",
        "futureReturnUsed",
        "icUsed",
        "strategyPerformanceUsed",
    )
    assert all(audit[key] is False for key in expected_false)
    assert qa["candidateThresholds"] == list(CANDIDATES)
    assert qa["selectedThreshold"] is None
    source = (PROJECT_ROOT / "scripts" / "build_unified_threshold_v3.py").read_text(
        encoding="utf-8"
    ).lower()
    assert "http://" not in source and "https://" not in source
    assert "requests." not in source and "urlopen(" not in source
    assert 'path(r"c:\\users\\hp\\documents\\zer0share")' not in source
    return {
        "localZer0shareOnly": True,
        **{key: audit[key] for key in expected_false},
        "algorithmFrozen": "qfq log-close -> independent window z -> single-window Pearson",
        "sourceNetworkCallScan": "pass",
    }


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    if PROJECT_ROOT not in output.parents:
        raise RuntimeError("QA 输出目录必须位于工作区")
    market = pd.read_csv(output / "daily_threshold_counts.csv")
    industry = pd.read_csv(output / "industry_daily.csv")
    top30 = pd.read_csv(output / "latest_top30.csv")
    template_eval = pd.read_csv(output / "candidate_template_evaluation.csv")

    industry_check = check_industry(industry)
    market_sums = industry_check.pop("marketSums")
    expected_sums = market.set_index(["threshold", "template", "trade_date"])[
        ["above_count", "eligible_count"]
    ].sort_index()
    assert market_sums.sort_index().equals(expected_sums)
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "codex/unified-threshold-app-v3"
    results = {
        "pass": True,
        "branch": branch,
        "market": check_market(market),
        "industry": {
            **industry_check,
            "marketAndIndustrySumsExact": True,
        },
        "canonicalCrosscheck": canonical_crosscheck(market),
        "conclusion": check_conclusion(output, market, template_eval),
        "boundaries": check_boundaries(output),
        "top30": {
            "rows": len(top30),
            "perTemplate": top30.groupby("template").size().to_dict(),
            "rankExact": all(
                group.sort_values("rank")["rank"].tolist() == list(range(1, 31))
                for _, group in top30.groupby("template")
            ),
        },
        "visualQa": {
            "appPageBuilt": False,
            "status": "not_applicable",
            "reason": "三条候选统一线均不支持；按实验闸门停止产品化。",
        },
    }
    assert results["top30"]["rankExact"]
    assert set(results["top30"]["perTemplate"].values()) == {30}
    (output / "qa-crosschecks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
