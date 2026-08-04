"""Compact, authoritative dataset state injected into every model request."""
from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from core.environment_resolver.column_detection import (
    DEFAULT_DEPTH_CANDIDATES,
    DEFAULT_LAT_CANDIDATES,
    DEFAULT_LON_CANDIDATES,
    DEFAULT_TIME_CANDIDATES,
    DEFAULT_TIME_END_CANDIDATES,
    detect_column,
    normalize_column_name,
)
from tools.session_store import SessionStore

_MAX_CAPSULE_CHARS = 12000
_MAX_ACTIVE_SKILL_RULES_CHARS = 4000
_MAX_SINGLE_SKILL_RULE_CHARS = 1600
_IDENTITY_COLUMNS = tuple(dict.fromkeys((
    "project_id",
    "sample_id",
    "profile_id",
    "object_id",
    "object_date",
    "sampledatetime",
    "station",
    "station_id",
    "latitude",
    "longitude",
    "depth",
    "object_depth_min",
    "object_depth_max",
    *DEFAULT_LAT_CANDIDATES,
    *DEFAULT_LON_CANDIDATES,
    *DEFAULT_TIME_CANDIDATES,
    *DEFAULT_DEPTH_CANDIDATES,
)))
_IDENTIFIER_ARGUMENTS = {"project_id", "project_ids", "sample_id", "sample_ids"}


def _clean(value: object, *, limit: int = 240) -> str:
    return " ".join(str(value).split())[:limit]


def _matching_aliases(store: SessionStore, thread_id: str, variable: str) -> list[str]:
    aliases: list[str] = []
    prefix = f"{thread_id}:"
    for key in store.keys(prefix=prefix):
        if ":dataset:" in key:
            continue
        entry = store.get(key)
        meta = (entry or {}).get("meta") or {}
        if meta.get("variable_name") == variable:
            aliases.append(key.removeprefix(prefix))
    return sorted(set(aliases))


def _present_columns(columns: Iterable[object]) -> list[str]:
    available = {str(column) for column in columns}
    return [column for column in _IDENTITY_COLUMNS if column in available]


# The always-injected dataset capsule must stay a compact orientation aid.
# The complete schema remains in the persisted DataFrame for targeted inspection.
_MAX_ALL_COLUMNS = 32
_MAX_TABLE_SCHEMA_COLUMNS = 16
_MAX_EXPORT_SCHEMA_COLUMNS = 24

# The model should encounter the columns in the same order a scientist uses to
# scope an analysis: first the observation/key, then when and where it was
# taken, then its depth and measurements.  Keep this list narrow and stable;
# unknown columns fall into the measure/category groups below.
_IDENTIFIER_PRIORITY = (
    "project_id",
    "project",
    "campaign_id",
    "campaign",
    "cruise_id",
    "cruise",
    "deployment_id",
    "deployment",
    "net_id",
    "net",
    "cast_id",
    "cast",
    "profile_id",
    "profile",
    "sample_id",
    "sample",
    "analysis_id",
    "analysis",
    "object_id",
    "object",
    "original_id",
    "station_id",
    "station_name",
    "station",
)

_TAXONOMY_PRIORITY = (
    "taxon",
    "taxon_name",
    "scientific_name",
    "object_annotation_category",
    "category",
    "taxonomy",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "stage",
    "life_stage",
)

_ABUNDANCE_MARKERS = (
    "abund",
    "biomass",
    "density",
    "concentration",
    "objectcount",
    "nobject",
    "count",
)

_NEOLABS_TIME_CANDIDATES = (
    "sampling_year",
    "DEPLOYMENT_DATE_START",
    "deployment_datetime_start",
)

_PROJECT_KEY_MARKERS = ("project", "campaign", "cruise")
_SAMPLE_MARKERS = (
    "sample", "profile", "station", "deployment", "net", "cast", "analysis",
)
_ENVIRONMENT_MARKERS = (
    "depth", "pres", "temperature", "temp", "salin", "oxygen", "conduct",
    "fluor", "chlorophyll", "ph", "turbid", "volume", "flowmeter",
)


