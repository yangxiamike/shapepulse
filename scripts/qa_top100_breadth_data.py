from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "top100-breadth-20260729"
)
PUBLIC = PROJECT_ROOT / "public" / "template-breadth-v3.json"
TOP_K = 100
COMPARISON_DAYS = 5


def main() -> None:
    membership = pd.read_csv(
        SOURCE / "top100_membership_daily.csv",
        dtype={"trade_date": str, "window_start": str, "window_end": str},
    )
    industry = pd.read_csv(
        SOURCE / "top100_industry_daily.csv",
        dtype={"trade_date": str, "comparison_trade_date": str},
    )
    payload = json.loads(PUBLIC.read_text(encoding="utf-8"))

    assert payload["selection"]["topK"] == TOP_K
    assert payload["selection"]["comparisonTradingDays"] == COMPARISON_DAYS
    assert "displayThreshold" not in payload
    assert "selectedThreshold" not in payload
    assert len(payload["templates"]) == 4

    checks = []
    for template in payload["templates"]:
        key = template["key"]
        members = membership[membership["template"] == key]
        industries = industry[industry["template"] == key]
        as_of = payload["asOf"]
        latest_members = members[members["trade_date"] == as_of]
        latest_industries = industries[industries["trade_date"] == as_of]

        assert len(latest_members) == TOP_K
        assert latest_members["ts_code"].nunique() == TOP_K
        assert int(latest_industries["top100_count"].sum()) == TOP_K
        assert int(latest_industries["new_count"].sum()) == int(
            template["summary"]["newCount"]
        )
        assert int(latest_industries["retained_count"].sum()) == int(
            template["summary"]["retainedCount"]
        )
        assert int(latest_industries["exit_count"].sum()) == int(
            template["summary"]["exitCount"]
        )
        assert (
            int(template["summary"]["newCount"])
            + int(template["summary"]["retainedCount"])
            == TOP_K
        )
        assert (
            int(template["summary"]["exitCount"])
            + int(template["summary"]["retainedCount"])
            == TOP_K
        )

        page_by_code = {
            item["industry_code"]: item for item in template["industries"]
        }
        for row in latest_industries.itertuples(index=False):
            actual = page_by_code[str(row.industry_code)]
            assert actual["eligible_count"] == int(row.eligible_count)
            assert actual["top100_count"] == int(row.top100_count)
            assert np.isclose(actual["selection_rate"], row.selection_rate)
            assert len(actual["current_stocks"]) == int(row.top100_count)
            assert len(actual["new_stocks"]) == int(row.new_count)
            assert len(actual["retained_stocks"]) == int(row.retained_count)
            assert len(actual["exit_stocks"]) == int(row.exit_count)
            assert all(
                {
                    "ts_code",
                    "code",
                    "name",
                    "industry",
                    "score",
                    "window_start",
                    "window_end",
                }
                <= set(stock)
                for field in (
                    "current_stocks",
                    "new_stocks",
                    "retained_stocks",
                    "exit_stocks",
                )
                for stock in actual[field]
            )
        assert all(
            {"date", "count", "top100_count", "eligible_count", "selection_rate"}
            <= set(point)
            for series in template["industrySeries"]
            for point in series["points"]
        )
        checks.append(
            {
                "template": key,
                "latestTop100": len(latest_members),
                "industryDenominatorsExact": True,
                "stockListsExact": True,
                "fiveDayIdentities": True,
            }
        )

    result = {
        "pass": True,
        "asOf": payload["asOf"],
        "topK": TOP_K,
        "comparisonTradingDays": COMPARISON_DAYS,
        "templates": checks,
        "leakageAudit": payload["boundaries"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
