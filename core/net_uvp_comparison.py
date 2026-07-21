"""Contrat déterministe : correspondance et comparaison filet ↔ UVP.

Pont entre l'abondance filet (NeoLabs, `core.neolabs_abundance`) et l'abondance
UVP (EcoTaxa/EcoPart, `core.copepod_sample_depth` → densité copépode). Trois
étapes, chacune imposée pour éviter qu'un `run_pandas` libre invente une
jointure ou compare des unités incompatibles :

1. `match_net_to_uvp` — apparie chaque déploiement filet au sample UVP le plus
   proche dans l'espace (haversine), avec l'écart temporel calculé et exposé.
   Le rapprochement est SPATIAL (stations de monitoring revisitées) : l'écart de
   temps n'est jamais masqué, il devient une colonne + un statut.
2. `to_ind_per_m3` — aligne une densité `ind./L` (UVP) sur `ind./m³` (filet)
   avant toute comparaison, unité rendue explicite dans le nom de colonne.
3. `compare_paired_density` — pose delta, ratio et log2-ratio sur une table déjà
   appariée à un grain commun (station ou sample), sans réordonner ni inventer.

Ce module ne lit aucune source ni session : il opère sur des DataFrames déjà
résolus par les tools. Il lève `ValueError` sur entrée incomplète plutôt que de
produire une comparaison fausse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


NET_UVP_MATCH_METHOD_VERSION = "net-uvp-station-date-match-v2"


def _normalize_station(name: str | None) -> str:
    """Lowercase + strip dashes/underscores for fuzzy station name matching.

    TCA-QF3 → tcaqf3, am_leg2_tcaqf3 → tcaqf3 (after cruise prefix removal).
    """
    if not name:
        return ""
    import re
    # Strip cruise prefix (am_leg2_, gn2015_, etc.)
    s = re.sub(r"^(?:[a-z]{1,6}\d{0,4}_(?:leg\d+_)?)", "", str(name), flags=re.IGNORECASE)
    return re.sub(r"[-_\s]", "", s).lower()
NET_UVP_COMPARE_METHOD_VERSION = "net-uvp-density-compare-v1"

_EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: np.ndarray | float,
    lon1: np.ndarray | float,
    lat2: np.ndarray | float,
    lon2: np.ndarray | float,
) -> np.ndarray:
    """Distance grand-cercle en km entre deux points (ou un point et un vecteur)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return _EARTH_RADIUS_KM * 2 * np.arcsin(np.sqrt(a))


