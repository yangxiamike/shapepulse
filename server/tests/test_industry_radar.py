from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from server.industry_radar import (
    ANOMALY_HISTORY_DAYS,
    BREADTH_WEIGHT,
    COMPREHENSIVE_SCORE_SCALE,
    CONFIRMATION_DECAY,
    PERSISTENCE_WEIGHT,
    SCORE_ROUND_DECIMALS,
    _deterministic_rank,
    analyze_industries,
    minimum_required_trading_days,
)


def panel(days: int = 140) -> pd.DataFrame:
    rows = []
    for day in range(days):
        date = f"2026{day // 31 + 1:02d}{day % 31 + 1:02d}"
        for code, l1, l2, base, name in [
            ("000001.SZ", "金融", "银行", 10.0, "平安银行"),
            ("000002.SZ", "金融", "银行", 8.0, "万科A"),
            ("000003.SZ", "工业", "工程机械", -7.0, "中联重科"),
            ("000004.SZ", "工业", "工程机械", -5.0, "国机重装"),
        ]:
            flow = base if day >= days - 20 else base * 0.1
            if code == "000001.SZ" and day == days - 1:
                flow = 80.0
            rows.append({
                "trade_date": date,
                "ts_code": code,
                "stock_name": name,
                "l1_code": l1,
                "l1_name": l1,
                "l2_code": l2,
                "l2_name": l2,
                "inst_net_flow": flow,
                "amount": 1000.0,
                "circ_mv": 5000.0 if code in {"000001.SZ", "000002.SZ"} else 2000.0,
                "close": 10.0 + day * (0.02 if base > 0 else -0.01),
            })
    return pd.DataFrame(rows)


