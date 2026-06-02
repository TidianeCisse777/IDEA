import pandas as pd
import pytest

from core.copepod_join_validation import profile_join_keys


def test_many_to_many_join_is_not_deliverable_safe():
    left = pd.DataFrame({"sample_id": [1, 1, 2], "taxon": ["a", "b", "c"]})
    right = pd.DataFrame({"sample_id": [1, 1, 3], "cast": ["x", "y", "z"]})

    profile = profile_join_keys(left, right, "sample_id", "sample_id")

    assert profile["cardinality"] == "many_to_many"
    assert profile["safe_for_join_deliverable"] is False
    assert profile["requires_aggregation"] is True
    assert profile["left_duplicate_keys"] == 1
    assert profile["right_duplicate_keys"] == 1
    assert profile["row_expansion_factor"] > 1.0


def test_many_to_one_join_is_safe_when_no_row_explosion():
    left = pd.DataFrame({"sample_id": [1, 1, 2], "taxon": ["a", "b", "c"]})
    right = pd.DataFrame({"sample_id": [1, 2], "station": ["A", "B"]})

    profile = profile_join_keys(left, right, "sample_id", "sample_id")

    assert profile["cardinality"] == "many_to_one"
    assert profile["safe_for_join_deliverable"] is True
    assert profile["row_expansion_factor"] == 1.0
    assert profile["left_match_rate"] == 100.0
    assert profile["right_match_rate"] == 100.0


def test_missing_join_key_raises_clear_key_error():
    left = pd.DataFrame({"sample_id": [1]})
    right = pd.DataFrame({"other_id": [1]})

    with pytest.raises(KeyError, match="Missing join key"):
        profile_join_keys(left, right, "missing", "other_id")


def test_profile_join_keys_is_available_in_copepod_data_runtime_tool():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401 - triggers registration

    ns = {}
    exec(registry.render({"copepod_data"}), ns)

    assert "profile_join_keys" in ns
    left = pd.DataFrame({"sample_id": [1, 1, 2]})
    right = pd.DataFrame({"sample_id": [1, 2]})
    profile = ns["profile_join_keys"](left, right, "sample_id", "sample_id")
    assert profile["cardinality"] == "many_to_one"
    assert profile["safe_for_join_deliverable"] is True


def test_runtime_merge_is_blocked_until_join_is_profiled():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401 - triggers registration

    ns = {}
    exec(registry.render({"copepod_data"}), ns)

    left = pd.DataFrame({"sample_id": [1, 1, 2]})
    right = pd.DataFrame({"sample_id": [1, 2]})

    with pytest.raises(RuntimeError, match="profile_join_keys"):
        left.merge(right, left_on="sample_id", right_on="sample_id")


def test_runtime_merge_is_allowed_after_safe_profile():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401 - triggers registration

    ns = {}
    exec(registry.render({"copepod_data"}), ns)

    left = pd.DataFrame({"sample_id": [1, 1, 2]})
    right = pd.DataFrame({"sample_id": [1, 2]})

    profile = ns["profile_join_keys"](left, right, "sample_id", "sample_id")
    assert profile["safe_for_join_deliverable"] is True

    left_work = left.copy()
    right_work = right.copy()
    merged = left_work.merge(right_work, left_on="sample_id", right_on="sample_id")
    assert merged.shape == (3, 1)
