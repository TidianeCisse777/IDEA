"""Construit data/geo/zones_registry.geojson à partir du shapefile IHO v3.

Source primaire : Marine Regions / VLIZ — World Seas IHO v3 (S-23 baseline).
Téléchargement habituel : https://www.marineregions.org/downloads.php

Le shapefile contient ~101 mers/baies/détroits au niveau IHO. On en extrait
les zones pertinentes pour NeoLab (Nord QC + Arctique + Saint-Laurent), et on
sépare manuellement :

- Hudson Bay → Baie d'Hudson (nord) + Baie de James (sud), coupe Cap Henrietta
  Maria → Pointe Louis-XIV (Canadian Sailing Directions / Canadian Encyclopedia).
- Hudson Strait → Détroit d'Hudson (nord) + Baie d'Ungava (sud), coupe Cap
  Hopes Advance → Cape Chidley (Canadian Sailing Directions ARC 401).

Les polygones sont simplifiés (tolérance 0.01° ≈ 1 km) avant écriture pour
garder la taille du GeoJSON gérable (< 1 MB cible) sans perdre de précision
pour la classification d'échantillons (échelle des points >> 1 km).

Usage:
    python -m core.geo.build_registry \
        --source ~/Downloads/World_Seas_IHO_v3 \
        --output data/geo/zones_registry.geojson
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import shapefile
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.geo import cut_polygon_at_cap_line


# Caps coords from Canadian Sailing Directions ARC 401 + Quebec Toponymy + DFO.
# Convention : (lon, lat) in WGS84 decimal degrees.
CAP_HENRIETTA_MARIA = (-82.30, 55.13)   # rive ouest sud d'Hudson Bay
POINTE_LOUIS_XIV    = (-79.75, 54.65)   # rive est, aka Cape Jones
CAP_HOPES_ADVANCE   = (-69.55, 61.08)   # rive NW entrée Ungava (Nuvuk)
CAPE_CHIDLEY        = (-64.50, 60.40)   # rive SE entrée Ungava (Killiniq)

SIMPLIFY_TOLERANCE_DEGREES = 0.05  # ~5 km à 60°N — précis pour la classification de stations en mer
COORD_PRECISION_DECIMALS = 4       # ~10 m à 60°N — largement assez en sortie

DEFAULT_SOURCE_DIR = Path("data/geo/sources/World_Seas_IHO_v3")
DEFAULT_OUTPUT_PATH = Path("data/geo/zones_registry.geojson")


@dataclass(frozen=True)
class ZoneSpec:
    canonical: str
    source: str
    iho_name: str | None = None
    aliases: tuple[str, ...] = ()


PASSTHROUGH_ZONES: tuple[ZoneSpec, ...] = (
    ZoneSpec("Baie de Baffin",         "IHO Marine Regions v3", "Baffin Bay",            ("Baffin Bay",)),
    ZoneSpec("Détroit de Davis",       "IHO Marine Regions v3", "Davis Strait",          ("Davis Strait",)),
    ZoneSpec("Mer du Labrador",        "IHO Marine Regions v3", "Labrador Sea",          ("Labrador Sea",)),
    ZoneSpec("Golfe du Saint-Laurent", "IHO Marine Regions v3", "Gulf of St. Lawrence",  ("Gulf of St. Lawrence", "GSL")),
    ZoneSpec("Mer de Beaufort",        "IHO Marine Regions v3", "Beaufort Sea",          ("Beaufort Sea",)),
    ZoneSpec("Mer des Tchouktches",    "IHO Marine Regions v3", "Chukchi Sea",           ("Chukchi Sea",)),
    ZoneSpec("Mer du Groenland",       "IHO Marine Regions v3", "Greenland Sea",         ("Greenland Sea",)),
    ZoneSpec("Mer de Lincoln",         "IHO Marine Regions v3", "Lincoln Sea",           ("Lincoln Sea",)),
)


# Hawke Channel : pas d'équivalent IHO. Approximation NeoLab par bbox carrée,
# à raffiner ultérieurement en convex hull des stations HC-* + buffer 25 km.
HAWKE_CHANNEL_BBOX = (-57.0, 52.0, -53.0, 56.0)  # (lon_min, lat_min, lon_max, lat_max)


def _read_iho_polygons(source_dir: Path) -> dict[str, BaseGeometry]:
    """Lit World_Seas_IHO_v3.shp et retourne {NAME: shapely geometry}."""
    shp_path = source_dir / "World_Seas_IHO_v3.shp"
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile introuvable : {shp_path}")
    sf = shapefile.Reader(str(shp_path))
    polygons: dict[str, BaseGeometry] = {}
    for sr in sf.iterShapeRecords():
        name = str(sr.record["NAME"])
        polygons[name] = shape(sr.shape.__geo_interface__)
    return polygons


def _simplify(geom: BaseGeometry) -> BaseGeometry:
    """Simplification topologique pour réduire la taille du GeoJSON."""
    return geom.simplify(SIMPLIFY_TOLERANCE_DEGREES, preserve_topology=True)


def build_registry_features(iho_polygons: dict[str, BaseGeometry]) -> list[dict]:
    """Construit la liste de features GeoJSON pour le registry NeoLab."""
    features: list[dict] = []

    hudson_bay_raw = iho_polygons["Hudson Bay"]
    james, hudson_bay_north = cut_polygon_at_cap_line(
        hudson_bay_raw,
        cap_west=CAP_HENRIETTA_MARIA,
        cap_east=POINTE_LOUIS_XIV,
    )
    features.append(_to_feature(
        canonical="Baie de James",
        source="IHO Marine Regions v3 + cut Cap Henrietta Maria → Pointe Louis-XIV (Canadian Sailing Directions)",
        geom=_simplify(james),
        aliases=("James Bay",),
    ))
    features.append(_to_feature(
        canonical="Baie d'Hudson",
        source="IHO Marine Regions v3 + cut Cap Henrietta Maria → Pointe Louis-XIV (sépare Baie de James)",
        geom=_simplify(hudson_bay_north),
        aliases=("Hudson Bay",),
    ))

    hudson_strait_raw = iho_polygons["Hudson Strait"]
    ungava, hudson_strait_north = cut_polygon_at_cap_line(
        hudson_strait_raw,
        cap_west=CAP_HOPES_ADVANCE,
        cap_east=CAPE_CHIDLEY,
    )
    features.append(_to_feature(
        canonical="Baie d'Ungava",
        source="IHO Marine Regions v3 + cut Cap Hopes Advance → Cape Chidley (Canadian Sailing Directions ARC 401)",
        geom=_simplify(ungava),
        aliases=("Ungava Bay", "Ungava"),
    ))
    features.append(_to_feature(
        canonical="Détroit d'Hudson",
        source="IHO Marine Regions v3 + cut Cap Hopes Advance → Cape Chidley (sépare Baie d'Ungava)",
        geom=_simplify(hudson_strait_north),
        aliases=("Hudson Strait",),
    ))

    for spec in PASSTHROUGH_ZONES:
        if spec.iho_name not in iho_polygons:
            raise KeyError(f"Zone IHO attendue absente du shapefile : {spec.iho_name!r}")
        features.append(_to_feature(
            canonical=spec.canonical,
            source=spec.source,
            geom=_simplify(iho_polygons[spec.iho_name]),
            aliases=spec.aliases,
        ))

    # Hawke Channel : approximation bbox (TODO : remplacer par convex hull
    # des stations NeoLab HC-* + buffer 25 km en UTM 21N).
    hawke = box(*HAWKE_CHANNEL_BBOX)
    features.append(_to_feature(
        canonical="Hawke Channel",
        source="NeoLab approximation — bbox carrée 52-56°N × 53-57°W (TODO: derive from HC-* stations + 25 km buffer)",
        geom=hawke,
        aliases=("Hawke", "HC", "Chenal Hawke"),
    ))

    # Nunavik : composite des eaux bordant le territoire administratif du Nunavik.
    nunavik = unary_union([hudson_bay_north, hudson_strait_north, ungava, james])
    features.append(_to_feature(
        canonical="Nunavik",
        source="NeoLab composite — union Baie d'Hudson + Détroit d'Hudson + Baie d'Ungava + Baie de James",
        geom=_simplify(nunavik),
        aliases=("Nord québécois", "Nord quebecois", "Québec nordique", "Quebec nordique"),
    ))

    # Arctique / Amundsen : composite circumpolaire.
    if "Arctic Ocean" not in iho_polygons:
        raise KeyError("Polygone IHO Arctic Ocean attendu manquant")
    arctique = unary_union([
        iho_polygons["Arctic Ocean"],
        iho_polygons["Beaufort Sea"],
        iho_polygons["Chukchi Sea"],
        iho_polygons["Lincoln Sea"],
        iho_polygons["Greenland Sea"],
    ])
    features.append(_to_feature(
        canonical="Arctique",
        source="NeoLab composite circumpolaire — IHO Arctic Ocean + Beaufort + Tchouktches + Lincoln + Groenland",
        geom=_simplify(arctique),
        aliases=("Arctic", "Amundsen", "Polaire", "Arctique / Amundsen"),
    ))

    return features


def _round_coords(obj):
    """Réduit la précision des coordonnées d'un objet GeoJSON-like (récursif)."""
    if isinstance(obj, float):
        return round(obj, COORD_PRECISION_DECIMALS)
    if isinstance(obj, list):
        return [_round_coords(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_round_coords(x) for x in obj)
    return obj


def _to_feature(*, canonical: str, source: str, geom: BaseGeometry, aliases: tuple[str, ...]) -> dict:
    if isinstance(geom, Polygon):
        geom_for_json: BaseGeometry = geom
    elif isinstance(geom, MultiPolygon):
        geom_for_json = geom
    else:
        # GeometryCollection (peut sortir des opérations d'intersection si elle
        # touche la frontière) → on filtre pour ne garder que les Polygons.
        polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not polys:
            raise ValueError(f"Pas de Polygon utilisable pour {canonical!r}")
        geom_for_json = MultiPolygon(
            [p for g in polys for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
        )
    geom_dict = mapping(geom_for_json)
    geom_dict["coordinates"] = _round_coords(geom_dict["coordinates"])
    return {
        "type": "Feature",
        "properties": {
            "canonical": canonical,
            "source": source,
            "aliases": list(aliases),
        },
        "geometry": geom_dict,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_DIR,
                        help=f"Dossier contenant World_Seas_IHO_v3.shp (défaut : {DEFAULT_SOURCE_DIR})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help=f"Chemin du GeoJSON de sortie (défaut : {DEFAULT_OUTPUT_PATH})")
    args = parser.parse_args()

    iho_polygons = _read_iho_polygons(args.source.expanduser())
    features = build_registry_features(iho_polygons)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": "neolab_zones_registry",
        "features": features,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(features)} zones → {args.output} "
          f"({args.output.stat().st_size / 1024:.1f} KB)")
    for f in features:
        print(f"  - {f['properties']['canonical']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
