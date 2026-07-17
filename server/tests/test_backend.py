from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.config import PROJECT_ROOT, load_settings, load_thresholds
from server.industry_strength import (
    build_industry_strength,
    fixed_sample_dates,
    heat_level,
    industry_status,
    latest_first,
    recent_persistence,
    recent_slope,
    rotation_observation_key,
    select_active_industries,
)
from server.patterns import (
    _breakout,
    _pullback,
    _range_bounce,
    score_category_arrays,
    score_stock,
)
from server.repository import LocalMarketRepository, SnapshotDates
from server.service import MarketService
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

    def test_array_fast_path_matches_the_existing_category_scores(self):
        length = 120
        frame = pd.DataFrame(
            {
                "trade_date": [f"2026{index:04d}" for index in range(length)],
                "close": np.linspace(10, 13, length),
                "high": np.linspace(10.2, 13.2, length),
                "low": np.linspace(9.8, 12.8, length),
                "vol": np.linspace(900, 1300, length),
                "pct_chg": np.zeros(length),
            }
        )
        full = score_stock(frame, self.thresholds)
        expected = {item["category"]: item["score"] for item in full["matches"]}
        matrix = frame[["close", "high", "low", "vol"]].to_numpy(float)
        close, high, low, volume = matrix.T
        for category in ("breakout", "pullback", "range_bounce"):
            with self.subTest(category=category):
                self.assertEqual(
                    score_category_arrays(
                        category, close, high, low, volume, self.thresholds
                    ),
                    expected.get(category),
                )


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

    def test_daily_normalization_keeps_ohlcv_on_one_valid_date_axis(self):
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 4,
                "trade_date": ["2026-01-02", "20260102", "20260103", "bad"],
                "open": ["10", 10.2, None, 9],
                "high": [9.5, 10.4, 11, 10],
                "low": [10.5, 10.1, 10, 8],
                "close": [10.1, 10.3, 10.5, 9.5],
                "pre_close": [9.9, 10.1, 10.3, 9],
                "vol": [None, 20, 30, 40],
                "amount": [100, 200, 300, 400],
            }
        )
        result = LocalMarketRepository._normalize_daily(frame)
        self.assertEqual(result["trade_date"].tolist(), ["20260102"])
        row = result.iloc[0]
        self.assertGreaterEqual(row["high"], max(row["open"], row["close"]))
        self.assertLessEqual(row["low"], min(row["open"], row["close"]))
        self.assertGreaterEqual(row["vol"], 0)


