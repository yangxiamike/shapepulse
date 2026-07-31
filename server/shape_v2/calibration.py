from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from . import CATEGORY_KEYS
from .dataset import content_hash, validate_audit_manifest, validate_public_payload
from .facts import extract_shared_facts


@dataclass(frozen=True)
class CalibrationRound:
    name: str
    labels_path: Path
    public_dir: Path
    audit_path: Path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rating_distribution(records: list[dict[str, Any]], category: str) -> dict[str, int]:
    counts = Counter(int(record["ratings"][category]) for record in records)
    return {str(score): counts.get(score, 0) for score in range(4)}


def _validate_label(label: dict[str, Any], dataset_version: str) -> None:
    if label.get("schema_version") != "shape-v2-labels/1":
        raise ValueError(f"{label.get('sample_id')}: unsupported label schema")
    if label.get("dataset_version") != dataset_version:
        raise ValueError(f"{label.get('sample_id')}: label dataset version mismatch")
    ratings = label.get("ratings")
    if not isinstance(ratings, dict) or tuple(ratings) != CATEGORY_KEYS:
        raise ValueError(f"{label.get('sample_id')}: category keys are incomplete or reordered")
    if any(type(ratings[key]) is not int or ratings[key] not in range(4) for key in CATEGORY_KEYS):
        raise ValueError(f"{label.get('sample_id')}: every category requires an integer 0..3")


def load_calibration_round(spec: CalibrationRound) -> dict[str, Any]:
    """Validate and join one public pack, its labels, and its private audit."""
    manifest_path = spec.public_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    audit = _load_json(spec.audit_path)
    labels = _load_json(spec.labels_path)
    if not isinstance(labels, list) or not labels:
        raise ValueError(f"{spec.name}: labels must be a non-empty JSON array")
    if manifest.get("role") != "calibration" or audit.get("role") != "calibration":
        raise ValueError(f"{spec.name}: only isolated calibration packs are accepted")
    if manifest.get("network_used") is not False or audit.get("source", {}).get("network_used") is not False:
        raise ValueError(f"{spec.name}: network_used must be false")
    dataset_version = str(manifest.get("dataset_version", ""))
    if audit.get("dataset_version") != dataset_version:
        raise ValueError(f"{spec.name}: public/private dataset version mismatch")
    findings = validate_audit_manifest(audit)
    if findings:
        raise ValueError(f"{spec.name}: audit failed: {'; '.join(findings)}")

    manifest_items = {str(item["sample_id"]): item for item in manifest.get("samples", [])}
    audit_items = {str(item["sample_id"]): item for item in audit.get("samples", [])}
    label_items: dict[str, dict[str, Any]] = {}
    for label in labels:
        _validate_label(label, dataset_version)
        sample_id = str(label.get("sample_id", ""))
        if not sample_id or sample_id in label_items:
            raise ValueError(f"{spec.name}: duplicate or empty label sample_id {sample_id!r}")
        label_items[sample_id] = label
    expected_ids = set(manifest_items)
    if expected_ids != set(audit_items) or expected_ids != set(label_items):
        raise ValueError(f"{spec.name}: manifest, audit, and labels do not contain identical samples")
    if int(manifest.get("sample_count", -1)) != len(expected_ids):
        raise ValueError(f"{spec.name}: manifest sample_count mismatch")

    records: list[dict[str, Any]] = []
    for sample_id in sorted(expected_ids):
        manifest_item = manifest_items[sample_id]
        sample_path = spec.public_dir / str(manifest_item["path"])
        sample = _load_json(sample_path)
        validate_public_payload(sample)
        sample_hash = content_hash(sample)
        if sample_hash != manifest_item.get("content_hash"):
            raise ValueError(f"{spec.name}/{sample_id}: public content differs from manifest")
        if sample_hash != audit_items[sample_id].get("public_content_hash"):
            raise ValueError(f"{spec.name}/{sample_id}: public content differs from private audit")
        records.append(
            {
                "round": spec.name,
                "dataset_version": dataset_version,
                "sample_id": sample_id,
                "ratings": {
                    key: int(label_items[sample_id]["ratings"][key]) for key in CATEGORY_KEYS
                },
                "note": str(label_items[sample_id].get("note", "")).strip(),
                # Older calibration packs intentionally remain immutable. Recompute the
                # current shared-fact schema from their already-censored anonymous bars
                # instead of mutating the archived public payload.
                "facts": {
                    key: float(value)
                    for key, value in extract_shared_facts(sample["bars"]).items()
                },
                "_ts_code": str(audit_items[sample_id]["ts_code"]),
                "_source_group_id": str(audit_items[sample_id]["source_group_id"]),
            }
        )
    return {
        "name": spec.name,
        "dataset_version": dataset_version,
        "source_snapshot": str(audit["source"]["snapshots"]["daily_kline"]),
        "network_used": False,
        "dataset_fingerprint": manifest["dataset_fingerprint"],
        "label_file_sha256": _file_sha256(spec.labels_path),
        "audit_file_sha256": _file_sha256(spec.audit_path),
        "record_count": len(records),
        "records": records,
    }


