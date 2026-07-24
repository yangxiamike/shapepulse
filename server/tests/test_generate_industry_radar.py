from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.generate_industry_radar import (
    HORIZON_SLUGS,
    MARKET_FLOW_DISPLAY_DAYS,
    MARKET_FLOW_MINIMUM_DAYS,
    PAGE_COUNT,
    STATE_ORDER,
    _comprehensive,
    _history_csv,
    _market_concentration,
    _market_flow_history,
    _money,
    _ranking_rows,
    _state_groups,
    _state_name,
    build_report_data,
    main,
    write_datasets,
    write_pdf,
)
from server.industry_radar import RadarResult, analyze_industries
from server.tests.test_industry_radar import panel


def ranking_result(count: int = 31, horizon: int = 5) -> RadarResult:
    rows = pd.DataFrame(
        {
            "l1_code": [f"L{index:02d}" for index in range(1, count + 1)],
            "l1_name": [f"行业{index:02d}" for index in range(1, count + 1)],
            "rank": list(range(1, count + 1)),
            "horizon": horizon,
            "score": np.linspace(0.1, -0.1, count),
            "comprehensive_score": np.linspace(1000, -1000, count),
            f"flow_{horizon}d": np.linspace(100, -100, count),
        }
    )
    return RadarResult(rows, pd.DataFrame(), pd.DataFrame(), {"horizon": horizon})


def state_frame() -> pd.DataFrame:
    rows = [
        ("A", "共振强", 3, 5, 4.0, 3.0, 0.0004, 0.0003, 1, 2),
        ("B", "共振次", 2, 2, 3.0, 2.0, 0.0003, 0.0002, 2, 3),
        ("C", "短线转入", 5, -4, 6.0, -3.0, 0.0006, -0.0003, 3, 8),
        ("D", "趋势保持", -3, 6, -2.0, 5.0, -0.0002, 0.0005, 8, 1),
        ("E", "接近改善", -1, -10, -0.5, -4.0, -0.00005, -0.0004, 5, 7),
        ("F", "流出最深", -20, -30, -8.0, -9.0, -0.0008, -0.0009, 9, 9),
    ]
    frame = pd.DataFrame(
        rows,
        columns=[
            "l2_code",
            "l2_name",
            "flow_5d",
            "flow_20d",
            "comprehensive_score_5d",
            "comprehensive_score_20d",
            "score_5d",
            "score_20d",
            "rank_5d",
            "rank_20d",
        ],
    )
    frame["state"] = [
        _state_name(five, twenty)
        for five, twenty in zip(frame["flow_5d"], frame["flow_20d"])
    ]
    frame["score_change"] = (
        frame["comprehensive_score_5d"] - frame["comprehensive_score_20d"]
    )
    frame["joint_strength"] = frame[
        ["comprehensive_score_5d", "comprehensive_score_20d"]
    ].min(axis=1)
    frame["deepest_score"] = frame[
        ["comprehensive_score_5d", "comprehensive_score_20d"]
    ].min(axis=1)
    return frame


