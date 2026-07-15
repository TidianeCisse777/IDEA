"""Geographic zone registry — polygones précis pour le filtrage des données NeoLab.

Source des polygones :
- IHO Marine Regions v3 (Marine Regions / VLIZ) pour les mers et baies majeures du
  Nord du Québec et de l'Arctique (Hudson Bay, Hudson Strait, Baffin Bay, etc.).
- IHO + ligne de coupe NeoLab pour Baie de James (cut Cap Henrietta Maria →
  Pointe Louis-XIV) et Baie d'Ungava (cut Cap Hopes Advance → Cape Chidley).
- Hawke Channel : convex hull des stations NeoLab HC-* + buffer 25 km (UTM 21N).
- Nunavik : lookup composite (union de plusieurs polygones IHO).

Le registry est sérialisé en GeoJSON sous data/geo/zones_registry.geojson et
chargé en mémoire par load_registry().
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd
from shapely import contains_xy
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class Zone:
    canonical: str
    source: str
    polygon: BaseGeometry
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Registry:
    zones: tuple[Zone, ...]


def load_registry(path: Path | str) -> Registry:
    """Charge un registry de zones depuis un GeoJSON FeatureCollection.

    Chaque Feature doit fournir au minimum :
    - properties.canonical : nom canonique de la zone
    - properties.source    : source du polygone (IHO, IHO + NeoLab cut, etc.)
    - geometry             : Polygon ou MultiPolygon en WGS84 (EPSG:4326)
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    zones: list[Zone] = []
    for feature in raw["features"]:
        props: Mapping = feature["properties"]
        zones.append(Zone(
            canonical=props["canonical"],
            source=props["source"],
            polygon=shape(feature["geometry"]),
            aliases=tuple(props.get("aliases", [])),
        ))
    return Registry(zones=tuple(zones))


def resolve_zone(name: str, *, registry: Registry) -> dict:
    """Résout un nom de zone vers son entrée canonique du registry.

    Match insensible à la casse sur le nom canonique ou ses aliases.
    """
    needle = name.strip().lower()
    for zone in registry.zones:
        names = (zone.canonical, *zone.aliases)
        if any(candidate.strip().lower() == needle for candidate in names):
            return {
                "canonical": zone.canonical,
                "source": zone.source,
                "polygon": zone.polygon,
            }
    raise KeyError(f"Zone inconnue : {name!r}")


def points_inside(
    df: pd.DataFrame,
    polygon: BaseGeometry,
    *,
    lat_col: str,
    lon_col: str,
) -> pd.DataFrame:
    """Retourne le sous-ensemble de df dont (lon, lat) est dans le polygone.

    Préserve l'index d'origine pour permettre les jointures aval. Utilise
    shapely.vectorized pour rester rapide sur les gros DataFrames EcoTaxa /
    Bio-ORACLE (~1e6 lignes attendues).
    """
    mask = contains_xy(polygon, df[lon_col].to_numpy(), df[lat_col].to_numpy())
    return df.loc[mask]


def audit_zone_coverage(
    df: pd.DataFrame,
    registry: Registry,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> dict:
    """Audit spatial : combien de points tombent dans chaque zone nommée.

    Retourne :
        - ``covered`` : zones contenant au moins un point, triées par compte
          décroissant (canonical, source, n_samples).
        - ``gaps`` : zones à zéro point dont la bbox recoupe l'emprise des points
          — c.-à-d. des trous spatiaux *pertinents* (une zone voisine des données
          mais non couverte), pas les zones lointaines trivialement vides.
        - ``n_unmatched`` : points hors de toute zone du registry.
        - ``n_points`` : total des points audités.

    Les zones composites (Arctique, Nunavik) chevauchent des zones plus fines :
    un même point peut être compté dans plusieurs zones. C'est voulu pour un
    audit de couverture — chaque zone est évaluée indépendamment.
    """
    n_points = len(df)
    if n_points == 0:
        return {"covered": [], "gaps": [], "n_unmatched": 0, "n_points": 0}

    lons = df[lon_col].to_numpy()
    lats = df[lat_col].to_numpy()
    env_minx, env_maxx = float(lons.min()), float(lons.max())
    env_miny, env_maxy = float(lats.min()), float(lats.max())

    covered: list[dict] = []
    gaps: list[dict] = []
    matched_any = None
    for zone in registry.zones:
        mask = contains_xy(zone.polygon, lons, lats)
        matched_any = mask if matched_any is None else (matched_any | mask)
        n = int(mask.sum())
        if n > 0:
            covered.append(
                {"canonical": zone.canonical, "source": zone.source, "n_samples": n}
            )
            continue
        zminx, zminy, zmaxx, zmaxy = zone.polygon.bounds
        overlaps = not (
            zmaxx < env_minx or zminx > env_maxx
            or zmaxy < env_miny or zminy > env_maxy
        )
        if overlaps:
            gaps.append({"canonical": zone.canonical, "source": zone.source})

    covered.sort(key=lambda z: (-z["n_samples"], z["canonical"]))
    gaps.sort(key=lambda z: z["canonical"])
    return {
        "covered": covered,
        "gaps": gaps,
        "n_unmatched": int((~matched_any).sum()) if matched_any is not None else n_points,
        "n_points": n_points,
    }


def cut_polygon_at_cap_line(
    polygon: BaseGeometry,
    *,
    cap_west: tuple[float, float],
    cap_east: tuple[float, float],
) -> tuple[BaseGeometry, BaseGeometry]:
    """Coupe un polygone le long de la droite passant par deux caps (lon, lat).

    Retourne (south_part, north_part) où 'south' = sous la droite cap_west→cap_east.
    La droite est extrapolée linéairement bien au-delà de la bbox du polygone
    pour garantir une coupe nette ; tout ce qui sort du polygone source est
    automatiquement éliminé par l'intersection / différence shapely.

    Convention NeoLab : les caps utilisés pour découper Hudson Bay et Hudson
    Strait sont issus des Canadian Sailing Directions (ARC 401) — voir le
    script build_registry.py pour les valeurs.
    """
    lon_w, lat_w = cap_west
    lon_e, lat_e = cap_east
    if lon_e == lon_w:
        raise ValueError("cap_west et cap_east doivent avoir des longitudes différentes")
    slope = (lat_e - lat_w) / (lon_e - lon_w)

    minx, miny, maxx, _ = polygon.bounds
    margin = 5.0
    lon_far_w = minx - margin
    lon_far_e = maxx + margin
    lat_at_far_w = lat_w + slope * (lon_far_w - lon_w)
    lat_at_far_e = lat_w + slope * (lon_far_e - lon_w)
    lat_floor = miny - margin

    south_half_plane = Polygon([
        (lon_far_w, lat_at_far_w),
        (lon_far_e, lat_at_far_e),
        (lon_far_e, lat_floor),
        (lon_far_w, lat_floor),
    ])

    south_part = polygon.intersection(south_half_plane)
    north_part = polygon.difference(south_half_plane)
    return south_part, north_part


def filter_by_zone(
    df: pd.DataFrame,
    zone_name: str,
    *,
    lat_col: str,
    lon_col: str,
    registry: Registry,
) -> pd.DataFrame:
    """Compose resolve_zone + points_inside : c'est l'API publique destinée
    au tool LLM tools/geo_tools.py.filter_by_zone. Lève KeyError si la zone
    est inconnue du registry — le tool LLM en haut interceptera pour
    transformer ça en message utilisateur lisible.
    """
    zone = resolve_zone(zone_name, registry=registry)
    return points_inside(df, zone["polygon"], lat_col=lat_col, lon_col=lon_col)
