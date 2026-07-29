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


NET_UVP_MATCH_METHOD_VERSION = "net-uvp-deployment-spatiotemporal-match-v3"


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
_MATCH_COLUMNS = [
    "net_sample_id", "net_deployment_id", "net_cast", "station", "latitude",
    "longitude", "net_datetime", "uvp_sample_id", "uvp_profile_str",
    "uvp_project_id", "uvp_instrument", "distance_km", "time_gap_days",
    "station_name_match", "candidate_count", "match_status", "join_eligible",
    "match_method", "method_version",
]


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
    net_deployment_col: str | None = None,
    net_cast_col: str | None = None,
    uvp_id_col: str = "sample_id",
    uvp_project_col: str = "project_id",
    uvp_instrument_col: str = "instrument",
    uvp_lat_col: str = "lat_avg",
    uvp_lon_col: str = "lon_avg",
    uvp_time_col: str | None = "date_min",
    uvp_profile_col: str | None = "profile_id",
) -> pd.DataFrame:
    """Match each deployment to its closest spatially plausible UVP sample.

    Station labels are evidence only, never a prerequisite: the cache and a net
    file can use different station naming conventions.  ``matched`` requires
    both spatial and temporal agreement; ``spatial_only`` is retained for audit
    when dates are missing or outside the requested tolerance. Only ``matched``
    rows are eligible for an abundance join. One chosen UVP sample is expanded
    to all net samples in the same deployment.
    """
    missing_net = sorted({net_id_col, net_lat_col, net_lon_col}.difference(net_df.columns))
    if missing_net:
        raise ValueError(
            "Appariement filet↔UVP refusé : colonne(s) filet absente(s) : "
            + ", ".join(f"`{c}`" for c in missing_net)
            + ". Des coordonnées sont nécessaires pour un rapprochement spatial fiable."
        )
    missing_uvp = sorted({uvp_id_col, uvp_lat_col, uvp_lon_col}.difference(uvp_df.columns))
    if missing_uvp:
        raise ValueError(
            "Appariement filet↔UVP refusé : colonne(s) UVP absente(s) : "
            + ", ".join(f"`{c}`" for c in missing_uvp)
            + "."
        )

    net = net_df.drop_duplicates(subset=[net_id_col]).copy()
    net["_match_lat"] = pd.to_numeric(net[net_lat_col], errors="coerce")
    net["_match_lon"] = pd.to_numeric(net[net_lon_col], errors="coerce")
    net["_match_time"] = (
        pd.to_datetime(net[net_time_col], errors="coerce", utc=True)
        if net_time_col and net_time_col in net.columns
        else pd.NaT
    )
    if net_deployment_col and net_deployment_col in net.columns:
        raw_deployment = net[net_deployment_col].astype("string").str.strip()
        net["_match_deployment"] = raw_deployment.mask(
            raw_deployment.isna() | raw_deployment.eq(""),
            "sample:" + net[net_id_col].astype(str),
        )
    else:
        net["_match_deployment"] = "sample:" + net[net_id_col].astype(str)

    uvp = uvp_df.copy().reset_index(drop=True)
    uvp["_match_lat"] = pd.to_numeric(uvp[uvp_lat_col], errors="coerce")
    uvp["_match_lon"] = pd.to_numeric(uvp[uvp_lon_col], errors="coerce")
    uvp["_match_time"] = (
        pd.to_datetime(uvp[uvp_time_col], errors="coerce", utc=True)
        if uvp_time_col and uvp_time_col in uvp.columns
        else pd.NaT
    )
    uvp = uvp.dropna(subset=["_match_lat", "_match_lon"]).reset_index(drop=True)
    if uvp.empty:
        return pd.DataFrame(columns=_MATCH_COLUMNS)

    has_profile = bool(uvp_profile_col and uvp_profile_col in uvp.columns)
    rows: list[dict] = []
    for deployment_id, deployment in net.groupby("_match_deployment", dropna=False, sort=False):
        geo_rows = deployment.dropna(subset=["_match_lat", "_match_lon"])
        if geo_rows.empty:
            continue
        net_lat = float(geo_rows["_match_lat"].mean())
        net_lon = float(geo_rows["_match_lon"].mean())
        net_time_values = deployment["_match_time"].dropna()
        net_time = net_time_values.min() if not net_time_values.empty else pd.NaT
        station_values = (
            deployment[net_station_col].dropna()
            if net_station_col in deployment.columns
            else pd.Series(dtype=object)
        )
        station = station_values.iloc[0] if not station_values.empty else deployment.iloc[0][net_id_col]
        cast_values = (
            deployment[net_cast_col].dropna()
            if net_cast_col and net_cast_col in deployment.columns
            else pd.Series(dtype=object)
        )
        net_cast = cast_values.iloc[0] if not cast_values.empty else None

        distances = haversine_km(
            net_lat, net_lon, uvp["_match_lat"].to_numpy(), uvp["_match_lon"].to_numpy()
        )
        candidates = uvp.loc[distances <= max_km].copy()
        if candidates.empty:
            continue
        candidates["_distance_km"] = distances[distances <= max_km]
        if pd.notna(net_time):
            candidates["_time_gap_days"] = (
                candidates["_match_time"] - net_time
            ).abs().dt.total_seconds() / 86400.0
        else:
            candidates["_time_gap_days"] = np.nan

        candidates["_temporal_match"] = candidates["_time_gap_days"].notna()
        if max_days is not None:
            candidates["_temporal_match"] &= candidates["_time_gap_days"] <= max_days
        normalized_station = _normalize_station(station)
        candidates["_station_name_match"] = (
            candidates["station_id"].map(_normalize_station).eq(normalized_station)
            if "station_id" in candidates.columns and normalized_station
            else False
        )
        # A synchronous candidate wins; then spatial proximity, temporal gap and
        # station-name agreement resolve ties. Station text never excludes data.
        candidates["_time_sort"] = candidates["_time_gap_days"].fillna(np.inf)
        selected = candidates.sort_values(
            ["_temporal_match", "_distance_km", "_time_sort", "_station_name_match", uvp_id_col],
            ascending=[False, True, True, False, True],
            kind="stable",
        ).iloc[0]
        matched = bool(selected["_temporal_match"])
        for _, net_row in deployment.iterrows():
            rows.append(
                {
                    "net_sample_id": net_row[net_id_col],
                    "net_deployment_id": deployment_id,
                    "net_cast": net_cast,
                    "station": station,
                    "latitude": net_lat,
                    "longitude": net_lon,
                    "net_datetime": net_time,
                    "uvp_sample_id": selected[uvp_id_col],
                    "uvp_profile_str": selected[uvp_profile_col] if has_profile else None,
                    "uvp_project_id": selected.get(uvp_project_col),
                    "uvp_instrument": selected.get(uvp_instrument_col),
                    "distance_km": round(float(selected["_distance_km"]), 3),
                    "time_gap_days": (
                        round(float(selected["_time_gap_days"]), 3)
                        if pd.notna(selected["_time_gap_days"])
                        else None
                    ),
                    "station_name_match": bool(selected["_station_name_match"]),
                    "candidate_count": int(len(candidates)),
                    "match_status": "matched" if matched else "spatial_only",
                    "join_eligible": matched,
                    "match_method": "deployment_spatiotemporal",
                    "method_version": NET_UVP_MATCH_METHOD_VERSION,
                }
            )

    return pd.DataFrame(rows, columns=_MATCH_COLUMNS)


