"""Regression tests for the agent-facing EcoTaxa profile-map capability."""

from __future__ import annotations

import pandas as pd


def test_profile_map_tool_persists_one_render_row_per_profile(tmp_path, monkeypatch):
    import tools.copepod_sources as source_module
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr(source_module, "_store", store)
    monkeypatch.setattr(
        source_module,
        "profiles_for_map",
        lambda zone_name: {
            "zone": {
                "requested": zone_name,
                "canonical": "Baie de Baffin",
                "source": "IHO test",
            },
            "profiles": [
                {"profile_id": "P-1", "n_samples": 2, "lat_avg": 70.0, "lon_avg": -65.0},
                {"profile_id": "P-2", "n_samples": 1, "lat_avg": 71.0, "lon_avg": -66.0},
            ],
            "coverage": {
                "samples_in_zone": 3,
                "samples_with_profile_id": 3,
                "profiles_with_coordinates": 2,
                "samples_missing_profile_id": 0,
                "profiles_missing_coordinates": 0,
            },
        },
    )

    tool = next(
        item for item in source_module.make_source_tools("profile-map-thread")
        if item.name == "summarize_ecotaxa_profiles_for_map"
    )
    result = tool.invoke({"zone_name": "Baie de Baffin"})

    assert "2 profils" in result
    assert "n_samples" in result
    session = store.get("profile-map-thread")
    assert session["meta"]["variable_name"] == "df_ecotaxa_profile_map"
    pd.testing.assert_frame_equal(
        session["df"].reset_index(drop=True),
        pd.DataFrame([
            {"profile_id": "P-1", "n_samples": 2, "lat_avg": 70.0, "lon_avg": -65.0},
            {"profile_id": "P-2", "n_samples": 1, "lat_avg": 71.0, "lon_avg": -66.0},
        ]),
    )


def test_profile_map_tool_explains_exact_zone_cache_gap(tmp_path, monkeypatch):
    import tools.copepod_sources as source_module
    from tools.session_store import SessionStore

    monkeypatch.setattr(source_module, "_store", SessionStore(tmp_path / "sessions"))
    monkeypatch.setattr(
        source_module,
        "profiles_for_map",
        lambda zone_name: {
            "zone": {"requested": zone_name, "canonical": "Baie d'Hudson", "source": "IHO test"},
            "profiles": [],
            "coverage": {
                "samples_in_zone": 0,
                "samples_with_profile_id": 0,
                "profiles_with_coordinates": 0,
                "samples_missing_profile_id": 0,
                "profiles_missing_coordinates": 4,
            },
        },
    )

    tool = next(
        item for item in source_module.make_source_tools("profile-map-empty-thread")
        if item.name == "summarize_ecotaxa_profiles_for_map"
    )
    result = tool.invoke({"zone_name": "Baie d'Hudson"})

    assert "0 sample dans le contour exact" in result
    assert "ne conclut pas" in result


def test_profile_map_tool_global_persists_zone_for_cast_coloring(tmp_path, monkeypatch):
    import tools.copepod_sources as source_module
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr(source_module, "_store", store)
    monkeypatch.setattr(
        source_module,
        "profiles_for_map",
        lambda *, zone_reference: {
            "zone": {
                "requested": None,
                "canonical": "Toutes les zones IHO",
                "source": "cache partagé EcoTaxa",
                "reference": zone_reference,
            },
            "profiles": [
                {"profile_id": "P-1", "n_samples": 2, "lat_avg": 70.0, "lon_avg": -65.0, "zone": "Baie de Baffin"},
            ],
            "coverage": {
                "samples_in_zone": 2,
                "samples_with_profile_id": 2,
                "profiles_with_coordinates": 1,
                "samples_missing_profile_id": 0,
                "profiles_missing_coordinates": 0,
                "zone_reference": "IHO",
            },
        },
    )

    tool = next(
        item for item in source_module.make_source_tools("profile-map-global-thread")
        if item.name == "summarize_ecotaxa_profiles_for_map"
    )
    result = tool.invoke({"zone_reference": "IHO"})

    assert "Référence globale : IHO" in result
    assert "colorer par `zone`" in result
    session = store.get("profile-map-global-thread")
    assert session["df"].columns.tolist() == ["profile_id", "n_samples", "lat_avg", "lon_avg", "zone"]
