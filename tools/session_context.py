"""Compact, authoritative dataset state injected into every model request."""
from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from tools.session_store import SessionStore

_MAX_CAPSULE_CHARS = 2000
_IDENTITY_COLUMNS = (
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
)
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
        found.append((variable, path, rows_text))
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

    Older registered datasets remain reusable by explicit variable name, but are
    intentionally excluded here so stale project/sample identifiers cannot be
    mistaken for the current conversational subject. When `messages` is given,
    the authorized source scope for the turn is appended as readable state.
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

    fields = [
        f"variable={variable}",
        f"source={source}",
        f"shape={rows}x{columns}",
        "aliases=" + (",".join(aliases) if aliases else "none"),
        "identity_columns=" + (
            ",".join(identity_columns) if identity_columns else "none"
        ),
    ]
    if meta.get("project_id") is not None:
        fields.append(f"project_id={_clean(meta['project_id'], limit=40)}")
    if meta.get("sample_id") is not None:
        fields.append(f"sample_id={_clean(meta['sample_id'], limit=80)}")

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

    scope_line = _source_scope_line(store, thread_id, messages)

    loaded_files_block = ""
    files = _loaded_files(store, thread_id)
    if len(files) > 1:
        listed = files[:_MAX_LOADED_FILES]
        lines = "\n".join(
            f"- {variable}: path={path}, rows={rows}" for variable, path, rows in listed
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
        "Identifiers absent from this capsule and the current user message are "
        "ungrounded; do not infer them from older conversation turns."
        + scope_line
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
