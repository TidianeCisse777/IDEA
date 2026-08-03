"""Petit cache exact pour les résultats complets des sources distantes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from core.erddap_cache import cache_get, cache_set


_CACHE_SCHEMA = "scientific-result-v1"


@dataclass(frozen=True)
class CachedResult:
    dataframe: pd.DataFrame
    cached_at: str
    provenance: dict[str, Any]
    n_rows: int


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def dataframe_fingerprint(dataframe: pd.DataFrame) -> str:
    """Empreinte sensible aux valeurs, à l'ordre, au schéma et à l'index."""
    digest = hashlib.sha256()
    digest.update(_canonical_json([str(column) for column in dataframe.columns]).encode())
    digest.update(_canonical_json([str(dtype) for dtype in dataframe.dtypes]).encode())
    try:
        row_hashes = pd.util.hash_pandas_object(dataframe, index=True).to_numpy()
        digest.update(row_hashes.tobytes())
    except (TypeError, ValueError):
        digest.update(dataframe.to_json(orient="split", date_format="iso").encode())
    return digest.hexdigest()


def build_result_cache_key(
    source_dataframe: pd.DataFrame,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Construit la clé exacte d'une requête scientifique sur une table."""
    return {
        "schema": _CACHE_SCHEMA,
        "source_fingerprint": dataframe_fingerprint(source_dataframe),
        "source_rows": int(len(source_dataframe)),
        "source_columns": [str(column) for column in source_dataframe.columns],
        "parameters": json.loads(_canonical_json(parameters)),
    }


def load_result(namespace: str, key: dict[str, Any]) -> CachedResult | None:
    payload = cache_get(f"scientific_result:{namespace}", key)
    if not isinstance(payload, dict) or payload.get("schema") != _CACHE_SCHEMA:
        return None
    dataframe = payload.get("dataframe")
    if not isinstance(dataframe, pd.DataFrame):
        return None
    if int(payload.get("n_rows", -1)) != len(dataframe):
        return None
    return CachedResult(
        dataframe=dataframe.copy(),
        cached_at=str(payload["cached_at"]),
        provenance=dict(payload.get("provenance") or {}),
        n_rows=int(len(dataframe)),
    )


def save_result(
    namespace: str,
    key: dict[str, Any],
    dataframe: pd.DataFrame,
    *,
    provenance: dict[str, Any],
) -> CachedResult:
    cached_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": _CACHE_SCHEMA,
        "dataframe": dataframe.copy(),
        "cached_at": cached_at,
        "provenance": dict(provenance),
        "n_rows": int(len(dataframe)),
    }
    cache_set(f"scientific_result:{namespace}", key, payload)
    return CachedResult(
        dataframe=dataframe.copy(),
        cached_at=cached_at,
        provenance=dict(provenance),
        n_rows=int(len(dataframe)),
    )
