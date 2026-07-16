from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from server.config import PROJECT_ROOT, load_thresholds
from server.patterns import _breakout, _pullback, _range_bounce
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


if __name__ == "__main__":
    unittest.main()
