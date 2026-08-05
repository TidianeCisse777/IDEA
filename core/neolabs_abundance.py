"""Contrat déterministe : densité par taxon/stade d'une table NeoLabs taxonomy.

Équivalent NeoLab de `core.copepod_sample_depth` côté UVP : impose la bonne
méthode (filtre taxon, choix des stades, somme par sample, moyenne par station)
et refuse les entrées incomplètes.
"""

from __future__ import annotations

import re

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

_NORMALIZED_TOTAL_COLUMN = "Total abundance (ind./m3 depth vol)"

# Groupes prédéfinis pour faciliter l'usage.
STAGE_GROUPS: dict[str, list[str]] = {
    # `ALL_STAGES` est déjà le total officiel : le sommer avec les colonnes
    # individuelles doublerait les organismes.
    "all":          ["ALL_STAGES"],
    "adults":       ["M", "F"],
    "copepodites":  ["C1", "C2", "C3", "C4", "C5"],
    "late_stages":  ["C4", "C5", "M", "F"],   # stades détectables par UVP
    "nauplii":      ["N1", "N2", "N3", "N4", "N5", "N6"],
}


def _resolve_stage_list(stages: list[str] | str | None) -> list[str]:
    """Normalise les préréglages et les sélections de stades NeoLabs."""
    if stages is None:
        return ["ALL_STAGES"]
    if isinstance(stages, str):
        selection = stages.strip()
        selection_key = selection.casefold()
        if selection_key in {"all", "all_stages", "all stages"}:
            return ["ALL_STAGES"]
        if selection_key in STAGE_GROUPS:
            return STAGE_GROUPS[selection_key]
        # Les appels peuvent venir d'une consigne utilisateur : accepter les
        # séparateurs naturels sans demander une syntaxe de tool exacte.
        return [
            part.strip().upper()
            for part in re.split(r"[,;+]", selection)
            if part.strip()
        ]
    return [str(stage).strip().upper() for stage in stages if str(stage).strip()]


def resolve_neolabs_stage_abundance(
    df: pd.DataFrame,
    *,
    stages: list[str] | str | None,
    output_column: str = "_selected_net_abundance_ind_m3",
) -> tuple[pd.DataFrame, list[str]]:
    """Ajoute une abondance NeoLabs pour une sélection de stades explicite.

    Le comparateur filet↔UVP utilise cette projection avant son agrégation par
    strate. `late_stages` (C4+C5+M+F) est un proxy de taille lorsque le fichier
    filet ne contient pas la taille individuelle. `ALL_STAGES` reste possible,
    mais le caller doit le traiter comme un contraste descriptif, pas comme une
    abondance automatiquement comparable à l'UVP.
    """
    stage_list = _resolve_stage_list(stages)
    if not stage_list:
        raise ValueError("Au moins un stade NeoLabs doit être sélectionné.")

    use_normalized_total = (
        stage_list == ["ALL_STAGES"]
        and _ALL_STAGE_COLS["ALL_STAGES"] not in df.columns
        and _NORMALIZED_TOTAL_COLUMN in df.columns
    )
    if use_normalized_total:
        stage_cols = [_NORMALIZED_TOTAL_COLUMN]
    else:
        unknown = [stage for stage in stage_list if stage not in _ALL_STAGE_COLS]
        if unknown:
            raise ValueError(
                f"Stade(s) inconnu(s) : {unknown}. "
                f"Disponibles : {list(_ALL_STAGE_COLS)}."
            )
        stage_cols = [_ALL_STAGE_COLS[stage] for stage in stage_list]

    missing = [column for column in stage_cols if column not in df.columns]
    if missing:
        raise ValueError(
            "Sélection de stades NeoLabs refusée : colonne(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )
    out = df.copy()
    out[output_column] = (
        out[stage_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
    )
    return out, stage_list


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
    # Même langage de sélection que la jointure filet↔UVP.
    stage_list = _resolve_stage_list(stages)

    # Colonnes abundance correspondantes. Les exports NeoLabs normalisés
    # exposent parfois seulement le total officiel, alors que le format wide
    # fournit `ALL_STAGES_ABUND`. Les deux représentent le même agrégat par
    # défaut et doivent donc suivre exactement le même contrat.
    use_normalized_total = (
        stage_list == ["ALL_STAGES"]
        and _ALL_STAGE_COLS["ALL_STAGES"] not in df.columns
        and _NORMALIZED_TOTAL_COLUMN in df.columns
    )
    stage_cols: list[str] = []
    unknown = []
    if use_normalized_total:
        stage_cols.append(_NORMALIZED_TOTAL_COLUMN)
    else:
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
    # lat/lon optionnels : présents dans neolabs_sample, pas dans neolabs_abundance.
    lat_column = lat_column if lat_column in df.columns else None
    lon_column = lon_column if lon_column in df.columns else None

    # Filtre taxon
    taxon_col_vals = df[taxon_column].astype("string")
    mask = taxon_col_vals.str.casefold() == taxon_filter.casefold()
    sub = df.loc[mask].copy()
    if sub.empty:
        raise ValueError(
            f"Aucune ligne de copépodes (`{taxon_column} == '{taxon_filter}'`) "
            "dans la table."
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
