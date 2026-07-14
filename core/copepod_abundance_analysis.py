"""Contrats déterministes pour les analyses d'abondance UVP."""

from __future__ import annotations

import numpy as np
import pandas as pd


_CANONICAL_VERSION = "copepod-sample-depth-v1"
_ABUNDANCE_COLUMNS = frozenset({"abundance_ind_L", "abundance_ind_m3"})


def prepare_environment_correlation(
    canonical: pd.DataFrame,
    environmental_columns: tuple[str, ...],
    *,
    abundance_column: str = "abundance_ind_L",
    presence_only: bool = False,
) -> pd.DataFrame:
    """Prépare les bins canoniques pour une analyse abondance–environnement."""
    if not environmental_columns:
        raise ValueError("Au moins une colonne d'environnement est requise.")
    if abundance_column not in _ABUNDANCE_COLUMNS:
        raise ValueError(f"Unité d'abondance non autorisée : `{abundance_column}`.")

    required = {
        "sample_id",
        "depth_bin",
        "canonical_method_version",
        abundance_column,
        *environmental_columns,
    }
    missing = sorted(required.difference(canonical.columns))
    if missing:
        raise ValueError(
            "Table canonique invalide : colonne(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )
    if not canonical["canonical_method_version"].eq(_CANONICAL_VERSION).all():
        raise ValueError(
            "Version canonique invalide : "
            f"`canonical_method_version` doit valoir `{_CANONICAL_VERSION}`."
        )

    selected_columns = [
        "sample_id",
        "depth_bin",
        abundance_column,
        *environmental_columns,
    ]
    work = canonical[selected_columns].copy()
    work[abundance_column] = pd.to_numeric(work[abundance_column], errors="coerce")
    abundance = work[abundance_column]
    if abundance.isna().any() or (~np.isfinite(abundance)).any() or (abundance < 0).any():
        raise ValueError(
            f"Valeur invalide dans `{abundance_column}` : "
            "les abondances doivent être numériques, finies et positives ou nulles."
        )
    for column in environmental_columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")

    n_initial = len(work)
    environment = work[list(environmental_columns)]
    missing_environment = environment.isna().any(axis=1) | (~np.isfinite(environment)).any(axis=1)
    work = work.loc[~missing_environment].copy()
    if presence_only:
        work = work.loc[work[abundance_column] > 0].copy()

    work.attrs = {
        "n_initial": n_initial,
        "n_retained": len(work),
        "n_zero_abundance": int(work[abundance_column].eq(0).sum()),
        "n_missing_environment": int(missing_environment.sum()),
        "presence_only": presence_only,
        "abundance_column": abundance_column,
    }
    return work
