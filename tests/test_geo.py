"""TDD tracer bullets for core.geo (Slice 1)."""
from __future__ import annotations
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from core.geo import (
    Registry,
    Zone,
    assign_zones,
    audit_zone_coverage,
    cut_polygon_at_cap_line,
    filter_by_zone,
    load_registry,
    points_inside,
    resolve_zone,
    zone_family,
)


FIXTURE = Path(__file__).parent / "fixtures" / "geo" / "zones_registry_minimal.geojson"


def _square(lon0, lat0, lon1, lat1):
    return Polygon([(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)])


def test_audit_zone_coverage_ranks_covered_and_flags_relevant_gaps():
    registry = Registry(zones=(
        Zone(canonical="Zone A", source="test", polygon=_square(-70, 60, -60, 70), aliases=()),
        Zone(canonical="Zone B", source="test", polygon=_square(-90, 60, -80, 70), aliases=()),
        # Voisine (bbox recoupe l'emprise -85..-63 / 65..67) mais sans point -> lacune.
        Zone(canonical="Zone C gap", source="test", polygon=_square(-80, 64, -72, 68), aliases=()),
        # Loin de toute donnée -> pas une lacune pertinente.
        Zone(canonical="Zone D far", source="test", polygon=_square(10, 30, 20, 40), aliases=()),
    ))
    df = pd.DataFrame({
        "latitude": [65.0, 66.0, 67.0, 65.0],
        "longitude": [-65.0, -64.0, -63.0, -85.0],  # 3 dans A, 1 dans B
    })

    audit = audit_zone_coverage(df, registry)

    covered = {z["canonical"]: z["n_samples"] for z in audit["covered"]}
    assert covered == {"Zone A": 3, "Zone B": 1}
    assert audit["covered"][0]["canonical"] == "Zone A"  # trié desc

    gap_names = {z["canonical"] for z in audit["gaps"]}
    assert "Zone C gap" in gap_names       # voisine, vide -> lacune
    assert "Zone D far" not in gap_names   # lointaine -> pas une lacune
    assert audit["n_points"] == 4


def test_audit_zone_coverage_handles_empty_frame():
    registry = Registry(zones=(
        Zone(canonical="Zone A", source="test", polygon=_square(-70, 60, -60, 70), aliases=()),
    ))
    audit = audit_zone_coverage(pd.DataFrame({"latitude": [], "longitude": []}), registry)
    assert audit["covered"] == [] and audit["gaps"] == [] and audit["n_points"] == 0


def test_resolve_zone_returns_canonical_name_source_and_polygon_for_ungava():
    """Tracer 1 : un nom canonique connu doit résoudre vers la zone du registry,
    avec un polygone shapely réel utilisable directement."""
    registry = load_registry(FIXTURE)

    result = resolve_zone("Baie d'Ungava", registry=registry)

    assert result["canonical"] == "Baie d'Ungava"
    assert result["source"] == "IHO + NeoLab cut"
    assert result["polygon"].contains(Point(-67.0, 59.5))
    assert not result["polygon"].contains(Point(-67.0, 50.0))


def test_resolve_zone_accepts_alias_case_insensitively():
    registry = load_registry(FIXTURE)

    result = resolve_zone("ungava bay", registry=registry)

    assert result["canonical"] == "Baie d'Ungava"
    assert result["polygon"].contains(Point(-67.0, 59.5))


def test_points_inside_keeps_points_strictly_within_polygon():
    """Tracer 2 : filtre un DataFrame par appartenance au polygone.

    Convention NeoLab : colonnes 'latitude' / 'longitude' en WGS84 décimal,
    polygone shapely en (lon, lat). On garde l'index original — c'est ce qui
    permettra à filter_by_zone de retourner le sous-ensemble du df d'entrée
    sans casser les jointures aval.
    """
    polygon = Polygon([(-69.5, 58.0), (-65.0, 58.0), (-65.0, 60.6), (-69.5, 60.6)])
    df = pd.DataFrame({
        "sample_id":  ["in_ungava", "in_strait", "in_labrador"],
        "latitude":   [59.5,        62.0,        56.0],
        "longitude":  [-67.0,       -72.0,       -55.0],
    })

    kept = points_inside(df, polygon, lat_col="latitude", lon_col="longitude")

    assert list(kept["sample_id"]) == ["in_ungava"]
    assert list(kept.index) == [0]