def _time_candidates_for(columns: Iterable[object]) -> tuple[str, ...]:
    """Prefer NeoLabs' explicit year/source date in dataset orientation only."""
    normalized = {normalize_column_name(column) for column in columns}
    is_neolabs = (
        normalize_column_name("sampling_year") in normalized
        and normalize_column_name("DEPLOYMENT_DATE_START") in normalized
    )
    if not is_neolabs:
        return DEFAULT_TIME_CANDIDATES
    return tuple(dict.fromkeys((*_NEOLABS_TIME_CANDIDATES, *DEFAULT_TIME_CANDIDATES)))


def _prioritized_columns(
    dataframe: "pd.DataFrame",
    env_detected: dict[str, str | None],
    *,
    limit: int = _MAX_ALL_COLUMNS,
) -> str:
    """Return columns in scientific-scoping order, truncated safely.

    Priority: identifiers/join keys, time, position, depth, taxonomy,
    abundance/biomass measures, other numeric measures, then remaining
    categories. This makes the compact context useful before the model has
    inspected rows, while preserving every available column in the underlying
    DataFrame for a subsequent targeted inspection.
    """
    import pandas as pd

    columns = list(dataframe.columns)
    normalized_to_real = {normalize_column_name(column): column for column in columns}

    def candidates(names: tuple[str, ...]) -> list[object]:
        return [
            normalized_to_real[normalize_column_name(name)]
            for name in names
            if normalize_column_name(name) in normalized_to_real
        ]

    identifiers = candidates(_IDENTIFIER_PRIORITY)
    identifier_set = set(identifiers)
    # Keep unfamiliar `*_id` keys early as well, without promoting generic
    # categorical names such as `taxon_id` above the canonical observation IDs.
    identifiers.extend(
        column
        for column in columns
        if column not in identifier_set
        and (str(column).lower().endswith("_id") or str(column).lower() == "id")
    )

    time_cols = candidates((*_time_candidates_for(columns), *DEFAULT_TIME_END_CANDIDATES))
    position_cols = candidates((*DEFAULT_LAT_CANDIDATES, *DEFAULT_LON_CANDIDATES))
    depth_cols = candidates(DEFAULT_DEPTH_CANDIDATES)
    taxonomy_cols = candidates(_TAXONOMY_PRIORITY)

    priority_sets = (
        set(identifiers)
        | set(time_cols)
        | set(position_cols)
        | set(depth_cols)
        | set(taxonomy_cols)
    )

    other_numeric_measures = [
        column
        for column in dataframe.select_dtypes(include="number").columns
        if column not in priority_sets
    ]
    abundance_measures = [
        column
        for column in other_numeric_measures
        if any(marker in normalize_column_name(column) for marker in _ABUNDANCE_MARKERS)
    ]
    numeric_measures = [
        column for column in other_numeric_measures if column not in abundance_measures
    ]
    categories = [
        column
        for column in columns
        if column not in priority_sets
        and column not in abundance_measures
        and column not in numeric_measures
    ]

    # Reserve room for every scientific family.  A wide export can contain many
    # *_id fields; letting those consume the whole preview would hide exactly the
    # time, space, environment, taxon and measure candidates needed for routing.
    ordered = [
        *identifiers[:8],
        *time_cols[:4],
        *position_cols[:4],
        *depth_cols[:4],
        *taxonomy_cols[:6],
        *abundance_measures[:6],
        *numeric_measures[:6],
        *categories,
    ]
    ordered = list(dict.fromkeys(ordered))
    ordered.extend(column for column in columns if column not in set(ordered))
    total = len(columns)
    shown = ordered[:limit]
    suffix = f",(+{total - len(shown)} more)" if total > len(shown) else ""
    return ",".join(shown) + suffix