class ReportDatasetTests(unittest.TestCase):
    def test_money_and_comprehensive_score_formatters_are_readable(self):
        self.assertEqual(_money(250_000), "+2.5亿")
        self.assertEqual(_money(-12_500), "-1,250万")
        self.assertEqual(_money(3), "+3,000元")
        self.assertEqual(_comprehensive(12.34), "+12.34")
        self.assertEqual(_comprehensive(-12.34), "-12.34")

    def test_market_flow_history_is_60_real_dates_and_matches_cards(self):
        source = panel()
        report = build_report_data(source)
        payload = report["market_flow_history"]
        history = pd.DataFrame(payload["series"])
        self.assertEqual(len(history), MARKET_FLOW_DISPLAY_DAYS)
        self.assertEqual(
            history["trade_date"].tolist(),
            sorted(source["trade_date"].astype(str).unique())[-60:],
        )
        self.assertTrue(payload["endpoint_matches_cards"])
        self.assertEqual(
            payload["recent_5d_change"],
            report["horizons"][5]["l2"].quality["market_flow_5d"],
        )
        self.assertEqual(
            payload["recent_20d_change"],
            report["horizons"][20]["l2"].quality["market_flow_20d"],
        )
        self.assertEqual(
            history.iloc[0]["market_large_active_flow_cumulative"], 0
        )

    def test_market_flow_history_daily_and_cumulative_are_consistent(self):
        source = panel()
        report = build_report_data(source)
        history = pd.DataFrame(report["market_flow_history"]["series"])
        work = source[
            source["l2_code"].notna() & source["l2_name"].notna()
        ].copy()
        daily = (
            work.groupby(["trade_date", "l2_code", "l2_name"])[
                "inst_net_flow"
            ]
            .sum()
            .groupby(level=0)
            .sum()
            .sort_index()
        )
        expected_daily = daily.reindex(history["trade_date"]).to_numpy()
        np.testing.assert_allclose(
            history["market_large_active_flow_daily"], expected_daily
        )
        cumulative = history["market_large_active_flow_cumulative"].to_numpy()
        np.testing.assert_allclose(np.diff(cumulative), expected_daily[1:])
        self.assertAlmostEqual(cumulative[-1] - cumulative[-6], expected_daily[-5:].sum())
        self.assertAlmostEqual(cumulative[-1] - cumulative[-21], expected_daily[-20:].sum())

    def test_market_flow_history_rejects_less_than_60_dates(self):
        source = panel(days=MARKET_FLOW_MINIMUM_DAYS - 1)
        daily = analyze_industries(source, "l2", horizon=20).daily_flows
        with self.assertRaisesRegex(ValueError, "at least 60"):
            _market_flow_history(daily, 0.0, 0.0)

    def test_market_concentration_uses_positive_pool_not_net_market_flow(self):
        rankings = pd.DataFrame(
            {
                "l2_code": ["A", "B", "C"],
                "l2_name": ["甲", "乙", "丙"],
                "flow_1d": [100.0, -99.999, 50.0],
            }
        )
        concentration = _market_concentration(rankings)
        self.assertAlmostEqual(concentration["top3_share"], 1.0)
        self.assertAlmostEqual(concentration["top5_share"], 1.0)
        self.assertAlmostEqual(concentration["top_industries"][0]["flow_1d"], 100)
        self.assertTrue(0 <= concentration["normalized_hhi"] <= 1)

    def test_builds_both_levels_horizons_states_and_history(self):
        report = build_report_data(panel())
        self.assertEqual(report["as_of"], report["l1"].quality["as_of"])
        self.assertEqual(set(report["horizons"]), {5, 20})
        self.assertEqual(set(report["fund_states"]), set(STATE_ORDER))
        self.assertEqual(
            set(report["daily_answers"]),
            {
                "inflow_industry_share",
                "market_concentration",
                "persistent_inflow",
                "recently_turned_in",
                "medium_strong_short_cooling",
                "persistent_outflow",
                "inflow_diffusion",
                "fastest_improving",
                "fastest_worsening",
            },
        )
        rotation = pd.DataFrame(report["rotation_history"]["current"])
        for column in (
            "rank_change_1d",
            "rank_change_5d",
            "strength_change_1d_bps",
            "transition_previous",
            "transition_5d",
            "state_streak_days",
        ):
            self.assertIn(column, rotation)
        self.assertGreaterEqual(report["market_concentration"]["top3_share"], 0)
        self.assertLessEqual(report["market_concentration"]["top5_share"], 1)
        for horizon in (5, 20):
            for level in ("l1", "l2"):
                result = report["horizons"][horizon][level]
                self.assertEqual(result.quality["horizon"], horizon)
                np.testing.assert_allclose(
                    result.rankings["comprehensive_score"],
                    result.rankings["score"] * 10_000,
                )
                self.assertEqual(
                    result.rankings.sort_values(
                        ["score", f"{level}_code"],
                        ascending=[False, True],
                        kind="stable",
                    )[f"{level}_code"].tolist(),
                    result.rankings.sort_values(
                        ["comprehensive_score", f"{level}_code"],
                        ascending=[False, True],
                        kind="stable",
                    )[f"{level}_code"].tolist(),
                )
        for level in ("l1", "l2"):
            history = report["history"][level]
            self.assertEqual(len(history["window_dates"]), 40)
            self.assertEqual(history["highlight_dates"], history["window_dates"][-20:])
            for side in ("top", "bottom"):
                for path in history[side]:
                    self.assertEqual(path["cumulative_flow"][0], 0)
                    self.assertEqual(len(path["cumulative_flow"]), 40)

    def test_ranking_fields_use_the_selected_window(self):
        report = build_report_data(panel())
        for horizon in (5, 20):
            rows = report["horizons"][horizon]["l2"].rankings
            self.assertTrue(
                (
                    rows["consistent_day_count"]
                    == rows[f"consistent_day_count_{horizon}d"]
                ).all()
            )
            self.assertTrue(
                (
                    rows["consistent_stock_count"]
                    == rows[f"consistent_stock_count_{horizon}d"]
                ).all()
            )
            self.assertTrue(
                (
                    rows["breadth_stock_count"]
                    == rows[f"breadth_stock_count_{horizon}d"]
                ).all()
            )
            self.assertIn(f"return_{horizon}d", rows)

    def test_front_and_back_15_are_deterministic_and_omit_l1_rank_16(self):
        result = ranking_result()
        front = _ranking_rows(result, tail=False)
        back = _ranking_rows(result, tail=True)
        self.assertEqual(front["rank"].tolist(), list(range(1, 16)))
        self.assertEqual(back["rank"].tolist(), list(range(17, 32)))
        self.assertNotIn(16, front["rank"].tolist() + back["rank"].tolist())
        shuffled = RadarResult(
            result.rankings.sample(frac=1, random_state=7),
            result.contributors,
            result.daily_flows,
            result.quality,
        )
        self.assertEqual(
            _ranking_rows(shuffled, tail=True)["l1_code"].tolist(),
            back["l1_code"].tolist(),
        )

    def test_four_states_and_representatives_are_deterministic(self):
        frame = state_frame()
        self.assertEqual(
            set(frame["state"]),
            {"双窗净流入", "短线转入", "趋势仍流入", "双窗净流出"},
        )
        first = _state_groups(frame)
        second = _state_groups(frame.sample(frac=1, random_state=11))
        for state in STATE_ORDER:
            self.assertEqual(first[state]["count"], second[state]["count"])
            self.assertEqual(
                first[state]["industries"]["l2_code"].tolist(),
                second[state]["industries"]["l2_code"].tolist(),
            )
        self.assertEqual(
            first["双窗净流出"]["representatives"]["接近改善"].iloc[0]["l2_code"],
            "E",
        )
        self.assertEqual(
            first["双窗净流出"]["representatives"]["流出最深"].iloc[0]["l2_code"],
            "F",
        )

    def test_history_top_bottom_come_from_20d_rank_and_use_last_40_dates(self):
        report = build_report_data(panel())
        ranked = report["horizons"][20]["l2"].rankings.sort_values("rank")
        history = report["history"]["l2"]
        self.assertEqual(
            [path["industry_code"] for path in history["top"]],
            ranked.head(5)["l2_code"].astype(str).tolist(),
        )
        self.assertEqual(
            [path["industry_code"] for path in history["bottom"]],
            ranked.tail(5)["l2_code"].astype(str).tolist(),
        )
        history_csv = _history_csv(report, "l2")
        self.assertEqual(set(history_csv["selection_basis"]), {"report-date 20-day final rank"})
        self.assertEqual(history_csv["trade_date"].nunique(), 40)

    def test_write_datasets_adds_score_state_history_and_manifest_audit(self):
        report = build_report_data(panel())
        with TemporaryDirectory() as tmp:
            paths, combined = write_datasets(report, Path(tmp))
            names = {path.name for path in paths}
            for slug in HORIZON_SLUGS.values():
                self.assertIn(
                    f"industry_radar_{slug}_{report['as_of']}.json", names
                )
            self.assertIn(
                f"industry_radar_l2_fund_states_{report['as_of']}.csv", names
            )
            self.assertIn(
                f"industry_radar_l1_40d_cumulative_paths_{report['as_of']}.csv",
                names,
            )
            market_name = (
                f"industry_radar_market_large_active_flow_60d_{report['as_of']}.csv"
            )
            self.assertIn(market_name, names)
            self.assertIn(
                f"industry_radar_l2_rotation_changes_{report['as_of']}.csv",
                names,
            )
            payload = json.loads(combined.read_text(encoding="utf-8"))
            self.assertEqual(payload["market_flow_history"]["display_points"], 60)
            self.assertTrue(payload["market_flow_history"]["endpoint_matches_cards"])
            self.assertEqual(
                payload["comprehensive_score_formula"],
                "comprehensive_score=10000*S_H",
            )
            ranking = payload["horizons"]["5"]["l2"]["rankings"][0]
            self.assertIn("score", ranking)
            self.assertIn("comprehensive_score", ranking)
            self.assertAlmostEqual(
                ranking["comprehensive_score"], ranking["score"] * 10_000
            )

    def test_pdf_has_all_pages_titles_and_manifest_ranking_text(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("pypdf unavailable")
        report = build_report_data(panel())
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "radar.pdf"
            write_pdf(report, pdf_path)
            reader = PdfReader(str(pdf_path))
            self.assertEqual(len(reader.pages), PAGE_COUNT)
            texts = [page.extract_text() or "" for page in reader.pages]
            expected_titles = [
                "市场总览",
                "每日结论与四类资金状态",
                "申万一级前15",
                "申万一级后15",
                "申万二级前15",
                "申万二级后15",
                "申万一级：20日Top/Bottom 5最近40日累计资金",
                "申万二级：20日Top/Bottom 5最近40日累计资金",
                "资金状态变化：改善与恶化",
                "代表行业完整计算链",
                "公式、数据覆盖与复核说明",
            ]
            for text, title in zip(texts, expected_titles):
                self.assertIn(title, text)
            all_text = "\n".join(texts)
            self.assertIn("可比强度", all_text)
            self.assertIn("bp", all_text.lower())
            top_name = report["horizons"][5]["l2"].rankings.sort_values(
                "rank"
            ).iloc[0]["l2_name"]
            self.assertIn(top_name, texts[2] + texts[4])
            self.assertIn("综合分", all_text)
            self.assertIn("同向天数", all_text)
            self.assertIn("同向个股", all_text)
            self.assertIn("大额主动资金", all_text)
            self.assertNotIn("市场机构资金", all_text)

    def test_cli_writes_one_combined_pdf(self):
        fake_report = {"as_of": "20260722"}
        with TemporaryDirectory() as tmp, patch(
            "server.generate_industry_radar.load_panel",
            return_value=pd.DataFrame(),
        ), patch(
            "server.generate_industry_radar.build_report_data",
            return_value=fake_report,
        ), patch(
            "server.generate_industry_radar.write_datasets",
            return_value=([], Path(tmp) / "manifest.json"),
        ), patch("server.generate_industry_radar.write_pdf") as pdf_writer:
            self.assertEqual(
                main(["--input", "ignored.parquet", "--output-dir", tmp]), 0
            )
            self.assertEqual(pdf_writer.call_count, 1)
            self.assertEqual(
                pdf_writer.call_args.args[1].name,
                "industry_fund_radar_20260722.pdf",
            )


if __name__ == "__main__":
    unittest.main()