class IndustryRadarTests(unittest.TestCase):
    def test_minimum_window_is_history_plus_selected_horizon(self):
        self.assertEqual(minimum_required_trading_days(), ANOMALY_HISTORY_DAYS + 20)
        self.assertEqual(minimum_required_trading_days(5, 3), 8)

    def test_formula_chain_is_exact_and_levels_are_ranked_separately(self):
        for level in ("l1", "l2"):
            rows = analyze_industries(panel(), level, horizon=5).rankings
            self.assertEqual(len(rows), 2)
            expected_confirmation = (
                PERSISTENCE_WEIGHT * rows["persistence_ratio"]
                + BREADTH_WEIGHT * rows["breadth_ratio"]
            )
            expected_multiplier = np.exp(
                -CONFIRMATION_DECAY * (1.0 - expected_confirmation)
            )
            expected_score = (
                rows["base_strength"] * expected_multiplier
            ).round(SCORE_ROUND_DECIMALS)
            np.testing.assert_allclose(
                rows["confirmation_score"], expected_confirmation
            )
            np.testing.assert_allclose(
                rows["confirmation_multiplier"], expected_multiplier
            )
            np.testing.assert_allclose(rows["score"], expected_score)
            np.testing.assert_allclose(
                rows["comprehensive_score"],
                rows["score"] * COMPREHENSIVE_SCORE_SCALE,
            )
            self.assertEqual(
                rows.sort_values(["score", f"{level}_code"], ascending=[False, True])[
                    f"{level}_code"
                ].tolist(),
                rows.sort_values(
                    ["comprehensive_score", f"{level}_code"],
                    ascending=[False, True],
                )[f"{level}_code"].tolist(),
            )
            self.assertNotIn("relative_state_score", rows)
            self.assertNotIn("direction_score", rows)
            self.assertNotIn("anomaly_percentile", rows)

    def test_direction_flip_flips_score_sign_without_a_formula_branch(self):
        positive = analyze_industries(panel(), "l2", horizon=5).rankings.set_index(
            "l2_name"
        )
        flipped_source = panel()
        flipped_source["inst_net_flow"] *= -1
        negative = analyze_industries(
            flipped_source, "l2", horizon=5
        ).rankings.set_index("l2_name")
        self.assertGreater(positive.loc["银行", "score"], 0)
        self.assertLess(negative.loc["银行", "score"], 0)
        self.assertAlmostEqual(
            positive.loc["银行", "confirmation_multiplier"],
            negative.loc["银行", "confirmation_multiplier"],
        )
        self.assertAlmostEqual(
            positive.loc["银行", "score"],
            -negative.loc["银行", "score"],
        )

    def test_every_inflow_ranks_before_every_outflow_in_both_horizons(self):
        source = panel()
        for horizon in (5, 20):
            rows = analyze_industries(source, "l2", horizon=horizon).rankings
            inflow = rows[rows[f"flow_{horizon}d"] > 0]
            outflow = rows[rows[f"flow_{horizon}d"] < 0]
            self.assertLess(inflow["rank"].max(), outflow["rank"].min())
            self.assertTrue((inflow["score"] > 0).all())
            self.assertTrue((outflow["score"] < 0).all())

    def test_obvious_outflow_cannot_be_lifted_above_a_real_inflow(self):
        source = panel()
        dates = sorted(source["trade_date"].unique())[-20:]
        bank = source["l2_name"].eq("银行")
        machinery = source["l2_name"].eq("工程机械")
        source.loc[bank & source["trade_date"].isin(dates), "inst_net_flow"] = 1.0
        source.loc[machinery & source["trade_date"].isin(dates), "inst_net_flow"] = -500.0
        for horizon in (5, 20):
            rows = analyze_industries(
                source, "l2", horizon=horizon
            ).rankings.set_index("l2_name")
            self.assertGreater(rows.loc["银行", "score"], 0)
            self.assertLess(rows.loc["工程机械", "score"], 0)
            self.assertLess(rows.loc["银行", "rank"], rows.loc["工程机械", "rank"])

    def test_all_outflow_market_still_has_a_complete_signed_ranking(self):
        source = panel()
        final_dates = sorted(source["trade_date"].unique())[-20:]
        source.loc[
            source["trade_date"].isin(final_dates), "inst_net_flow"
        ] = -np.arange(1, len(source[source["trade_date"].isin(final_dates)]) + 1)
        for level in ("l1", "l2"):
            for horizon in (5, 20):
                rows = analyze_industries(source, level, horizon=horizon).rankings
                self.assertTrue((rows["direction_sign"] == -1).all())
                self.assertTrue((rows["score"] < 0).all())
                self.assertEqual(
                    sorted(rows["rank"].tolist()), list(range(1, len(rows) + 1))
                )

    def test_zero_flow_defines_both_confirmation_ratios_and_score_as_zero(self):
        source = panel()
        final_dates = sorted(source["trade_date"].unique())[-20:]
        source.loc[source["trade_date"].isin(final_dates), "inst_net_flow"] = 0.0
        for level in ("l1", "l2"):
            for horizon in (5, 20):
                rows = analyze_industries(source, level, horizon=horizon).rankings
                self.assertTrue((rows["direction_sign"] == 0).all())
                self.assertTrue((rows["persistence_ratio"] == 0).all())
                self.assertTrue((rows["breadth_ratio"] == 0).all())
                self.assertTrue((rows["base_strength"] == 0).all())
                self.assertTrue((rows["score"] == 0).all())
                self.assertFalse(
                    rows[
                        [
                            "persistence_ratio",
                            "breadth_ratio",
                            "confirmation_score",
                            "confirmation_multiplier",
                            "base_strength",
                            "score",
                        ]
                    ].isna().any().any()
                )

    def test_five_and_twenty_day_windows_are_independent(self):
        source = panel()
        last_twenty = sorted(source["trade_date"].unique())[-20:]
        last_five = last_twenty[-5:]
        bank = source["l2_name"].eq("银行")
        machinery = source["l2_name"].eq("工程机械")
        source.loc[bank & source["trade_date"].isin(last_twenty), "inst_net_flow"] = -10
        source.loc[bank & source["trade_date"].isin(last_five), "inst_net_flow"] = 20
        source.loc[
            machinery & source["trade_date"].isin(last_twenty), "inst_net_flow"
        ] = 10
        source.loc[
            machinery & source["trade_date"].isin(last_five), "inst_net_flow"
        ] = -5
        five = analyze_industries(source, "l2", horizon=5).rankings.set_index(
            "l2_name"
        )
        twenty = analyze_industries(source, "l2", horizon=20).rankings.set_index(
            "l2_name"
        )
        self.assertEqual(five.loc["银行", "rank"], 1)
        self.assertEqual(twenty.loc["工程机械", "rank"], 1)
        self.assertGreater(five.loc["银行", "score"], 0)
        self.assertLess(twenty.loc["银行", "score"], 0)

    def test_return_and_anomaly_changes_do_not_affect_score_or_rank(self):
        source = panel()
        first = {
            (level, horizon): analyze_industries(
                source, level, horizon=horizon
            ).rankings.set_index(f"{level}_code")
            for level in ("l1", "l2")
            for horizon in (5, 20)
        }
        bank_latest = source["ts_code"].eq("000001.SZ") & source[
            "trade_date"
        ].eq(source["trade_date"].max())
        source.loc[bank_latest, "close"] *= 10
        # Change only flow history before both scoring windows so current
        # 5-day and 20-day formula inputs stay fixed while anomaly z changes.
        old_dates = sorted(source["trade_date"].unique())[:-20]
        source.loc[
            source["l2_name"].eq("银行")
            & source["trade_date"].isin(old_dates),
            "inst_net_flow",
        ] *= 100
        second = {
            (level, horizon): analyze_industries(
                source, level, horizon=horizon
            ).rankings.set_index(f"{level}_code")
            for level in ("l1", "l2")
            for horizon in (5, 20)
        }
        for key in first:
            pd.testing.assert_series_equal(
                first[key]["score"], second[key]["score"]
            )
            pd.testing.assert_series_equal(
                first[key]["rank"], second[key]["rank"]
            )
        self.assertFalse(
            np.isclose(
                first[("l2", 5)].loc["银行", "return_20d"],
                second[("l2", 5)].loc["银行", "return_20d"],
            )
        )
        self.assertFalse(
            np.isclose(
                first[("l2", 20)].loc["银行", "anomaly_raw"],
                second[("l2", 20)].loc["银行", "anomaly_raw"],
            )
        )

    def test_persistence_and_breadth_only_apply_light_confirmation(self):
        source = panel()
        result = analyze_industries(source, "l2", horizon=5).rankings
        minimum = np.exp(-CONFIRMATION_DECAY)
        self.assertTrue(
            result["confirmation_multiplier"].between(
                minimum, 1.0, inclusive="both"
            ).all()
        )
        self.assertTrue(
            np.isclose(
                result["score"].abs() / result["base_strength"].abs(),
                result["confirmation_multiplier"],
                atol=10 ** -SCORE_ROUND_DECIMALS,
            ).all()
        )

        final_dates = sorted(source["trade_date"].unique())[-5:]
        bank = source["l2_name"].eq("银行")
        bank_a = bank & source["ts_code"].eq("000001.SZ")
        bank_b = bank & source["ts_code"].eq("000002.SZ")
        source.loc[bank & source["trade_date"].isin(final_dates), "inst_net_flow"] = 0
        for date, value in zip(final_dates, [100, -20, 100, -20, 100]):
            source.loc[
                bank_a & source["trade_date"].eq(date), "inst_net_flow"
            ] = value
        source.loc[
            bank_b & source["trade_date"].isin(final_dates), "inst_net_flow"
        ] = -1
        weak = analyze_industries(source, "l2", horizon=5).rankings.set_index(
            "l2_name"
        ).loc["银行"]
        self.assertAlmostEqual(weak["persistence_ratio"], 3 / 5)
        self.assertAlmostEqual(weak["breadth_ratio"], 0.5)
        self.assertLess(weak["confirmation_multiplier"], 1)
        self.assertGreaterEqual(weak["confirmation_multiplier"], minimum)

    def test_rank_is_deterministic_under_input_order_changes(self):
        source = panel()
        shuffled = source.sample(frac=1, random_state=44)
        for level in ("l1", "l2"):
            for horizon in (5, 20):
                code = f"{level}_code"
                first = analyze_industries(
                    source, level, horizon=horizon
                ).rankings[[code, "rank"]]
                second = analyze_industries(
                    shuffled, level, horizon=horizon
                ).rankings[[code, "rank"]]
                pd.testing.assert_frame_equal(
                    first.reset_index(drop=True), second.reset_index(drop=True)
                )

    def test_near_float_tie_uses_quantized_auditable_keys(self):
        rankings = pd.DataFrame([
            {
                "l2_code": "NEG",
                "score": 0.00100000000004,
                "base_strength": 0.001,
                "flow_5d": -10.0,
                "flow_1d": 0.0,
            },
            {
                "l2_code": "POS",
                "score": 0.00099999999996,
                "base_strength": 0.001,
                "flow_5d": 10.0,
                "flow_1d": 0.0,
            },
        ])
        ranked = _deterministic_rank(rankings, "l2_code", 5)
        self.assertEqual(ranked["l2_code"].tolist(), ["POS", "NEG"])
        self.assertEqual(ranked["score"].nunique(), 1)

    def test_invalid_horizon_and_duplicate_stock_day_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "horizon"):
            analyze_industries(panel(), "l2", horizon=10)
        source = pd.concat([panel(), panel().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            analyze_industries(source, "l2")

    def test_contributors_use_real_names_and_follow_selected_direction(self):
        result = analyze_industries(panel(), "l2", horizon=5)
        self.assertTrue((result.contributors.groupby("l2_name").size() <= 3).all())
        bank = result.contributors[result.contributors["l2_name"].eq("银行")].iloc[0]
        machinery = result.contributors[
            result.contributors["l2_name"].eq("工程机械")
        ].iloc[0]
        self.assertEqual(bank["stock_name"], "平安银行")
        self.assertGreater(bank["inst_net_flow"], 0)
        self.assertLess(machinery["inst_net_flow"], 0)


if __name__ == "__main__":
    unittest.main()
