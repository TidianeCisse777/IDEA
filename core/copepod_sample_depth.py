"""Construction déterministe des bins UVP EcoTaxa–EcoPart."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.copepod_taxonomy import copepod_hierarchy_mask


CANONICAL_METHOD_VERSION = "copepod-sample-depth-v1"
_KEY_COLUMNS = ("sample_id", "depth_bin")


def _build_taxon_mask(df: pd.DataFrame, taxon_filter: str | None) -> pd.Series:
    """Masque booléen sur object_annotation_hierarchy.

    - ``None``  → copépodes (comportement historique, ``copepod_hierarchy_mask``).
    - ``"*"``   → tous les organismes sans filtre taxonomique.
    - Toute autre chaîne → recherche insensible à la casse dans la hiérarchie
      (ex. ``"Calanus"``, ``"Calanidae"``, ``"Copepoda"``).
    """
    if taxon_filter is None:
        return copepod_hierarchy_mask(df)
    if taxon_filter == "*":
        return pd.Series(True, index=df.index)
    hier = df["object_annotation_hierarchy"].astype("string")
    return hier.str.contains(taxon_filter, case=False, na=False, regex=False)


def build_canonical_sample_depth(
    df: pd.DataFrame,
    *,
    taxon_filter: str | None = None,
    volume_column: str = "ecopart_Sampled volume [L]",
    stable_columns: tuple[str, ...] | None = None,
    volume_rtol: float = 1e-6,
    volume_atol: float = 1e-9,
) -> pd.DataFrame:
    """Agrège une table objet en une ligne canonique par sample et bin 5 m.

    Quand ``export_project_id`` est présent, il fait partie de la clé canonique :
    deux projets portant le même identifiant de sample restent donc séparés.

    ``taxon_filter`` contrôle quels organismes sont comptés comme cible :

    - ``None`` (défaut) → copépodes uniquement (``copepod_hierarchy_mask``).
    - ``"Calanus"`` → tout objet dont la hiérarchie contient « Calanus ».
    - ``"Copepoda"`` → tout copépode (plus large que le masque taxonomique strict).
    - ``"*"`` → tous les organismes (densité totale toutes catégories).

    Si ``depth_bin`` est absent mais ``object_depth_min`` est présent, dérive
    automatiquement les bins EcoPart centrés à 2.5, 7.5, 12.5 … m
    (floor(depth/5)*5 + 2.5), compatibles avec la colonne ``Depth [m]`` EcoPart.
    """
    if "depth_bin" not in df.columns and "object_depth_min" in df.columns:
        df = df.copy()
        df["depth_bin"] = (df["object_depth_min"] // 5) * 5 + 2.5

    required = (*_KEY_COLUMNS, "object_annotation_hierarchy", volume_column)
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            "Table sample–profondeur refusée : colonne(s) requise(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing)
            + "."
        )
    missing_stable = [column for column in stable_columns or () if column not in df.columns]
    if missing_stable:
        raise ValueError(
            "Colonne(s) stable(s) absente(s) : "
            + ", ".join(f"`{column}`" for column in missing_stable)
            + "."
        )

    work = df.copy()
    key_columns = (
        ("export_project_id", *_KEY_COLUMNS)
        if "export_project_id" in work.columns
        else _KEY_COLUMNS
    )
    work["_is_target"] = _build_taxon_mask(work, taxon_filter).astype("int64")
    work["depth_bin"] = pd.to_numeric(work["depth_bin"], errors="coerce")
    work[volume_column] = pd.to_numeric(work[volume_column], errors="coerce")
    invalid_keys = {
        "sample_id": work["sample_id"].isna() | work["sample_id"].astype("string").str.strip().eq(""),
        "depth_bin": work["depth_bin"].isna() | ~np.isfinite(work["depth_bin"]),
    }
    if "export_project_id" in work.columns:
        invalid_keys["export_project_id"] = (
            work["export_project_id"].isna()
            | work["export_project_id"].astype("string").str.strip().eq("")
        )
    for column, mask in invalid_keys.items():
        if mask.any():
            bad_rows = ", ".join(str(index) for index in work.index[mask][:5])
            raise ValueError(
                f"Clé sample–profondeur invalide : `{column}` absent ou invalide "
                f"à la/aux ligne(s) {bad_rows}."
            )

    rows: list[dict[str, object]] = []
    for key, group in work.groupby(list(key_columns), sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        key_map = dict(zip(key_columns, key_values, strict=True))
        volumes = group[volume_column].to_numpy(dtype=float)
        key_text = ", ".join(
            f"{column}={value}" for column, value in key_map.items()
        )
        if not np.all(np.isfinite(volumes) & (volumes > 0)):
            raise ValueError(f"volume invalide pour la clé {key_text}.")
        canonical_volume = float(volumes.mean())
        if not np.all(
            np.isclose(volumes, canonical_volume, rtol=volume_rtol, atol=volume_atol)
        ):
            raise ValueError(f"Volumes incompatibles pour la clé {key_text}.")

        row: dict[str, object] = {
            **key_map,
            "target_count": int(group["_is_target"].sum()),
            "sampled_volume_L": canonical_volume,
        }
        for column in stable_columns or ():
            values = group[column].dropna().unique()
            if len(values) > 1:
                raise ValueError(
                    f"Valeurs contradictoires pour `{column}` à la clé {key_text}."
                )
            row[column] = values[0] if len(values) == 1 else pd.NA
        rows.append(row)

    canonical = pd.DataFrame(rows)
    canonical["abundance_ind_L"] = (
        canonical["target_count"] / canonical["sampled_volume_L"]
    )
    canonical["abundance_ind_m3"] = canonical["abundance_ind_L"] * 1000.0
    canonical["taxon_filter"] = taxon_filter if taxon_filter is not None else "Copepoda(mask)"
    canonical["canonical_method_version"] = CANONICAL_METHOD_VERSION
    return canonical