def test_filter_by_zone_composes_resolve_and_points_inside():
    """Tracer 3 : la composition publique appelée par le tool LLM.

    On lui donne un nom de zone + un df avec ses colonnes lat/lon, et il
    rend le sous-df filtré. C'est ce qu'on branchera côté agent dans
    tools/geo_tools.py.filter_by_zone.
    """
    registry = load_registry(FIXTURE)
    df = pd.DataFrame({
        "sample_id":  ["ungava_pt", "labrador_pt"],
        "latitude":   [59.5,         56.0],
        "longitude":  [-67.0,       -55.0],
    })

    kept = filter_by_zone(
        df, "Baie d'Ungava",
        lat_col="latitude", lon_col="longitude",
        registry=registry,
    )

    assert list(kept["sample_id"]) == ["ungava_pt"]


def test_filter_by_zone_raises_on_unknown_zone():
    registry = load_registry(FIXTURE)
    df = pd.DataFrame({"latitude": [59.5], "longitude": [-67.0]})

    try:
        filter_by_zone(df, "Mer de Nulle Part",
                       lat_col="latitude", lon_col="longitude",
                       registry=registry)
    except KeyError as e:
        assert "Mer de Nulle Part" in str(e)
    else:
        raise AssertionError("filter_by_zone aurait dû lever KeyError")


def test_cut_polygon_at_cap_line_splits_square_in_two_halves():
    """Tracer cut : ligne horizontale (lat constante) coupe un carré 10x10
    en deux moitiés égales de 50."""
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    south, north = cut_polygon_at_cap_line(
        square, cap_west=(0.0, 5.0), cap_east=(10.0, 5.0),
    )

    assert south.area == pytest.approx(50.0, rel=0.01)
    assert north.area == pytest.approx(50.0, rel=0.01)
    assert south.contains(Point(5, 2.5))
    assert north.contains(Point(5, 7.5))


def test_cut_polygon_at_cap_line_handles_diagonal_cut():
    """Une vraie diagonale (Ungava-style) doit produire deux parts cohérentes
    qui se recollent sans trou ni recouvrement (à l'erreur shapely près)."""
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])

    south, north = cut_polygon_at_cap_line(
        square, cap_west=(0.0, 6.0), cap_east=(10.0, 4.0),
    )

    assert south.area + north.area == pytest.approx(100.0, rel=1e-6)
    assert south.contains(Point(5, 1.0))
    assert north.contains(Point(5, 9.0))


# --- assign_zones : découpage station -> zone la plus spécifique -------------


def _iho(name, poly):
    return Zone(canonical=name, source="IHO Marine Regions v3", polygon=poly, aliases=())


def test_zone_family_classifies_iho_composite_and_meow():
    iho = Zone(canonical="Baie X", source="IHO Marine Regions v3", polygon=_square(0, 0, 1, 1), aliases=())
    composite = Zone(canonical="Nunavik", source="NeoLab composite — union", polygon=_square(0, 0, 1, 1), aliases=())
    approx = Zone(canonical="Hawke Channel", source="NeoLab approximation — bbox", polygon=_square(0, 0, 1, 1), aliases=())
    meow = Zone(canonical="MEOW: Northern Labrador", source="MEOW v1 — Spalding et al. 2007", polygon=_square(0, 0, 1, 1), aliases=())

    assert zone_family(iho) == "iho"
    assert zone_family(composite) == "composite"
    assert zone_family(approx) == "composite"
    assert zone_family(meow) == "meow"


