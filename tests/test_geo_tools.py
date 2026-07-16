"""TDD pour tools/geo_tools.py — get_zone_info, le tool LangChain qui
remplace l'ancien get_zone_filter.

Le tool s'appuie sur core.geo + le registry de prod
(data/geo/zones_registry.geojson). Les tests requièrent donc que le registry
ait été construit (skip sinon, mais le registry est commit dans le repo).
"""
from __future__ import annotations
from pathlib import Path

import pytest
from shapely import wkt
from shapely.geometry import Point


PROD_REGISTRY = Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"
pytestmark = pytest.mark.skipif(
    not PROD_REGISTRY.exists(),
    reason="zones_registry.geojson absent — lancer python -m core.geo.build_registry",
)


def test_get_zone_info_returns_canonical_bbox_polygon_for_ungava():
    """Tracer principal : résoudre une zone connue → dict complet."""
    from tools.geo_tools import get_zone_info

    result = get_zone_info.invoke({"zone_name": "Baie d'Ungava"})

    assert result["canonical"] == "Baie d'Ungava"
    assert "IHO" in result["source"]
    # polygon_wkt_preview is the truncated preview; the full WKT no longer
    # transits through the LLM channel (downstream tools use zone_name).
    assert "polygon_wkt_preview" in result
    assert "zone_name" in result["usage_hint"]
    # bbox calculé depuis le polygone, pas hardcodé
    bbox = result["bbox"]
    assert {"south", "west", "north", "east"} == set(bbox)
    # Ungava : la bbox englobe le polygone réel (qui hérite de la tongue
    # IHO Hudson Strait au sud-est) — vérifier des bornes plausibles plutôt
    # que serrer les valeurs exactes du polygone simplifié.
    assert 55 <= bbox["south"] <= 60
    assert 60 <= bbox["north"] <= 62
    assert -73 <= bbox["west"] <= -68
    assert -66 <= bbox["east"] <= -63


def test_get_zone_info_resolves_english_alias_case_insensitively():
    """L'ancien get_zone_filter acceptait 'ungava bay', 'Ungava', etc. — on garde."""
    from tools.geo_tools import get_zone_info

    for alias in ["ungava bay", "Ungava Bay", "ungava", "UNGAVA"]:
        result = get_zone_info.invoke({"zone_name": alias})
        assert result.get("canonical") == "Baie d'Ungava", f"alias {alias!r} a échoué"


def test_get_zone_info_returns_error_dict_on_unknown_zone():
    """Convention agent : retourner un dict d'erreur, pas lever d'exception."""
    from tools.geo_tools import get_zone_info

    result = get_zone_info.invoke({"zone_name": "Mer de Nulle Part"})

    assert "error" in result
    assert "Mer de Nulle Part" in result["error"]
    assert "available_zones" in result


def test_get_zone_info_polygon_wkt_preview_is_truncated_with_note():
    """Le polygon_wkt_preview doit être tronqué et indiquer la taille totale
    pour éviter qu'un LLM copie 480 KB de WKT à un tool aval."""
    from tools.geo_tools import get_zone_info

    result = get_zone_info.invoke({"zone_name": "Baie d'Hudson"})
    preview = result["polygon_wkt_preview"]

    assert len(preview) < 300, "preview must stay short to avoid LLM truncation"
    assert "chars total" in preview or preview.startswith("POLYGON")
    assert "zone_name" in result["usage_hint"]


def test_get_zone_info_pandas_filter_string_uses_polygon_aware_columns():
    """Le pandas_filter conservé pour compat reste un bbox filter df['latitude']/'longitude',
    parce que c'est ce que l'agent injectait dans run_pandas. Plus précis maintenant
    parce que le bbox vient du polygone, pas d'une bbox tapée à la main."""
    from tools.geo_tools import get_zone_info

    result = get_zone_info.invoke({"zone_name": "Baie d'Ungava"})
    f = result["pandas_filter"]
    assert "df['latitude']"  in f
    assert "df['longitude']" in f
    assert ">=" in f and "<=" in f


def test_get_zone_info_supports_hawke_and_nunavik_and_arctique():
    """Les 3 zones non-IHO (registry composite/synthétique) doivent répondre."""
    from tools.geo_tools import get_zone_info

    for zone in ["Hawke Channel", "Nunavik", "Arctique"]:
        result = get_zone_info.invoke({"zone_name": zone})
        assert "error" not in result, f"{zone!r} aurait dû résoudre"
        assert result["canonical"] == zone