def _schema_by_type(
    dataframe: "pd.DataFrame",
    env_detected: dict[str, str | None],
    *,
    limit: int,
) -> str:
    """Return a short schema grouped by scientific role, never every column."""
    selected = _prioritized_columns(
        dataframe, env_detected, limit=limit
    ).split(",")
    remainder = next((item for item in selected if item.startswith("(+")), "")
    names = [item for item in selected if not item.startswith("(+")]
    taxon_names = {normalize_column_name(name) for name in _TAXONOMY_PRIORITY}
    time_names = {
        normalize_column_name(name)
        for name in (
            *_time_candidates_for(dataframe.columns),
            *DEFAULT_TIME_END_CANDIDATES,
        )
    }
    space_names = {
        normalize_column_name(name)
        for name in (*DEFAULT_LAT_CANDIDATES, *DEFAULT_LON_CANDIDATES)
    }
    environment_names = {
        normalize_column_name(name) for name in DEFAULT_DEPTH_CANDIDATES
    }
    environment_names.update(
        normalize_column_name(name)
        for name in env_detected.values()
        if name and normalize_column_name(name) not in space_names | time_names
    )
    numeric_names = {
        str(column)
        for column in dataframe.select_dtypes(include="number").columns
    }
    groups: dict[str, list[str]] = {
        "keys": [], "sample": [], "space": [], "time": [],
        "environment": [], "taxon": [], "measures": [], "other": [],
    }
    for name in names:
        normalized_name = normalize_column_name(name)
        if any(marker in normalized_name for marker in _PROJECT_KEY_MARKERS):
            groups["keys"].append(name)
        elif normalized_name in space_names:
            groups["space"].append(name)
        elif normalized_name in time_names:
            groups["time"].append(name)
        elif normalized_name in taxon_names:
            groups["taxon"].append(name)
        elif normalized_name in environment_names:
            groups["environment"].append(name)
        elif any(marker in normalized_name for marker in _ABUNDANCE_MARKERS):
            groups["measures"].append(name)
        elif any(marker in normalized_name for marker in _ENVIRONMENT_MARKERS):
            groups["environment"].append(name)
        elif (
            any(marker in normalized_name for marker in _SAMPLE_MARKERS)
            or normalized_name in {"object", "objectid"}
        ):
            groups["sample"].append(name)
        elif name in numeric_names:
            groups["measures"].append(name)
        else:
            groups["other"].append(name)
    rendered = [
        f"{label}=[{','.join(values)}]"
        for label, values in groups.items()
        if values
    ]
    return "; ".join(rendered + ([remainder] if remainder else []))


_MAX_DERIVED_SUBSETS = 6
_MAX_LOADED_FILES = 6
_MAX_WORKING_TABLES = 8
# Meta keys that carry an external EcoTaxa identifier. A dataset carrying any of
# them is a raw project/sample-keyed export and must stay hidden so its id is not
# re-exposed as the current subject (see the module docstring).
_STALE_ID_KEYS = ("project_id", "sample_id", "sample_ids")


def _working_tables(
    store: SessionStore, thread_id: str, *, active_variable: str
) -> list[tuple[str, str, str, str, str]]:
    """Return (variable, source, rows, description, compact_schema).

    These are results that are neither loaded files nor zone subsets — EcoTaxa
    cache queries (`df_ecotaxa_cache_query`), joins, enrichment outputs. Surfacing
    them by name — symmetric to :func:`_loaded_files` and
    :func:`_live_zone_subsets` — keeps the most coherent table selectable across
    sources once it is no longer the single active df. Datasets carrying an
    external project/sample id (`_STALE_ID_KEYS`) are skipped so no stale
    identifier is re-exposed.
    """
    found: list[tuple[str, str, str, str, str]] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key)
        meta = (entry or {}).get("meta") or {}
        source = str(meta.get("source") or "")
        if source.startswith("file:") or meta.get("zone_canonical"):
            continue  # already surfaced by _loaded_files / _live_zone_subsets
        if meta.get("alias_of"):
            continue  # moving compatibility alias, not a distinct working table
        if (
            source != "ecotaxa_selection"
            and any(meta.get(id_key) is not None for id_key in _STALE_ID_KEYS)
        ):
            continue  # raw project/sample-keyed export — keep hidden
        variable = _clean(meta.get("variable_name") or key.rsplit(":", 1)[-1], limit=80)
        if variable == active_variable and source != "ecotaxa_selection":
            continue  # already the headline active dataset
        rows = meta.get("n_rows")
        rows_text = str(int(rows)) if isinstance(rows, (int, float)) else "?"
        description = _clean(meta.get("description") or "", limit=100)
        dataframe = (entry or {}).get("df")
        if dataframe is not None:
            environment_columns = {
                "latitude": detect_column(dataframe.columns, DEFAULT_LAT_CANDIDATES),
                "longitude": detect_column(dataframe.columns, DEFAULT_LON_CANDIDATES),
                "time": detect_column(dataframe.columns, DEFAULT_TIME_CANDIDATES),
                "depth": detect_column(dataframe.columns, DEFAULT_DEPTH_CANDIDATES),
            }
            schema = _schema_by_type(
                dataframe, environment_columns, limit=_MAX_TABLE_SCHEMA_COLUMNS
            )
        else:
            schema = "unknown"
        found.append(
            (
                variable,
                _clean(source or "derived", limit=60),
                rows_text,
                description,
                schema,
            )
        )
    return sorted(set(found))


