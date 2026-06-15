"""EcoTaxa column distribution service.

Returns either numeric stats (``min``, ``max``, ``mean``, ``median``, ``p25``,
``p75``, ``n``) or a categorical breakdown (``top_values`` + ``total_distinct``),
depending on the column type detected by ``get_project_schema``.

Primary path uses ``GET /project_set/column_stats`` for numeric columns —
served pre-aggregated by EcoTaxa, validated objects only. When the endpoint
returns no usable payload, the function falls back to reading the first
sample window of objects via ``POST /object_set/{id}/query``. The chosen
path is reported in the ``source`` field of the response.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Literal

from core.ecotaxa_browser.errors import EcoTaxaBrowserError
from core.ecotaxa_browser.schema import get_project_schema
from tools.ecotaxa_client import EcotaxaClient

_NORMALIZE_PATTERN = re.compile(r"[\s_\-]+")
_DEFAULT_SAMPLE_SIZE = 1000
_TOP_N_DEFAULT = 20

Level = Literal["sample", "acquisition", "object"]


def get_column_distribution(
    project_id: int,
    column_name: str,
    level: Level | None = None,
    *,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    top_n: int = _TOP_N_DEFAULT,
) -> dict:
    """Inspect the value distribution of a single column on a project."""
    schema = get_project_schema(project_id, verbose=True)
    norm = _normalize(column_name)
    matches = schema["labels_index"].get(norm, [])
    if level is not None:
        matches = [m for m in matches if m["level"] == level]

    if not matches:
        raise EcoTaxaBrowserError(
            "COLUMN_NOT_FOUND",
            f"Column '{column_name}' is not declared on project {project_id}.",
        )
    if len(matches) > 1:
        raise EcoTaxaBrowserError(
            "AMBIGUOUS_COLUMN",
            f"Column '{column_name}' exists at multiple levels; specify level=.",
            candidates=[
                {"level": m["level"], "kind": m["kind"], "type": m["type"]}
                for m in matches
            ],
        )

    match = matches[0]
    raw = _lookup_raw(schema, level=match["level"], kind=match["kind"], norm=norm)

    client = EcotaxaClient()
    client.login()

    if match["type"] == "number":
        stats = _try_column_stats(client, project_id, raw["label"])
        if stats is not None:
            return _envelope(
                match=match,
                raw=raw,
                source="ecotaxa_column_stats",
                stats=stats,
            )
        # Fallback: read first window of objects.
        values = _first_window_values(client, project_id, raw, sample_size)
        return _envelope(
            match=match,
            raw=raw,
            source="first_window_sample",
            stats=_numeric_stats(values),
        )

    # Categorical / text path.
    values = _first_window_values(client, project_id, raw, sample_size)
    return _envelope(
        match=match,
        raw=raw,
        source="first_window_sample",
        stats=_categorical_stats(values, top_n=top_n),
    )


def _normalize(label: str) -> str:
    return _NORMALIZE_PATTERN.sub("", label).lower()


def _lookup_raw(schema: dict, *, level: str, kind: str, norm: str) -> dict:
    """Find the raw label/name/code for a normalized column."""
    entries = schema["levels"][level][kind]
    for entry in entries:
        if kind == "free":
            if _normalize(entry["label"]) == norm:
                return {
                    "label": entry["label"],
                    "code": entry.get("code"),
                    "kind": "free",
                }
        else:  # fixed
            if _normalize(entry["name"]) == norm:
                return {
                    "label": entry["name"],
                    "code": None,
                    "kind": "fixed",
                }
    raise EcoTaxaBrowserError(
        "COLUMN_NOT_FOUND",
        f"Internal schema lookup failed for normalized column '{norm}'.",
    )


def _try_column_stats(client, project_id: int, label: str) -> dict | None:
    try:
        payload = client.column_stats(project_ids=[project_id], names=[label])
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    relevant_keys = {"min", "max", "mean", "median", "p25", "p75", "n"}
    if not relevant_keys & set(payload):
        return None
    return {k: payload.get(k) for k in relevant_keys if k in payload}


def _first_window_values(client, project_id: int, raw: dict, sample_size: int) -> list:
    field = _resolve_field_path(raw)
    payload = client.query_objects(
        project_id=project_id,
        filters={},
        fields=field,
        window_start=0,
        window_size=sample_size,
    )
    rows = payload.get("details") or []
    return [row[0] for row in rows if row and row[0] is not None]


def _resolve_field_path(raw: dict) -> str:
    # EcoTaxa expects "obj.<code>" or "obj.<fixed_name>" syntax. Sample- and
    # acquisition-level fields use "sam." / "acq." prefixes respectively, but
    # the V1 fallback is object-only — broaden when the use case shows up.
    if raw["kind"] == "free" and raw.get("code"):
        return f"obj.{raw['code']}"
    return f"obj.{raw['label']}"


def _numeric_stats(values: list) -> dict:
    floats = [float(v) for v in values if v is not None]
    if not floats:
        return {"n": 0}
    sorted_values = sorted(floats)
    quantile = lambda q: sorted_values[max(0, min(len(sorted_values) - 1, int(q * (len(sorted_values) - 1))))]
    return {
        "min": min(floats),
        "max": max(floats),
        "mean": statistics.mean(floats),
        "median": statistics.median(floats),
        "p25": quantile(0.25),
        "p75": quantile(0.75),
        "n": len(floats),
    }


def _categorical_stats(values: list, *, top_n: int) -> dict:
    counter = Counter(str(v) for v in values)
    top = counter.most_common(top_n)
    return {
        "sample_size": len(values),
        "total_distinct": len(counter),
        "top_values": [{"value": value, "count": count} for value, count in top],
    }


def _envelope(*, match: dict, raw: dict, source: str, stats: dict) -> dict:
    return {
        "level": match["level"],
        "kind": match["kind"],
        "type": match["type"],
        "column": raw["label"],
        "source": source,
        "stats": stats,
    }