def join_certified_net_uvp_enriched(
    net_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    uvp_enriched_df: pd.DataFrame,
) -> pd.DataFrame:
    """Joint filet, correspondances certifiées et export UVP enrichi.

    Seules les correspondances dont ``join_eligible`` vaut vrai sont retenues.
    La jointure UVP est volontairement limitée aux deux clés auditables : projet
    EcoTaxa et profil UVP. Côté export, le profil est choisi dans cet ordre :
    ``sample_profileid``, puis ``sample_id`` ou ``obj_orig_id`` sans suffixe
    d'objet ``_NNN``. Les clés absentes ou contradictoires sont refusées.
    """
    def require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(
                f"Jointure filet↔UVP refusée : colonne(s) {label} absente(s) : "
                + ", ".join(f"`{column}`" for column in missing)
                + "."
            )

    def normalized_id(values: pd.Series) -> pd.Series:
        return values.astype("string").str.strip().replace("", pd.NA)

    net_id_col = next(
        (column for column in ("SAMPLE_ID", "sample_id", "net_sample_id") if column in net_df.columns),
        None,
    )
    if net_id_col is None:
        raise ValueError(
            "Jointure filet↔UVP refusée : aucune colonne identifiant le sample filet "
            "(`SAMPLE_ID`, `sample_id` ou `net_sample_id`) n'est présente."
        )
    require_columns(
        audit_df,
        ("net_sample_id", "uvp_project_id", "uvp_profile_str", "join_eligible"),
        "audit",
    )
    require_columns(uvp_enriched_df, ("export_project_id",), "export UVP")

    audit = audit_df.loc[audit_df["join_eligible"].fillna(False).astype(bool)].copy()
    if audit.empty:
        return net_df.iloc[0:0].copy()
    audit["_net_sample_key"] = normalized_id(audit["net_sample_id"])
    audit["_audit_project_key"] = normalized_id(audit["uvp_project_id"])
    audit["_audit_profile_key"] = normalized_id(audit["uvp_profile_str"])
    if audit[["_net_sample_key", "_audit_project_key", "_audit_profile_key"]].isna().any().any():
        raise ValueError("Jointure filet↔UVP refusée : clé d'audit certifiée absente.")
    audit = audit.drop_duplicates(
        subset=["_net_sample_key", "_audit_project_key", "_audit_profile_key"]
    )
    if audit.duplicated("_net_sample_key", keep=False).any():
        raise ValueError("Jointure filet↔UVP refusée : clé de profil audit ambiguë.")

    enriched = uvp_enriched_df.copy()
    profile_candidates: dict[str, pd.Series] = {}
    for column in ("sample_profileid", "sample_id", "obj_orig_id"):
        if column in enriched.columns:
            candidate = normalized_id(enriched[column])
            if column != "sample_profileid":
                candidate = candidate.str.replace(r"_\d+$", "", regex=True)
            profile_candidates[column] = candidate
    if not profile_candidates:
        raise ValueError(
            "Jointure filet↔UVP refusée : aucune clé de profil exportée "
            "(`sample_profileid`, `sample_id` ou `obj_orig_id`) n'est présente."
        )
    fallback_values = pd.concat(
        [
            profile_candidates[column]
            for column in ("sample_id", "obj_orig_id")
            if column in profile_candidates
        ],
        axis=1,
    ) if any(column in profile_candidates for column in ("sample_id", "obj_orig_id")) else None
    if fallback_values is not None and fallback_values.nunique(axis=1, dropna=True).gt(1).any():
        fallback_conflict = fallback_values.nunique(axis=1, dropna=True).gt(1)
        explicit_profile = profile_candidates.get("sample_profileid")
        if explicit_profile is None or explicit_profile[fallback_conflict].isna().any():
            raise ValueError("Jointure filet↔UVP refusée : clé de profil exportée ambiguë.")
    if "sample_profileid" in profile_candidates:
        profile_key = profile_candidates["sample_profileid"].copy()
        if fallback_values is not None:
            profile_key = profile_key.fillna(fallback_values.bfill(axis=1).iloc[:, 0])
    else:
        assert fallback_values is not None
        profile_key = fallback_values.bfill(axis=1).iloc[:, 0]
    if profile_key.isna().any():
        raise ValueError("Jointure filet↔UVP refusée : clé de profil exportée absente.")
    enriched["_export_profile_key"] = profile_key
    enriched["_export_project_key"] = normalized_id(enriched["export_project_id"])
    if enriched["_export_project_key"].isna().any():
        raise ValueError("Jointure filet↔UVP refusée : clé de projet exportée absente.")

    net = net_df.copy()
    net["_net_sample_key"] = normalized_id(net[net_id_col])
    out = net.merge(audit, on="_net_sample_key", how="inner", suffixes=("", "_audit"))
    return out.merge(
        enriched,
        left_on=["_audit_project_key", "_audit_profile_key"],
        right_on=["_export_project_key", "_export_profile_key"],
        how="inner",
        suffixes=("", "_uvp"),
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