def _loaded_files(store: SessionStore, thread_id: str) -> list[tuple[str, str, str]]:
    """Return (variable, path, rows) for every loaded file in the session.

    Each `load_file` registers a distinct `df_file_*` variable. Surfacing the
    whole roster lets the agent target the right file by name across a
    multi-file session instead of reloading it or guessing from the transcript.
    """
    found: list[tuple[str, str, str]] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key)
        meta = (entry or {}).get("meta") or {}
        source = str(meta.get("source") or "")
        if not source.startswith("file:"):
            continue
        variable = _clean(meta.get("variable_name") or key.rsplit(":", 1)[-1], limit=80)
        path = _clean(meta.get("path") or source[len("file:"):], limit=120)
        rows = meta.get("n_rows")
        rows_text = str(int(rows)) if isinstance(rows, (int, float)) else "?"
        description = _clean(meta.get("description") or "", limit=100)
        found.append((variable, path, rows_text, description))
    return sorted(set(found))


def _live_zone_subsets(store: SessionStore, thread_id: str) -> list[tuple[str, str, str]]:
    """Return (variable, zone, rows) for every live zone-derived subset.

    A zone subset carries `zone_canonical` in its registry metadata (produced by
    `filter_dataframe_by_zone`). Surfacing them lets the model read which
    variable maps to which zone instead of re-inferring it from the transcript.
    """
    found: list[tuple[str, str, str]] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key)
        meta = (entry or {}).get("meta") or {}
        zone = meta.get("zone_canonical")
        if not zone:
            continue
        variable = _clean(meta.get("variable_name") or key.rsplit(":", 1)[-1], limit=80)
        rows = meta.get("n_rows")
        rows_text = str(int(rows)) if isinstance(rows, (int, float)) else "?"
        found.append((variable, _clean(zone, limit=60), rows_text))
    return sorted(set(found))


def _source_scope_line(store: SessionStore, thread_id: str, messages: object) -> str:
    """Render the authorized source scope for this turn as readable state.

    Makes the executable source decision (explicit source / persisted restriction)
    visible to the model instead of being enforced silently, so the agent reads
    which sources are active this turn rather than re-deriving them.
    """
    if not messages:
        return ""
    try:
        from tools.source_scope import source_decision_for_turn  # noqa: PLC0415

        decision = source_decision_for_turn(
            store, thread_id, list(messages), persist=False
        )
    except Exception:
        return ""
    authorized = ",".join(decision.authorized_sources) or "none"
    primary = decision.primary_source or "none"
    return (
        f"\nACTIVE SOURCE SCOPE: authorized={authorized}; primary={primary}. "
        "Only these sources are usable this turn; naming a new external source "
        "switches scope, a loaded file resets it to the file."
    )


def _active_skill_rules(store: SessionStore, thread_id: str) -> str:
    """Render bounded, versioned rules retained after tool-history compaction."""
    meta = (store.get(thread_id) or {}).get("meta") or {}
    capsules = meta.get("active_skill_capsules") or {}
    lines: list[str] = []
    for name, capsule in sorted(capsules.items()):
        if not isinstance(capsule, dict):
            continue
        content = _clean(capsule.get("content") or "", limit=_MAX_SINGLE_SKILL_RULE_CHARS)
        if content:
            lines.append(f"- {name}@{_clean(capsule.get('version') or '?', limit=20)}: {content}")
    if not lines:
        return ""
    return ("\nACTIVE SKILL RULES (already loaded; reuse them, do not reload):\n"
            + "\n".join(lines))[:_MAX_ACTIVE_SKILL_RULES_CHARS]


