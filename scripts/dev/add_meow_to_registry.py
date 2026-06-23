#!/usr/bin/env python3
"""Append (idempotent) MEOW ecoregions to data/geo/zones_registry.geojson.

Source : data/geo/sources/MEOW/meow_north_40N.geojson (téléchargé par
scripts/dev/fetch_meow.py — Spalding et al. 2007, via ArcGIS Online).

Convention NeoLab :
- canonical = f"MEOW: {ECOREGION}" (préfixe = traçabilité source ; évite
  les collisions avec les noms IHO type "Baie d'Hudson").
- aliases   = [ECOREGION] (nom court anglais Spalding, sans préfixe).
- source    = "MEOW v1 — Spalding et al. 2007 (BioScience 57:573-583)
              via ArcGIS Online MEOW FeatureServer".

Les polygones MEOW sont simplifiés à tolérance 0.05° (~5 km à 60°N) pour
rester sous le seuil de poids GeoJSON du registry — précision largement
suffisante pour la classification station-niveau.

Usage:
    python scripts/dev/add_meow_to_registry.py
"""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import mapping, shape


MEOW_SOURCE = Path("data/geo/sources/MEOW/meow_north_40N.geojson")
REGISTRY_PATH = Path("data/geo/zones_registry.geojson")
SIMPLIFY_TOLERANCE_DEGREES = 0.05
COORD_PRECISION_DECIMALS = 4

SOURCE_LABEL = (
    "MEOW v1 — Spalding et al. 2007 (BioScience 57:573-583) "
    "via ArcGIS Online MEOW FeatureServer"
)


def _round_coords(obj):
    if isinstance(obj, float):
        return round(obj, COORD_PRECISION_DECIMALS)
    if isinstance(obj, list):
        return [_round_coords(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_round_coords(x) for x in obj)
    return obj


def _meow_feature_to_registry(feature: dict) -> dict:
    props = feature["properties"]
    ecoregion = props["ECOREGION"]
    geom = shape(feature["geometry"]).simplify(
        SIMPLIFY_TOLERANCE_DEGREES, preserve_topology=True,
    )
    geom_dict = mapping(geom)
    geom_dict["coordinates"] = _round_coords(geom_dict["coordinates"])
    return {
        "type": "Feature",
        "properties": {
            "canonical": f"MEOW: {ecoregion}",
            "source": SOURCE_LABEL,
            "aliases": [ecoregion],
            "meow_province": props.get("PROVINCE"),
            "meow_realm": props.get("REALM"),
            "meow_lat_zone": props.get("Lat_Zone"),
        },
        "geometry": geom_dict,
    }


def main() -> int:
    if not MEOW_SOURCE.exists():
        print(
            f"ERROR: {MEOW_SOURCE} introuvable. "
            f"Lance d'abord : python scripts/dev/fetch_meow.py"
        )
        return 1

    meow = json.loads(MEOW_SOURCE.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    existing = {f["properties"]["canonical"] for f in registry["features"]}

    new_features = []
    for feature in meow["features"]:
        candidate = _meow_feature_to_registry(feature)
        if candidate["properties"]["canonical"] not in existing:
            new_features.append(candidate)

    if not new_features:
        print(f"Registry already contains all {len(meow['features'])} MEOW ecoregions — no-op.")
        return 0

    registry["features"].extend(new_features)
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False), encoding="utf-8",
    )
    print(f"Appended {len(new_features)} MEOW ecoregions to {REGISTRY_PATH}:")
    for f in new_features[:10]:
        print(f"  - {f['properties']['canonical']}")
    if len(new_features) > 10:
        print(f"  ... ({len(new_features) - 10} more)")
    print(f"\nRegistry size: {REGISTRY_PATH.stat().st_size / 1024:.1f} KB "
          f"({len(registry['features'])} total features)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
