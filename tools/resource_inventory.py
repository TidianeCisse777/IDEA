"""Machine-readable inventory of resources available to an exploration run."""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import Any, Iterable

import pandas as pd

from agents.exploration_state import (
    ExplorationCapability,
    ResourceColumnProfile,
    ResourceJoinCandidate,
    ResourceRecord,
)
from tools.session_store import SessionStore

_MAX_COLUMNS_PER_RESOURCE = 500
_MAX_PROFILED_COLUMNS = 80
_MAX_PROFILE_ROWS = 5_000
_MAX_JOIN_CANDIDATES = 8
_MAX_PROFILE_CACHE_ENTRIES = 256
_MAX_VALUE_CACHE_ENTRIES = 512
_SCOPE_VALUE_LIMITS = {
    "project_ids": 100,
    "profile_ids": 500,
    "sample_ids": 50,
    "stations": 200,
}
_IDENTIFIER_TOKENS = (
    "id",
    "sample",
    "project",
    "profile",
    "station",
    "cast",
    "taxon",
    "date",
    "time",
    "latitude",
    "longitude",
    "depth",
)
_SCIENTIFIC_TEXT_TOKENS = (
    "taxon",
    "species",
    "genus",
    "family",
    "stage",
    "instrument",
    "category",
)

_PROFILE_CACHE: OrderedDict[
    str,
    tuple[
        tuple[Any, ...],
        tuple[ResourceColumnProfile, ...],
        tuple[str, ...],
    ],
] = OrderedDict()
_VALUE_CACHE: OrderedDict[tuple[Any, ...], frozenset[Any]] = OrderedDict()


