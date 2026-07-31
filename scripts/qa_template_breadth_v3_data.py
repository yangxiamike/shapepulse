from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "outputs" / "shape-v2" / "unified-threshold-v3-20260729"
PUBLIC_DATA = PROJECT_ROOT / "public" / "template-breadth-v3.json"
THRESHOLD = 0.80


def close(left: object, right: object, tolerance: float = 1e-9) -> bool:
    return math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=tolerance
    )


def main() -> None:
    data = json.loads(PUBLIC_DATA.read_text(encoding="utf-8"))
    market = pd.read_csv(SOURCE / "daily_threshold_counts.csv")
    industry = pd.read_csv(SOURCE / "industry_daily.csv")
    top30 = pd.read_csv(SOURCE / "latest_top30.csv")

    assert close(data["displayThreshold"], THRESHOLD)
    assert "试用观察线" in data["warning"]
    assert len(data["templates"]) == 4
    assert all(value is False for key, value in data["boundaries"].items() if key.endswith(("Used", "Read")))

    market = market[np.isclose(market["threshold"], THRESHOLD)].copy()
    industry = industry[np.isclose(industry["threshold"], THRESHOLD)].copy()
    as_of = int(data["asOf"])
    assert as_of == int(market["trade_date"].max())

    checks = []
    for template in data["templates"]:
        key = template["key"]
        expected_market = market[market["template"] == key].sort_values(
            "trade_date"
        )
        expected_latest = expected_market.iloc[-1]
        summary = template["summary"]
        assert summary["count"] == int(expected_latest["above_count"])
        assert summary["change1d"] == int(expected_latest["change_1d"])
        assert summary["change5d"] == int(expected_latest["change_5d"])
        assert close(summary["ma5"], expected_latest["ma5"])
        assert summary["position"] == expected_latest["historical_position"]
        assert close(
            summary["historicalPercentile"],
            float(expected_latest["historical_percentile"]) * 100,
            tolerance=0.051,
        )

        expected_series = expected_market.tail(60)
        assert len(template["marketSeries"]) == 60
        for actual, expected in zip(
            template["marketSeries"],
            expected_series.itertuples(index=False),
            strict=True,
        ):
            assert actual["date"] == str(int(expected.trade_date))
            assert actual["count"] == int(expected.above_count)
            assert close(actual["ma5"], expected.ma5, tolerance=0.011)

        expected_top30 = top30[top30["template"] == key].sort_values("rank")
        assert len(template["top30"]) == 30
        for actual, expected in zip(
            template["top30"],
            expected_top30.itertuples(index=False),
            strict=True,
        ):
            assert int(actual["rank"]) == int(expected.rank)
            assert actual["ts_code"] == expected.ts_code
            assert close(actual["score"], expected.score)
            assert actual["above_threshold"] == bool(expected.score >= THRESHOLD)

        expected_industry = industry[industry["template"] == key].sort_values(
            ["industry_code", "trade_date"]
        )
        expected_industry["change_5d"] = expected_industry.groupby(
            "industry_code"
        )["above_count"].diff(5)
        expected_current = expected_industry[
            expected_industry["trade_date"] == as_of
        ].set_index("industry_code")
        assert len(template["industries"]) == len(expected_current)
        for actual in template["industries"]:
            expected = expected_current.loc[actual["industry_code"]]
            for column in (
                "above_count",
                "top100_count",
                "new_count",
                "retained_count",
                "exit_count",
            ):
                assert int(actual[column]) == int(expected[column])
            assert close(actual["top100_share"], expected["top100_share"])
            assert int(actual["change_5d"]) == int(expected["change_5d"])

        checks.append(
            {
                "template": key,
                "marketSeriesRows": len(template["marketSeries"]),
                "top30Rows": len(template["top30"]),
                "industryRows": len(template["industries"]),
                "summaryExact": True,
            }
        )

    result = {
        "pass": True,
        "asOf": data["asOf"],
        "displayThreshold": data["displayThreshold"],
        "warningPresent": True,
        "templates": checks,
        "leakageAudit": data["boundaries"],
    }
    (SOURCE / "qa-app-data-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
