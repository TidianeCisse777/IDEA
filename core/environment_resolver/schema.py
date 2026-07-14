"""Résolution déterministe des colonnes d'enrichissement environnemental."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.environment_resolver.column_detection import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    detect_column,
)


@dataclass(frozen=True)
class ResolvedEnvironmentSchema:
    latitude_column: str
    longitude_column: str
    time_column: str | None
    depth_column: str | None
    resolution: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "columns": {
                "latitude": self.latitude_column,
                "longitude": self.longitude_column,
                "time": self.time_column,
                "depth": self.depth_column,
            },
            "resolution": dict(self.resolution),
        }


def _resolve_role(
    dataframe: pd.DataFrame,
    *,
    role: str,
    override: str | None,
    candidates: tuple[str, ...],
    required: bool,
) -> tuple[str | None, str]:
    if override is not None:
        resolved = detect_column(dataframe.columns, (override,))
        if resolved is None:
            available = ", ".join(map(str, dataframe.columns))
            raise ValueError(
                f"Override {role} `{override}` absent. Colonnes disponibles : {available}."
            )
        return str(resolved), "explicit"

    resolved = detect_column(dataframe.columns, candidates)
    if resolved is None and required:
        raise ValueError(
            f"Colonne requise `{role}` introuvable. Alias essayés : "
            + ", ".join(candidates)
            + "."
        )
    return (str(resolved) if resolved is not None else None), "detected"


def resolve_environment_schema(
    dataframe: pd.DataFrame,
    *,
    latitude_column: str | None = None,
    longitude_column: str | None = None,
    time_column: str | None = None,
    depth_column: str | None = None,
    require_time: bool = True,
    require_depth: bool = False,
) -> ResolvedEnvironmentSchema:
    """Résout une fois les colonnes utilisées par un enrichissement."""
    latitude, lat_mode = _resolve_role(
        dataframe,
        role="latitude",
        override=latitude_column,
        candidates=DEFAULT_LAT_CANDIDATES,
        required=True,
    )
    longitude, lon_mode = _resolve_role(
        dataframe,
        role="longitude",
        override=longitude_column,
        candidates=DEFAULT_LON_CANDIDATES,
        required=True,
    )
    time, time_mode = _resolve_role(
        dataframe,
        role="time",
        override=time_column,
        candidates=DEFAULT_TIME_CANDIDATES,
        required=require_time,
    )
    depth, depth_mode = _resolve_role(
        dataframe,
        role="depth",
        override=depth_column,
        candidates=DEFAULT_DEPTH_CANDIDATES,
        required=require_depth,
    )
    return ResolvedEnvironmentSchema(
        latitude_column=latitude,
        longitude_column=longitude,
        time_column=time,
        depth_column=depth,
        resolution={
            "latitude": lat_mode,
            "longitude": lon_mode,
            "time": time_mode,
            "depth": depth_mode,
        },
    )
