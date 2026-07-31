"""Research-only Shape Classification V2 building blocks.

Nothing in this package is wired into the V1 production API or UI.
"""

from __future__ import annotations


SCHEMA_VERSION = "shape-v2-dataset/1"
CATEGORY_KEYS = (
    "fresh_breakout",
    "healthy_uptrend",
    "pullback_strengthening",
)
RESEARCH_SPLITS = ("template", "tuning", "final_evaluation")