def load_calibration_rounds(specs: Iterable[CalibrationRound]) -> list[dict[str, Any]]:
    rounds = [load_calibration_round(spec) for spec in specs]
    seen_samples: set[str] = set()
    seen_codes: dict[str, str] = {}
    for round_data in rounds:
        for record in round_data["records"]:
            sample_id = record["sample_id"]
            if sample_id in seen_samples:
                raise ValueError(f"sample {sample_id} appears in multiple calibration rounds")
            seen_samples.add(sample_id)
            code = record["_ts_code"]
            prior_round = seen_codes.get(code)
            if prior_round is not None:
                raise ValueError(
                    f"source security crosses calibration rounds: {prior_round} and {round_data['name']}"
                )
            seen_codes[code] = round_data["name"]
    return rounds


def _robust_scale(values: np.ndarray) -> float:
    q25, median, q75 = np.quantile(values, [0.25, 0.5, 0.75])
    iqr_scale = float((q75 - q25) / 1.349)
    mad_scale = float(np.median(np.abs(values - median)) * 1.4826)
    spread_floor = max(
        1e-4,
        abs(float(median)) * 0.02,
        float(np.max(values) - np.min(values)) * 0.02,
    )
    return max(iqr_scale, mad_scale, spread_floor)


def _distance(
    facts: dict[str, float],
    feature_stats: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> float:
    weighted = 0.0
    total_weight = 0.0
    for key, stats in feature_stats.items():
        weight = float(weights[key])
        delta = (float(facts[key]) - float(stats["median"])) / float(stats["robust_scale"])
        weighted += weight * min(delta * delta, 64.0)
        total_weight += weight
    return math.sqrt(weighted / total_weight)


def build_calibration_summary(
    rounds: list[dict[str, Any]],
    category_configs: Iterable[dict[str, Any]],
    weight_priors: dict[str, dict[str, float]],
) -> dict[str, Any]:
    records = [record for round_data in rounds for record in round_data["records"]]
    category_models: dict[str, Any] = {}
    for category in category_configs:
        key = str(category["key"])
        feature_keys = [str(value) for value in category["feature_keys"]]
        positive = [record for record in records if record["ratings"][key] >= 2]
        if len(positive) < 4:
            raise ValueError(f"{key}: fewer than four rating-2/3 calibration examples")
        weights = {
            feature: float(weight_priors.get(key, {}).get(feature, 1.0))
            for feature in feature_keys
        }
        if any(value <= 0 or not math.isfinite(value) for value in weights.values()):
            raise ValueError(f"{key}: feature weights must be finite and positive")
        feature_stats: dict[str, dict[str, float]] = {}
        for feature in feature_keys:
            try:
                all_values = np.asarray([record["facts"][feature] for record in records], dtype=float)
                positive_values = np.asarray(
                    [record["facts"][feature] for record in positive], dtype=float
                )
            except KeyError as exc:
                raise ValueError(f"{key}: missing shared fact {feature}") from exc
            if not np.isfinite(all_values).all() or not np.isfinite(positive_values).all():
                raise ValueError(f"{key}/{feature}: non-finite calibration fact")
            q25, median, q75 = np.quantile(positive_values, [0.25, 0.5, 0.75])
            feature_stats[feature] = {
                "median": round(float(median), 8),
                "q25": round(float(q25), 8),
                "q75": round(float(q75), 8),
                "robust_scale": round(_robust_scale(all_values), 8),
            }
        positive_distances = [
            _distance(record["facts"], feature_stats, weights) for record in positive
        ]
        median_positive_distance = float(np.median(positive_distances))
        distance_scale = max(0.5, median_positive_distance / 0.6680472308)
        positive_count = len(positive)
        confidence = "limited" if positive_count >= 12 else "low"
        category_models[key] = {
            "label": str(category["label"]),
            "feature_keys": feature_keys,
            "weights": weights,
            "template": feature_stats,
            "representative_rule": "human rating >= 2 across isolated calibration rounds",
            "representative_count": positive_count,
            "rating_3_count": sum(record["ratings"][key] == 3 for record in records),
            "distance_scale": round(distance_scale, 8),
            "confidence": confidence,
            "confidence_limit": (
                "临时校准模板；正样本很少，只能用于基准排名与下一轮调优评审。"
                if confidence == "low"
                else "临时校准模板；样本仍不足以替代独立模板集和封存评估。"
            ),
        }
    return {
        "schema_version": "shape-v2-calibration-summary/1",
        "model_version": "shape-v2.0.0-baseline1.1-provisional",
        "status": "calibration_prior_only",
        "formal_scoring_enabled": False,
        "allowed_use": ["definition", "weight_prior", "provisional_template", "tuning_ranking"],
        "forbidden_use": ["final_evaluation", "production_claim", "future_return_prediction"],
        "source": {
            "provider": "local_zer0share",
            "network_used": False,
            "snapshots": sorted({round_data["source_snapshot"] for round_data in rounds}),
        },
        "sample_role": {
            "calibration_count": len(records),
            "template_count": 0,
            "tuning_count": 0,
            "final_evaluation_count": 0,
            "note": "54条历史标注全部保留为定义/先验；当前统计模板是临时降级方案。",
        },
        "rounds": [
            {
                key: round_data[key]
                for key in (
                    "name",
                    "dataset_version",
                    "source_snapshot",
                    "network_used",
                    "dataset_fingerprint",
                    "label_file_sha256",
                    "audit_file_sha256",
                    "record_count",
                )
            }
            for round_data in rounds
        ],
        "rating_distributions": {
            key: _rating_distribution(records, key) for key in CATEGORY_KEYS
        },
        "categories": category_models,
    }


def public_records(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop private source identifiers before diagnostics are serialized."""
    return [
        {key: value for key, value in record.items() if not key.startswith("_")}
        for round_data in rounds
        for record in round_data["records"]
    ]
