"""Contrat déterministe : densité de copépodes d'une table NeoLabs taxonomy.

Équivalent NeoLab de `core.copepod_sample_depth` côté UVP : il impose la bonne
méthode (filtre Copepoda, somme par sample, moyenne par station) et refuse les
entrées incomplètes, au lieu de laisser un `run_pandas` libre faire une moyenne
tous-taxons sur les lignes brutes.
"""

from __future__ import annotations

import pandas as pd


NEOLABS_COPEPOD_METHOD_VERSION = "neolabs-copepod-density-v1"
# NeoLabs exports use per-stage columns; ALL_STAGES_ABUND is the sum across
# all copepodite and naupliar stages for a given taxon × sample row.
_DEPTH_ABUNDANCE = "ALL_STAGES_ABUND (ind./m3 depth vol.)"
_DEPTH_ABUNDANCE_LEGACY = "Total abundance (ind./m3 depth vol)"


def neolabs_copepod_density(
    df: pd.DataFrame,
    *,
    abundance_column: str | None = None,
    class_column: str = "CLASS",
    copepod_class: str = "Copepoda",
    sample_column: str = "SAMPLE_ID",
    station_column: str = "STATION_NAME",
    lat_column: str = "latitude",
    lon_column: str = "longitude",
) -> pd.DataFrame:
    """Densité de copépodes par station, méthode imposée et traçable.

    1. Filtre `CLASS == 'Copepoda'` (obligatoire — pas de moyenne tous-taxons).
    2. Densité par sample = somme de l'abondance sur les taxons/stades copépodes.
    3. Par station = moyenne des samples.

    Renvoie une ligne par station : `STATION_NAME`, `latitude`, `longitude`,
    `copepod_density_ind_m3`, `n_samples`, `method_version`. Lève `ValueError`
    sur entrée incomplète plutôt que de produire un chiffre faux.
    """
    # Auto-detect abundance column: prefer ALL_STAGES, fall back to legacy name.
    if abundance_column is None:
        if _DEPTH_ABUNDANCE in df.columns:
            abundance_column = _DEPTH_ABUNDANCE
        elif _DEPTH_ABUNDANCE_LEGACY in df.columns:
            abundance_column = _DEPTH_ABUNDANCE_LEGACY
        else:
            abundance_column = _DEPTH_ABUNDANCE  # will raise a clear error below

    required = {class_column, sample_column, station_column, abundance_column}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(
            "Densité copépode NeoLabs refusée : colonne(s) requise(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )

    is_copepod = (
        df[class_column].astype("string").str.casefold() == copepod_class.casefold()
    )
    cop = df.loc[is_copepod].copy()
    if cop.empty:
        raise ValueError(
            f"Aucune ligne `{class_column} == '{copepod_class}'` : "
            "la table ne contient pas de copépodes identifiés."
        )

    cop[abundance_column] = pd.to_numeric(cop[abundance_column], errors="coerce")
    if cop[abundance_column].notna().sum() == 0:
        raise ValueError(
            f"Colonne `{abundance_column}` entièrement non numérique — "
            "abondance inexploitable."
        )
    # Les NaN résiduels (taxons copépodes sans abondance mesurée) sont ignorés par
    # la somme, comme il se doit — ils ne contribuent pas à la densité.

    sample_agg: dict[str, str] = {abundance_column: "sum"}
    for column in (station_column, lat_column, lon_column):
        if column in cop.columns:
            sample_agg[column] = "first"
    per_sample = cop.groupby(sample_column, as_index=False).agg(sample_agg)
    per_sample = per_sample.rename(
        columns={abundance_column: "copepod_density_ind_m3"}
    )

    station_agg: dict[str, str] = {"copepod_density_ind_m3": "mean", sample_column: "size"}
    for column in (lat_column, lon_column):
        if column in per_sample.columns:
            station_agg[column] = "mean"
    per_station = per_sample.groupby(station_column, as_index=False).agg(station_agg)
    per_station = per_station.rename(columns={sample_column: "n_samples"})
    per_station["method_version"] = NEOLABS_COPEPOD_METHOD_VERSION
    return per_station