def build_dataset_state_capsule(
    store: SessionStore, thread_id: str, messages: object = None
) -> str:
    """Describe only the active dataset using registry metadata, never row values.

    Id-free derived working tables (files, zone subsets, EcoTaxa cache queries,
    joins) are surfaced as named menus so the most coherent table stays
    selectable across sources. Datasets carrying an external project/sample id
    are still excluded so stale identifiers cannot be mistaken for the current
    conversational subject. When `messages` is given, the authorized source scope
    for the turn is appended as readable state.
    """
    active = store.get(thread_id)
    if not active or active.get("df") is None:
        return ""

    dataframe = active["df"]
    meta = dict(active.get("meta") or {})
    variable = _clean(meta.get("variable_name") or "df")
    source = _clean(meta.get("source") or "unknown")
    physical_rows, physical_columns = dataframe.shape
    rows = int(meta.get("n_rows", physical_rows))
    columns = int(meta.get("n_cols", physical_columns))
    aliases = _matching_aliases(store, thread_id, variable)
    identity_columns = _present_columns(dataframe.columns)
    environment_columns = {
        "latitude": detect_column(dataframe.columns, DEFAULT_LAT_CANDIDATES),
        "longitude": detect_column(dataframe.columns, DEFAULT_LON_CANDIDATES),
        "time": detect_column(dataframe.columns, _time_candidates_for(dataframe.columns)),
        "depth": detect_column(dataframe.columns, DEFAULT_DEPTH_CANDIDATES),
    }

    description = _clean(meta.get("description") or "", limit=140)
    fields = [
        f"variable={variable}",
        f"source={source}",
        *( [f"description={description}"] if description else [] ),
        f"shape={rows}x{columns}",
        "aliases=" + (",".join(aliases) if aliases else "none"),
        "identity_columns=" + (
            ",".join(identity_columns) if identity_columns else "none"
        ),
        "environment_columns=" + ",".join(
            f"{role}:{column or 'none'}"
            for role, column in environment_columns.items()
        ),
        "all_columns=" + _prioritized_columns(dataframe, environment_columns),
    ]
    important_columns = [
        str(column)
        for column in (meta.get("important_columns") or [])
        if str(column) in dataframe.columns
    ][:12]
    if important_columns:
        fields.append("important_columns=" + ",".join(important_columns))
        descriptions = meta.get("column_descriptions") or {}
        meanings = [
            f"{column}:{_clean(descriptions[column], limit=90)}"
            for column in important_columns
            if descriptions.get(column)
        ]
        if meanings:
            fields.append("column_meanings=" + " | ".join(meanings))
    if meta.get("matched_ctd_depth_column"):
        fields.append(
            "matched_ctd_depth_column="
            + _clean(meta["matched_ctd_depth_column"], limit=80)
        )
    if meta.get("profile_depth_column"):
        fields.append(
            "profile_depth_column=" + _clean(meta["profile_depth_column"], limit=80)
        )
    active_join_note = ""
    if source == "analysis:join":
        active_join_note = (
            "\nACTIVE PERSISTED JOIN: this joined table is the active file for "
            "follow-up analysis. Reuse its exact variable name; do not reload "
            "or rejoin the source files unless explicitly requested."
        )
    if meta.get("project_id") is not None:
        fields.append(f"project_id={_clean(meta['project_id'], limit=40)}")
    if meta.get("sample_id") is not None:
        fields.append(f"sample_id={_clean(meta['sample_id'], limit=80)}")

    selection_block = ""
    if meta.get("source") == "ecotaxa_selection" or meta.get("selection_name"):
        selection_name = _clean(meta.get("selection_name") or "latest")
        sample_ids = meta.get("sample_ids") or []
        project_ids = meta.get("project_ids") or []
        project_id_text = ",".join(str(value) for value in project_ids)
        filters = meta.get("filters") or {}
        filter_text = ", ".join(
            f"{key}={_clean(value, limit=100)}"
            for key, value in filters.items()
        )
        selection_block = (
            "\nACTIVE ECOTAXA SELECTION (authoritative scope for follow-ups):\n"
            f"- name={selection_name}\n"
            f"- variable={variable}\n"
            f"- samples={len(sample_ids) or rows}\n"
            f"- project_ids={project_id_text or 'not listed'}\n"
            f"- filters={filter_text or 'not listed'}\n"
            "- Reuse this selection for follow-up tables, SQL, pandas, and graphs; "
            "preserve every listed filter (including dates) unless the user "
            "explicitly requests a wider or different scope."
        )

    campaigns: list[str] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key) or {}
        campaign_meta = entry.get("meta") or {}
        if campaign_meta.get("source") != "ecotaxa_export_campaign":
            continue
        name = _clean(campaign_meta.get("variable_name") or key.rsplit(":", 1)[-1])
        description = _clean(campaign_meta.get("description") or "Export EcoTaxa consolidé")
        campaign_df = entry.get("df")
        if campaign_df is not None:
            campaign_environment = {
                "latitude": detect_column(campaign_df.columns, DEFAULT_LAT_CANDIDATES),
                "longitude": detect_column(campaign_df.columns, DEFAULT_LON_CANDIDATES),
                "time": detect_column(campaign_df.columns, DEFAULT_TIME_CANDIDATES),
                "depth": detect_column(campaign_df.columns, DEFAULT_DEPTH_CANDIDATES),
            }
            schema = _schema_by_type(
                campaign_df, campaign_environment, limit=_MAX_EXPORT_SCHEMA_COLUMNS
            )
        else:
            schema = "unknown"
        marker = " (active)" if name == variable else ""
        campaigns.append(f"- {name}{marker}: {description}; schema={schema}")
    campaign_block = (
        "\nECO TAXA EXPORTED CAMPAIGNS (persistent, reusable tables):\n"
        + "\n".join(sorted(campaigns)[:8]) + "\n"
        if campaigns else ""
    )

    # When the active df is a derived subset, surface the loaded file as the
    # canonical source so a new geographic/zone request re-anchors on the full
    # file instead of a subset of a different zone (docs/e2e/cartes-samples-labrador-2026).
    anchor_note = ""
    loaded = store.get(f"{thread_id}:loaded_file")
    if loaded and loaded.get("df") is not None:
        loaded_variable = _clean((loaded.get("meta") or {}).get("variable_name") or "")
        if loaded_variable and loaded_variable != variable:
            anchor_note = (
                f"\nCANONICAL SOURCE: loaded_file={loaded_variable}. The active "
                f"dataset above is a derived subset. "
                f"To analyse, graph, or enrich the current subset, use {variable} directly — never re-filter from {loaded_variable}. "
                f"Only for a NEW zone/geographic filter, start from {loaded_variable} "
                f"(or call filter_dataframe_by_zone without source_variable)."
            )

    derived_block = ""
    subsets = _live_zone_subsets(store, thread_id)
    if subsets:
        listed = subsets[:_MAX_DERIVED_SUBSETS]
        lines = "\n".join(
            f"- {variable}: zone={zone}, rows={rows}" for variable, zone, rows in listed
        )
        more = (
            f"\n- (+{len(subsets) - len(listed)} more)"
            if len(subsets) > len(listed)
            else ""
        )
        derived_block = (
            "\nDERIVED ZONE SUBSETS (reusable by exact variable name — pick the "
            "one whose zone matches the request; do not recompute a subset that "
            "already exists):\n" + lines + more
        )

    working_block = ""
    tables = _working_tables(store, thread_id, active_variable=variable)
    if tables:
        # Every named EcoTaxa selection remains visible for the life of the
        # conversation. Only unrelated derived tables use the compact cap.
        selections = [item for item in tables if item[1] == "ecotaxa_selection"]
        other_tables = [item for item in tables if item[1] != "ecotaxa_selection"]
        listed = [*selections[:_MAX_WORKING_TABLES], *other_tables[:_MAX_WORKING_TABLES]]
        lines = "\n".join(
            f"- {variable}: source={source}, rows={rows}"
            + f", schema={schema}"
            + (f", desc={description}" if description else "")
            for variable, source, rows, description, schema in listed
        )
        more = (
            f"\n- (+{len(selections) - _MAX_WORKING_TABLES} other selections)"
            if len(selections) > _MAX_WORKING_TABLES
            else ""
        ) + (
            f"\n- (+{len(other_tables) - _MAX_WORKING_TABLES} other derived tables)"
            if len(other_tables) > _MAX_WORKING_TABLES
            else ""
        )
        working_block = (
            "\nWORKING TABLES (derived results reusable by exact variable name — "
            "pick the one whose source/scope matches the request; do not recompute "
            "a result that already exists):\n" + lines + more
        )

    scope_line = _source_scope_line(store, thread_id, messages)
    skill_rules = _active_skill_rules(store, thread_id)

    loaded_files_block = ""
    files = _loaded_files(store, thread_id)
    if len(files) >= 1:
        listed = files[:_MAX_LOADED_FILES]
        lines = "\n".join(
            f"- {variable}: path={path}, rows={rows}"
            + (f", desc={description}" if description else "")
            for variable, path, rows, description in listed
        )
        more = (
            f"\n- (+{len(files) - len(listed)} more)"
            if len(files) > len(listed)
            else ""
        )
        loaded_files_block = (
            "\nLOADED FILES (already in session — do not call load_file again for "
            "any path listed here; use the variable name directly):\n"
            + lines + more
        )

    capsule = (
        "\n\n## ACTIVE DATASET STATE (authoritative, current turn)\n"
        "- " + "; ".join(fields) + "\n"
        "SCHEMA BY TYPE: "
        + _schema_by_type(dataframe, environment_columns, limit=_MAX_ALL_COLUMNS)
        + "\n"
        + active_join_note
        + selection_block
        + campaign_block
        + "Canonical environmental enrichment validates these detected aliases "
        "itself; direct station/cast identifiers are not required.\n"
        "Identifiers absent from this capsule and the current user message are "
        "ungrounded; do not infer them from older conversation turns."
        + scope_line
        + skill_rules
        + working_block
        + loaded_files_block
        + anchor_note
        + derived_block
    )
    return capsule[:_MAX_CAPSULE_CHARS]


