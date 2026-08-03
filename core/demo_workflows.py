"""Préparations déterministes et traçables des parcours de démonstration."""

from __future__ import annotations

import numpy as np
import pandas as pd


NEOLABS_DEMO_METHOD_VERSION = "neolabs-demo-preparation-v1"
_NEOLABS_DENSITY_COLUMN = "ALL_STAGES_ABUND (ind./m3 depth vol.)"
NEOLABS_COLUMN_DESCRIPTIONS = {
    "SAMPLE_ID": "Identifiant du sample dans la table d'abondance.",
    "ANALYSIS_ID": "Identifiant de l'analyse dans la table d'abondance.",
    "sample_id": "Identifiant du sample dans la table sample ou la table consolidée.",
    "analysis_id": "Identifiant de l'analyse dans la table sample ou la table consolidée.",
    "TAXON_ID": "Taxon observé dans la ligne d'abondance.",
    "CLASS": "Classe taxonomique utilisée notamment pour sélectionner Copepoda.",
    _NEOLABS_DENSITY_COLUMN: "Abondance de tous les stades par mètre cube filtré en profondeur.",
    "source_abundance_row": "Numéro de la ligne d'origine dans le fichier d'abondance.",
    "source_sample_row": "Numéro de la ligne d'origine dans le fichier sample.",
    "canonical_sample_id": "Identifiant sample commun après la jointure externe.",
    "canonical_analysis_id": "Identifiant analyse commun après la jointure externe.",
    "join_status": "Statut de jointure : matched, abundance_without_sample ou sample_without_abundance.",
    "copepod_density_ind_m3": "Somme calculée des abondances de copépodes en individus par mètre cube.",
    "density_status": "calculated, no_value parmi les couples appariés, ou not_applicable pour les lignes hors dénominateur.",
    "n_abundance_source_rows": "Nombre de lignes d'abondance sources représentées.",
    "n_sample_source_rows": "Nombre de lignes sample sources représentées.",
    "n_copepod_taxon_rows": "Nombre de lignes taxonomiques de classe Copepoda représentées.",
    "sampling_year": "Année d'échantillonnage.",
    "deployment_datetime_start": "Date et heure de début du déploiement.",
    "deployment_datetime_end": "Date et heure de fin du déploiement.",
    "cast_number": "Numéro de cast indiqué dans le fichier sample NeoLabs.",
    "sampling_platform": "Plateforme utilisée pour l'échantillonnage.",
    "station_name": "Nom ou identifiant de la station.",
    "min_sample_depth": "Profondeur minimale échantillonnée, en mètres.",
    "max_sample_depth": "Profondeur maximale échantillonnée, en mètres.",
    "latitude": "Latitude décimale de l'échantillonnage.",
    "longitude": "Longitude décimale de l'échantillonnage.",
    "n_sample_analysis_rows": "Nombre de couples sample-analyse dans ce groupe de couverture.",
}


