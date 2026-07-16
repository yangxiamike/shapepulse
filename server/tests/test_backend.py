from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.config import PROJECT_ROOT, load_thresholds
from server.patterns import _breakout, _pullback, _range_bounce, score_stock
from server.repository import LocalMarketRepository
from server.state import StateStore


class ThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.thresholds = load_thresholds(PROJECT_ROOT / "config" / "thresholds.json")

    def test_category_history_gates_are_independent(self):
        close = np.linspace(10.0, 12.0, 99)
        high = close * 1.01
        low = close * 0.99
        volume = np.full(len(close), 1000.0)
        self.assertIsNone(_breakout(close[:59], volume[:59], self.thresholds["breakout"]))
        self.assertIsNotNone(_breakout(close[:60], volume[:60], self.thresholds["breakout"]))
        self.assertIsNone(_pullback(close[:79], high[:79], self.thresholds["pullback"]))
        self.assertIsNotNone(_pullback(close[:80], high[:80], self.thresholds["pullback"]))
        self.assertIsNone(
            _range_bounce(close, high, low, self.thresholds["range_bounce"])
        )
        close100 = np.append(close, 12.1)
        self.assertIsNotNone(
            _range_bounce(close100, close100 * 1.01, close100 * 0.99, self.thresholds["range_bounce"])
        )

    def test_categories_are_evaluated_independently(self):
        frame = pd.DataFrame(
            {
                "trade_date": [f"2026{month:02d}{day:02d}" for month in range(1, 6) for day in range(1, 21)],
                "close": np.linspace(10, 12, 100),
                "high": np.linspace(10.1, 12.1, 100),
                "low": np.linspace(9.9, 11.9, 100),
                "vol": np.full(100, 1000.0),
                "pct_chg": np.zeros(100),
            }
        )
        details = lambda score: {"score": score, "reasons": ["测试"], "metrics": {"value": 1.0}}
        with patch("server.patterns._breakout", return_value=details(88)), patch(
            "server.patterns._pullback", return_value=details(72)
        ), patch("server.patterns._range_bounce", return_value=details(66)):
            result = score_stock(frame, self.thresholds)
        self.assertEqual(result["status"], "matched")
        self.assertEqual([item["category"] for item in result["matches"]], ["breakout", "pullback", "range_bounce"])
        self.assertEqual(result["category"], "breakout")


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 6,
                "trade_date": ["20251230", "20251231", "20260102", "20260331", "20260401", "20260702"],
                "open": [10, 11, 12, 13, 14, 15],
                "high": [11, 12, 13, 14, 15, 16],
                "low": [9, 10, 11, 12, 13, 14],
                "close": [10.5, 11.5, 12.5, 13.5, 14.5, 15.5],
                "pre_close": [9.5, 10.5, 11.5, 12.5, 13.5, 14.5],
                "vol": [1, 2, 3, 4, 5, 6],
                "amount": [10, 20, 30, 40, 50, 60],
            }
        )

    def test_week_month_quarter_and_year_have_distinct_boundaries(self):
        weekly = LocalMarketRepository._resample(self.frame, "1w")
        monthly = LocalMarketRepository._resample(self.frame, "1m")
        quarterly = LocalMarketRepository._resample(self.frame, "1q")
        yearly = LocalMarketRepository._resample(self.frame, "1y")
        self.assertNotEqual(len(weekly), len(monthly))
        self.assertNotEqual(len(monthly), len(quarterly))
        self.assertEqual(len(yearly), 2)
        first_2026_quarter = quarterly[quarterly["trade_date"].eq("20260331")].iloc[0]
        self.assertEqual(first_2026_quarter["open"], 12)
        self.assertEqual(first_2026_quarter["high"], 14)
        self.assertEqual(first_2026_quarter["low"], 11)
        self.assertEqual(first_2026_quarter["close"], 13.5)
        self.assertEqual(first_2026_quarter["vol"], 7)


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tempdir.name) / "state.sqlite3")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_view_save_pending_and_clear(self):
        code = "000001.SZ"
        self.store.update(code, "viewed")
        self.store.update(code, "save")
        state = self.store.update(code, "pending")
        self.assertTrue(state["viewed"])
        self.assertEqual(state["view_count"], 1)
        self.assertTrue(state["saved"])
        self.assertTrue(state["pending"])
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["saved"][0]["ts_code"], code)
        self.store.update(code, "clear")
        self.assertFalse(self.store.for_code(code)["viewed"])

    def test_screen_history_round_trip(self):
        run_id = self.store.record_screen(
            "20260716",
            {"boards": ["主板"], "top_k": 50},
            [
                {
                    "ts_code": "000001.SZ",
                    "category": "pullback",
                    "category_label": "上升趋势回调",
                    "rank": 1,
                    "score": 78.2,
                    "reasons": ["高点后浅回撤"],
                }
            ],
        )
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot["history"]["runs"][0]["run_id"], run_id)
        self.assertEqual(
            snapshot["history"]["recommendations"][0]["reasons"], ["高点后浅回撤"]
        )

    def test_pattern_states_and_real_previous_snapshot_counts(self):
        filters = {"boards": ["主板"], "top_k": 50, "mode": "per_category"}
        self.store.record_screen(
            "20260715",
            filters,
            [],
            evaluations=[{"ts_code": "000001.SZ", "status": "no_match", "matches": [], "history_bars": 120, "trade_date": "20260715"}],
            category_counts={"breakout": 3, "pullback": 4, "range_bounce": 5},
        )
        previous = self.store.previous_category_counts(filters, "20260716")
        self.assertEqual(previous, ("20260715", {"breakout": 3, "pullback": 4, "range_bounce": 5}))
        pattern = self.store.pattern_for_code("000001.SZ")
        self.assertEqual(pattern["calculation_state"], "calculated_no_match")
        self.store.record_screen(
            "20260716",
            filters,
            [],
            evaluations=[{
                "ts_code": "000001.SZ",
                "status": "matched",
                "matches": [{"category": "breakout", "category_label": "突破启动", "score": 81, "reasons": ["平台突破"], "metrics": {}}],
                "history_bars": 120,
                "trade_date": "20260716",
            }],
            category_counts={"breakout": 4, "pullback": 4, "range_bounce": 5},
        )
        self.assertEqual(self.store.pattern_for_code("000001.SZ")["calculation_state"], "matched")


if __name__ == "__main__":
    unittest.main()
