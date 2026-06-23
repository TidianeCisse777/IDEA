#!/usr/bin/env python3
"""Fetch MEOW (Marine Ecoregions of the World) via ArcGIS Online REST API.

MEOW est le standard peer-reviewed des écorégions marines :
- Spalding M.D. et al. 2007. Marine Ecoregions of the World: A Bioregionalization
  of Coastal and Shelf Areas. BioScience 57(7):573-583.
  https://doi.org/10.1641/B570707

Source canonique des polygones : ArcGIS Online "MEOW" (owner: kvangraafeiland_oceans)
  https://www.arcgis.com/home/item.html?id=74b6ac5c8fc24dcb8abaad6428a5dfa4
FeatureServer : https://services.arcgis.com/bDAhvQYMG4WL8O5o/arcgis/rest/services/MEOW/FeatureServer/0
Champs Spalding 2007 : ECOREGION, PROVINCE, REALM, Lat_Zone.

On récupère uniquement les écorégions dont l'enveloppe intersecte >40°N pour
limiter la taille du fichier et coller au périmètre NeoLab (Arctique +
NW Atlantique + Saint-Laurent + plate-forme labradorienne).

Output : data/geo/sources/MEOW/meow_north_40N.geojson

Usage:
    python scripts/dev/fetch_meow.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import urllib.request
import urllib.parse


FEATURE_SERVER = (
    "https://services.arcgis.com/bDAhvQYMG4WL8O5o/arcgis/rest/services/"
    "MEOW/FeatureServer/0/query"
)
BBOX_NORTH = {"xmin": -180, "ymin": 40, "xmax": 180, "ymax": 90,
              "spatialReference": {"wkid": 4326}}

OUTPUT_PATH = Path("data/geo/sources/MEOW/meow_north_40N.geojson")
MANUAL_FALLBACK_URL = (
    "https://www.arcgis.com/home/item.html?id=74b6ac5c8fc24dcb8abaad6428a5dfa4"
)


def fetch_meow_geojson(timeout_s: int = 60) -> dict:
    params = {
        "where": "1=1",
        "geometry": json.dumps(BBOX_NORTH),
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ECOREGION,PROVINCE,REALM,Lat_Zone,ECO_CODE,PROV_CODE,RLM_CODE",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    query = urllib.parse.urlencode(params)
    url = f"{FEATURE_SERVER}?{query}"
    print(f"Fetching MEOW from ArcGIS Online (filter: lat>40°N)...")
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        if resp.status != 200:
            raise RuntimeError(f"ArcGIS returned HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    try:
        gj = fetch_meow_geojson()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print(
            f"\nFallback: download the MEOW shapefile manually from "
            f"{MANUAL_FALLBACK_URL}\n"
            f"and place the GeoJSON or shapefile under {OUTPUT_PATH.parent}/",
            file=sys.stderr,
        )
        return 1

    features = gj.get("features", [])
    if not features:
        print("WFS returned 0 features — check the BBOX / typeName.", file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(features)} ecoregions → {OUTPUT_PATH}")
    print(f"({OUTPUT_PATH.stat().st_size / 1024:.1f} KB)")

    # Preview ecoregions retrieved (canonical Spalding 2007 field is ECOREGION).
    names = sorted({
        f.get("properties", {}).get("ECOREGION", "?")
        for f in features
    })
    print(f"\n{len(names)} unique ecoregions:")
    for n in names:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
