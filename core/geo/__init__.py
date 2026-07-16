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

import numpy as np
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


OUTSIDE_ZONE_LABEL = "Hors zone référencée"
MISSING_COORDS_LABEL = "Sans coordonnées"


def zone_family(zone: Zone) -> str:
    """Classe une zone du registry en famille de découpage.

    - ``"iho"``       : mer / baie / détroit physique (IHO Marine Regions v3,
      y compris les coupes NeoLab qui héritent d'un polygone IHO).
    - ``"meow"``      : écorégion marine (MEOW Spalding et al. 2007).
    - ``"composite"`` : union / approximation NeoLab (Nunavik, Arctique,
      Hawke Channel) — chevauche les zones fines, hors partition par défaut.

    Sert à choisir un jeu de zones *non chevauchantes* pour l'assignation :
    les familles IHO se tuilent proprement, MEOW forme un autre tuilage, mais
    mélanger IHO + composite + MEOW ferait matcher un même point dans plusieurs
    zones. ``assign_zones`` filtre donc par famille.
    """
    source = zone.source.lower()
    if zone.canonical.startswith("MEOW:") or source.startswith("meow"):
        return "meow"
    if source.startswith("iho"):
        return "iho"
    return "composite"


def assign_zones(
    df: pd.DataFrame,
    registry: Registry,
    *,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    family: str = "iho",
    outside_label: str = OUTSIDE_ZONE_LABEL,
    missing_label: str = MISSING_COORDS_LABEL,
) -> pd.Series:
    """Assigne à chaque ligne la zone (unique) dans laquelle son point tombe.

    Contrairement à :func:`audit_zone_coverage` — qui compte chaque zone
    indépendamment et laisse les zones composites se chevaucher — cette fonction
    produit une **partition** : exactement un label par ligne. Base du découpage
    automatique par mers / baies / détroits d'un fichier chargé.

    Politique :
    - ``family`` restreint le jeu de zones candidates (voir :func:`zone_family`).
      ``"auto"`` par défaut = cascade IHO physique PUIS MEOW pour les points hors
      des polygones IHO (couverture maximale : nom de mer/baie/détroit quand il
      existe, sinon écorégion). ``"iho"`` = seulement mers/baies/détroits ;
      ``"meow"`` = seulement écorégions ; ``"composite"`` = unions NeoLab ;
      ``"all"`` = toutes les zones confondues.
    - Chevauchement dans une famille : la zone du **plus petit polygone** (la plus
      spécifique) l'emporte, de façon déterministe.
    - Point hors de toute zone candidate → ``outside_label`` (jamais un
      identifiant de station : une station n'est pas une zone géographique).
    - Latitude ou longitude manquante → ``missing_label``.

    Retourne une ``pd.Series`` alignée sur ``df.index`` (index préservé pour les
    jointures aval). Vectorisé via ``shapely.contains_xy`` pour rester rapide sur
    les gros DataFrames EcoTaxa / Bio-ORACLE.
    """
    labels = pd.Series(outside_label, index=df.index, dtype=object)
    if len(df) == 0:
        return labels

    lons = pd.to_numeric(df[lon_col], errors="coerce").to_numpy(dtype=float)
    lats = pd.to_numeric(df[lat_col], errors="coerce").to_numpy(dtype=float)
    missing = np.isnan(lons) | np.isnan(lats)
    # contains_xy n'accepte pas les NaN : on remplace par un point loin de toute
    # zone (aucun match), puis on écrase avec missing_label à la fin.
    safe_lons = np.where(missing, 1e9, lons)
    safe_lats = np.where(missing, 1e9, lats)

    # Une passe = un tuilage cohérent. En 'auto', on enchaîne IHO puis MEOW :
    # MEOW ne comble QUE les lignes encore hors zone après IHO (les noms
    # physiques priment, les écorégions rattrapent la couverture côtière/hauturière).
    if family == "auto":
        passes = ["iho", "meow"]
    elif family == "all":
        passes = ["all"]
    else:
        passes = [family]

    for pass_family in passes:
        if pass_family == "all":
            candidates = list(registry.zones)
        else:
            candidates = [z for z in registry.zones if zone_family(z) == pass_family]
        # Seules les lignes encore non assignées (et non manquantes) sont
        # candidates pour cette passe.
        still_open = (labels == outside_label).to_numpy() & ~missing
        if not still_open.any():
            break
        # Trier par aire décroissante : les plus petits polygones (plus spécifiques)
        # sont appliqués en dernier et écrasent les plus grands sur les points communs.
        for zone in sorted(candidates, key=lambda z: z.polygon.area, reverse=True):
            mask = contains_xy(zone.polygon, safe_lons, safe_lats) & still_open
            if mask.any():
                labels.loc[df.index[mask]] = zone.canonical

    if missing.any():
        labels.loc[df.index[missing]] = missing_label
    return labels


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