def test_assign_zones_labels_each_point_with_its_zone():
    registry = Registry(zones=(
        _iho("Baie A", _square(-70, 60, -60, 70)),
        _iho("Baie B", _square(-90, 60, -80, 70)),
    ))
    df = pd.DataFrame({
        "latitude":  [65.0,  66.0,  65.0],
        "longitude": [-65.0, -64.0, -85.0],  # A, A, B
    })

    labels = assign_zones(df, registry)

    assert list(labels) == ["Baie A", "Baie A", "Baie B"]
    assert labels.index.tolist() == df.index.tolist()  # index préservé pour jointure


def test_assign_zones_prefers_the_smallest_matching_polygon():
    """Zones qui se chevauchent : la plus spécifique (plus petite aire) gagne."""
    registry = Registry(zones=(
        _iho("Grande mer", _square(-90, 50, -50, 80)),      # englobe tout
        _iho("Petit détroit", _square(-70, 60, -65, 65)),   # inclus dans la grande
    ))
    df = pd.DataFrame({"latitude": [62.0, 78.0], "longitude": [-67.0, -55.0]})

    labels = assign_zones(df, registry)

    assert list(labels) == ["Petit détroit", "Grande mer"]


def test_assign_zones_uses_explicit_buckets_for_outside_and_missing():
    registry = Registry(zones=(_iho("Baie A", _square(-70, 60, -60, 70)),))
    df = pd.DataFrame({
        "latitude":  [65.0,   10.0,       None],
        "longitude": [-65.0,  100.0,      -65.0],  # dans A, hors zone, sans coord
    })

    labels = assign_zones(df, registry)

    assert labels.tolist() == ["Baie A", "Hors zone référencée", "Sans coordonnées"]


def test_assign_zones_family_filter_excludes_meow_and_composite_by_default():
    registry = Registry(zones=(
        Zone(canonical="MEOW: Ecoregion", source="MEOW v1", polygon=_square(-90, 50, -50, 80), aliases=()),
        _iho("Baie A", _square(-70, 60, -60, 70)),
    ))
    df = pd.DataFrame({"latitude": [65.0], "longitude": [-65.0]})

    # défaut family="iho" : ignore l'écorégion MEOW qui chevauche
    assert assign_zones(df, registry).tolist() == ["Baie A"]
    # family="meow" : bascule sur le découpage écologique
    assert assign_zones(df, registry, family="meow").tolist() == ["MEOW: Ecoregion"]


def test_assign_zones_empty_frame_returns_empty_series():
    registry = Registry(zones=(_iho("Baie A", _square(-70, 60, -60, 70)),))
    labels = assign_zones(pd.DataFrame({"latitude": [], "longitude": []}), registry)
    assert labels.tolist() == []


# Registry de prod — produit par python -m core.geo.build_registry à partir de
# data/geo/sources/World_Seas_IHO_v3/. Commit du GeoJSON dans le repo.
PROD_REGISTRY = Path(__file__).parent.parent / "data" / "geo" / "zones_registry.geojson"


@pytest.mark.skipif(not PROD_REGISTRY.exists(),
                    reason="zones_registry.geojson absent — lancer python -m core.geo.build_registry")
