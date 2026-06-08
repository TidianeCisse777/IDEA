"""Chargement multi-format de fichiers de données en DataFrame pandas."""
from pathlib import Path

import pandas as pd

_READERS = {
    "csv": lambda p: pd.read_csv(p),
    "tsv": lambda p: pd.read_csv(p, sep="\t"),
    "xlsx": lambda p: pd.read_excel(p),
    "xls": lambda p: pd.read_excel(p),
    "json": lambda p: pd.read_json(p, orient="records"),
    "parquet": lambda p: pd.read_parquet(p),
}


def load_file(path: str) -> tuple[pd.DataFrame, dict]:
    """Charge un fichier de données et retourne (DataFrame, métadonnées).

    Formats supportés : CSV, TSV, Excel (.xlsx/.xls), JSON (records), Parquet.

    Args:
        path: Chemin absolu ou relatif vers le fichier.

    Returns:
        Tuple (df, meta) où meta contient :
          - path     : chemin original
          - format   : extension détectée
          - n_rows   : nombre de lignes
          - n_cols   : nombre de colonnes
          - columns  : liste de {name, dtype}

    Raises:
        FileNotFoundError: si le fichier n'existe pas.
        ValueError: si l'extension n'est pas supportée.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    ext = p.suffix.lstrip(".").lower()
    if ext not in _READERS:
        supported = ", ".join(_READERS)
        raise ValueError(
            f"Format non supporté : '{ext}'. Formats acceptés : {supported}"
        )

    df = _READERS[ext](p)

    meta = {
        "path": str(p),
        "format": ext,
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "columns": [{"name": col, "dtype": str(df[col].dtype)} for col in df.columns],
    }
    return df, meta
