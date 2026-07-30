from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    PROJECT_ROOT / "outputs" / "shape-v2" / "top100-breadth-20260730"
)
PUBLIC = PROJECT_ROOT / "public" / "template-breadth-v3.json"
PUBLIC_DETAILS = PROJECT_ROOT / "public" / "template-breadth-v3-details"
PUBLIC_RANKINGS = PROJECT_ROOT / "public" / "template-rankings"
PUBLIC_TIMELINES = PROJECT_ROOT / "public" / "template-breadth-v3-timelines"
PUBLIC_DEFINITIONS = PROJECT_ROOT / "public" / "template-definitions"
REGISTRY = PROJECT_ROOT / "config" / "similarity_templates.json"
TOP_K = 100
CHANGE_WINDOWS = (10, 20)
DEFAULT_CHANGE_WINDOW = 10
DISPLAY_DAYS = 60
TIMELINE_HISTORY_DAYS = 252
TIMELINE_SAMPLE_STEP = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--public", type=Path, default=PUBLIC)
    parser.add_argument(
        "--public-details",
        type=Path,
        default=PUBLIC_DETAILS,
    )
    parser.add_argument(
        "--public-rankings",
        type=Path,
        default=PUBLIC_RANKINGS,
    )
    parser.add_argument(
        "--public-timelines",
        type=Path,
        default=PUBLIC_TIMELINES,
    )
    return parser.parse_args()


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in all_keys(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in all_keys(child)}
    return set()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    public = args.public.resolve()
    public_details = args.public_details.resolve()
    public_rankings = args.public_rankings.resolve()
    public_timelines = args.public_timelines.resolve()
    membership = pd.read_csv(
        source / "top100_membership_daily.csv",
        dtype={"trade_date": str, "window_start": str, "window_end": str},
    )
    industry = pd.read_csv(
        source / "top100_industry_daily.csv",
        dtype={
            "trade_date": str,
            "comparison_trade_date": str,
        },
        keep_default_na=False,
    )
    payload = json.loads(public.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry_by_key = {
        item["key"]: item for item in registry["templates"]
    }
    parabolic = next(
        item
        for item in registry["templates"]
        if item["key"] == "parabolic_uptrend"
    )
    assert parabolic["source_ts_code"] == "001309.SZ"
    assert parabolic["start_date"] == "20260115"
    assert parabolic["end_date"] == "20260520"
    assert int(parabolic["window_bars"]) == 80

    assert payload["selection"]["topK"] == TOP_K
    assert payload["defaultChangeWindow"] == DEFAULT_CHANGE_WINDOW
    assert payload["changeWindows"] == list(CHANGE_WINDOWS)
    assert payload["selection"]["comparisonTradingDays"] == list(
        CHANGE_WINDOWS
    )
    assert "displayThreshold" not in payload
    assert "selectedThreshold" not in payload
    assert not (
        all_keys(payload)
        & {
            "current_stocks",
            "new_stocks",
            "retained_stocks",
            "exit_stocks",
            "series",
            "bars",
        }
    )
    assert len(payload["templates"]) == 4
    assert public.stat().st_size < 200_000

    checks = []
    for template in payload["templates"]:
        key = template["key"]
        members = membership[membership["template"] == key]
        industries = industry[industry["template"] == key]
        as_of = payload["asOf"]
        latest_members = members[members["trade_date"] == as_of]
        latest_industries = industries[
            (industries["trade_date"] == as_of)
            & (
                industries["comparison_trading_days"]
                == DEFAULT_CHANGE_WINDOW
            )
        ]

        assert len(latest_members) == TOP_K
        assert latest_members["ts_code"].nunique() == TOP_K
        assert int(latest_industries["top100_count"].sum()) == TOP_K
        daily = members.groupby("trade_date")["ts_code"].agg(
            ["count", "nunique"]
        )
        assert (daily["count"] == TOP_K).all()
        assert (daily["nunique"] == TOP_K).all()
        member_dates = sorted(members["trade_date"].unique())
        for comparison_days in CHANGE_WINDOWS:
            window_rows = industries[
                industries["comparison_trading_days"]
                == comparison_days
            ]
            totals = window_rows.groupby("trade_date").agg(
                top100_count=("top100_count", "sum"),
                new_count=("new_count", "sum"),
                retained_count=("retained_count", "sum"),
                exit_count=("exit_count", "sum"),
            )
            assert (totals["top100_count"] == TOP_K).all()
            comparable = window_rows[
                window_rows["comparison_trade_date"] != ""
            ]
            comparable_totals = comparable.groupby("trade_date").agg(
                new_count=("new_count", "sum"),
                retained_count=("retained_count", "sum"),
                exit_count=("exit_count", "sum"),
            )
            assert (
                comparable_totals["new_count"]
                + comparable_totals["retained_count"]
                == TOP_K
            ).all()
            assert (
                comparable_totals["exit_count"]
                + comparable_totals["retained_count"]
                == TOP_K
            ).all()
            for current_date, group in comparable.groupby("trade_date"):
                index = member_dates.index(str(current_date))
                assert index >= comparison_days
                assert set(group["comparison_trade_date"]) == {
                    member_dates[index - comparison_days]
                }

        page_by_code = {
            item["industry_code"]: item for item in template["industries"]
        }
        for row in latest_industries.itertuples(index=False):
            actual = page_by_code[str(row.industry_code)]
            assert actual["eligible_count"] == int(row.eligible_count)
            assert actual["top100_count"] == int(row.top100_count)
            assert np.isclose(actual["selection_rate"], row.selection_rate)
            for comparison_days in CHANGE_WINDOWS:
                change_row = industries[
                    (industries["trade_date"] == as_of)
                    & (
                        industries["comparison_trading_days"]
                        == comparison_days
                    )
                    & (
                        industries["industry_code"].astype(str)
                        == str(row.industry_code)
                    )
                ].iloc[0]
                change = actual["changes"][str(comparison_days)]
                assert change["comparison_date"] == str(
                    change_row["comparison_trade_date"]
                )
                assert change["new_count"] == int(
                    change_row["new_count"]
                )
                assert change["retained_count"] == int(
                    change_row["retained_count"]
                )
                assert change["exit_count"] == int(
                    change_row["exit_count"]
                )
                assert change["net_change"] == (
                    int(change_row["new_count"])
                    - int(change_row["exit_count"])
                )

        assert sum(
            item["top100_count"] for item in template["industries"]
        ) == TOP_K
        assert sum(
            item["top100_count"]
            for item in template["treemap_industries"]
        ) == TOP_K
        low = [
            item
            for item in template["industries"]
            if item["top100_count"] in (1, 2)
        ]
        other = next(
            (
                item
                for item in template["treemap_industries"]
                if item["industry_code"] == "other"
            ),
            None,
        )
        assert (other is not None) == bool(low)
        if other:
            assert other["neutral"] is True
            assert other["top100_count"] == sum(
                item["top100_count"] for item in low
            )
            assert other["component_industry_count"] == len(low)

        detail_path = public_details / f"{key}.json"
        ranking_path = public_rankings / f"{key}.json"
        timeline_path = public_timelines / f"{key}.json"
        definition_path = PUBLIC_DEFINITIONS / f"{key}.json"
        assert template["detail_url"] == (
            f"/template-breadth-v3-details/{key}.json"
        )
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        definition = json.loads(
            definition_path.read_text(encoding="utf-8")
        )
        assert detail["template_id"] == key
        assert detail["change_windows"] == list(CHANGE_WINDOWS)
        detail_by_code = {
            item["industry_code"]: item
            for item in detail["industries"]
        }
        for summary in template["industries"]:
            actual = detail_by_code[summary["industry_code"]]
            assert len(actual["current_stocks"]) == summary["top100_count"]
            assert len(actual["series"]) == DISPLAY_DAYS
            for comparison_days in CHANGE_WINDOWS:
                window = str(comparison_days)
                change = actual["changes"][window]
                summary_change = summary["changes"][window]
                assert len(change["new_stocks"]) == summary_change[
                    "new_count"
                ]
                assert len(change["retained_stocks"]) == summary_change[
                    "retained_count"
                ]
                assert len(change["exit_stocks"]) == summary_change[
                    "exit_count"
                ]
        if other:
            detail_other = detail["other"]
            assert len(detail_other["components"]) == len(low)
            assert len(detail_other["current_stocks"]) == other[
                "top100_count"
            ]
            for index, point in enumerate(detail_other["series"]):
                assert point["top100_count"] == sum(
                    component["series"][index]["top100_count"]
                    for component in detail_other["components"]
                )

        assert ranking["as_of"] == as_of
        assert ranking["template_id"] == key
        frozen = registry_by_key[key]
        assert ranking["algorithm"] == registry["algorithm"]
        assert ranking["template"] == {
            "source_ts_code": frozen["source_ts_code"],
            "start_date": frozen["start_date"],
            "end_date": frozen["end_date"],
            "window_bars": int(frozen["window_bars"]),
        }
        assert len(ranking["items"]) == TOP_K
        assert len(
            {item["ts_code"] for item in ranking["items"]}
        ) == TOP_K
        expected_latest = latest_members.sort_values("rank")
        for actual, expected in zip(
            ranking["items"],
            expected_latest.itertuples(index=False),
            strict=True,
        ):
            assert actual["rank"] == int(expected.rank)
            assert actual["ts_code"] == str(expected.ts_code)
            assert np.isclose(actual["score"], float(expected.score))
            assert actual["start_date"] == str(expected.window_start)
            assert actual["end_date"] == str(expected.window_end)
        if key == "parabolic_uptrend":
            assert {
                item["window_bars"] for item in ranking["items"]
            } == {80}
        assert definition["algorithm"] == registry["algorithm"]
        assert definition["template"]["source_ts_code"] == frozen[
            "source_ts_code"
        ]
        assert len(definition["bars"]) == int(frozen["window_bars"])
        assert definition["bars"][0]["trade_date"] == frozen["start_date"]
        assert definition["bars"][-1]["trade_date"] == frozen["end_date"]
        assert len(definition["curve"]) == int(frozen["window_bars"])
        assert template["timeline_url"] == (
            f"/template-breadth-v3-timelines/{key}.json"
        )
        assert timeline["template_id"] == key
        assert timeline["as_of"] == as_of
        assert timeline["sampling"]["history_trading_days"] == (
            TIMELINE_HISTORY_DAYS
        )
        assert timeline["sampling"]["trading_day_step"] == (
            TIMELINE_SAMPLE_STEP
        )
        assert timeline["sampling"]["latest_always_included"] is True
        assert len(timeline["snapshots"]) == template["timeline"][
            "sampled_points"
        ]
        assert timeline["snapshots"][-1]["date"] == as_of
        assert timeline_path.stat().st_size < 300_000
        assert not (
            all_keys(timeline)
            & {
                "current_stocks",
                "new_stocks",
                "retained_stocks",
                "exit_stocks",
                "stocks",
                "bars",
                "score",
                "rank",
                "ts_code",
            }
        )
        snapshot_dates = [
            snapshot["date"] for snapshot in timeline["snapshots"]
        ]
        snapshot_positions = [
            member_dates.index(current) for current in snapshot_dates
        ]
        assert all(
            right - left == TIMELINE_SAMPLE_STEP
            for left, right in zip(
                snapshot_positions[:-2],
                snapshot_positions[1:-1],
                strict=True,
            )
        )
        assert 1 <= (
            snapshot_positions[-1] - snapshot_positions[-2]
        ) <= TIMELINE_SAMPLE_STEP
        layout_position = {
            code: index
            for index, code in enumerate(timeline["layout_order"])
        }
        for snapshot in timeline["snapshots"]:
            assert sum(
                item["top100_count"]
                for item in snapshot["treemap_industries"]
            ) == TOP_K
            assert [
                item["industry_code"]
                for item in snapshot["treemap_industries"]
            ] == sorted(
                [
                    item["industry_code"]
                    for item in snapshot["treemap_industries"]
                ],
                key=layout_position.__getitem__,
            )
            current_position = member_dates.index(snapshot["date"])
            for comparison_days in CHANGE_WINDOWS:
                expected_date = member_dates[
                    current_position - comparison_days
                ]
                assert snapshot["comparison_dates"][
                    str(comparison_days)
                ] == expected_date
                assert {
                    item["changes"][str(comparison_days)][
                        "comparison_date"
                    ]
                    for item in snapshot["treemap_industries"]
                } == {expected_date}
        assert definition["boundaries"] == {
            "data_source": r"C:\Users\hp\Documents\zer0share",
            "network_used": False,
            "sealed_final_read": False,
            "future_return_used": False,
            "ic_used": False,
            "strategy_performance_used": False,
        }

        checks.append(
            {
                "template": key,
                "latestTop100": len(latest_members),
                "industryDenominatorsExact": True,
                "comparisonDatesAreTradingDayOffsets": True,
                "stockListsExact": True,
                "tenAndTwentyDayIdentities": True,
                "treemapTotal": TOP_K,
                "otherTop100Count": (
                    int(other["top100_count"]) if other else 0
                ),
                "otherIndustryCount": len(low),
                "detailBytes": detail_path.stat().st_size,
                "rankingBytes": ranking_path.stat().st_size,
                "templateDefinitionBytes": definition_path.stat().st_size,
                "timelinePoints": len(timeline["snapshots"]),
                "timelineBytes": timeline_path.stat().st_size,
            }
        )

    result = {
        "pass": True,
        "asOf": payload["asOf"],
        "topK": TOP_K,
        "defaultChangeWindow": DEFAULT_CHANGE_WINDOW,
        "comparisonTradingDays": list(CHANGE_WINDOWS),
        "initialPayloadBytes": public.stat().st_size,
        "initialPayloadHasStockLists": False,
        "initialPayloadHasKlineBars": False,
        "parabolicFrozenWindow": {
            "source_ts_code": parabolic["source_ts_code"],
            "start_date": parabolic["start_date"],
            "end_date": parabolic["end_date"],
            "window_bars": int(parabolic["window_bars"]),
        },
        "templates": checks,
        "leakageAudit": payload["boundaries"],
    }
    (source / "qa-independent-results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
