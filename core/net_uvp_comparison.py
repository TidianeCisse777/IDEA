"""Contrat déterministe : correspondance et comparaison filet ↔ UVP.

Pont entre l'abondance filet Calanus (NeoLabs/Hydrobios) et les images UVP6
curées (EcoTaxa/EcoPart). Trois
étapes, chacune imposée pour éviter qu'un `run_pandas` libre invente une
jointure ou compare des unités incompatibles :

1. `match_net_to_uvp` — apparie chaque déploiement filet au sample UVP le plus
   proche dans l'espace (haversine), avec l'écart temporel calculé et exposé.
   Le rapprochement est SPATIAL (stations de monitoring revisitées) : l'écart de
   temps n'est jamais masqué, il devient une colonne + un statut.
2. `to_ind_per_m3` — aligne une densité `ind./L` (UVP) sur `ind./m³` (filet).
3. `build_paired_depth_strata` — déduplique la jointure objet×taxon et construit
   une ligne par intervalle filet avec les seuls bins UVP de ce même intervalle.
4. `compare_paired_density` — pose delta, ratio et log2-ratio sur une table déjà
   appariée à un grain commun (station ou sample), sans réordonner ni inventer.

Ce module ne lit aucune source ni session : il opère sur des DataFrames déjà
résolus par les tools. Il lève `ValueError` sur entrée incomplète plutôt que de
produire une comparaison fausse. La sélection finale suit le protocole
Calanus UVP6–Hydrobios : C4+C5+M+F au filet (sans *C. finmarchicus* C4) et
images UVP candidates ≥3 mm avec calibration documentée.
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
NET_UVP_DEPTH_METHOD_VERSION = "net-uvp-calanus-uvp6-hydrobios-v1"
NET_UVP_PROFILE_METHOD_VERSION = "net-uvp-calanus-uvp6-hydrobios-profile-v1"

_CALANUS_LATE_STAGES = frozenset({"C4", "C5", "M", "F"})
_CALANUS_STAGE_COLUMNS = (
    "C4_ABUND (ind./m3 depth vol.)",
    "C5_ABUND (ind./m3 depth vol.)",
    "M_ABUND (ind./m3 depth vol.)",
    "F_ABUND (ind./m3 depth vol.)",
)
_UVP_NON_CALANUS_TOKENS = (
    "antenna", "with-eggs", "copepoda eggs", "dead", "part<", "cyclopoida",
    "harpacticoida", "heterorhab", "paraeuchaeta", "metridia",
)


def normalize_target_stages(value: str | tuple[str, ...] = "C4,C5,M,F") -> tuple[str, ...]:
    """Parse a declared late-stage selection; never silently change it."""
    raw = value.split(",") if isinstance(value, str) else value
    stages = tuple(dict.fromkeys(str(stage).strip().upper() for stage in raw if str(stage).strip()))
    unsupported = sorted(set(stages).difference(_CALANUS_LATE_STAGES))
    if not stages or unsupported:
        raise ValueError(
            "Stades filet non pris en charge : " + ", ".join(unsupported or ["aucun"])
            + ". Choisir parmi C4, C5, M, F."
        )
    return stages

_EARTH_RADIUS_KM = 6371.0
_MATCH_COLUMNS = [
    "net_sample_id", "net_deployment_id", "net_cast", "station", "latitude",
    "longitude", "net_datetime", "uvp_sample_id", "uvp_profile_str",
    "uvp_project_id", "uvp_instrument", "distance_km", "time_gap_days",
    "station_name_match", "candidate_count", "match_status", "join_eligible",
    "match_method", "method_version",
]


def _calanus_net_density(
    net_group: pd.DataFrame,
    *,
    sample_col: str,
    analysis_col: str,
    taxon_col: str,
    depth_min_col: str,
    depth_max_col: str,
    abundance_col: str,
    taxon_filter: str = "Calanus",
    stages: str | tuple[str, ...] = "C4,C5,M,F",
) -> tuple[float, int, int, int]:
    """Declared taxon/stage density from long Hydrobios or wide NeoLabs rows."""
    taxon_filter = str(taxon_filter).strip()
    if not taxon_filter:
        raise ValueError("Comparaison refusée : taxon cible vide.")
    selected_stages = normalize_target_stages(stages)
    is_calanus_protocol = taxon_filter.casefold() == "calanus"
    if taxon_col not in net_group.columns:
        raise ValueError(f"Comparaison Calanus refusée : colonne filet `{taxon_col}` absente.")
    taxon = net_group[taxon_col].astype("string").str.strip()
    selected = net_group.loc[
        taxon.str.contains(taxon_filter, case=False, na=False, regex=False)
        & (~taxon.str.casefold().eq("calanus spp.") if is_calanus_protocol else True)
    ].copy()
    if selected.empty:
        return np.nan, 0, 0, 0

    stage_col = next(
        (column for column in ("TAXON_LIFE_DEV_STAGE", "stage", "STAGE") if column in selected.columns),
        None,
    )
    if stage_col is not None:
        stages = selected[stage_col].astype("string").str.strip().str.upper()
        selected = selected.loc[stages.isin(selected_stages)].copy()
        selected_stages = stages.loc[selected.index]
        finmarchicus_c4 = (
            is_calanus_protocol
            & selected[taxon_col].astype("string").str.contains(
                "calanus finmarchicus", case=False, na=False
            )
            & selected_stages.eq("C4")
        )
        selected = selected.loc[~finmarchicus_c4]
        if abundance_col not in selected.columns:
            raise ValueError(
                f"Comparaison Calanus refusée : colonne d'abondance filet `{abundance_col}` absente."
            )
        selected["_calanus_net_value"] = pd.to_numeric(
            selected[abundance_col], errors="coerce"
        )
    else:
        stage_columns = {
            stage: f"{stage}_ABUND (ind./m3 depth vol.)" for stage in selected_stages
        }
        missing_stages = [column for column in stage_columns.values() if column not in selected.columns]
        if missing_stages:
            raise ValueError(
                "(ni colonne de stade, ni colonnes wide complètes)."
                "Comparaison refusée : stades demandés absents du filet "
                "(ni colonne de stade, ni colonnes wide complètes)."
                "(ni colonne de stade, ni colonnes wide complètes)."
            )
        values = selected.loc[:, list(stage_columns.values())].apply(
            pd.to_numeric, errors="coerce"
        )
        # In the NeoLabs wide format, a blank stage cell represents no
        # individual in this stage, while the taxon row itself is measured.
        selected["_calanus_net_value"] = values.fillna(0.0).sum(axis=1)
        finmarchicus = is_calanus_protocol & selected[taxon_col].astype("string").str.contains(
            "calanus finmarchicus", case=False, na=False
        )
        if "C4" in selected_stages:
            selected.loc[finmarchicus, "_calanus_net_value"] -= values.loc[
                finmarchicus, stage_columns["C4"]
            ].fillna(0.0)

    if selected.empty:
        return np.nan, 0, 0, 0
    keys = [sample_col, analysis_col, taxon_col, depth_min_col, depth_max_col]
    if stage_col is not None:
        # A long Hydrobios export has one abundance per taxon *and* stage:
        # C4, C5, M and F are therefore distinct legitimate contributions.
        keys.append(stage_col)
    missing = 0
    incompatible = 0
    canonical: list[float] = []
    for _, rows in selected.groupby(keys, sort=True, dropna=False):
        candidate_values = rows["_calanus_net_value"].to_numpy(dtype=float)
        finite = candidate_values[np.isfinite(candidate_values)]
        if len(finite) == 0 or len(finite) != len(candidate_values):
            missing += 1
            continue
        candidate = float(finite[0])
        if not np.allclose(finite, candidate, rtol=1e-6, atol=1e-9):
            incompatible += 1
            continue
        canonical.append(candidate)
    density = float(sum(canonical)) if not missing and not incompatible else np.nan
    return density, missing, incompatible, len(selected)


def _calanus_uvp6_count(
    frame: pd.DataFrame,
    *,
    object_col: str,
    taxonomy_col: str,
    taxon_filter: str = "Calanus",
    min_size_mm: float = 3.0,
) -> tuple[int, int]:
    """Count curated target images using the declared calibrated size threshold."""
    taxon_filter = str(taxon_filter).strip()
    if not taxon_filter or not np.isfinite(min_size_mm) or float(min_size_mm) <= 0:
        raise ValueError("Comparaison refusée : taxon ou seuil de taille invalide.")
    is_calanus_protocol = taxon_filter.casefold() == "calanus"
    required = (object_col, taxonomy_col, "object_major", "acq_pixel")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(
            "Comparaison Calanus UVP6 refusée : champs image/calibration absents : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )
    taxonomy = frame[taxonomy_col].astype("string")
    category = (
        frame["object_annotation_category"].astype("string")
        if "object_annotation_category" in frame.columns
        else taxonomy
    )
    # The Calanus source protocol first keeps Copepoda / Copepoda-lipidsac,
    # groups, then removes taxa which are certainly not Calanus.  A confirmed
    # Calanus annotation remains sufficient when the export lacks `taxagroup`.
    if is_calanus_protocol and "taxagroup" in frame.columns:
        image_group = frame["taxagroup"].astype("string").str.casefold().str.strip()
        candidate = image_group.isin({"copepoda", "copepoda-lipidsac"})
    elif is_calanus_protocol:
        candidate = taxonomy.str.contains("copepoda", case=False, na=False, regex=False)
        candidate |= category.str.contains("copepoda", case=False, na=False, regex=False)
    else:
        candidate = taxonomy.str.contains(taxon_filter, case=False, na=False, regex=False)
        candidate |= category.str.contains(taxon_filter, case=False, na=False, regex=False)
    if is_calanus_protocol:
        candidate |= taxonomy.str.contains("calanus", case=False, na=False, regex=False)
        candidate |= category.str.casefold().isin(
            {"calanus", "side<with visible lipid sac", "top-bottom<with visible lipid sac"}
        )
    labels = (taxonomy.fillna("") + " " + category.fillna("")).str.casefold()
    if is_calanus_protocol:
        for token in _UVP_NON_CALANUS_TOKENS:
            candidate &= ~labels.str.contains(token, regex=False, na=False)
    object_ids = frame[object_col].astype("string").str.strip()
    major_mm = (
        pd.to_numeric(frame["object_major"], errors="coerce")
        * pd.to_numeric(frame["acq_pixel"], errors="coerce")
        / 1000.0
    )
    manual = pd.Series(False, index=frame.index)
    for column in ("segmentation_source", "trait_source", "source"):
        if column in frame.columns:
            manual |= frame[column].astype("string").str.contains(
                "manual", case=False, na=False, regex=False
            )
    retained = frame.loc[
        candidate & object_ids.notna() & object_ids.ne("") & (major_mm.ge(float(min_size_mm)) | manual)
    ].drop_duplicates(object_col)
    return int(len(retained)), int(candidate.sum())


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
    max_days: float | None = 0.5,
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

    A normalized station label is a mandatory first key.  Spatial and temporal
    proximity only disambiguate candidates already assigned to that station.
    ``matched`` therefore requires station, spatial, and temporal agreement;
    ``spatial_only`` is retained only for station-matched candidates when dates
    are missing or outside the requested tolerance. Only ``matched`` rows are
    eligible for an abundance join. One chosen UVP sample is expanded to all
    net samples in the same deployment.
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
        # Station identity is the primary audit key.  Distance and time narrow
        # down only station-matched candidates; they can never compensate for
        # a different station label.
        candidates = candidates.loc[candidates["_station_name_match"]].copy()
        if candidates.empty:
            continue
        # A synchronous candidate wins; then spatial proximity, temporal gap and
        # deterministic source ID resolve ties within the same station.
        candidates["_time_sort"] = candidates["_time_gap_days"].fillna(np.inf)
        selected = candidates.sort_values(
            ["_temporal_match", "_distance_km", "_time_sort", uvp_id_col],
            ascending=[False, True, True, True],
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
    *,
    allow_unverified_ctd: bool = False,
) -> pd.DataFrame:
    """Joint filet, correspondances certifiées et export UVP enrichi.

    Seules les correspondances dont ``join_eligible`` vaut vrai et dont toute
    preuve CTD explicite est vérifiée sont retenues.
    Une dérogation explicite peut aussi retenir les lignes exploratoires dont la
    vérification CTD est exactement ``unavailable``; elle ne couvre jamais un
    échec de correspondance CTD.
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

    def explicitly_certified(value: object) -> bool:
        """Accept only booleans or unambiguous serialized true values."""
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1"}
        return False

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

    certified = audit_df["join_eligible"].map(explicitly_certified)
    if "ctd_verification" in audit_df.columns:
        certified &= (
            audit_df["ctd_verification"]
            .astype("string")
            .str.strip()
            .eq("verified")
        )
    elif "ctd_filename_join_eligible" in audit_df.columns:
        certified &= audit_df["ctd_filename_join_eligible"].map(
            explicitly_certified
        )
    elif "ctd_filename_match_status" in audit_df.columns:
        certified &= (
            audit_df["ctd_filename_match_status"]
            .astype("string")
            .str.strip()
            .eq("matched")
        )
    accepted = certified
    if (
        allow_unverified_ctd
        and "ctd_verification" in audit_df.columns
        and "exploratory" in audit_df.columns
    ):
        accepted |= (
            audit_df["ctd_verification"].astype("string").str.strip().eq("unavailable")
            & audit_df["exploratory"].map(explicitly_certified)
        )
    audit = audit_df.loc[accepted].copy()
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


