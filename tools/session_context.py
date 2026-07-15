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


def build_dataset_state_capsule(store: SessionStore, thread_id: str) -> str:
    """Describe only the active dataset using registry metadata, never row values.

    Older registered datasets remain reusable by explicit variable name, but are
    intentionally excluded here so stale project/sample identifiers cannot be
    mistaken for the current conversational subject.
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

    capsule = (
        "\n\n## ACTIVE DATASET STATE (authoritative, current turn)\n"
        "- " + "; ".join(fields) + "\n"
        "Identifiers absent from this capsule and the current user message are "
        "ungrounded; do not infer them from older conversation turns."
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
