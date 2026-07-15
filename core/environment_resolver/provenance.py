"""Validation et sérialisation de la provenance des enrichissements."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from urllib.parse import urlparse

from core.environment_resolver.schema import ResolvedEnvironmentSchema


def build_enrichment_provenance(
    *,
    source: str,
    dataset_id: str,
    dataset_url: str,
    completed_at: datetime,
    parameters: dict,
    resolved_schema: ResolvedEnvironmentSchema | dict,
    variables: list[str],
    coverage: dict,
) -> dict:
    """Construit une provenance JSON après validation de tous les champs."""
    if not str(source).strip():
        raise ValueError("`source` est obligatoire.")
    if not str(dataset_id).strip():
        raise ValueError("`dataset_id` est obligatoire.")
    parsed_url = urlparse(str(dataset_url))
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("`dataset_url` doit être une URL HTTP(S) absolue.")
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("`completed_at` doit être une date UTC avec fuseau.")
    completed_utc = completed_at.astimezone(timezone.utc)

    required_coverage = {"total_rows", "matched_rows", "match_rate", "status_counts"}
    missing = required_coverage.difference(coverage)
    if missing:
        raise ValueError(
            "Couverture incomplète : " + ", ".join(sorted(missing)) + "."
        )
    total_rows = int(coverage["total_rows"])
    matched_rows = int(coverage["matched_rows"])
    status_counts = {str(k): int(v) for k, v in coverage["status_counts"].items()}
    if total_rows < 0 or matched_rows < 0 or matched_rows > total_rows:
        raise ValueError("Couverture incohérente : total_rows/matched_rows invalides.")
    if sum(status_counts.values()) != total_rows:
        raise ValueError("Couverture incohérente : la somme des statuts diffère du total.")
    expected_rate = matched_rows / total_rows if total_rows else 0.0
    if not math.isclose(float(coverage["match_rate"]), expected_rate, abs_tol=1e-12):
        raise ValueError("`match_rate` diffère de matched_rows / total_rows.")

    if isinstance(resolved_schema, ResolvedEnvironmentSchema):
        resolved_columns = resolved_schema.to_dict()
    elif isinstance(resolved_schema, dict):
        resolved_columns = {
            "columns": dict(resolved_schema.get("columns", {})),
            "resolution": dict(resolved_schema.get("resolution", {})),
        }
        if not resolved_columns["columns"]:
            raise ValueError("`resolved_schema.columns` est obligatoire.")
    else:
        raise ValueError("`resolved_schema` doit être un schéma structuré.")

    return {
        "source": str(source),
        "dataset_id": str(dataset_id),
        "dataset_url": str(dataset_url),
        "completed_at_utc": completed_utc.isoformat(),
        "parameters": dict(parameters),
        "resolved_columns": resolved_columns,
        "variables": list(variables),
        "coverage": {
            "total_rows": total_rows,
            "matched_rows": matched_rows,
            "match_rate": expected_rate,
            "status_counts": status_counts,
        },
    }
