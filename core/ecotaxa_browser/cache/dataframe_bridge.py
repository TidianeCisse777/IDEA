"""Ephemeral SQLite workspace joining session DataFrames to EcoTaxa cache tables."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

import numpy as np
import pandas as pd


DATAFRAME_TABLE_PATTERN = re.compile(r"^df_[A-Za-z0-9_]+$")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_scalar(value: object) -> object:
    """Convert one object-dtype cell to a stable SQLite-compatible scalar."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        serializable = sorted(value) if isinstance(value, set) else value
        return json.dumps(serializable, ensure_ascii=False, default=str)
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, np.generic):
        return _sqlite_scalar(value.item())
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bytes, bool)):
        return value
    return str(value)


def sqlite_ready_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return a non-mutating, SQLite-compatible copy of a session DataFrame."""
    if dataframe.columns.empty:
        raise ValueError("un DataFrame sans colonne ne peut pas être monté en SQL")

    normalized = dataframe.copy()
    normalized.columns = [str(column) for column in normalized.columns]
    folded = [column.casefold() for column in normalized.columns]
    if len(folded) != len(set(folded)):
        raise ValueError(
            "les noms de colonnes du DataFrame ne sont pas uniques pour SQLite"
        )

    for column in normalized.columns:
        series = normalized[column]
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            normalized[column] = series.map(
                lambda value: None if pd.isna(value) else value.isoformat()
            )
        elif pd.api.types.is_datetime64_any_dtype(series.dtype):
            normalized[column] = series.map(
                lambda value: None if pd.isna(value) else pd.Timestamp(value).isoformat()
            )
        elif pd.api.types.is_timedelta64_dtype(series.dtype):
            normalized[column] = series.map(
                lambda value: None if pd.isna(value) else str(value)
            )
        elif isinstance(series.dtype, pd.CategoricalDtype):
            normalized[column] = series.astype(object).map(_sqlite_scalar)
        elif pd.api.types.is_extension_array_dtype(series.dtype):
            normalized[column] = series.astype(object).map(_sqlite_scalar)
        elif pd.api.types.is_object_dtype(series.dtype):
            normalized[column] = series.map(_sqlite_scalar)
    return normalized


def open_dataframe_cache_workspace(
    cache_path: str,
    dataframes: Mapping[str, pd.DataFrame],
) -> sqlite3.Connection:
    """Create an in-memory SQL workspace with read-only EcoTaxa and named frames.

    Cache tables are exposed with their usual unqualified names through TEMP
    views. Only explicitly supplied ``df_*`` tables are copied into memory.
    Closing the returned connection deletes every copied table.
    """
    resolved = Path(cache_path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"cache EcoTaxa introuvable : {resolved}")

    cache_uri = f"file:{quote(str(resolved), safe='/')}?mode=ro"
    connection = sqlite3.connect(":memory:", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        connection.execute("ATTACH DATABASE ? AS ecotaxa", (cache_uri,))
        cache_tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM ecotaxa.sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        ]
        for table_name in cache_tables:
            quoted = _quote_identifier(table_name)
            connection.execute(
                f"CREATE TEMP VIEW {quoted} AS SELECT * FROM ecotaxa.{quoted}"
            )

        for variable_name, dataframe in dataframes.items():
            if not DATAFRAME_TABLE_PATTERN.fullmatch(variable_name):
                raise ValueError(
                    f"référence DataFrame SQL invalide : {variable_name!r}"
                )
            sqlite_ready_dataframe(dataframe).to_sql(
                variable_name,
                connection,
                index=False,
                if_exists="fail",
            )

        # Setup writes only to the in-memory database. From this point onward,
        # even those tables are immutable while the user SELECT is evaluated.
        connection.execute("PRAGMA query_only=ON")
        return connection
    except Exception:
        connection.close()
        raise
