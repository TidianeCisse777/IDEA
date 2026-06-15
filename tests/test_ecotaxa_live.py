"""Live integration tests against ecotaxa.obs-vlfr.fr.

Skipped by default — run with ``ECOTAXA_LIVE=1 pytest tests/test_ecotaxa_live.py``.
These tests catch regressions in the EcoTaxa API contract that VCR
cassettes cannot detect (because cassettes record our own assumptions).

History of bugs caught by live testing:
- M3: free object fields require the ``fre.<label>`` prefix in
  /object_set/{id}/query, not ``obj.<code>``.
- M3: /object_set/{id}/summary expects ``{"taxo": "<id>"}`` as a string,
  not a list.
- M3: /taxon_set/search returns ``text`` for the display name, not
  ``display_name``.
- M4: /object_set/{id}/query exposes per-row sample_ids in a parallel
  top-level array, not in ``details``; obj.sample_id is not a queryable
  field.
"""

from __future__ import annotations

import os

import pytest


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("ECOTAXA_LIVE") != "1",
        reason="Live EcoTaxa tests are opt-in (set ECOTAXA_LIVE=1).",
    ),
]


_PROJECT_ID = 42  # UVP5 GREEN EDGE Ice Camp 2015 — stable, public-friendly.


def test_live_search_projects_returns_known_project():
    from core.ecotaxa_browser.search import search_projects

    results = search_projects(page_size=100)
    assert any(p["project_id"] == _PROJECT_ID for p in results), \
        "Service account no longer sees project 42 — check credentials/permissions."


def test_live_get_project_schema_includes_three_levels():
    from core.ecotaxa_browser.schema import get_project_schema

    schema = get_project_schema(_PROJECT_ID)
    assert schema["project_id"] == _PROJECT_ID
    assert set(schema["levels"].keys()) == {"sample", "acquisition", "object"}
    # Project 42 has free object fields named 'area', 'mean', etc.
    free_labels = {f["label"] for f in schema["levels"]["object"]["free"]}
    assert "area" in free_labels, \
        "Expected 'area' free object field missing — EcoTaxa schema regression?"


def test_live_column_distribution_numeric_fixed_field():
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    result = get_column_distribution(_PROJECT_ID, "depth_min")
    assert result["type"] == "number"
    assert result["level"] == "object"
    stats = result["stats"]
    assert stats["n"] > 0
    assert stats["max"] >= stats["min"]


def test_live_column_distribution_numeric_free_field():
    """Catches the 'fre.<label>' vs 'obj.<code>' regression (M3 bug)."""
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    result = get_column_distribution(_PROJECT_ID, "area")
    assert result["type"] == "number"
    assert result["kind"] == "free"
    stats = result["stats"]
    assert stats["n"] > 0, "free field 'area' returned zero samples — fre.<label> path broken?"
    assert stats["min"] >= 0


def test_live_column_distribution_categorical_fixed_field():
    from core.ecotaxa_browser.column_distribution import get_column_distribution

    result = get_column_distribution(_PROJECT_ID, "classif_qual")
    assert result["type"] == "text"
    stats = result["stats"]
    assert stats["sample_size"] > 0
    assert stats["total_distinct"] >= 1


def test_live_search_taxa_returns_text_field():
    """Catches the 'text' vs 'display_name' regression (M3 bug)."""
    from tools.ecotaxa_client import EcotaxaClient

    client = EcotaxaClient()
    client.login()
    candidates = client.search_taxa("Calanus finmarchicus")
    assert candidates, "search_taxa returned no candidates for 'Calanus finmarchicus'."
    first = candidates[0]
    assert "id" in first
    label = first.get("display_name") or first.get("text")
    assert label, "Taxon result has neither display_name nor text — API shape changed."


def test_live_taxon_summary_accepts_string_taxo_payload():
    """Catches the {'taxo': [list]} vs {'taxo': '<id>'} regression (M3 bug)."""
    from tools.ecotaxa_client import EcotaxaClient

    client = EcotaxaClient()
    client.login()
    summary = client.taxon_summary(_PROJECT_ID, 82431)  # Calanus finmarchicus
    assert isinstance(summary, dict)
    assert "total_objects" in summary


def test_live_query_objects_exposes_sample_ids_parallel_array():
    """Catches the M4 bug: obj.sample_id is NOT a queryable field;
    sample_ids ships as a parallel top-level array."""
    from tools.ecotaxa_client import EcotaxaClient

    client = EcotaxaClient()
    client.login()
    payload = client.query_objects(
        project_id=_PROJECT_ID,
        filters={},
        fields="obj.latitude,obj.longitude,obj.objdate",
        window_start=0,
        window_size=5,
    )
    assert "sample_ids" in payload, \
        "EcoTaxa /object_set/query no longer returns top-level sample_ids — sync engine will break."
    assert len(payload["sample_ids"]) == len(payload["details"]), \
        "sample_ids and details arrays diverged — sync zip() will misalign."