class IndustryStrengthTests(unittest.TestCase):
    def test_sampling_is_exactly_120_days_at_five_day_intervals(self):
        dates = [f"2026{index:04d}" for index in range(1, 121)]
        samples = fixed_sample_dates(dates)
        self.assertEqual(len(samples), 24)
        self.assertEqual(samples[0], dates[4])
        self.assertEqual(samples[-1], dates[-1])
        self.assertEqual(
            [int(samples[index]) - int(samples[index - 1]) for index in range(1, 24)],
            [5] * 23,
        )

    def test_heat_scale_caps_visually_but_preserves_real_value(self):
        self.assertEqual([heat_level(value) for value in [0, 1, 3, 5, 8, 10, 17]], [0, 1, 2, 3, 4, 4, 5])
        self.assertEqual(17.0, float(17))

    def test_recent_four_point_slope_and_persistence_are_linear_and_stable(self):
        self.assertEqual(recent_slope([99, 0, 1, 2, 3]), 1.0)
        self.assertEqual(recent_slope([8, 6, 4, 2]), -2.0)
        self.assertEqual(recent_slope([4, 4, 4, 4]), 0.0)
        self.assertEqual(recent_persistence([0, 1, 2, 3]), 1.0)
        self.assertEqual(recent_persistence([0, 2, 1, 3]), 0.67)

    def test_latest_first_order_is_a_copy(self):
        dates = ["20260101", "20260102", "20260103"]
        self.assertEqual(latest_first(dates), list(reversed(dates)))
        self.assertEqual(dates, ["20260101", "20260102", "20260103"])

    def test_active_selection_excludes_zero_and_reserves_both_directions(self):
        rows: list[dict[str, object]] = []
        for index in range(6):
            counts = [0, index + 1, (index + 1) * 2, (index + 1) * 3]
            slope = recent_slope(counts)
            rows.append({
                "code": f"U{index}",
                "counts": counts,
                "recent_slope": slope,
                "recent_persistence": recent_persistence(counts, slope),
            })
        for index in range(8):
            value = index + 1
            counts = [value * 3, value * 2, value, 0]
            slope = recent_slope(counts)
            rows.append({
                "code": f"D{index}",
                "counts": counts,
                "recent_slope": slope,
                "recent_persistence": recent_persistence(counts, slope),
            })
        rows.append({
            "code": "ZERO",
            "counts": [0, 0, 0, 0],
            "recent_slope": 0.0,
            "recent_persistence": 0.0,
        })
        selected = select_active_industries(rows)
        self.assertEqual(len(selected), 12)
        self.assertNotIn("ZERO", {row["code"] for row in selected})
        self.assertGreaterEqual(sum(row["recent_slope"] > 0 for row in selected), 4)
        self.assertGreaterEqual(sum(row["recent_slope"] < 0 for row in selected), 4)
        self.assertEqual(
            [row["recent_slope"] for row in selected],
            sorted((row["recent_slope"] for row in selected), reverse=True),
        )

    def test_same_speed_observation_sort_uses_persistence_level_then_code(self):
        rows = [
            {"code": "B", "counts": [0, 1, 2, 3], "recent_slope": 1.0, "recent_persistence": 1.0},
            {"code": "A", "counts": [0, 1, 2, 3], "recent_slope": 1.0, "recent_persistence": 1.0},
            {"code": "C", "counts": [2, 1, 2, 3], "recent_slope": 1.0, "recent_persistence": 0.67},
        ]
        self.assertEqual(
            [row["code"] for row in sorted(rows, key=rotation_observation_key)],
            ["A", "B", "C"],
        )

    def test_status_boundaries_are_stable(self):
        self.assertEqual(industry_status([0, 0, 0, 3], 12), "↗ 快速启动")
        self.assertEqual(industry_status([1, 1, 1, 1], 12), "→ 变化不大")
        self.assertEqual(industry_status([1, 2, 3, 4], 8), "↑ 持续增强")
        self.assertEqual(industry_status([7, 6, 5, 4], 3), "⇣ 高位退潮")
        self.assertEqual(industry_status([7, 6, 5, 4], 8), "↓ 正在走弱")

    def test_top100_percent_sorting_clip_and_current_top10_promotion(self):
        dates = [f"2026{index:04d}" for index in range(5, 121, 5)]
        industries = [
            {"code": f"I{index:02d}", "name": f"行业{index:02d}"}
            for index in range(31)
        ]
        top_by_date: dict[str, list[dict[str, object]]] = {}
        for date_index, date in enumerate(dates):
            items: list[dict[str, object]] = []
            for stock_index in range(100):
                industry_index = stock_index % 20
                if date_index == len(dates) - 1 and stock_index < 8:
                    industry_index = 30
                items.append(
                    {
                        "ts_code": f"{stock_index:06d}.SZ",
                        "name": f"股票{stock_index}",
                        "score": 100 - stock_index,
                        "industry_code": f"I{industry_index:02d}",
                        "industry_name": f"行业{industry_index:02d}",
                    }
                )
            top_by_date[date] = items
        result = build_industry_strength(
            pattern="breakout",
            pattern_label="突破启动",
            requested_end_date=None,
            sample_dates=dates,
            industries=industries,
            top_by_date=top_by_date,
        )
        self.assertEqual(result["sampling"]["sample_count"], 24)
        self.assertEqual(result["scope"]["industry_count"], 31)
        self.assertEqual(result["actual_top_by_date"][dates[-1]], 100)
        self.assertEqual(result["display"]["default_visible_count"], 12)
        self.assertEqual(result["display"]["folded_count"], 0)
        self.assertIn("I30", result["display"]["default_visible_codes"])
        current_total = sum(row["current_count"] for row in result["ranking"])
        self.assertEqual(current_total, 100)
        self.assertTrue(all(row["current_percent"] == float(row["current_count"]) for row in result["ranking"]))
        self.assertEqual(
            sorted(row["rank"] for row in result["ranking"]),
            list(range(1, 32)),
        )
        self.assertEqual(
            result["display"]["latest_first_dates"],
            list(reversed(dates)),
        )

    def test_incomplete_top_and_missing_industry_are_explicit(self):
        date = "20260716"
        result = build_industry_strength(
            pattern="pullback",
            pattern_label="上升趋势回调",
            requested_end_date=date,
            sample_dates=[date],
            industries=[{"code": "I01", "name": "电子"}],
            top_by_date={
                date: [
                    {
                        "ts_code": "000001.SZ",
                        "name": "测试",
                        "score": 80,
                        "industry_code": None,
                    }
                ]
            },
        )
        self.assertEqual(result["actual_top_by_date"][date], 1)
        self.assertEqual(result["missing_industry_by_date"][date], 1)
        self.assertTrue(any("固定以 100 为分母" in item for item in result["warnings"]))
        self.assertTrue(any("缺少可追溯" in item for item in result["warnings"]))


class ScreenSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.service = MarketService.__new__(MarketService)
        self.service.thresholds = load_thresholds(PROJECT_ROOT / "config" / "thresholds.json")
        industry = pd.DataFrame(
            {"l1_code": ["801780.SI", "801080.SI"], "l1_name": ["银行", "电子"]}
        )
        self.service.repository = type("Repository", (), {"industries": lambda _self: industry})()

    def test_market_cap_range_four_modes_are_inclusive(self):
        values = pd.Series([49.9, 50.0, 100.0, 100.1])
        cases = [
            ({"market_cap_min_yi": None, "market_cap_max_yi": None}, [True] * 4),
            ({"market_cap_min_yi": 50.0, "market_cap_max_yi": None}, [False, True, True, True]),
            ({"market_cap_min_yi": None, "market_cap_max_yi": 100.0}, [True, True, True, False]),
            ({"market_cap_min_yi": 50.0, "market_cap_max_yi": 100.0}, [False, True, True, False]),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                self.assertEqual(MarketService._market_cap_mask(values, filters).tolist(), expected)

    def test_filter_normalization_supports_industry_range_st_and_unbounded_top_k(self):
        filters = self.service._normalize_filters(
            {
                "boards": ["主板", "创业板"],
                "industries": ["银行", "801080.SI"],
                "market_cap_min_yi": "",
                "market_cap_max_yi": "100",
                "exclude_st": "false",
                "top_k": "1000",
            }
        )
        self.assertEqual(filters["industries"], ["银行", "801080.SI"])
        self.assertIsNone(filters["market_cap_min_yi"])
        self.assertEqual(filters["market_cap_max_yi"], 100.0)
        self.assertFalse(filters["exclude_st"])
        self.assertEqual(filters["top_k"], 1000)

    def test_invalid_range_and_non_integer_top_k_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            self.service._normalize_filters(
                {"market_cap_min_yi": 101, "market_cap_max_yi": 100}
            )
        for value in (0, -1, "1.5", True):
            with self.subTest(top_k=value), self.assertRaisesRegex(ValueError, "positive integer"):
                self.service._normalize_filters({"top_k": value})

    def test_pattern_pool_uses_current_complete_calculation_not_saved_snapshot(self):
        saved_item = {"ts_code": "000001.SZ", "name": "旧快照股票", "score": 99}
        self.service.state_store = type(
            "StateStore",
            (),
            {"latest_saved_category": lambda _self, _category: ({"run_id": "old-run"}, [saved_item])},
        )()
        current_items = [
            {"ts_code": "600001.SH", "name": "当前股票一", "score": 92},
            {"ts_code": "600002.SH", "name": "当前股票二", "score": 91},
        ]
        received: dict[str, object] = {}

        def screen(filters, save):
            received.update({"filters": filters, "save": save})
            return {
                "categories": {"breakout": current_items},
                "counts": {"by_category": {"breakout": 2}},
                "as_of": {"daily": "20260716"},
            }

        self.service.screen = screen
        result = self.service.pattern_pool("breakout", 500)

        self.assertEqual(received, {"filters": {"mode": "per_category", "top_k": 500}, "save": False})
        self.assertEqual(result["source"], "current_calculation")
        self.assertEqual(result["total"], 2)
        self.assertEqual([item["ts_code"] for item in result["items"]], ["600001.SH", "600002.SH"])

    def test_pattern_calculates_current_stock_without_saved_history(self):
        dates = [f"2026{month:02d}{day:02d}" for month in range(1, 7) for day in range(1, 21)]
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * len(dates),
                "trade_date": dates,
                "open": np.linspace(10.0, 10.8, len(dates)),
                "high": np.linspace(10.1, 10.9, len(dates)),
                "low": np.linspace(9.9, 10.7, len(dates)),
                "close": np.linspace(10.0, 10.8, len(dates)),
                "vol": np.full(len(dates), 1000.0),
            }
        )
        snapshots = SnapshotDates(
            daily_kline="20260620",
            daily_basic="20260620",
            adj_factor="20260620",
            stock_st="20260620",
            suspend_d="20260619",
            stk_limit="20260620",
            universe="20260619",
        )
        self.service.repository = type(
            "Repository",
            (),
            {
                "resolve_code": lambda _self, _code: "000001.SZ",
                "snapshots": lambda _self: snapshots,
                "pattern_daily": lambda _self, _code, _start, _end: frame,
            },
        )()
        self.service.state_store = type(
            "StateStore",
            (),
            {
                "pattern_for_code": lambda _self, _code, _limit: {
                    "calculation_state": "not_calculated",
                    "history": [],
                }
            },
        )()

        result = self.service.pattern("000001")

        self.assertEqual(result["source"], "current_local_snapshot")
        self.assertNotEqual(result["calculation_state"], "not_calculated")
        self.assertEqual(result["current"]["trade_date"], "20260620")
        self.assertEqual(result["current"]["history_bars"], 120)
        self.assertEqual(result["as_of"]["daily_kline"], "20260620")


class LocalDataIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = load_settings()
        if not settings.zer0share_root.is_dir():
            raise unittest.SkipTest("local zer0share data is unavailable")
        cls.repository = LocalMarketRepository(
            settings.zer0share_root, settings.zer0share_config
        )

    @classmethod
    def tearDownClass(cls):
        cls.repository._duck.close()

    def test_estun_qfq_segments_share_anchor_and_renderer_safe_ohlcv(self):
        current = self.repository.bars(
            "002747.SZ", "20250101", None, "qfq", "1d", 120
        )
        self.assertIsNotNone(current)
        self.assertEqual(current["bars"][-1]["trade_date"], current["range"]["newest_available"])
        segment_end = current["bars"][20]["trade_date"]
        older = self.repository.bars(
            "002747.SZ", "20250101", segment_end, "qfq", "1d", 80
        )
        current_close = {item["trade_date"]: item["close"] for item in current["bars"]}
        overlap = [item for item in older["bars"] if item["trade_date"] in current_close]
        self.assertTrue(overlap)
        self.assertTrue(
            all(item["close"] == current_close[item["trade_date"]] for item in overlap)
        )
        self.assertTrue(current["range"]["has_more_before"])
        for item in current["bars"]:
            self.assertLessEqual(item["low"], min(item["open"], item["close"]))
            self.assertGreaterEqual(item["high"], max(item["open"], item["close"]))
            self.assertIsNotNone(item["volume"])


class ScreenTokenTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = MarketService.__new__(MarketService)
        self.service.thresholds = load_thresholds(PROJECT_ROOT / "config" / "thresholds.json")
        self.service.state_store = StateStore(Path(self.tempdir.name) / "state.sqlite3")
        self.service._screen_lock = threading.RLock()
        self.service._completed_screens = {}

    def tearDown(self):
        self.tempdir.cleanup()

    def test_token_persists_exact_payload_and_is_idempotent(self):
        result = {
            "ts_code": "000001.SZ",
            "category": "breakout",
            "category_label": "突破启动",
            "rank": 1,
            "score": 88.8,
            "match_score": 88.8,
            "reasons": ["放量突破"],
        }
        payload = {
            "screen_token": "token-1",
            "as_of": {"daily": "20260716"},
            "filters": {"mode": "combined", "top_k": 50, "industries": ["电子"]},
            "results": [result],
            "categories": {"breakout": [result], "pullback": [], "range_bounce": []},
            "counts": {"by_category": {"breakout": 1, "pullback": 0, "range_bounce": 0}},
            "warnings": [],
        }
        self.service._remember_completed_screen("token-1", payload, [])
        payload["results"][0]["score"] = 1.0
        first = self.service.save_screen_snapshot("token-1")
        second = self.service.save_screen_snapshot("token-1")
        self.assertEqual(first["history_run_id"], second["history_run_id"])
        detail = self.service.saved_snapshot(first["history_run_id"])
        self.assertEqual(detail["results"][0]["score"], 88.8)
        self.assertEqual(self.service.saved_snapshots()["total"], 1)


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

    def test_user_saved_snapshot_pagination_detail_and_hidden_calculation(self):
        result = {
            "ts_code": "000001.SZ",
            "category": "breakout",
            "category_label": "突破启动",
            "rank": 1,
            "score": 88.8,
            "reasons": ["放量突破"],
            "match": 0.888,
        }
        self.store.record_screen("20260715", {"top_k": 50}, [result], saved_by_user=False)
        run_id = self.store.record_screen(
            "20260716",
            {"industries": ["电子"], "market_cap_min_yi": 50, "top_k": 50},
            [result],
            rule_version="2",
            payload={"results": [result], "categories": {"breakout": [result]}},
            saved_by_user=True,
        )
        page = self.store.list_saved_snapshots(page=1, page_size=1)
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["run_id"], run_id)
        detail = self.store.saved_snapshot(run_id)
        self.assertEqual(detail["restore"]["filters"]["industries"], ["电子"])
        self.assertEqual(detail["results"][0]["match"], 0.888)
        self.assertEqual(detail["rule_version"], "2")

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