def match_net_to_uvp(
    net_df: pd.DataFrame,
    uvp_df: pd.DataFrame,
    *,
    max_km: float = 50.0,
    max_days: float | None = 2.0,
    net_id_col: str = "SAMPLE_ID",
    net_station_col: str = "STATION_NAME",
    net_lat_col: str = "latitude",
    net_lon_col: str = "longitude",
    net_time_col: str | None = "deployment_datetime_start",
    uvp_id_col: str = "sample_id",
    uvp_project_col: str = "project_id",
    uvp_instrument_col: str = "instrument",
    uvp_lat_col: str = "lat_avg",
    uvp_lon_col: str = "lon_avg",
    uvp_time_col: str | None = "date_min",
    uvp_profile_col: str | None = "profile_id",
) -> pd.DataFrame:
    """Apparie chaque déploiement filet à son sample UVP le plus proche (< max_km).

    Pour chaque déploiement filet unique, on collecte TOUS les samples UVP dont le
    nom de station normalisé correspond, puis on sélectionne celui dont l'écart
    temporel est minimal (best temporal match parmi les candidats de même station).
    L'écart temporel (`time_gap_days`) est toujours calculé et renvoyé — jamais
    masqué. Si `max_days` est fourni, `match_status` vaut `matched` seulement
    quand l'écart temporel est aussi respecté, sinon `spatial_only` (même station,
    campagnes d'années différentes — cas typique filet historique vs UVP récent).

    `uvp_profile_col` : colonne du cache contenant le nom de profil string (ex.
    `gn2015_l2`). Si présente, propagée dans la sortie comme `uvp_profile_str` —
    évite au skill de reconstruire ce bridge depuis `df_ecotaxa_ecopart`.

    Renvoie une ligne par déploiement filet ayant un voisin UVP < `max_km` :
    `net_sample_id`, `station`, `latitude`, `longitude`, `net_datetime`,
    `uvp_sample_id`, `uvp_profile_str`, `uvp_project_id`, `uvp_instrument`,
    `distance_km`, `time_gap_days`, `match_status`, `method_version`. Lève
    `ValueError` sur colonnes manquantes ou coordonnées entièrement absentes.
    """
    # Seul net_id_col est strictement obligatoire — lat/lon sont optionnels
    # (distance_km sera None si absent, mais le matching station+date reste valide).
    missing_net = sorted({net_id_col}.difference(net_df.columns))
    if missing_net:
        raise ValueError(
            "Appariement filet↔UVP refusé : colonne(s) filet absente(s) : "
            + ", ".join(f"`{c}`" for c in missing_net)
            + "."
        )
    missing_uvp = sorted({uvp_id_col}.difference(uvp_df.columns))
    if missing_uvp:
        raise ValueError(
            "Appariement filet↔UVP refusé : colonne(s) UVP absente(s) : "
            + ", ".join(f"`{c}`" for c in missing_uvp)
            + "."
        )

    net = net_df.drop_duplicates(subset=[net_id_col]).copy()

    # Lat/lon filet : optionnels — uniquement pour distance_km en sortie.
    _has_net_coords = net_lat_col in net.columns and net_lon_col in net.columns
    if _has_net_coords:
        net_lat = pd.to_numeric(net[net_lat_col], errors="coerce")
        net_lon = pd.to_numeric(net[net_lon_col], errors="coerce")
    else:
        net_lat = pd.Series(pd.NA, index=net.index, dtype=float)
        net_lon = pd.Series(pd.NA, index=net.index, dtype=float)

    uvp = uvp_df.copy().reset_index(drop=True)

    # Lat/lon UVP : optionnels — utilisés pour distance_km quand les deux côtés ont des coords.
    _has_uvp_coords = uvp_lat_col in uvp.columns and uvp_lon_col in uvp.columns
    if _has_uvp_coords:
        u_lat = pd.to_numeric(uvp[uvp_lat_col], errors="coerce").to_numpy()
        u_lon = pd.to_numeric(uvp[uvp_lon_col], errors="coerce").to_numpy()
    else:
        u_lat = np.full(len(uvp), np.nan)
        u_lon = np.full(len(uvp), np.nan)

    net_time = None
    if net_time_col and net_time_col in net.columns:
        net_time = pd.to_datetime(net[net_time_col], errors="coerce", utc=True)
    uvp_time = None
    if uvp_time_col and uvp_time_col in uvp.columns:
        uvp_time = pd.to_datetime(uvp[uvp_time_col], errors="coerce", utc=True)

    # Pre-compute normalized station names for UVP (from station_id column when available).
    uvp_station_col_name = "station_id" if "station_id" in uvp.columns else None
    uvp_norm_stations: list[str] = []
    if uvp_station_col_name:
        uvp_norm_stations = [_normalize_station(v) for v in uvp[uvp_station_col_name]]

    has_profile = uvp_profile_col and uvp_profile_col in uvp.columns

    rows: list[dict] = []
    for pos, (idx, net_row) in enumerate(net.iterrows()):
        net_station_norm = _normalize_station(str(net_row.get(net_station_col) or net_row[net_id_col]))

        # Collect ALL UVP candidates matching this station name, then pick best
        # temporal match. Avoids silently returning the first (wrong-date) sample
        # when a station is visited multiple times by different campaigns.
        candidate_indices: list[int] = []
        if uvp_norm_stations and net_station_norm:
            for i, s in enumerate(uvp_norm_stations):
                if s and s == net_station_norm:
                    candidate_indices.append(i)

        if not candidate_indices:
            continue

        nt = net_time.iloc[pos] if net_time is not None else None

        def _time_gap(i: int) -> float:
            if uvp_time is not None and nt is not None and pd.notna(nt):
                ut = uvp_time.iloc[i]
                if pd.notna(ut):
                    return abs((ut - nt).total_seconds()) / 86400.0
            return float("inf")

        # Best = smallest time gap among candidates (inf when time unavailable).
        nearest = min(candidate_indices, key=_time_gap)
        time_gap_val = _time_gap(nearest)
        time_gap: float | None = None if time_gap_val == float("inf") else time_gap_val

        # distance_km : calculée si les deux côtés ont des coordonnées, None sinon.
        nl = net_lat.iloc[pos]
        nlo = net_lon.iloc[pos]
        if (
            pd.notna(nl) and pd.notna(nlo)
            and not np.isnan(u_lat[nearest]) and not np.isnan(u_lon[nearest])
        ):
            distance: float | None = round(float(haversine_km(nl, nlo, u_lat, u_lon)[nearest]), 3)
        else:
            distance = None

        if max_days is not None and (time_gap is None or time_gap > max_days):
            status = "spatial_only"
        else:
            status = "matched"

        u = uvp.iloc[nearest]
        rows.append(
            {
                "net_sample_id": net_row[net_id_col],
                "station": net_row.get(net_station_col) or net_row[net_id_col],
                "latitude": float(nl) if pd.notna(nl) else None,
                "longitude": float(nlo) if pd.notna(nlo) else None,
                "net_datetime": nt,
                "uvp_sample_id": u[uvp_id_col],
                "uvp_profile_str": u[uvp_profile_col] if has_profile else None,
                "uvp_project_id": u.get(uvp_project_col),
                "uvp_instrument": u.get(uvp_instrument_col),
                "distance_km": distance,
                "time_gap_days": round(time_gap, 1) if time_gap is not None else None,
                "match_status": status,
                "match_method": "station_name",
                "method_version": NET_UVP_MATCH_METHOD_VERSION,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "net_sample_id",
            "station",
            "latitude",
            "longitude",
            "net_datetime",
            "uvp_sample_id",
            "uvp_profile_str",
            "uvp_project_id",
            "uvp_instrument",
            "distance_km",
            "time_gap_days",
            "match_status",
            "match_method",
            "method_version",
        ],
    )