def _resource_id(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"resource-{digest}"


def _clean_json_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if item is None or isinstance(item, (str, int, float, bool)):
            clean[str(key)] = item
        elif isinstance(item, (list, tuple)):
            clean[str(key)] = [
                child for child in item
                if child is None or isinstance(child, (str, int, float, bool))
            ]
    return clean


def _grain(
    meta: dict[str, Any],
    profiles: tuple[ResourceColumnProfile, ...] = (),
) -> str | None:
    for key in ("grain", "row_grain", "unit_of_analysis", "entity"):
        value = meta.get(key)
        if value:
            return str(value)[:160]
    declared = [profile.name for profile in profiles if profile.key_likelihood == "declared"]
    if declared:
        return f"clé déclarée: {' + '.join(declared[:3])}"[:160]
    sampled = [
        profile.name
        for profile in profiles
        if profile.key_likelihood == "sampled_unique"
    ]
    if len(sampled) == 1:
        return f"probablement une ligne par {sampled[0]} (échantillonné)"[:160]
    return None


def _relations(meta: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in (
        "alias_of",
        "parent_variable",
        "parent_variables",
        "source_variable",
        "input_dataframes",
        "raw_export_variables",
        "net_variable_name",
        "audit_variable",
        "uvp_enriched_variable",
        "selection_name",
    ):
        value = meta.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(f"{key}:{item}" for item in value if item)
        elif value:
            values.append(f"{key}:{value}")
    return tuple(dict.fromkeys(values))


def _identifiers(columns: Iterable[object]) -> tuple[str, ...]:
    found: list[str] = []
    for raw in columns:
        name = str(raw)
        lowered = name.casefold()
        if any(token in lowered for token in _IDENTIFIER_TOKENS):
            found.append(name)
    return tuple(found[:40])


def _declared_keys(meta: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("primary_key", "primary_keys", "key_column", "key_columns", "join_keys"):
        raw = meta.get(key)
        if isinstance(raw, str):
            values.extend(part.strip() for part in raw.split(",") if part.strip())
        elif isinstance(raw, (list, tuple, set)):
            values.extend(str(part) for part in raw if part)
    return tuple(dict.fromkeys(values))


def _semantic_role(name: str, series: pd.Series) -> str:
    lowered = name.casefold().replace("-", "_").replace(" ", "_")
    if lowered in {"lat", "latitude", "sample_latitude", "decimal_latitude"}:
        return "latitude"
    if lowered in {"lon", "lng", "longitude", "sample_longitude", "decimal_longitude"}:
        return "longitude"
    if "depth" in lowered or "profondeur" in lowered:
        return "depth"
    if any(token in lowered for token in ("date", "time", "timestamp", "datetime", "heure")):
        return "time"
    if lowered == "id" or lowered.endswith("_id") or lowered.startswith("id_"):
        return "identifier"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "time"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "measure"
    if isinstance(series.dtype, pd.CategoricalDtype) or pd.api.types.is_bool_dtype(series.dtype):
        return "category"
    if pd.api.types.is_string_dtype(series.dtype) or pd.api.types.is_object_dtype(series.dtype):
        return "text"
    return "unknown"


def _column_profiles(
    dataframe: pd.DataFrame,
    meta: dict[str, Any],
) -> tuple[tuple[ResourceColumnProfile, ...], tuple[str, ...]]:
    raw_by_name = {str(column): column for column in dataframe.columns}
    columns = list(raw_by_name)
    identifiers = list(_identifiers(columns))
    declared_names = {name.casefold() for name in _declared_keys(meta)}
    declared_columns = [name for name in columns if name.casefold() in declared_names]
    scientific_text: list[str] = []
    measures: list[str] = []
    categories: list[str] = []
    for name in columns:
        series = dataframe[raw_by_name[name]]
        lowered = name.casefold()
        role = _semantic_role(name, series)
        if any(token in lowered for token in _SCIENTIFIC_TEXT_TOKENS):
            scientific_text.append(name)
        elif role == "measure":
            measures.append(name)
        elif role == "category":
            categories.append(name)
    selected = list(
        dict.fromkeys(
            [
                *declared_columns,
                *identifiers,
                *scientific_text[:16],
                *measures[:16],
                *categories[:8],
                *columns[:60],
            ]
        )
    )[:_MAX_PROFILED_COLUMNS]
    if not selected:
        return (), ()
    declared = declared_names
    profiles: list[ResourceColumnProfile] = []
    key_candidates: list[str] = []
    row_count = len(dataframe)
    for name in selected:
        series = dataframe[raw_by_name[name]]
        sample_series = series.head(_MAX_PROFILE_ROWS).dropna()
        distinct_sample = int(sample_series.nunique(dropna=True)) if len(sample_series) else 0
        missing_count = int(series.isna().sum())
        semantic_role = _semantic_role(name, series)
        if name.casefold() in declared:
            likelihood = "declared"
        elif (
            semantic_role == "identifier"
            and len(sample_series) >= 2
            and distinct_sample == len(sample_series)
            and missing_count == 0
        ):
            likelihood = "sampled_unique"
        elif semantic_role == "identifier":
            likelihood = "identifier"
        else:
            likelihood = "none"
        if likelihood != "none":
            key_candidates.append(name)
        profiles.append(
            ResourceColumnProfile(
                name=name,
                dtype=str(series.dtype),
                missing_count=missing_count,
                missing_fraction=(round(missing_count / row_count, 6) if row_count else 0.0),
                distinct_sample=distinct_sample,
                semantic_role=semantic_role,
                key_likelihood=likelihood,
            )
        )
    return tuple(profiles), tuple(dict.fromkeys(key_candidates))


def _cached_column_profiles(
    resource_id: str,
    dataframe: pd.DataFrame,
    meta: dict[str, Any],
) -> tuple[tuple[ResourceColumnProfile, ...], tuple[str, ...]]:
    signature = (
        id(dataframe),
        dataframe.shape,
        tuple(str(column) for column in dataframe.columns),
        _declared_keys(meta),
    )
    cached = _PROFILE_CACHE.get(resource_id)
    if cached is not None and cached[0] == signature:
        _PROFILE_CACHE.move_to_end(resource_id)
        return cached[1], cached[2]
    profiles, keys = _column_profiles(dataframe, meta)
    _PROFILE_CACHE[resource_id] = (signature, profiles, keys)
    _PROFILE_CACHE.move_to_end(resource_id)
    while len(_PROFILE_CACHE) > _MAX_PROFILE_CACHE_ENTRIES:
        _PROFILE_CACHE.popitem(last=False)
    return profiles, keys


def _freshness(meta: dict[str, Any]) -> str | None:
    for key in (
        "updated_at",
        "retrieved_at",
        "fetched_at",
        "cached_at",
        "created_at",
        "timestamp",
    ):
        if meta.get(key):
            return str(meta[key])[:120]
    return None


def _declared_scope(meta: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "project_id",
        "project_ids",
        "sample_id",
        "sample_ids",
        "profile_id",
        "profile_ids",
        "selection_name",
        "zone",
        "date_from",
        "date_to",
    )
    scope = {key: meta.get(key) for key in keys if meta.get(key) is not None}
    filters = meta.get("filters")
    if isinstance(filters, dict):
        scope.update({
            f"filter.{key}": value
            for key, value in filters.items()
            if value is None
            or isinstance(value, (str, int, float, bool))
            or (
                isinstance(value, (list, tuple))
                and all(
                    item is None or isinstance(item, (str, int, float, bool))
                    for item in value
                )
            )
        })
    return _clean_json_mapping(scope)


def _normalized_column_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _scope_role(column: object) -> str | None:
    normalized = _normalized_column_name(column)
    if normalized.endswith("projectid"):
        return "project_ids"
    if normalized.endswith("profileid"):
        return "profile_ids"
    if normalized in {"sampleid", "netsampleid"}:
        return "sample_ids"
    if normalized in {
        "station",
        "stationname",
        "samplestation",
        "neolabsstation",
        "ecotaxastation",
    }:
        return "stations"
    return None


def _json_scalar(value: object) -> object:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _observed_values(series: pd.Series, *, limit: int) -> tuple[list[object], int, bool]:
    unique = series.dropna().drop_duplicates()
    count = int(len(unique))
    values = [_json_scalar(value) for value in unique.head(limit).tolist()]
    try:
        values.sort()
    except TypeError:
        values.sort(key=str)
    return values, count, count > limit


def _observed_scope(dataframe: pd.DataFrame) -> dict[str, Any]:
    """Derive bounded scope facts from actual dataframe values."""
    observed: dict[str, Any] = {}
    columns_by_role: dict[str, list[str]] = {}
    for column in dataframe.columns:
        role = _scope_role(column)
        if role is not None:
            columns_by_role.setdefault(role, []).append(str(column))

    for role, columns in columns_by_role.items():
        raw_columns = [
            raw
            for name in columns
            for raw in dataframe.columns
            if str(raw) == name
        ]
        combined = pd.concat(
            [dataframe[column] for column in raw_columns],
            ignore_index=True,
        )
        values, count, truncated = _observed_values(
            combined,
            limit=_SCOPE_VALUE_LIMITS[role],
        )
        observed[role] = values
        observed[f"{role}_count"] = count
        if truncated:
            observed[f"{role}_truncated"] = True

    time_columns = []
    for column in dataframe.columns:
        normalized = _normalized_column_name(column)
        series = dataframe[column]
        is_named_time = (
            "datetime" in normalized
            or "timestamp" in normalized
            or normalized.endswith("date")
            or normalized
            in {
                "date",
                "sampledate",
                "startdate",
                "enddate",
            }
        )
        if is_named_time or pd.api.types.is_datetime64_any_dtype(series.dtype):
            time_columns.append(column)
    parsed_times: list[pd.Series] = []
    for column in time_columns:
        series = dataframe[column]
        if pd.api.types.is_numeric_dtype(series.dtype):
            continue
        parsed = pd.to_datetime(series, errors="coerce", utc=True).dropna()
        if not parsed.empty:
            parsed_times.append(parsed)
    if parsed_times:
        combined_times = pd.concat(parsed_times, ignore_index=True)
        observed["date_from"] = combined_times.min().isoformat()
        observed["date_to"] = combined_times.max().isoformat()
        observed["time_columns"] = [str(column) for column in time_columns]

    if observed:
        observed["scope_basis"] = "dataframe_values"
        observed["scope_columns"] = columns_by_role
    return observed


def _scope(meta: dict[str, Any], dataframe: pd.DataFrame | None) -> dict[str, Any]:
    declared = _declared_scope(meta)
    if dataframe is None:
        return {
            **declared,
            **({"scope_basis": "declared_metadata"} if declared else {}),
        }
    observed = _observed_scope(dataframe)
    if not observed:
        return {
            **declared,
            **({"scope_basis": "declared_metadata"} if declared else {}),
        }
    conflicts = {
        key: value
        for key, value in declared.items()
        if key in observed and observed[key] != value
    }
    scope = {**declared, **observed}
    if conflicts:
        scope["declared_conflicts"] = conflicts
    return scope


def _table_capabilities(dataframe: pd.DataFrame | None) -> tuple[ExplorationCapability, ...]:
    if dataframe is None:
        return ("inspect_resources", "retrieve_data")
    return (
        "inspect_resources",
        "filter_data",
        "join_data",
        "compute_metric",
        "validate_data",
        "summarize_data",
        "compare_data",
        "visualize_data",
        "export_deliverable",
    )


def _record_for_entry(key: str, entry: dict[str, Any]) -> ResourceRecord | None:
    meta = dict(entry.get("meta") or {})
    dataframe = entry.get("df")
    variable = str(
        meta.get("variable_name")
        or meta.get("selection_name")
        or key.rsplit(":", 1)[-1]
    )
    source = str(meta.get("source") or "session")
    is_selection = bool(meta.get("selection_name") or ":selection:" in key)
    if dataframe is None and not is_selection and not meta.get("variable_name"):
        return None
    columns = tuple(str(column) for column in dataframe.columns) if isinstance(dataframe, pd.DataFrame) else ()
    rows = len(dataframe) if isinstance(dataframe, pd.DataFrame) else meta.get("n_rows")
    try:
        row_count = int(rows) if rows is not None else None
    except (TypeError, ValueError):
        row_count = None
    provenance = _clean_json_mapping(meta.get("provenance"))
    if not provenance:
        provenance = {
            key: value
            for key, value in {
                "source": source,
                "path": meta.get("path"),
                "description": meta.get("description"),
            }.items()
            if value
        }
    column_profiles: tuple[ResourceColumnProfile, ...] = ()
    key_candidates: tuple[str, ...] = ()
    if isinstance(dataframe, pd.DataFrame):
        column_profiles, key_candidates = _cached_column_profiles(
            _resource_id(key),
            dataframe,
            meta,
        )
    return ResourceRecord(
        resource_id=_resource_id(key),
        kind="selection" if is_selection else "table",
        name=variable[:160],
        source=source[:120],
        persisted=True,
        rows=row_count,
        description=(str(meta.get("description"))[:300] if meta.get("description") else None),
        columns=columns[:_MAX_COLUMNS_PER_RESOURCE],
        columns_truncated=len(columns) > _MAX_COLUMNS_PER_RESOURCE,
        grain=_grain(meta, column_profiles),
        identifiers=_identifiers(columns),
        relations=_relations(meta),
        column_profiles=column_profiles,
        key_candidates=key_candidates,
        freshness=_freshness(meta),
        scope=_scope(meta, dataframe if isinstance(dataframe, pd.DataFrame) else None),
        capabilities=_table_capabilities(dataframe if isinstance(dataframe, pd.DataFrame) else None),
        provenance=provenance,
    )


def _sample_composite_values(
    dataframe: pd.DataFrame,
    columns: tuple[str, ...],
) -> frozenset[Any]:
    cache_key = (
        id(dataframe),
        dataframe.shape,
        tuple(str(column) for column in dataframe.columns),
        columns,
    )
    cached = _VALUE_CACHE.get(cache_key)
    if cached is not None:
        _VALUE_CACHE.move_to_end(cache_key)
        return cached
    raw_columns: list[Any] = []
    for name in columns:
        raw = next(
            (candidate for candidate in dataframe.columns if str(candidate) == name),
            None,
        )
        if raw is None:
            return frozenset()
        raw_columns.append(raw)
    sample = dataframe[raw_columns].dropna().head(_MAX_PROFILE_ROWS)
    try:
        values: frozenset[Any] = frozenset(
            tuple(row) if len(raw_columns) > 1 else row[0]
            for row in sample.itertuples(index=False, name=None)
        )
    except TypeError:
        values = frozenset(
            tuple(str(value) for value in row) if len(raw_columns) > 1 else str(row[0])
            for row in sample.itertuples(index=False, name=None)
        )
    _VALUE_CACHE[cache_key] = values
    _VALUE_CACHE.move_to_end(cache_key)
    while len(_VALUE_CACHE) > _MAX_VALUE_CACHE_ENTRIES:
        _VALUE_CACHE.popitem(last=False)
    return values


def _join_candidates(
    records: list[ResourceRecord],
    frames: dict[str, pd.DataFrame],
) -> list[ResourceRecord]:
    updated: list[ResourceRecord] = []
    for record in records:
        candidates: list[ResourceJoinCandidate] = []
        left_frame = frames.get(record.resource_id)
        left_names = {
            name.casefold(): name
            for name in record.key_candidates
        }
        if left_names:
            for target in records:
                if target.resource_id == record.resource_id or target.kind not in {"table", "selection"}:
                    continue
                right_names = {
                    name.casefold(): name
                    for name in target.key_candidates
                }
                shared = [name for key, name in left_names.items() if key in right_names]
                if not shared:
                    continue
                left_coverage: float | None = None
                right_coverage: float | None = None
                confidence = "name_only"
                right_frame = frames.get(target.resource_id)
                if left_frame is not None and right_frame is not None:
                    join_columns = tuple(shared[:3])
                    right_columns = tuple(
                        right_names[left_column.casefold()]
                        for left_column in join_columns
                    )
                    left_values = _sample_composite_values(left_frame, join_columns)
                    right_values = _sample_composite_values(right_frame, right_columns)
                    overlap = left_values & right_values
                    left_coverage = round(len(overlap) / len(left_values), 4) if left_values else 0.0
                    right_coverage = round(len(overlap) / len(right_values), 4) if right_values else 0.0
                    confidence = "sampled"
                candidates.append(
                    ResourceJoinCandidate(
                        target_resource_id=target.resource_id,
                        target_name=target.name,
                        columns=tuple(shared[:3]),
                        left_coverage=left_coverage,
                        right_coverage=right_coverage,
                        confidence=confidence,
                    )
                )
                if len(candidates) >= _MAX_JOIN_CANDIDATES:
                    break
        updated.append(record.model_copy(update={"join_candidates": tuple(candidates)}))
    return updated


def build_resource_inventory(
    store: SessionStore,
    thread_id: str,
    *,
    authorized_sources: Iterable[str] = (),
    excluded_variables: Iterable[str] = (),
) -> tuple[ResourceRecord, ...]:
    """Return a compact, checkpoint-safe inventory for one conversation."""
    from tools.dataframe_cleanup import dataframe_usage_ages

    records: list[ResourceRecord] = []
    excluded = {str(item) for item in excluded_variables}
    usage_ages = dataframe_usage_ages(store, thread_id)
    frames: dict[str, pd.DataFrame] = {}
    keys = [
        key for key in store.keys()
        if key == thread_id or key.startswith(f"{thread_id}:")
    ]
    for key in keys:
        entry = store.get(key)
        if not isinstance(entry, dict):
            continue
        record = _record_for_entry(key, entry)
        if record is not None and record.name not in excluded:
            if record.name in usage_ages:
                record = record.model_copy(
                    update={"age_turns": usage_ages[record.name]}
                )
            records.append(record)
            dataframe = entry.get("df")
            if isinstance(dataframe, pd.DataFrame):
                frames[record.resource_id] = dataframe

    records.append(
        ResourceRecord(
            resource_id="resource-copepod-rag",
            kind="knowledge_base",
            name="Base de connaissances copépodes",
            source="knowledge",
            persisted=True,
            capabilities=("ground_method", "inspect_resources"),
            provenance={"source": "local RAG index"},
        )
    )
    for source in sorted({str(item) for item in authorized_sources if item and item != "file"}):
        records.append(
            ResourceRecord(
                resource_id=f"resource-source-{source}",
                kind="external_source",
                name=source,
                source=source,
                persisted=False,
                capabilities=("inspect_resources", "retrieve_data"),
                provenance={"authorization": "current turn source policy"},
            )
        )

    deduplicated: dict[tuple[str, str, str], ResourceRecord] = {}
    for record in records:
        identity = (record.kind, record.name, record.source)
        current = deduplicated.get(identity)
        if current is None or (record.rows is not None and current.rows is None):
            deduplicated[identity] = record
    kind_priority = {
        "table": 0,
        "selection": 1,
        "external_source": 2,
        "knowledge_base": 3,
    }
    sorted_records = sorted(
        deduplicated.values(),
        key=lambda item: (kind_priority[item.kind], item.source, item.name),
    )
    return tuple(_join_candidates(sorted_records, frames))