def _flatten_identifier_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [item for nested in value for item in _flatten_identifier_values(nested)]
    if value is None or isinstance(value, bool):
        return []
    return [str(value).strip()]


def _mentioned(identifier: str, text: str) -> bool:
    return bool(re.search(rf"(?<!\d){re.escape(identifier)}(?!\d)", text))


def reject_ungrounded_ecotaxa_identifiers(
    store: SessionStore,
    thread_id: str,
    messages: Iterable[object],
    tool_name: str,
    arguments: dict[str, Any],
) -> str | None:
    """Return a refusal when an EcoTaxa call relies only on an older turn.

    Grounding may come from the current user message, a tool result produced
    after that message, or explicit metadata of the active dataset. Data rows
    and earlier conversation turns are deliberately not searched.
    """
    if "ecotaxa" not in tool_name.lower():
        return None
    requested = {
        identifier
        for key, value in arguments.items()
        if key in _IDENTIFIER_ARGUMENTS
        for identifier in _flatten_identifier_values(value)
        if identifier
    }
    if not requested:
        return None

    sequence = list(messages)
    last_human = max(
        (index for index, message in enumerate(sequence) if isinstance(message, HumanMessage)),
        default=-1,
    )
    current_turn = sequence[last_human:] if last_human >= 0 else []
    grounding_text = "\n".join(
        str(message.content)
        for message in current_turn
        if isinstance(message, (HumanMessage, ToolMessage))
    )

    active = store.get(thread_id)
    active_meta = (active or {}).get("meta") or {}
    pending_export = active_meta.get("pending_ecotaxa_export_plan") or {}
    pending_sample_ids = {
        identifier
        for identifier in _flatten_identifier_values(pending_export.get("sample_ids"))
    }
    if (
        tool_name == "export_ecotaxa_samples"
        and arguments.get("confirmed") is True
        and requested == pending_sample_ids
    ):
        return None
    grounded_from_meta = {
        identifier
        for key in _IDENTIFIER_ARGUMENTS
        for identifier in _flatten_identifier_values(active_meta.get(key))
    }
    ungrounded = sorted(
        identifier
        for identifier in requested
        if identifier not in grounded_from_meta
        and not _mentioned(identifier, grounding_text)
    )
    if not ungrounded:
        return None
    return (
        "Refus : identifiant EcoTaxa non fondé pour le tour courant "
        f"({', '.join(ungrounded)}). L'identifiant doit provenir du message "
        "utilisateur courant, de l'état actif ou d'un résultat d'outil du même tour."
    )
