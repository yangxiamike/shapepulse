from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Any

import numpy as np

from . import CATEGORY_KEYS


def _ndcg(ratings: list[int]) -> float:
    gains = [2**rating - 1 for rating in ratings]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sorted(gains, reverse=True)
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return 0.0 if idcg == 0 else dcg / idcg


def _pairwise_accuracy(items: list[dict[str, Any]], category: str) -> dict[str, Any]:
    correct = 0
    ties = 0
    total = 0
    for left, right in combinations(items, 2):
        left_rating = int(left["ratings"][category])
        right_rating = int(right["ratings"][category])
        if left_rating == right_rating:
            continue
        total += 1
        left_score = float(left["predictions"][category]["score"])
        right_score = float(right["predictions"][category]["score"])
        if math.isclose(left_score, right_score, abs_tol=1e-12):
            ties += 1
            correct += 0.5
        elif (left_score > right_score) == (left_rating > right_rating):
            correct += 1
    return {
        "accuracy": round(correct / total, 6) if total else None,
        "comparable_pairs": total,
        "predicted_ties": ties,
    }


def calibration_diagnostics(
    records: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    items = [
        {**record, "predictions": predictions[record["sample_id"]]} for record in records
    ]
    categories: dict[str, Any] = {}
    severe_errors: dict[str, list[dict[str, Any]]] = {}
    for category in CATEGORY_KEYS:
        ranked = sorted(
            items,
            key=lambda item: (
                -float(item["predictions"][category]["score"]),
                item["sample_id"],
            ),
        )
        top_metrics: dict[str, Any] = {}
        for requested in (20, 50):
            selected = ranked[: min(requested, len(ranked))]
            top_metrics[f"top{requested}"] = {
                "actual_n": len(selected),
                "purity_rating_ge_2": round(
                    sum(item["ratings"][category] >= 2 for item in selected)
                    / len(selected),
                    6,
                ),
                "severe_error_rate_rating_0": round(
                    sum(item["ratings"][category] == 0 for item in selected)
                    / len(selected),
                    6,
                ),
            }
        strata = []
        for index, bucket in enumerate(np.array_split(np.asarray(ranked, dtype=object), 4), 1):
            bucket_items = list(bucket)
            strata.append(
                {
                    "stratum": index,
                    "n": len(bucket_items),
                    "score_min": round(
                        min(float(item["predictions"][category]["score"]) for item in bucket_items),
                        6,
                    ),
                    "score_max": round(
                        max(float(item["predictions"][category]["score"]) for item in bucket_items),
                        6,
                    ),
                    "mean_human_rating": round(
                        sum(item["ratings"][category] for item in bucket_items)
                        / len(bucket_items),
                        6,
                    ),
                }
            )
        categories[category] = {
            **top_metrics,
            "ndcg_0_3": round(
                _ndcg([int(item["ratings"][category]) for item in ranked]), 6
            ),
            "pairwise": _pairwise_accuracy(items, category),
            "score_strata": strata,
        }
        severe_errors[category] = [
            {
                "sample_id": item["sample_id"],
                "round": item["round"],
                "human_rating": 0,
                "score": item["predictions"][category]["score"],
                "caps": item["predictions"][category]["caps"],
                "note": item["note"],
            }
            for item in ranked[:20]
            if item["ratings"][category] == 0
        ]

    confusion: dict[str, dict[str, int]] = {
        human: {predicted: 0 for predicted in CATEGORY_KEYS} for human in CATEGORY_KEYS
    }
    excluded_ties = 0
    for item in items:
        human_max = max(item["ratings"].values())
        human_winners = [
            key for key in CATEGORY_KEYS if item["ratings"][key] == human_max
        ]
        if len(human_winners) != 1:
            excluded_ties += 1
            continue
        predicted = max(
            CATEGORY_KEYS,
            key=lambda key: (
                float(item["predictions"][key]["score"]),
                -CATEGORY_KEYS.index(key),
            ),
        )
        confusion[human_winners[0]][predicted] += 1
    return {
        "schema_version": "shape-v2-calibration-diagnostics/1",
        "status": "apparent_in_sample_only",
        "warning": "模型统计模板来自同一批校准标注；这些指标只用于找明显错误，不能当作调优或封存测试成绩。",
        "sample_count": len(items),
        "categories": categories,
        "dominant_category_confusion": {
            "definition": "仅统计人工最高分唯一的样本；三类原始标签仍是独立且可重叠的。",
            "excluded_human_ties": excluded_ties,
            "matrix": confusion,
        },
        "severe_errors_in_top20": severe_errors,
    }
