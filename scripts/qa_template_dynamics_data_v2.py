from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "shape-v2" / "template-dynamics-validation-v2-20260729"
TOP_KS = {5, 10, 30, 100}


def main() -> None:
    data = json.loads((OUTPUT / "validation-data.json").read_text(encoding="utf-8"))
    thresholds = pd.read_csv(OUTPUT / "thresholds.csv")
    distribution = pd.read_csv(OUTPUT / "distribution_snapshots.csv")
    qualified = pd.read_csv(OUTPUT / "qualified_memberships.csv")
    stability = pd.read_csv(OUTPUT / "stability_pairs.csv")
    jaccard = pd.read_csv(OUTPUT / "dynamic_jaccard.csv")
    transitions = pd.read_csv(OUTPUT / "state_transitions.csv")
    industry = pd.read_csv(OUTPUT / "industry_dynamic.csv")
    cap = pd.read_csv(OUTPUT / "cap_dynamic.csv")

    latest = str(data["asOf"])
    latest_distribution = distribution[
        (distribution["frequency"] == "monthly")
        & (distribution["as_of"].astype(str) == latest)
    ].set_index("template")["qualified_count"]
    latest_memberships = (
        qualified[
            (qualified["frequency"] == "monthly")
            & (qualified["as_of"].astype(str) == latest)
        ]
        .groupby("template")
        .size()
        .reindex(latest_distribution.index, fill_value=0)
    )
    row_sums = transitions.groupby(["frequency", "from_state"])["row_rate"].sum()
    expected_distribution_rows = 4 * (
        int(data["audit"]["weeklyAsOfs"]) + int(data["audit"]["monthlyAsOfs"])
    )
    expected_jaccard_rows = 6 * (
        int(data["audit"]["weeklyAsOfs"]) + int(data["audit"]["monthlyAsOfs"])
    )
    forbidden = {
        key: data["boundaries"][key]
        for key in (
            "networkUsed",
            "sealedFinalRead",
            "futureReturnUsed",
            "icUsed",
            "strategyPerformanceUsed",
        )
    }
    checks = {
        "fourIndependentThresholds": len(thresholds) == 4
        and thresholds["template"].nunique() == 4,
        "thresholdsNotUnified": thresholds["frozen_threshold"].nunique() == 4,
        "distributionRowsComplete": len(distribution) == expected_distribution_rows,
        "latestQualifiedCountsReconcile": latest_distribution.astype(int).equals(
            latest_memberships.astype(int)
        ),
        "distributionScoreTolerance": bool(
            (distribution["max_score"] <= 1 + 1e-9).all()
            and (distribution["p05_score"] >= -1 - 1e-9).all()
        ),
        "topKCombinationsComplete": set(stability["top_k"].unique()) == TOP_KS,
        "stabilityRatesValid": bool(
            stability["retention"].between(0, 1).all()
            and stability["turnover"].between(0, 1).all()
        ),
        "sixJaccardPairsComplete": jaccard["pair"].nunique() == 6
        and len(jaccard) == expected_jaccard_rows,
        "jaccardRatesValid": bool(
            jaccard[["top30_jaccard", "qualified_jaccard"]]
            .apply(lambda column: column.between(0, 1).all())
            .all()
        ),
        "transitionRowRatesSum": bool(
            np.isclose(row_sums.to_numpy(float), 1.0, atol=1e-9).all()
        ),
        "wilsonContainsObservedRate": bool(
            (
                (industry["wilson_low"] <= industry["qualified_rate"] + 1e-12)
                & (industry["wilson_high"] + 1e-12 >= industry["qualified_rate"])
            ).all()
        ),
        "capRatesValid": bool(cap["qualified_rate"].between(0, 1).all()),
        "leakageFlagsAllFalse": not any(forbidden.values()),
    }
    result = {
        "pass": all(checks.values()),
        "checks": checks,
        "evidence": {
            "latestAsOf": latest,
            "thresholdRows": len(thresholds),
            "distributionRows": len(distribution),
            "qualifiedMembershipRows": len(qualified),
            "stabilityRows": len(stability),
            "jaccardRows": len(jaccard),
            "transitionRows": len(transitions),
            "industryRows": len(industry),
            "capRows": len(cap),
            "leakageFlags": forbidden,
        },
    }
    (OUTPUT / "qa-crosschecks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["pass"]:
        raise RuntimeError("数据交叉校验未通过")


if __name__ == "__main__":
    main()
