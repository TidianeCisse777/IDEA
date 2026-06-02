from __future__ import annotations

from typing import Any

import pandas as pd


def _normalized_key_series(df: pd.DataFrame, key: str) -> pd.Series:
    if key not in df.columns:
        raise KeyError(f"Missing join key: {key}")
    return df[key].dropna().astype(str).str.strip()


def profile_join_keys(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_key: str,
    right_key: str,
) -> dict[str, Any]:
    """Profile join cardinality and row expansion before building deliverables."""
    left_keys = _normalized_key_series(left, left_key)
    right_keys = _normalized_key_series(right, right_key)

    left_counts = left_keys.value_counts()
    right_counts = right_keys.value_counts()
    left_duplicate_keys = int((left_counts > 1).sum())
    right_duplicate_keys = int((right_counts > 1).sum())

    if left_duplicate_keys and right_duplicate_keys:
        cardinality = "many_to_many"
    elif left_duplicate_keys:
        cardinality = "many_to_one"
    elif right_duplicate_keys:
        cardinality = "one_to_many"
    else:
        cardinality = "one_to_one"

    left_unique = set(left_counts.index)
    right_unique = set(right_counts.index)
    matched_unique = left_unique & right_unique
    left_match_rate = round(len(matched_unique) / len(left_unique) * 100, 2) if left_unique else 0.0
    right_match_rate = round(len(matched_unique) / len(right_unique) * 100, 2) if right_unique else 0.0

    estimated_rows = 0
    for key in matched_unique:
        estimated_rows += int(left_counts[key]) * int(right_counts[key])
    row_expansion_factor = round(estimated_rows / len(left), 4) if len(left) else 0.0

    requires_aggregation = cardinality in {"one_to_many", "many_to_many"}
    safe_for_join_deliverable = (
        cardinality in {"one_to_one", "many_to_one"}
        and row_expansion_factor <= 1.05
    )

    return {
        "left_key": left_key,
        "right_key": right_key,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_unique_keys": int(len(left_unique)),
        "right_unique_keys": int(len(right_unique)),
        "matched_unique_keys": int(len(matched_unique)),
        "left_duplicate_keys": left_duplicate_keys,
        "right_duplicate_keys": right_duplicate_keys,
        "cardinality": cardinality,
        "left_match_rate": left_match_rate,
        "right_match_rate": right_match_rate,
        "estimated_join_rows": int(estimated_rows),
        "row_expansion_factor": row_expansion_factor,
        "requires_aggregation": requires_aggregation,
        "safe_for_join_deliverable": safe_for_join_deliverable,
    }
