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
    detect_column,
)
from tools.session_store import SessionStore

_MAX_CAPSULE_CHARS = 2000
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


_MAX_DERIVED_SUBSETS = 12
_MAX_LOADED_FILES = 12
_MAX_WORKING_TABLES = 12
# Meta keys that carry an external EcoTaxa identifier. A dataset carrying any of
# them is a raw project/sample-keyed export and must stay hidden so its id is not
# re-exposed as the current subject (see the module docstring).
_STALE_ID_KEYS = ("project_id", "sample_id", "sample_ids")


def _working_tables(
    store: SessionStore, thread_id: str, *, active_variable: str
) -> list[tuple[str, str, str]]:
    """Return (variable, source, rows) for derived working tables.

    These are results that are neither loaded files nor zone subsets — EcoTaxa
    cache queries (`df_ecotaxa_cache_query`), joins, enrichment outputs. Surfacing
    them by name — symmetric to :func:`_loaded_files` and
    :func:`_live_zone_subsets` — keeps the most coherent table selectable across
    sources once it is no longer the single active df. Datasets carrying an
    external project/sample id (`_STALE_ID_KEYS`) are skipped so no stale
    identifier is re-exposed.
    """
    found: list[tuple[str, str, str]] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key)
        meta = (entry or {}).get("meta") or {}
        source = str(meta.get("source") or "")
        if source.startswith("file:") or meta.get("zone_canonical"):
            continue  # already surfaced by _loaded_files / _live_zone_subsets
        if any(meta.get(id_key) is not None for id_key in _STALE_ID_KEYS):
            continue  # raw project/sample-keyed export — keep hidden
        variable = _clean(meta.get("variable_name") or key.rsplit(":", 1)[-1], limit=80)
        if variable == active_variable:
            continue  # already the headline active dataset
        rows = meta.get("n_rows")
        rows_text = str(int(rows)) if isinstance(rows, (int, float)) else "?"
        description = _clean(meta.get("description") or "", limit=100)
        found.append(
            (variable, _clean(source or "derived", limit=60), rows_text, description)
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
        "time": detect_column(dataframe.columns, DEFAULT_TIME_CANDIDATES),
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
    ]
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
        sample_id_text = ",".join(str(value) for value in sample_ids[:20])
        if len(sample_ids) > 20:
            sample_id_text += f",...(+{len(sample_ids) - 20})"
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
            f"- sample_ids={sample_id_text or 'not listed'}\n"
            f"- project_ids={project_id_text or 'not listed'}\n"
            f"- filters={filter_text or 'not listed'}\n"
            "- Reuse this selection for follow-up tables, SQL, pandas, and graphs; "
            "do not ask for the geographic scope again."
        )

    campaigns: list[str] = []
    for key in store.keys(prefix=f"{thread_id}:dataset:"):
        entry = store.get(key) or {}
        campaign_meta = entry.get("meta") or {}
        if campaign_meta.get("source") != "ecotaxa_export_campaign":
            continue
        name = _clean(campaign_meta.get("variable_name") or key.rsplit(":", 1)[-1])
        description = _clean(campaign_meta.get("description") or "Export EcoTaxa consolidé")
        marker = " (active)" if name == variable else ""
        campaigns.append(f"- {name}{marker}: {description}")
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
                f"dataset above is a derived subset. For a new zone/geographic "
                f"filter, start from {loaded_variable} (or call "
                f"filter_dataframe_by_zone without source_variable), never from "
                f"a subset of another zone."
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
        listed = tables[:_MAX_WORKING_TABLES]
        lines = "\n".join(
            f"- {variable}: source={source}, rows={rows}"
            + (f", desc={description}" if description else "")
            for variable, source, rows, description in listed
        )
        more = (
            f"\n- (+{len(tables) - len(listed)} more)"
            if len(tables) > len(listed)
            else ""
        )
        working_block = (
            "\nWORKING TABLES (derived results reusable by exact variable name — "
            "pick the one whose source/scope matches the request; do not recompute "
            "a result that already exists):\n" + lines + more
        )

    scope_line = _source_scope_line(store, thread_id, messages)

    loaded_files_block = ""
    files = _loaded_files(store, thread_id)
    if len(files) > 1:
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
            "\nLOADED FILES (each reusable by its exact variable name — target the "
            "right file by name; do not reload a file already listed here):\n"
            + lines + more
        )

    capsule = (
        "\n\n## ACTIVE DATASET STATE (authoritative, current turn)\n"
        "- " + "; ".join(fields) + "\n"
        + active_join_note
        + selection_block
        + campaign_block
        + "Canonical environmental enrichment validates these detected aliases "
        "itself; direct station/cast identifiers are not required.\n"
        "Identifiers absent from this capsule and the current user message are "
        "ungrounded; do not infer them from older conversation turns."
        + scope_line
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