def to_ind_per_m3(density: pd.Series, *, from_unit: str) -> pd.Series:
    """Convertit une densité vers `ind./m³` (base filet) avant comparaison.

    `from_unit` ∈ {`ind_per_m3`, `ind_per_L`}. 1 m³ = 1000 L, donc `ind./L` ×
    1000 → `ind./m³`. Lève `ValueError` sur unité inconnue plutôt que de comparer
    des grandeurs incompatibles.
    """
    values = pd.to_numeric(density, errors="coerce")
    if from_unit == "ind_per_m3":
        return values
    if from_unit == "ind_per_L":
        return values * 1000.0
    raise ValueError(
        f"Unité `{from_unit}` inconnue : attendu `ind_per_m3` ou `ind_per_L`."
    )


def compare_paired_density(
    paired: pd.DataFrame,
    *,
    net_col: str,
    uvp_col: str,
) -> pd.DataFrame:
    """Pose delta / ratio / log2-ratio sur une table déjà appariée (même grain).

    `net_col` et `uvp_col` doivent être exprimés dans la MÊME unité (`ind./m³` —
    passer d'abord la densité UVP dans `to_ind_per_m3`). Ajoute :
    `abundance_delta_ind_m3` (uvp − filet), `abundance_abs_delta_ind_m3`,
    `abundance_ratio` (uvp / filet), `abundance_log2_ratio`,
    `method_version`. Ne réordonne pas les lignes. Lève `ValueError` si une
    colonne est absente.
    """
    missing = [c for c in (net_col, uvp_col) if c not in paired.columns]
    if missing:
        raise ValueError(
            "Comparaison d'abondance refusée : colonne(s) absente(s) : "
            + ", ".join(f"`{c}`" for c in missing)
            + "."
        )
    out = paired.copy()
    net = pd.to_numeric(out[net_col], errors="coerce")
    uvp = pd.to_numeric(out[uvp_col], errors="coerce")
    out["abundance_delta_ind_m3"] = uvp - net
    out["abundance_abs_delta_ind_m3"] = (uvp - net).abs()
    ratio = uvp / net.where(net != 0)
    out["abundance_ratio"] = ratio
    out["abundance_log2_ratio"] = np.log2(ratio.where(ratio > 0))
    out["method_version"] = NET_UVP_COMPARE_METHOD_VERSION
    return out
