from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.shape_v2_dataset import render_review_html
from server.shape_v2.dataset import (
    anonymous_id,
    assign_grouped_splits,
    assign_research_split,
    build_public_bars,
    build_public_sample,
    source_group_id,
    validate_audit_manifest,
    validate_public_payload,
)
from server.shape_v2.calibration import build_calibration_summary, public_records
from server.shape_v2.metrics import calibration_diagnostics
from server.shape_v2.scoring import CATEGORY_WEIGHT_PRIORS, score_all
from server.shape_v2.facts import extract_shared_facts
from server.patterns import CATEGORY_ORDER as V1_CATEGORY_ORDER
from scripts.shape_v2_template_discovery import healthy_visual_prefilter
from server.shape_v2.selection import (
    BREAKOUT_STAGE_QUOTAS,
    PROFILE_QUOTAS,
    select_targeted_candidates,
)


def source_frame(count: int = 130) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=count)
    close = np.linspace(10.0, 14.0, count)
    return pd.DataFrame(
        {
            "trade_date": dates.strftime("%Y%m%d"),
            "open": close * 0.995,
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "vol": np.linspace(900, 1300, count),
            "adj_factor": np.where(np.arange(count) < 60, 1.0, 1.2),
        }
    )


class ShapeV2DatasetTests(unittest.TestCase):
    def test_window_is_censored_at_score_date_and_has_no_identity_or_dates(self):
        frame = source_frame()
        score_date = str(frame.iloc[124]["trade_date"])
        bars, private = build_public_bars(frame, score_date, 120)
        self.assertEqual(len(bars), 120)
        self.assertEqual(bars[-1]["t"], 0)
        self.assertEqual(private["resolved_score_date"], score_date)
        self.assertTrue(all(set(bar) == {"t", "open", "high", "low", "close", "volume"} for bar in bars))
        self.assertAlmostEqual(bars[0]["close"], 100.0)
        self.assertLessEqual(max(private["source_trade_dates"]), score_date)

    def test_future_rows_cannot_change_a_scoring_date_sample(self):
        frame = source_frame()
        score_date = str(frame.iloc[124]["trade_date"])
        before, _ = build_public_bars(frame.iloc[:125], score_date, 120)
        after, _ = build_public_bars(frame, score_date, 120)
        self.assertEqual(before, after)

    def test_public_sample_schema_rejects_identity(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        validate_public_payload(sample)
        sample["ts_code"] = "000001.SZ"
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_public_payload(sample)

    def test_same_security_is_stably_grouped_and_split(self):
        secret = b"x" * 32
        group_a = source_group_id(secret, "000001.SZ")
        group_b = source_group_id(secret, "000001.SZ")
        self.assertEqual(group_a, group_b)
        weights = {"template": 0.5, "tuning": 0.25, "final_evaluation": 0.25}
        self.assertEqual(
            assign_research_split(group_a, weights),
            assign_research_split(group_b, weights),
        )
        self.assertEqual(
            anonymous_id(secret, "draft", "000001.SZ", "20260701"),
            anonymous_id(secret, "draft", "000001.SZ", "20260701"),
        )

    def test_grouped_split_keeps_small_dataset_near_exact_target(self):
        weights = {"template": 0.5, "tuning": 0.25, "final_evaluation": 0.25}
        assignments = assign_grouped_splits(
            [f"G-{index:02d}" for index in range(24)], weights
        )
        counts = {
            split: list(assignments.values()).count(split) for split in weights
        }
        self.assertEqual(
            counts, {"template": 12, "tuning": 6, "final_evaluation": 6}
        )

    def test_every_category_vector_uses_a_shared_fact(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "shape_v2"
            / "research-v2.0.0-draft1.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        available = set(sample["shared_facts"])
        for category in config["categories"]:
            with self.subTest(category=category["key"]):
                self.assertTrue(set(category["feature_keys"]).issubset(available))

    def test_draft2_category_vectors_use_shared_facts(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "shape_v2"
            / "research-v2.0.0-draft2.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        available = set(sample["shared_facts"])
        for category in config["categories"]:
            with self.subTest(category=category["key"]):
                self.assertTrue(set(category["feature_keys"]).issubset(available))

    def test_draft3_category_vectors_and_breakout_stage_facts_exist(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "shape_v2"
            / "research-v2.0.0-draft3.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        available = set(sample["shared_facts"])
        for category in config["categories"]:
            with self.subTest(category=category["key"]):
                self.assertTrue(set(category["feature_keys"]).issubset(available))
        self.assertTrue(
            {
                "breakout_current_margin",
                "breakout_post_event_drawdown",
                "breakout_approach_return_5",
                "breakout_approach_positive_ratio_10",
            }.issubset(available)
        )

    def test_targeted_selection_fills_profiles_without_reusing_groups(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        base = build_public_sample("S-BASE", "draft", "calibration", bars)
        candidates = []
        for index in range(sum(PROFILE_QUOTAS.values()) + 5):
            candidates.append(
                {
                    "sample": {**base, "sample_id": f"S-{index:02d}"},
                    "audit": {"source_group_id": f"G-{index:02d}"},
                }
            )
        selected = select_targeted_candidates(candidates)
        self.assertEqual(len(selected), sum(PROFILE_QUOTAS.values()))
        self.assertEqual(
            len({item["audit"]["source_group_id"] for item in selected}),
            len(selected),
        )

    def test_breakout_stage_selection_fills_specialized_profiles(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        base = build_public_sample("S-BASE", "draft", "calibration", bars)
        candidates = []
        for index in range(sum(BREAKOUT_STAGE_QUOTAS.values()) + 5):
            candidates.append(
                {
                    "sample": {**base, "sample_id": f"S-STAGE-{index:02d}"},
                    "audit": {"source_group_id": f"G-STAGE-{index:02d}"},
                }
            )
        selected = select_targeted_candidates(candidates, BREAKOUT_STAGE_QUOTAS)
        self.assertEqual(len(selected), sum(BREAKOUT_STAGE_QUOTAS.values()))
        self.assertEqual(
            {item["selection_profile"] for item in selected},
            set(BREAKOUT_STAGE_QUOTAS),
        )

    def test_review_page_uses_clickable_score_buttons(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config = {
            "categories": [
                {
                    "key": "fresh_breakout",
                    "label": "刚突破",
                    "definition": "测试",
                    "core_contradictions": ["测试"],
                },
                {
                    "key": "healthy_uptrend",
                    "label": "健康上升趋势",
                    "definition": "测试",
                    "core_contradictions": ["测试"],
                },
                {
                    "key": "pullback_strengthening",
                    "label": "回调转强",
                    "definition": "测试",
                    "core_contradictions": ["测试"],
                },
            ]
        }
        page = render_review_html(
            {"dataset_version": "draft"},
            {**config, "review_focus": "重点检查突破阶段。"},
            [sample],
        )
        self.assertIn('data-score="3"', page)
        self.assertIn("localStorage", page)
        self.assertIn("重点检查突破阶段", page)
        self.assertNotIn("<select", page)

    def test_audit_rejects_cross_split_security(self):
        base = {
            "source_group_id": "G-A",
            "ts_code": "000001.SZ",
            "requested_score_date": "20260701",
            "resolved_score_date": "20260701",
            "source_trade_dates": ["20260630", "20260701"],
        }
        audit = {
            "samples": [
                {**base, "sample_id": "S-1", "split": "template"},
                {**base, "sample_id": "S-2", "split": "final_evaluation"},
            ]
        }
        findings = validate_audit_manifest(audit)
        self.assertTrue(any("crosses splits" in finding for finding in findings))

    def test_provisional_templates_keep_calibration_role_separate(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "shape_v2"
            / "research-v2.0.0-draft3.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        records = []
        for index in range(8):
            records.append(
                {
                    "round": "C-SYNTHETIC",
                    "dataset_version": "draft",
                    "sample_id": f"S-{index}",
                    "ratings": {
                        category: 3 if index < 4 else 0
                        for category in (
                            "fresh_breakout",
                            "healthy_uptrend",
                            "pullback_strengthening",
                        )
                    },
                    "note": "",
                    "facts": {
                        key: value + index * 0.0001
                        for key, value in sample["shared_facts"].items()
                    },
                    "_ts_code": f"{index:06d}.SZ",
                    "_source_group_id": f"G-{index}",
                }
            )
        rounds = [
            {
                "name": "C-SYNTHETIC",
                "dataset_version": "draft",
                "source_snapshot": "20260727",
                "network_used": False,
                "dataset_fingerprint": "fingerprint",
                "label_file_sha256": "labels",
                "audit_file_sha256": "audit",
                "record_count": len(records),
                "records": records,
            }
        ]
        summary = build_calibration_summary(
            rounds, config["categories"], CATEGORY_WEIGHT_PRIORS
        )
        self.assertEqual(summary["sample_role"]["calibration_count"], 8)
        self.assertEqual(summary["sample_role"]["template_count"], 0)
        self.assertFalse(summary["formal_scoring_enabled"])
        self.assertNotIn("_ts_code", public_records(rounds)[0])

    def test_three_scorers_are_independent_and_explain_caps(self):
        bars, _ = build_public_bars(source_frame(), "20260630", 120)
        sample = build_public_sample("S-TEST", "draft", "calibration", bars)
        config_path = (
            Path(__file__).resolve().parents[2]
            / "config"
            / "shape_v2"
            / "research-v2.0.0-draft3.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        records = []
        for index in range(8):
            records.append(
                {
                    "round": "C",
                    "dataset_version": "draft",
                    "sample_id": f"S-{index}",
                    "ratings": {
                        category: 2 if index < 4 else 0
                        for category in (
                            "fresh_breakout",
                            "healthy_uptrend",
                            "pullback_strengthening",
                        )
                    },
                    "note": "",
                    "facts": {
                        key: value + index * 0.0001
                        for key, value in sample["shared_facts"].items()
                    },
                    "_ts_code": f"{index:06d}.SZ",
                    "_source_group_id": f"G-{index}",
                }
            )
        rounds = [
            {
                "name": "C",
                "dataset_version": "draft",
                "source_snapshot": "20260727",
                "network_used": False,
                "dataset_fingerprint": "fingerprint",
                "label_file_sha256": "labels",
                "audit_file_sha256": "audit",
                "record_count": len(records),
                "records": records,
            }
        ]
        summary = build_calibration_summary(
            rounds, config["categories"], CATEGORY_WEIGHT_PRIORS
        )
        facts = dict(sample["shared_facts"])
        facts["breakout_age"] = 0.0
        predictions = score_all(facts, summary)
        self.assertEqual(set(predictions), set(CATEGORY_WEIGHT_PRIORS))
        self.assertLessEqual(predictions["fresh_breakout"]["score"], 2.0)
        self.assertTrue(
            any(
                cap["code"] == "breakout_day_ceiling"
                for cap in predictions["fresh_breakout"]["caps"]
            )
        )

    def test_calibration_metrics_are_explicitly_in_sample(self):
        records = []
        predictions = {}
        for index in range(4):
            sample_id = f"S-{index}"
            ratings = {
                "fresh_breakout": index,
                "healthy_uptrend": 3 - index,
                "pullback_strengthening": index % 2,
            }
            records.append(
                {
                    "sample_id": sample_id,
                    "round": "C",
                    "ratings": ratings,
                    "note": "",
                }
            )
            predictions[sample_id] = {
                category: {"score": float(ratings[category]), "caps": []}
                for category in ratings
            }
        diagnostics = calibration_diagnostics(records, predictions)
        self.assertEqual(diagnostics["status"], "apparent_in_sample_only")
        self.assertEqual(
            diagnostics["categories"]["fresh_breakout"]["pairwise"]["accuracy"], 1.0
        )

    def test_local_20_day_breakout_is_not_blocked_by_an_old_60_day_high(self):
        close = np.concatenate(
            [
                np.linspace(100.0, 130.0, 30),
                np.linspace(112.0, 105.0, 40),
                np.linspace(104.0, 112.0, 47),
                np.asarray([114.0, 116.0, 117.0]),
            ]
        )
        bars = [
            {
                "t": index - 119,
                "open": float(value * 0.997),
                "high": float(value * 1.002),
                "low": float(value * 0.995),
                "close": float(value),
                "volume": 1.0,
            }
            for index, value in enumerate(close)
        ]
        facts = extract_shared_facts(bars)
        self.assertLessEqual(facts["breakout_age"], 2.0)
        self.assertEqual(facts["breakout_resistance_window"], 20.0)
        self.assertLess(facts["old_high_gap_120"], 0.0)

    def test_v2_namespace_does_not_break_v1_or_keep_range_bounce(self):
        self.assertEqual(
            V1_CATEGORY_ORDER, ("breakout", "pullback", "range_bounce")
        )
        self.assertEqual(
            tuple(CATEGORY_WEIGHT_PRIORS),
            ("fresh_breakout", "healthy_uptrend", "pullback_strengthening"),
        )
        self.assertNotIn("range_bounce", CATEGORY_WEIGHT_PRIORS)

    def test_healthy_template_prefilter_prefers_full_window_rise_over_tail_spike(self):
        smooth_close = np.linspace(100.0, 155.0, 120) * (
            1.0 + np.sin(np.arange(120) / 7.0) * 0.012
        )
        tail_close = np.concatenate(
            [np.linspace(100.0, 96.0, 110), np.linspace(96.0, 155.0, 10)]
        )

        def facts_for(close_values):
            bars = [
                {
                    "t": index - 119,
                    "open": float(value * 0.998),
                    "high": float(value * 1.006),
                    "low": float(value * 0.994),
                    "close": float(value),
                    "volume": 1.0,
                }
                for index, value in enumerate(close_values)
            ]
            return extract_shared_facts(bars)

        smooth = healthy_visual_prefilter(facts_for(smooth_close))
        tail = healthy_visual_prefilter(facts_for(tail_close))
        self.assertGreater(smooth["score"], tail["score"])
        self.assertGreater(
            smooth["components"]["rise_exists_before_tail"],
            tail["components"]["rise_exists_before_tail"],
        )


if __name__ == "__main__":
    unittest.main()
