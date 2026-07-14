"""Sélection taxonomique stricte pour les tables EcoTaxa chargées."""

from __future__ import annotations

import re

import pandas as pd


_HIERARCHY_SEPARATOR = re.compile(r"\s*[>|;/]\s*")


def copepod_hierarchy_mask(
    df: pd.DataFrame,
    hierarchy_column: str = "object_annotation_hierarchy",
) -> pd.Series:
    """Retourne les lignes dont la hiérarchie contient le nœud Copepoda.

    La colonne de hiérarchie est obligatoire. Aucun fallback par catégorie,
    liste de descendants ou résolution réseau n'est appliqué.
    """
    if hierarchy_column not in df.columns:
        raise ValueError(
            "Sélection Copepoda refusée : la colonne "
            f"`{hierarchy_column}` est requise."
        )

    def belongs_to_copepoda(value: object) -> bool:
        if pd.isna(value):
            return False
        nodes = _HIERARCHY_SEPARATOR.split(str(value).strip())
        return any(node.casefold() == "copepoda" for node in nodes)

    return df[hierarchy_column].map(belongs_to_copepoda).astype(bool)