def prepare_neolabs_tables(
    abundance: pd.DataFrame,
    samples: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Relie les deux grains NeoLabs sans perdre de ligne source.

    La jointure est externe sur ``sample + analysis``. Une table condensée garde
    ensuite une ligne par couple sample-analyse et ne calcule la densité que si
    toutes les abondances de copépodes requises sont numériques.
    """
    abundance_required = {
        "SAMPLE_ID",
        "ANALYSIS_ID",
        "TAXON_ID",
        "CLASS",
        _NEOLABS_DENSITY_COLUMN,
    }
    sample_required = {
        "sample_id",
        "analysis_id",
        "sampling_year",
        "station_name",
        "min_sample_depth",
        "max_sample_depth",
        "latitude",
        "longitude",
    }
    missing_abundance = sorted(abundance_required.difference(abundance.columns))
    missing_samples = sorted(sample_required.difference(samples.columns))
    if missing_abundance or missing_samples:
        details = []
        if missing_abundance:
            details.append("abondance: " + ", ".join(missing_abundance))
        if missing_samples:
            details.append("sample: " + ", ".join(missing_samples))
        raise ValueError("Préparation NeoLabs refusée — colonnes absentes (" + "; ".join(details) + ").")

    left = abundance.copy().reset_index(drop=True)
    right = samples.copy().reset_index(drop=True)
    left["source_abundance_row"] = np.arange(len(left), dtype=int)
    right["source_sample_row"] = np.arange(len(right), dtype=int)
    if right.duplicated(["sample_id", "analysis_id"]).any():
        raise ValueError(
            "Préparation NeoLabs refusée : plusieurs lignes sample portent la "
            "même clé sample_id + analysis_id."
        )

    working = left.merge(
        right,
        how="outer",
        left_on=["SAMPLE_ID", "ANALYSIS_ID"],
        right_on=["sample_id", "analysis_id"],
        validate="many_to_one",
        indicator=True,
        sort=False,
    )
    working["join_status"] = working["_merge"].map(
        {
            "both": "matched",
            "left_only": "abundance_without_sample",
            "right_only": "sample_without_abundance",
        }
    ).astype("string")
    working = working.drop(columns="_merge")
    working["canonical_sample_id"] = working["SAMPLE_ID"].combine_first(
        working["sample_id"]
    )
    working["canonical_analysis_id"] = working["ANALYSIS_ID"].combine_first(
        working["analysis_id"]
    )

    summary_rows: list[dict[str, object]] = []
    keys = ["canonical_sample_id", "canonical_analysis_id"]
    for (sample_id, analysis_id), group in working.groupby(
        keys, dropna=False, sort=False
    ):
        statuses = set(group["join_status"].dropna().astype(str))
        if "matched" in statuses:
            join_status = "matched"
        elif "abundance_without_sample" in statuses:
            join_status = "abundance_without_sample"
        else:
            join_status = "sample_without_abundance"

        copepods = group.loc[
            group["source_abundance_row"].notna()
            & group["CLASS"].astype("string").str.casefold().eq("copepoda")
        ].drop_duplicates("source_abundance_row")
        values = pd.to_numeric(copepods[_NEOLABS_DENSITY_COLUMN], errors="coerce")
        calculable = bool(join_status == "matched" and not values.empty and values.notna().all())
        density = float(values.sum()) if calculable else np.nan
        if join_status != "matched":
            density_status = "not_applicable"
        elif calculable:
            density_status = "calculated"
        else:
            density_status = "no_value"

        row: dict[str, object] = {
            "sample_id": sample_id,
            "analysis_id": analysis_id,
            "join_status": join_status,
            "copepod_density_ind_m3": density,
            "density_status": density_status,
            "n_abundance_source_rows": int(group["source_abundance_row"].nunique()),
            "n_sample_source_rows": int(group["source_sample_row"].nunique()),
            "n_copepod_taxon_rows": int(len(copepods)),
            "method_version": NEOLABS_DEMO_METHOD_VERSION,
        }
        for column in right.columns:
            if column in {"sample_id", "analysis_id", "source_sample_row"}:
                continue
            if column in group.columns:
                present = group[column].dropna()
                row[column] = present.iloc[0] if not present.empty else pd.NA
        summary_rows.append(row)

    sample_summary = pd.DataFrame(summary_rows)
    coverage_keys = [
        "sampling_year",
        "station_name",
        "min_sample_depth",
        "max_sample_depth",
        "join_status",
        "density_status",
    ]
    for column in coverage_keys:
        if column not in sample_summary.columns:
            sample_summary[column] = pd.NA
    coverage = (
        sample_summary.groupby(coverage_keys, dropna=False, sort=True)
        .size()
        .rename("n_sample_analysis_rows")
        .reset_index()
    )
    graph = sample_summary.loc[
        sample_summary["density_status"].eq("calculated")
        & pd.to_numeric(sample_summary["latitude"], errors="coerce").notna()
        & pd.to_numeric(sample_summary["longitude"], errors="coerce").notna()
    ].copy()

    return {
        "working": working,
        "samples": sample_summary,
        "coverage": coverage,
        "graph": graph,
    }
