"""TDD — core/ecotaxa_browser/column_distribution.py."""

from unittest.mock import MagicMock, patch

import pytest


_SCHEMA_SAMPLE_FIXED_DEPTH = {
    "project_id": 42,
    "title": "Stub",
    "instrument": "UVP5",
    "levels": {
        "sample": {"fixed": [{"name": "orig_id", "type": "text"}], "free": []},
        "acquisition": {"fixed": [{"name": "orig_id", "type": "text"}], "free": []},
        "object": {
            "fixed": [
                {"name": "depth_min", "type": "number"},
                {"name": "depth_max", "type": "number"},
                {"name": "classif_qual", "type": "text"},
            ],
            "free": [{"label": "area", "type": "number"}],
        },
    },
    "labels_index": {
        "depthmin": [{"level": "object", "kind": "fixed", "type": "number"}],
        "depthmax": [{"level": "object", "kind": "fixed", "type": "number"}],
        "classifqual": [{"level": "object", "kind": "fixed", "type": "text"}],
        "area": [{"level": "object", "kind": "free", "type": "number"}],
    },
}

_SCHEMA_AMBIGUOUS_DEPTH = {
    "project_id": 42,
    "title": "Stub",
    "instrument": "UVP5",
    "levels": {
        "sample": {
            "fixed": [{"name": "orig_id", "type": "text"}],
            "free": [{"label": "depth", "code": "n02", "type": "number"}],
        },
        "acquisition": {
            "fixed": [{"name": "orig_id", "type": "text"}],
            "free": [{"label": "depth", "code": "n08", "type": "number"}],
        },
        "object": {"fixed": [], "free": []},
    },
    "labels_index": {
        "depth": [
            {"level": "sample", "kind": "free", "type": "number"},
            {"level": "acquisition", "kind": "free", "type": "number"},
        ],
    },
}


def _patched(schema, *, client=None):
    client = client or MagicMock()
    client.login.return_value = None
    return (
        patch(
            "core.ecotaxa_browser.column_distribution.get_project_schema",
            return_value=schema,
        ),
        patch(
            "core.ecotaxa_browser.column_distribution.EcotaxaClient",
            return_value=client,
        ),
        client,
    )


def test_numeric_distribution_uses_column_stats_when_supported():
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    client = MagicMock()
    client.column_stats.return_value = {
        "min": 5.0,
        "max": 120.0,
        "mean": 42.3,
        "median": 38.0,
        "p25": 20.0,
        "p75": 60.0,
        "n": 84668,
    }

    patches = _patched(_SCHEMA_SAMPLE_FIXED_DEPTH, client=client)
    with patches[0], patches[1]:
        result = get_column_distribution(42, "area")

    assert result["source"] == "ecotaxa_column_stats"
    assert result["type"] == "number"
    assert result["level"] == "object"
    assert result["kind"] == "free"
    stats = result["stats"]
    assert stats["min"] == 5.0
    assert stats["max"] == 120.0
    assert stats["mean"] == 42.3
    assert stats["median"] == 38.0
    assert stats["n"] == 84668


def test_categorical_distribution_falls_back_to_first_window():
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    client = MagicMock()
    client.query_objects.return_value = {
        "details": [["V"], ["V"], ["P"], ["V"], ["D"], ["V"], ["P"], ["V"]],
    }

    patches = _patched(_SCHEMA_SAMPLE_FIXED_DEPTH, client=client)
    with patches[0], patches[1]:
        result = get_column_distribution(42, "classif_qual")

    assert result["source"] == "first_window_sample"
    assert result["type"] == "text"
    stats = result["stats"]
    assert stats["total_distinct"] == 3
    top = {item["value"]: item["count"] for item in stats["top_values"]}
    assert top == {"V": 5, "P": 2, "D": 1}
    assert stats["sample_size"] == 8


def test_get_column_distribution_raises_AMBIGUOUS_COLUMN_with_candidates():
    from core.ecotaxa_browser.column_distribution import get_column_distribution
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    patches = _patched(_SCHEMA_AMBIGUOUS_DEPTH)
    with patches[0], patches[1]:
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            get_column_distribution(42, "depth")

    assert exc_info.value.code == "AMBIGUOUS_COLUMN"
    candidates_levels = sorted(c["level"] for c in exc_info.value.candidates)
    assert candidates_levels == ["acquisition", "sample"]


def test_get_column_distribution_resolves_explicit_level_disambiguates():
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    client = MagicMock()
    client.column_stats.return_value = {
        "min": 0.0, "max": 200.0, "mean": 50.0, "median": 45.0,
        "p25": 20.0, "p75": 80.0, "n": 100,
    }

    patches = _patched(_SCHEMA_AMBIGUOUS_DEPTH, client=client)
    with patches[0], patches[1]:
        result = get_column_distribution(42, "depth", level="sample")

    assert result["level"] == "sample"
    assert result["source"] == "ecotaxa_column_stats"


def test_get_column_distribution_raises_COLUMN_NOT_FOUND():
    from core.ecotaxa_browser.column_distribution import get_column_distribution
    from core.ecotaxa_browser.errors import EcoTaxaBrowserError

    patches = _patched(_SCHEMA_SAMPLE_FIXED_DEPTH)
    with patches[0], patches[1]:
        with pytest.raises(EcoTaxaBrowserError) as exc_info:
            get_column_distribution(42, "completely_unknown_field")

    assert exc_info.value.code == "COLUMN_NOT_FOUND"


def test_numeric_fallback_when_column_stats_unsupported():
    """If column_stats returns no usable payload, fall back to first window."""
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    client = MagicMock()
    client.column_stats.return_value = {}
    client.query_objects.return_value = {
        "details": [[1.0], [2.0], [3.0], [4.0], [5.0]],
    }

    patches = _patched(_SCHEMA_SAMPLE_FIXED_DEPTH, client=client)
    with patches[0], patches[1]:
        result = get_column_distribution(42, "area")

    assert result["source"] == "first_window_sample"
    assert result["type"] == "number"
    stats = result["stats"]
    assert stats["min"] == 1.0
    assert stats["max"] == 5.0
    assert stats["mean"] == 3.0
    assert stats["n"] == 5
