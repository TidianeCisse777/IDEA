"""Contrat déterministe : densité par taxon/stade d'une table NeoLabs taxonomy.

Équivalent NeoLab de `core.copepod_sample_depth` côté UVP : impose la bonne
méthode (filtre taxon, choix des stades, somme par sample, moyenne par station)
et refuse les entrées incomplètes.
"""

from __future__ import annotations

import pandas as pd


NEOLABS_COPEPOD_METHOD_VERSION = "neolabs-copepod-density-v1"

# Stades disponibles dans les exports NeoLabs avec leur colonne depth-vol.
_ALL_STAGE_COLS: dict[str, str] = {
    "C1": "C1_ABUND (ind./m3 depth vol.)",
    "C2": "C2_ABUND (ind./m3 depth vol.)",
    "C3": "C3_ABUND (ind./m3 depth vol.)",
    "C4": "C4_ABUND (ind./m3 depth vol.)",
    "C5": "C5_ABUND (ind./m3 depth vol.)",
    "M":  "M_ABUND (ind./m3 depth vol.)",
    "F":  "F_ABUND (ind./m3 depth vol.)",
    "COP_NS":     "COP_NS_ABUND (ind./m3 depth vol.)",
    "COPEPODID":  "COPEPODID_ABUND (ind./m3 depth vol.)",
    "N1": "N1_ABUND (ind./m3 depth vol.)",
    "N2": "N2_ABUND (ind./m3 depth vol.)",
    "N3": "N3_ABUND (ind./m3 depth vol.)",
    "N4": "N4_ABUND (ind./m3 depth vol.)",
    "N5": "N5_ABUND (ind./m3 depth vol.)",
    "N6": "N6_ABUND (ind./m3 depth vol.)",
    "NAUP_NS":    "NAUP_NS_ABUND (ind./m3 depth vol.)",
    "NAUPLIUS":   "NAUPLIUS_ABUND (ind./m3 depth vol.)",
    "ALL_STAGES": "ALL_STAGES_ABUND (ind./m3 depth vol.)",
}

# Groupes prédéfinis pour faciliter l'usage.
STAGE_GROUPS: dict[str, list[str]] = {
    "all":          list(_ALL_STAGE_COLS),
    "adults":       ["M", "F"],
    "copepodites":  ["C1", "C2", "C3", "C4", "C5"],
    "late_stages":  ["C4", "C5", "M", "F"],   # stades détectables par UVP
    "nauplii":      ["N1", "N2", "N3", "N4", "N5", "N6"],
}


def neolabs_copepod_density(
    df: pd.DataFrame,
    *,
    stages: list[str] | str | None = None,
    taxon_column: str = "CLASS",
    taxon_filter: str = "Copepoda",
    sample_column: str = "SAMPLE_ID",
    station_column: str = "STATION_NAME",
    lat_column: str = "latitude",
    lon_column: str = "longitude",
) -> pd.DataFrame:
    """Densité par taxon et stades choisis, méthode imposée et traçable.

    ``stages`` détermine quels stades sont sommés par sample :

    - ``None`` ou ``"ALL_STAGES"`` → colonne ``ALL_STAGES_ABUND`` (somme officielle).
    - ``"late_stages"`` → C4 + C5 + M + F (stades comparables à l'UVP, > ~600 µm).
    - ``"adults"`` → M + F uniquement.
    - ``"copepodites"`` → C1 à C5.
    - ``"nauplii"`` → N1 à N6.
    - Liste explicite, ex. ``["C5", "M", "F"]``.

    ``taxon_filter`` filtre la colonne ``taxon_column`` (ex. ``CLASS=="Copepoda"``
    ou ``FAMILY=="Calanidae"``).

    Renvoie une ligne par station : ``STATION_NAME``, ``latitude``, ``longitude``,
    ``copepod_density_ind_m3``, ``n_samples``, ``stages_used``, ``method_version``.
    Lève ``ValueError`` sur entrée incomplète.
    """
    # Résoudre la liste de stades
    if stages is None or stages == "ALL_STAGES":
        stage_list = ["ALL_STAGES"]
    elif isinstance(stages, str) and stages in STAGE_GROUPS:
        stage_list = STAGE_GROUPS[stages]
    elif isinstance(stages, str):
        stage_list = [stages]
    else:
        stage_list = list(stages)

    # Colonnes abundance correspondantes
    stage_cols: list[str] = []
    unknown = []
    for s in stage_list:
        col = _ALL_STAGE_COLS.get(s)
        if col is None:
            unknown.append(s)
        else:
            stage_cols.append(col)
    if unknown:
        raise ValueError(
            f"Stade(s) inconnu(s) : {unknown}. "
            f"Disponibles : {list(_ALL_STAGE_COLS)}."
        )

    required = {taxon_column, sample_column, station_column, *stage_cols}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(
            "Densité NeoLabs refusée : colonne(s) requise(s) absente(s) : "
            + ", ".join(f"`{c}`" for c in missing)
            + "."
        )

    # Filtre taxon
    taxon_col_vals = df[taxon_column].astype("string")
    mask = taxon_col_vals.str.casefold() == taxon_filter.casefold()
    sub = df.loc[mask].copy()
    if sub.empty:
        raise ValueError(
            f"Aucune ligne `{taxon_column} == '{taxon_filter}'` dans la table."
        )

    # Somme des stades par ligne → densité de la ligne
    for col in stage_cols:
        sub[col] = pd.to_numeric(sub[col], errors="coerce").fillna(0.0)
    sub["_density"] = sub[stage_cols].sum(axis=1)

    # Agrégation par sample puis par station
    agg: dict[str, str] = {"_density": "sum"}
    for col in (station_column, lat_column, lon_column):
        if col in sub.columns:
            agg[col] = "first"
    per_sample = sub.groupby(sample_column, as_index=False).agg(agg)
    per_sample = per_sample.rename(columns={"_density": "copepod_density_ind_m3"})

    st_agg: dict[str, str] = {"copepod_density_ind_m3": "mean", sample_column: "size"}
    for col in (lat_column, lon_column):
        if col in per_sample.columns:
            st_agg[col] = "mean"
    per_station = per_sample.groupby(station_column, as_index=False).agg(st_agg)
    per_station = per_station.rename(columns={sample_column: "n_samples"})
    per_station["stages_used"] = "+".join(stage_list)
    per_station["taxon_filter"] = taxon_filter
    per_station["method_version"] = NEOLABS_COPEPOD_METHOD_VERSION
    return per_station