def test_prod_registry_classifies_ungava_station_correctly():
    """Une station type Amundsen au centre d'Ungava (~59°N, 67°W) doit tomber
    dans Baie d'Ungava et NI dans Détroit d'Hudson NI dans Baie d'Hudson."""
    registry = load_registry(PROD_REGISTRY)

    ungava  = resolve_zone("Baie d'Ungava",   registry=registry)["polygon"]
    strait  = resolve_zone("Détroit d'Hudson", registry=registry)["polygon"]
    hudson  = resolve_zone("Baie d'Hudson",   registry=registry)["polygon"]

    station = Point(-67.0, 59.0)  # (lon, lat) — centre d'Ungava Bay
    assert ungava.contains(station), "Station Ungava devrait être dans Baie d'Ungava"
    assert not strait.contains(station), "Station Ungava NE devrait PAS être dans Détroit d'Hudson"
    assert not hudson.contains(station), "Station Ungava NE devrait PAS être dans Baie d'Hudson"


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_classifies_james_bay_station_correctly():
    """Une station type au centre de James Bay (~53°N, 80.5°W) doit tomber dans
    Baie de James et pas dans Baie d'Hudson."""
    registry = load_registry(PROD_REGISTRY)

    james  = resolve_zone("Baie de James",  registry=registry)["polygon"]
    hudson = resolve_zone("Baie d'Hudson",  registry=registry)["polygon"]

    station = Point(-80.5, 53.0)
    assert james.contains(station)
    assert not hudson.contains(station)


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_includes_composite_and_synthetic_zones():
    """Couverture du registry de prod : 4 zones non-IHO doivent être présentes.

    Hawke Channel (NeoLab bbox), Nunavik (composite IHO), Arctique (composite
    circumpolaire) — ces 3 zones existent en plus des 12 IHO + cuts pour
    coller au périmètre métier NeoLab (cf. ancien tools/geo_tools.py).
    """
    registry = load_registry(PROD_REGISTRY)
    canonicals = {z.canonical for z in registry.zones}
    assert {"Hawke Channel", "Nunavik", "Arctique"}.issubset(canonicals)

    # Hawke : station test au centre de la bbox NeoLab
    hawke = resolve_zone("Hawke Channel", registry=registry)["polygon"]
    assert hawke.contains(Point(-55.0, 54.0))

    # Nunavik englobe une station d'Ungava ET une de Hudson Bay
    nunavik = resolve_zone("Nunavik", registry=registry)["polygon"]
    assert nunavik.contains(Point(-67.0, 59.0))   # Ungava
    assert nunavik.contains(Point(-85.0, 60.0))   # Hudson Bay

    # Arctique englobe Beaufort et le bassin polaire
    arctique = resolve_zone("Arctique", registry=registry)["polygon"]
    assert arctique.contains(Point(-140.0, 72.0))   # Beaufort
    assert arctique.contains(Point(0.0, 88.0))      # Pôle Nord, IHO Arctic Ocean


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_includes_meow_hudson_complex():
    """Étape 2 MEOW : 'MEOW: Hudson Complex' (Spalding 2007) doit être présent
    dans le registry de prod en complément de 'Baie d'Hudson' IHO."""
    registry = load_registry(PROD_REGISTRY)
    canonicals = {z.canonical for z in registry.zones}
    assert "MEOW: Hudson Complex" in canonicals
    assert "Baie d'Hudson" in canonicals  # coexistence IHO + MEOW


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_meow_hudson_complex_contains_central_hudson_bay():
    """MEOW Hudson Complex (composite Hudson+James+Strait+Ungava de Spalding) doit
    contenir une station typique du centre de la baie d'Hudson (~-85°W, 60°N)."""
    registry = load_registry(PROD_REGISTRY)
    hudson_meow = resolve_zone("MEOW: Hudson Complex", registry=registry)["polygon"]
    station = Point(-85.0, 60.0)
    assert hudson_meow.contains(station)


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_includes_meow_northern_labrador():
    """L'écorégion 'Northern Labrador' (MEOW Spalding 2007) doit être intégrée —
    nouveau découpage écologique non-couvert par IHO."""
    registry = load_registry(PROD_REGISTRY)
    canonicals = {z.canonical for z in registry.zones}
    assert "MEOW: Northern Labrador" in canonicals


@pytest.mark.skipif(not PROD_REGISTRY.exists(), reason="registry not built")
def test_prod_registry_classifies_hudson_strait_station_north_of_cut():
    """Une station dans le détroit proprement dit (~62.5°N, 72°W, bien au nord
    de la coupe Cap Hopes Advance) doit être dans Détroit d'Hudson."""
    registry = load_registry(PROD_REGISTRY)
    strait = resolve_zone("Détroit d'Hudson", registry=registry)["polygon"]
    ungava = resolve_zone("Baie d'Ungava",    registry=registry)["polygon"]

    station = Point(-72.0, 62.5)
    assert strait.contains(station)
    assert not ungava.contains(station)