# --- Slice 3 : filter_dataframe_by_zone -------------------------------------


@pytest.fixture
def session_store(tmp_path):
    from tools.session_store import SessionStore
    return SessionStore(storage_dir=tmp_path)


def _load_df_into_session(store, thread_id, df, *, variable_name="df_test"):
    """Mimic what load_file does: register df as the latest session df and pin
    it as the canonical loaded file."""
    from tools.dataset_registry import store_dataset
    store_dataset(
        store, thread_id, df,
        variable_name=variable_name,
        meta={"source": "file:test.csv", "columns": []},
        latest_alias=variable_name,
        is_loaded_file=True,
    )


def test_filter_dataframe_by_zone_keeps_only_points_inside_polygon(session_store):
    """Tracer principal : un df mixte (Baffin + Hudson + Labrador) filtré par
    'Baie de Baffin' ne doit garder QUE les points strictement dans le polygone IHO."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    # Baffin in (74°N -68°W) and (75°N -73°W) — verified inside IHO polygon.
    # Hudson out (58°N -85°W), Labrador out (55°N -55°W).
    df = pd.DataFrame({
        "station_id": ["BAF1", "BAF2", "HUD1", "LAB1"],
        "latitude":   [74.0,   75.0,   58.0,   55.0],
        "longitude": [-68.0,  -73.0,  -85.0,  -55.0],
    })
    thread = "thread-filter-baffin"
    _load_df_into_session(session_store, thread, df)

    tools = make_geo_tools(thread, store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    out = fn.invoke({
        "zone_name": "Baie de Baffin",
        "lat_col": "latitude",
        "lon_col": "longitude",
    })

    # tool returns a dict summary
    assert out["zone_canonical"] == "Baie de Baffin"
    assert out["n_in"] == 2
    assert out["n_out"] == 2
    assert "variable_name" in out  # new df under a session alias

    # the filtered df must be retrievable from the session under that name
    sess = session_store.get(f"{thread}:dataset:{out['variable_name']}")
    assert sess is not None
    kept = sess["df"]
    assert sorted(kept["station_id"].tolist()) == ["BAF1", "BAF2"]


def test_filter_dataframe_by_zone_defaults_lat_lon_column_names(session_store):
    """Convention NeoLab : si l'utilisateur ne précise pas, on tente
    latitude/longitude (les noms standard EcoTaxa/Amundsen)."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({
        "latitude":  [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    thread = "thread-filter-defaults"
    _load_df_into_session(session_store, thread, df)

    tools = make_geo_tools(thread, store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    out = fn.invoke({"zone_name": "Baie de Baffin"})

    assert out["n_in"] == 1
    assert out["n_out"] == 1


def test_filter_dataframe_by_zone_blocks_on_unknown_zone(session_store):
    """Zone inconnue → précondition bloquée, jamais faux résultat vide."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({"latitude": [74.0], "longitude": [-68.0]})
    thread = "thread-filter-unknown"
    _load_df_into_session(session_store, thread, df)

    tools = make_geo_tools(thread, store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    result = fn.invoke({"zone_name": "Mer de Nulle Part"})
    assert "Mer de Nulle Part" in result


def test_filter_dataframe_by_zone_errors_when_no_df_loaded(session_store):
    """Aucun fichier chargé → message d'erreur clair (similaire à run_pandas)."""
    from tools.geo_tools import make_geo_tools

    tools = make_geo_tools("thread-no-df", store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    out = fn.invoke({"zone_name": "Baie de Baffin"})
    # Either return a string error OR raise — accept both, but message must mention load_file
    if isinstance(out, str):
        assert "load_file" in out.lower() or "aucun" in out.lower()
    else:
        # If implementer chose to raise: ensure it's not a silent empty result
        pytest.fail("filter_dataframe_by_zone should not return success when no df is loaded")


def test_filter_dataframe_by_zone_blocks_when_lat_lon_columns_missing(session_store):
    """Si lat/lon ne sont pas dans le df, on doit échouer explicitement
    (le LLM doit pouvoir corriger en passant les bons noms de colonnes)."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({"lat_avg": [74.0], "lon_avg": [-68.0]})
    thread = "thread-filter-bad-cols"
    _load_df_into_session(session_store, thread, df)

    tools = make_geo_tools(thread, store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    # default latitude/longitude don't exist in this df
    msg = fn.invoke({"zone_name": "Baie de Baffin"}).lower()
    assert "latitude" in msg or "longitude" in msg or "colonne" in msg or "column" in msg


def test_filter_dataframe_by_zone_does_not_mutate_original_df(session_store):
    """Le df original reste accessible — filter crée un nouveau df sous un autre nom."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({
        "latitude":  [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    thread = "thread-filter-immut"
    _load_df_into_session(session_store, thread, df, variable_name="df_loki_2024")

    tools = make_geo_tools(thread, store=session_store)
    fn = next(t for t in tools if t.name == "filter_dataframe_by_zone")
    fn.invoke({"zone_name": "Baie de Baffin"})

    original = session_store.get(f"{thread}:dataset:df_loki_2024")
    assert original is not None
    assert len(original["df"]) == 2  # original unchanged


def test_filter_dataframe_by_zone_can_rebase_on_named_source_variable(session_store):
    """A second zone request must be able to use the original file, not the
    previously filtered active subset."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({
        "station_id": ["BAF", "LAB"],
        "latitude": [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    thread = "thread-filter-rebase"
    _load_df_into_session(
        session_store, thread, df, variable_name="df_file_original"
    )
    fn = next(
        tool for tool in make_geo_tools(thread, store=session_store)
        if tool.name == "filter_dataframe_by_zone"
    )
    fn.invoke({"zone_name": "Baie de Baffin"})

    out = fn.invoke({
        "zone_name": "Mer du Labrador",
        "source_variable": "df_file_original",
    })

    assert out["n_in"] == 1
    kept = session_store.get(f"{thread}:dataset:{out['variable_name']}")["df"]
    assert kept["station_id"].tolist() == ["LAB"]
    assert out["source_variable"] == "df_file_original"


def test_filter_dataframe_by_zone_defaults_to_loaded_file_not_active_subset(session_store):
    """Régression cartes-samples-labrador-2026 : après un filtre Baffin devenu
    le df actif, une demande Labrador SANS source_variable doit repartir du
    fichier chargé, pas du sous-ensemble Baffin (zones disjointes → 0)."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({
        "station_id": ["BAF", "LAB"],
        "latitude": [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    thread = "thread-filter-default-anchor"
    _load_df_into_session(
        session_store, thread, df, variable_name="df_file_original"
    )
    fn = next(
        tool for tool in make_geo_tools(thread, store=session_store)
        if tool.name == "filter_dataframe_by_zone"
    )
    # Premier filtre : Baffin devient le df actif.
    baffin = fn.invoke({"zone_name": "Baie de Baffin"})
    assert baffin["n_in"] == 1

    # Second filtre Labrador sans source_variable : doit re-ancrer sur le fichier.
    out = fn.invoke({"zone_name": "Mer du Labrador"})

    assert out["n_in"] == 1  # LAB retrouvé — pas 0 depuis le sous-ensemble Baffin
    kept = session_store.get(f"{thread}:dataset:{out['variable_name']}")["df"]
    assert kept["station_id"].tolist() == ["LAB"]
    assert out["source_variable"] == "df_file_original"
    assert out.get("rebased_on") == "df_file_original"
    assert "note" in out  # le rebasage est signalé au modèle


def test_filter_dataframe_by_zone_reanchors_even_when_subset_passed_explicitly(session_store):
    """Curl 5 : l'agent passe EXPLICITEMENT le sous-ensemble Baffin comme
    source_variable pour un filtre Labrador. Le tool doit ignorer ce mauvais
    choix et re-ancrer sur le fichier chargé (un filtre de zone repart du
    fichier, jamais d'un sous-ensemble d'une autre zone)."""
    import pandas as pd
    from tools.geo_tools import make_geo_tools

    df = pd.DataFrame({
        "station_id": ["BAF", "LAB"],
        "latitude": [74.0, 55.0],
        "longitude": [-68.0, -55.0],
    })
    thread = "thread-filter-explicit-subset"
    _load_df_into_session(session_store, thread, df, variable_name="df_file_original")
    fn = next(
        tool for tool in make_geo_tools(thread, store=session_store)
        if tool.name == "filter_dataframe_by_zone"
    )
    baffin = fn.invoke({"zone_name": "Baie de Baffin"})
    baffin_var = baffin["variable_name"]

    # L'erreur exacte de l'agent : source explicite = sous-ensemble Baffin.
    out = fn.invoke({
        "zone_name": "Mer du Labrador",
        "source_variable": baffin_var,
    })

    assert out["n_in"] == 1  # re-ancré sur le fichier → LAB retrouvé, pas 0
    assert out["source_variable"] == "df_file_original"
    assert out.get("rebased_on") == "df_file_original"
