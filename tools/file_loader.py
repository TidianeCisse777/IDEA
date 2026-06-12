"""Chargement multi-format de fichiers de données en DataFrame pandas."""
from pathlib import Path

import pandas as pd

_TEXT_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]


def _read_text(p: Path, sep: str = ",") -> tuple[pd.DataFrame, str]:
    """Essaie plusieurs encodages et retourne (df, encodage_utilisé)."""
    last_exc: Exception | None = None
    for enc in _TEXT_ENCODINGS:
        try:
            df = pd.read_csv(p, sep=sep, encoding=enc)
            return df, enc
        except (UnicodeDecodeError, UnicodeError):
            last_exc = last_exc or Exception(enc)
            continue
    raise ValueError(
        f"Impossible de lire '{p.name}' : aucun encodage parmi "
        f"{_TEXT_ENCODINGS} n'a fonctionné."
    ) from last_exc


def load_file(path: str) -> tuple[pd.DataFrame, dict]:
    """Charge un fichier de données et retourne (DataFrame, métadonnées).

    Formats supportés : CSV, TSV, Excel (.xlsx/.xls), JSON (records), Parquet.
    Pour CSV/TSV, essaie automatiquement utf-8, utf-8-sig, latin-1, cp1252.

    Args:
        path: Chemin absolu ou relatif vers le fichier.

    Returns:
        Tuple (df, meta) où meta contient :
          - path     : chemin original
          - format   : extension détectée
          - encoding : encodage utilisé (CSV/TSV seulement)
          - n_rows   : nombre de lignes
          - n_cols   : nombre de colonnes
          - columns  : liste de {name, dtype}

    Raises:
        FileNotFoundError: si le fichier n'existe pas.
        ValueError: si l'extension n'est pas supportée ou aucun encodage ne fonctionne.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")

    ext = p.suffix.lstrip(".").lower()
    encoding_used: str | None = None

    if ext == "csv":
        df, encoding_used = _read_text(p, sep=",")
    elif ext == "tsv":
        df, encoding_used = _read_text(p, sep="\t")
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(p)
    elif ext == "json":
        df = pd.read_json(p, orient="records")
    elif ext == "parquet":
        df = pd.read_parquet(p)
    else:
        supported = "csv, tsv, xlsx, xls, json, parquet"
        raise ValueError(f"Format non supporté : '{ext}'. Formats acceptés : {supported}")

    meta: dict = {
        "path": str(p),
        "format": ext,
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "columns": [{"name": col, "dtype": str(df[col].dtype)} for col in df.columns],
    }
    if encoding_used:
        meta["encoding"] = encoding_used
    return df, meta
