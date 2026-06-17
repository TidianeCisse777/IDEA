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
    assert "polygon_wkt" in result
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


def test_get_zone_info_polygon_wkt_is_valid_and_matches_bbox():
    """Le polygon_wkt doit être chargeable shapely et son enveloppe doit
    correspondre au bbox renvoyé."""
    from tools.geo_tools import get_zone_info

    result = get_zone_info.invoke({"zone_name": "Baie d'Hudson"})
    polygon = wkt.loads(result["polygon_wkt"])
    minx, miny, maxx, maxy = polygon.bounds
    bbox = result["bbox"]

    assert bbox["west"]  == pytest.approx(minx, abs=1e-3)
    assert bbox["south"] == pytest.approx(miny, abs=1e-3)
    assert bbox["east"]  == pytest.approx(maxx, abs=1e-3)
    assert bbox["north"] == pytest.approx(maxy, abs=1e-3)


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