def build_paired_depth_strata_from_certified_inputs(
    net_df: pd.DataFrame,
    audit_df: pd.DataFrame,
    uvp_enriched_df: pd.DataFrame,
    *,
    allow_unverified_ctd: bool = False,
    net_sample_col: str = "SAMPLE_ID",
    net_analysis_col: str = "ANALYSIS_ID",
    net_taxon_col: str = "TAXON_ID",
    net_class_col: str = "CLASS",
    net_depth_min_col: str = "MIN_SAMPLE_DEPTH",
    net_depth_max_col: str = "MAX_SAMPLE_DEPTH",
    net_abundance_col: str = "ALL_STAGES_ABUND (ind./m3 depth vol.)",
    uvp_depth_col: str = "depth_bin",
    uvp_object_col: str = "object_id",
    uvp_taxonomy_col: str = "object_annotation_hierarchy",
    uvp_volume_col: str = "ecopart_Sampled volume [L]",
    taxon_filter: str = "Calanus",
    net_stages: str = "C4,C5,M,F",
    uvp_min_size_mm: float = 3.0,
    depth_window_min_m: float | None = None,
    depth_window_max_m: float | None = None,
) -> pd.DataFrame:
    """Construit les strates Calanus certifiées sans matérialiser taxons × objets.

    Le contrat scientifique est identique à
    :func:`join_certified_net_uvp_enriched` suivi de
    :func:`build_paired_depth_strata`, mais chaque numérateur est calculé à son
    grain natif : lignes taxonomiques NeoLabs d'un côté et objets/bins UVP de
    l'autre. Ainsi, un profil très dense ne crée jamais une table intermédiaire
    de taille ``n_taxons × n_objets``.
    """
    def require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(
                f"Comparaison filet↔UVP par tranche refusée : colonne(s) {label} absente(s) : "
                + ", ".join(f"`{column}`" for column in missing)
                + "."
            )

    def normalized_id(values: pd.Series) -> pd.Series:
        return values.astype("string").str.strip().replace("", pd.NA)

    def explicitly_certified(value: object) -> bool:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1"}
        return False

    require_columns(
        net_df,
        (
            net_sample_col,
            net_analysis_col,
            net_taxon_col,
            net_depth_min_col,
            net_depth_max_col,
            net_abundance_col,
        ),
        "filet",
    )
    require_columns(
        audit_df,
        ("net_sample_id", "uvp_project_id", "uvp_profile_str", "join_eligible"),
        "audit",
    )
    require_columns(
        uvp_enriched_df,
        (
            "export_project_id",
            uvp_depth_col,
            uvp_object_col,
            uvp_taxonomy_col,
            uvp_volume_col,
            "object_major",
            "acq_pixel",
        ),
        "export UVP",
    )
    if uvp_taxonomy_col != "object_annotation_hierarchy":
        raise ValueError(
            "Comparaison filet↔UVP par tranche refusée : la taxonomie UVP "
            "doit provenir de `object_annotation_hierarchy`."
        )
    normalize_target_stages(net_stages)
    if not np.isfinite(uvp_min_size_mm) or float(uvp_min_size_mm) <= 0:
        raise ValueError("Comparaison refusée : seuil UVP de taille invalide.")
    if (
        depth_window_min_m is not None
        and depth_window_max_m is not None
        and float(depth_window_min_m) > float(depth_window_max_m)
    ):
        raise ValueError("Comparaison refusée : fenêtre verticale inversée.")

    certified = audit_df["join_eligible"].map(explicitly_certified)
    if "ctd_verification" in audit_df.columns:
        certified &= audit_df["ctd_verification"].astype("string").str.strip().eq("verified")
    elif "ctd_filename_join_eligible" in audit_df.columns:
        certified &= audit_df["ctd_filename_join_eligible"].map(explicitly_certified)
    elif "ctd_filename_match_status" in audit_df.columns:
        certified &= audit_df["ctd_filename_match_status"].astype("string").str.strip().eq("matched")
    accepted = certified
    if (
        allow_unverified_ctd
        and "ctd_verification" in audit_df.columns
        and "exploratory" in audit_df.columns
    ):
        accepted |= (
            audit_df["ctd_verification"].astype("string").str.strip().eq("unavailable")
            & audit_df["exploratory"].map(explicitly_certified)
        )
    audit = audit_df.loc[accepted].copy()
    if audit.empty:
        return pd.DataFrame()
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
    fallback_values = (
        pd.concat(
            [
                profile_candidates[column]
                for column in ("sample_id", "obj_orig_id")
                if column in profile_candidates
            ],
            axis=1,
        )
        if any(column in profile_candidates for column in ("sample_id", "obj_orig_id"))
        else None
    )
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
    net["_net_sample_key"] = normalized_id(net[net_sample_col])
    net = net.merge(audit, on="_net_sample_key", how="inner", suffixes=("", "_audit"))
    if net.empty:
        return pd.DataFrame()
    # The audit is authoritative for the profile/project shown in the result.
    net["export_project_id"] = net["uvp_project_id"]
    available_profiles = enriched[["_export_project_key", "_export_profile_key"]].drop_duplicates()
    net = net.merge(
        available_profiles,
        left_on=["_audit_project_key", "_audit_profile_key"],
        right_on=["_export_project_key", "_export_profile_key"],
        how="inner",
    )
    if net.empty:
        return pd.DataFrame()

    profile_rows = {
        key: group
        for key, group in enriched.groupby(
            ["_export_project_key", "_export_profile_key"], sort=False, dropna=False
        )
    }
    for frame in (net, enriched):
        for column in (
            net_depth_min_col,
            net_depth_max_col,
            net_abundance_col,
            uvp_depth_col,
            uvp_volume_col,
        ):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

    rows: list[dict[str, object]] = []
    stratum_key = [net_sample_col, net_depth_min_col, net_depth_max_col]
    for (sample_id, depth_min, depth_max), net_group in net.groupby(
        stratum_key, sort=True, dropna=False
    ):
        if (
            (depth_window_min_m is not None and (not np.isfinite(depth_min) or depth_min < float(depth_window_min_m)))
            or (depth_window_max_m is not None and (not np.isfinite(depth_max) or depth_max > float(depth_window_max_m)))
        ):
            continue
        profile_keys = net_group[["_audit_project_key", "_audit_profile_key"]].drop_duplicates()
        if len(profile_keys) != 1:
            raise ValueError("Jointure filet↔UVP refusée : clé de profil audit ambiguë.")
        profile_key_tuple = tuple(profile_keys.iloc[0])
        uvp_group = profile_rows[profile_key_tuple]

        net_abundance, net_missing, net_incompatible, net_target_rows = _calanus_net_density(
            net_group,
            sample_col=net_sample_col,
            analysis_col=net_analysis_col,
            taxon_col=net_taxon_col,
            depth_min_col=net_depth_min_col,
            depth_max_col=net_depth_max_col,
            abundance_col=net_abundance_col,
            taxon_filter=taxon_filter,
            stages=net_stages,
        )

        valid_depth_interval = bool(
            np.isfinite(depth_min)
            and np.isfinite(depth_max)
            and float(depth_max) > float(depth_min)
        )
        in_interval = (
            uvp_group.loc[
                uvp_group[uvp_depth_col].between(
                    float(depth_min), float(depth_max), inclusive="both"
                )
            ]
            if valid_depth_interval
            else uvp_group.iloc[0:0]
        )
        target_count, uvp_calanus_candidate_images = _calanus_uvp6_count(
            in_interval,
            object_col=uvp_object_col,
            taxonomy_col=uvp_taxonomy_col,
            taxon_filter=taxon_filter,
            min_size_mm=uvp_min_size_mm,
        )
        bin_count = int(in_interval[uvp_depth_col].dropna().nunique())
        missing_volume_bins = 0
        incompatible_volume_bins = 0
        canonical_volumes: list[float] = []
        for _, depth_rows in in_interval.groupby(uvp_depth_col, sort=True):
            raw_volumes = depth_rows[uvp_volume_col].to_numpy(dtype=float)
            finite = raw_volumes[np.isfinite(raw_volumes)]
            if len(finite) == 0 or len(finite) != len(raw_volumes):
                missing_volume_bins += 1
                continue
            candidate = float(finite[0])
            if candidate <= 0 or not np.allclose(finite, candidate, rtol=1e-6, atol=1e-9):
                incompatible_volume_bins += 1
                continue
            canonical_volumes.append(candidate)

        if not valid_depth_interval:
            status = "invalid_net_depth"
            reason = "Intervalle de profondeur du filet absent ou invalide."
        elif net_target_rows == 0:
            status = "missing_net_target"
            reason = f"Aucune ligne {taxon_filter} {net_stages} comparable pour cette tranche de filet."
        elif net_incompatible:
            status = "incompatible_net_abundance"
            reason = "Abondances filet contradictoires pour une même ligne taxonomique."
        elif net_missing:
            status = "missing_net_abundance"
            reason = "Au moins une abondance filet requise est manquante."
        elif bin_count == 0:
            status = "no_depth_coverage"
            reason = "Aucun bin UVP dans la même tranche de profondeur que le filet."
        elif incompatible_volume_bins:
            status = "incompatible_volume"
            reason = "Valeurs de volume EcoPart contradictoires ou non positives dans un bin."
        elif missing_volume_bins:
            status = "missing_volume"
            reason = "Volume EcoPart manquant pour au moins un bin de profondeur."
        else:
            status = "matched"
            reason = pd.NA

        calculable = status == "matched"
        sampled_volume = float(sum(canonical_volumes)) if calculable else np.nan
        uvp_abundance = target_count / sampled_volume * 1000.0 if calculable else np.nan
        abundance_delta = uvp_abundance - net_abundance if calculable else np.nan
        abundance_ratio = (
            uvp_abundance / net_abundance
            if calculable and net_abundance != 0
            else np.nan
        )
        row: dict[str, object] = {
            "net_sample_id": sample_id,
            "net_depth_min_m": float(depth_min),
            "net_depth_max_m": float(depth_max),
            "net_abundance_ind_m3": net_abundance,
            "net_calanus_target_rows": net_target_rows,
            "net_missing_abundance_rows": net_missing,
            "net_incompatible_abundance_rows": net_incompatible,
            "uvp_target_count": target_count,
            "uvp_calanus_candidate_images": uvp_calanus_candidate_images,
            "uvp_size_threshold_mm": float(uvp_min_size_mm),
            "taxon_scope": f"{taxon_filter}; stades filet {net_stages}",
            "depth_window_min_m": depth_window_min_m,
            "depth_window_max_m": depth_window_max_m,
            "uvp_depth_bin_count": bin_count,
            "uvp_missing_volume_bins": missing_volume_bins,
            "uvp_incompatible_volume_bins": incompatible_volume_bins,
            "uvp_sampled_volume_L": sampled_volume,
            "uvp_abundance_ind_m3": uvp_abundance,
            "abundance_delta_ind_m3": abundance_delta,
            "abundance_ratio": abundance_ratio,
            "depth_match_status": status,
            "comparison_calculable": calculable,
            "exclusion_reason": reason,
            "method_version": NET_UVP_DEPTH_METHOD_VERSION,
        }
        for source, target in (
            ("STATION_NAME", "station"),
            ("export_project_id", "uvp_project_id"),
            ("uvp_profile_str", "uvp_profile"),
            ("ctd_verification", "ctd_verification"),
            ("exploratory", "exploratory"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
        ):
            if source in net_group.columns:
                values = net_group[source].dropna()
                row[target] = values.iloc[0] if not values.empty else pd.NA
        rows.append(row)

    return pd.DataFrame(rows)


def integrate_paired_depth_strata(strata: pd.DataFrame) -> pd.DataFrame:
    """Integrate same-depth Calanus strata to one net–UVP profile in ind./m².

    This is the profile-level comparison used by the Calanus UVP6–Hydrobios
    workflow: each native density is multiplied by the corresponding net depth
    interval, then summed.  Missing/excluded strata are never converted to zero;
    their depth coverage is retained and the profile is labelled partial.
    """
    required = {
        "net_sample_id", "net_depth_min_m", "net_depth_max_m",
        "net_abundance_ind_m3", "uvp_abundance_ind_m3", "comparison_calculable",
    }
    missing = sorted(required.difference(strata.columns))
    if missing:
        raise ValueError(
            "Intégration filet↔UVP refusée : colonne(s) de strate absente(s) : "
            + ", ".join(f"`{column}`" for column in missing) + "."
        )

    work = strata.copy()
    work["_depth_min"] = pd.to_numeric(work["net_depth_min_m"], errors="coerce")
    work["_depth_max"] = pd.to_numeric(work["net_depth_max_m"], errors="coerce")
    work["_thickness_m"] = work["_depth_max"] - work["_depth_min"]
    if (~np.isfinite(work["_thickness_m"]) | work["_thickness_m"].le(0)).any():
        raise ValueError("Intégration filet↔UVP refusée : tranche de profondeur invalide.")
    for column in ("net_abundance_ind_m3", "uvp_abundance_ind_m3"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work["_calculable"] = work["comparison_calculable"].fillna(False).astype(bool)
    group_columns = ["net_sample_id"]
    for column in ("uvp_project_id", "uvp_profile", "station"):
        if column in work.columns:
            group_columns.append(column)

    rows: list[dict[str, object]] = []
    for key, group in work.groupby(group_columns, sort=True, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        result = dict(zip(group_columns, key, strict=True))
        total_depth_m = float(group["_thickness_m"].sum())
        used = group.loc[group["_calculable"]].copy()
        used_depth_m = float(used["_thickness_m"].sum())
        missing_count = int((~group["_calculable"]).sum())
        if used.empty:
            net_ind_m2 = np.nan
            uvp_ind_m2 = np.nan
            status = "not_calculable"
        else:
            net_ind_m2 = float((used["net_abundance_ind_m3"] * used["_thickness_m"]).sum())
            uvp_ind_m2 = float((used["uvp_abundance_ind_m3"] * used["_thickness_m"]).sum())
            status = "integrated" if missing_count == 0 else "partial_depth_coverage"
        result.update({
            "net_integrated_ind_m2": net_ind_m2,
            "uvp_integrated_ind_m2": uvp_ind_m2,
            "integrated_delta_ind_m2": uvp_ind_m2 - net_ind_m2 if np.isfinite(net_ind_m2) and np.isfinite(uvp_ind_m2) else np.nan,
            "integrated_ratio": uvp_ind_m2 / net_ind_m2 if np.isfinite(net_ind_m2) and net_ind_m2 != 0 else np.nan,
            "depth_coverage_m": used_depth_m,
            "total_requested_depth_m": total_depth_m,
            "depth_coverage_fraction": used_depth_m / total_depth_m if total_depth_m else np.nan,
            "excluded_strata_count": missing_count,
            "profile_comparison_status": status,
            "method_version": NET_UVP_PROFILE_METHOD_VERSION,
        })
        rows.append(result)
    return pd.DataFrame(rows)


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


def build_paired_depth_strata(
    joined: pd.DataFrame,
    *,
    net_sample_col: str = "SAMPLE_ID",
    net_analysis_col: str = "ANALYSIS_ID",
    net_taxon_col: str = "TAXON_ID",
    net_class_col: str = "CLASS",
    net_depth_min_col: str = "MIN_SAMPLE_DEPTH",
    net_depth_max_col: str = "MAX_SAMPLE_DEPTH",
    net_abundance_col: str = "ALL_STAGES_ABUND (ind./m3 depth vol.)",
    uvp_depth_col: str = "depth_bin",
    uvp_object_col: str = "object_id",
    uvp_taxonomy_col: str = "object_annotation_hierarchy",
    uvp_volume_col: str = "ecopart_Sampled volume [L]",
    taxon_filter: str = "Calanus",
    net_stages: str = "C4,C5,M,F",
    uvp_min_size_mm: float = 3.0,
    depth_window_min_m: float | None = None,
    depth_window_max_m: float | None = None,
) -> pd.DataFrame:
    """Construit une ligne Calanus comparable par tranche de filet certifiée.

    La table d'entrée est la jointure objet EcoTaxa–EcoPart ↔ lignes taxonomiques
    NeoLabs. Le produit cartésien de cette jointure est dédupliqué aux deux grains
    légitimes : taxon filet pour le numérateur NeoLabs, puis objet et bin UVP pour
    le numérateur et le dénominateur UVP. Seuls les bins dont le centre appartient
    à l'intervalle du filet contribuent à la tranche.
    """
    required = {
        net_sample_col,
        net_analysis_col,
        net_taxon_col,
        net_depth_min_col,
        net_depth_max_col,
        net_abundance_col,
        uvp_depth_col,
        uvp_object_col,
        uvp_taxonomy_col,
        uvp_volume_col,
        "object_major",
        "acq_pixel",
    }
    missing = sorted(required.difference(joined.columns))
    if missing:
        raise ValueError(
            "Comparaison filet↔UVP par tranche refusée : colonne(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )

    normalize_target_stages(net_stages)
    if not np.isfinite(uvp_min_size_mm) or float(uvp_min_size_mm) <= 0:
        raise ValueError("Comparaison refusée : seuil UVP de taille invalide.")
    if (
        depth_window_min_m is not None
        and depth_window_max_m is not None
        and float(depth_window_min_m) > float(depth_window_max_m)
    ):
        raise ValueError("Comparaison refusée : fenêtre verticale inversée.")

    work = joined.copy()
    for column in (net_depth_min_col, net_depth_max_col, net_abundance_col, uvp_depth_col, uvp_volume_col):
        work[column] = pd.to_numeric(work[column], errors="coerce")

    rows: list[dict[str, object]] = []
    stratum_key = [net_sample_col, net_depth_min_col, net_depth_max_col]
    for (sample_id, depth_min, depth_max), group in work.groupby(
        stratum_key, sort=True, dropna=False
    ):
        if (
            (depth_window_min_m is not None and (not np.isfinite(depth_min) or depth_min < float(depth_window_min_m)))
            or (depth_window_max_m is not None and (not np.isfinite(depth_max) or depth_max > float(depth_window_max_m)))
        ):
            continue
        net_abundance, net_missing, net_incompatible, net_target_rows = _calanus_net_density(
            group,
            sample_col=net_sample_col,
            analysis_col=net_analysis_col,
            taxon_col=net_taxon_col,
            depth_min_col=net_depth_min_col,
            depth_max_col=net_depth_max_col,
            abundance_col=net_abundance_col,
            taxon_filter=taxon_filter,
            stages=net_stages,
        )

        valid_depth_interval = bool(
            np.isfinite(depth_min)
            and np.isfinite(depth_max)
            and float(depth_max) > float(depth_min)
        )
        in_interval = (
            group.loc[
                group[uvp_depth_col].between(
                    float(depth_min), float(depth_max), inclusive="both"
                )
            ]
            if valid_depth_interval
            else group.iloc[0:0]
        )
        if uvp_taxonomy_col != "object_annotation_hierarchy":
            raise ValueError(
                "Comparaison filet↔UVP par tranche refusée : la taxonomie UVP "
                "doit provenir de `object_annotation_hierarchy`."
            )
        target_count, uvp_calanus_candidate_images = _calanus_uvp6_count(
            in_interval,
            object_col=uvp_object_col,
            taxonomy_col=uvp_taxonomy_col,
            taxon_filter=taxon_filter,
            min_size_mm=uvp_min_size_mm,
        )
        bin_count = int(in_interval[uvp_depth_col].dropna().nunique())
        missing_volume_bins = 0
        incompatible_volume_bins = 0
        canonical_volumes: list[float] = []
        for _, depth_rows in in_interval.groupby(uvp_depth_col, sort=True):
            raw_volumes = depth_rows[uvp_volume_col].to_numpy(dtype=float)
            finite = raw_volumes[np.isfinite(raw_volumes)]
            if len(finite) == 0 or len(finite) != len(raw_volumes):
                missing_volume_bins += 1
                continue
            candidate = float(finite[0])
            if candidate <= 0 or not np.allclose(
                finite, candidate, rtol=1e-6, atol=1e-9
            ):
                incompatible_volume_bins += 1
                continue
            canonical_volumes.append(candidate)

        if not valid_depth_interval:
            status = "invalid_net_depth"
            reason = "Intervalle de profondeur du filet absent ou invalide."
        elif net_target_rows == 0:
            status = "missing_net_target"
            reason = f"Aucune ligne {taxon_filter} {net_stages} comparable pour cette tranche de filet."
        elif net_incompatible:
            status = "incompatible_net_abundance"
            reason = "Abondances filet contradictoires pour une même ligne taxonomique."
        elif net_missing:
            status = "missing_net_abundance"
            reason = "Au moins une abondance filet requise est manquante."
        elif bin_count == 0:
            status = "no_depth_coverage"
            reason = "Aucun bin UVP dans la même tranche de profondeur que le filet."
        elif incompatible_volume_bins:
            status = "incompatible_volume"
            reason = "Valeurs de volume EcoPart contradictoires ou non positives dans un bin."
        elif missing_volume_bins:
            status = "missing_volume"
            reason = "Volume EcoPart manquant pour au moins un bin de profondeur."
        else:
            status = "matched"
            reason = pd.NA

        calculable = status == "matched"
        sampled_volume = float(sum(canonical_volumes)) if calculable else np.nan
        uvp_abundance = (
            target_count / sampled_volume * 1000.0 if calculable else np.nan
        )
        abundance_delta = (
            uvp_abundance - net_abundance if calculable else np.nan
        )
        abundance_ratio = (
            uvp_abundance / net_abundance
            if calculable and net_abundance != 0
            else np.nan
        )

        row: dict[str, object] = {
            "net_sample_id": sample_id,
            "net_depth_min_m": float(depth_min),
            "net_depth_max_m": float(depth_max),
            "net_abundance_ind_m3": net_abundance,
            "net_calanus_target_rows": net_target_rows,
            "net_missing_abundance_rows": net_missing,
            "net_incompatible_abundance_rows": net_incompatible,
            "uvp_target_count": target_count,
            "uvp_calanus_candidate_images": uvp_calanus_candidate_images,
            "uvp_size_threshold_mm": float(uvp_min_size_mm),
            "taxon_scope": f"{taxon_filter}; stades filet {net_stages}",
            "depth_window_min_m": depth_window_min_m,
            "depth_window_max_m": depth_window_max_m,
            "uvp_depth_bin_count": bin_count,
            "uvp_missing_volume_bins": missing_volume_bins,
            "uvp_incompatible_volume_bins": incompatible_volume_bins,
            "uvp_sampled_volume_L": sampled_volume,
            "uvp_abundance_ind_m3": uvp_abundance,
            "abundance_delta_ind_m3": abundance_delta,
            "abundance_ratio": abundance_ratio,
            "depth_match_status": status,
            "comparison_calculable": calculable,
            "exclusion_reason": reason,
            "method_version": NET_UVP_DEPTH_METHOD_VERSION,
        }
        for source, target in (
            ("STATION_NAME", "station"),
            ("export_project_id", "uvp_project_id"),
            ("uvp_profile_str", "uvp_profile"),
            ("ctd_verification", "ctd_verification"),
            ("exploratory", "exploratory"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
        ):
            if source in group.columns:
                values = group[source].dropna()
                row[target] = values.iloc[0] if not values.empty else pd.NA
        rows.append(row)

    return pd.DataFrame(rows)


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
