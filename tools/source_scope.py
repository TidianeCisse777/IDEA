"""Source-scope gate — a loaded file is the default target of searches/analyses.

Principle (see docs/e2e/cartes-samples-labrador-2026): if a file is loaded, every
"samples / échantillons / positions / stations / zone / analyse / carte" request
operates on that file. EcoTaxa/EcoPart routes are reachable only when the user
emits an **explicit EcoTaxa/EcoPart signal** (names the source, a project id, the
cache…), or when no file is loaded.

Generic words like "samples", "échantillons", "zone", "positions" are NOT signals
— a loaded file has samples too. This gate is enforced in code because prompt
prose alone does not hold: the model kept drifting to EcoTaxa on file-scoped
requests (scenario turns 3 & 5) despite an explicit override rule.
"""

from __future__ import annotations

import re
from typing import Any

# An *explicit* reference to the EcoTaxa / EcoPart sources or their identifiers.
# Deliberately narrow: only unblock EcoTaxa routing when the user actually points
# at the source, never on generic sampling vocabulary.
_ECOTAXA_SIGNAL = re.compile(
    r"eco\s*taxa"                       # ecotaxa / eco taxa
    r"|eco\s*part"                      # ecopart / eco part
    r"|\bproje?t\s+n?[°o]?\s*\d{3,6}\b"  # "projet 17498", "project 42"
    r"|\bprojects?\s+\d{3,6}\b"
    r"|\bprj[ /]?\d{3,6}\b"             # prj/17498
    r"|obs-vlfr"                         # the EcoTaxa/EcoPart host
    r"|\bcache\s+(ecotaxa|copépode|copepode)\b"
    r"|\ble\s+cache\b|\bthe\s+cache\b",  # "le cache", "the cache" (EcoTaxa cache)
    re.IGNORECASE,
)

# Skills that drive the remote EcoTaxa navigation/query flows.
_ECOTAXA_SKILLS = {"ecotaxa_navigation", "ecotaxa_query"}


def ecotaxa_signal(text: str | None) -> bool:
    """True if the text explicitly references the EcoTaxa/EcoPart sources."""
    return bool(text) and bool(_ECOTAXA_SIGNAL.search(text))


def is_ecotaxa_scoped_tool(name: str | None) -> bool:
    """True for the EcoTaxa/EcoPart *source* tools (find/summarize/query/... )."""
    n = (name or "").lower()
    return "ecotaxa" in n or "ecopart" in n


def is_ecotaxa_skill_load(name: str | None, args: dict | None) -> bool:
    """True when the call is `load_skill(skill_name=<an EcoTaxa skill>)`."""
    if (name or "") != "load_skill":
        return False
    skill = str((args or {}).get("skill_name", "")).strip().lower()
    return skill in _ECOTAXA_SKILLS


def _message_role(message: Any) -> str:
    role = getattr(message, "type", None)
    if role is None and isinstance(message, dict):
        role = message.get("role") or message.get("type")
    return str(role or "")


def _message_text(message: Any) -> str:
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(content, list):  # some providers use content blocks
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return content if isinstance(content, str) else str(content or "")


def latest_user_text(messages: list | None) -> str:
    """Text of the most recent human/user message."""
    for message in reversed(messages or []):
        if _message_role(message) in ("human", "user"):
            return _message_text(message)
    return ""


def is_file_loaded(store: Any, thread_id: str) -> bool:
    try:
        session = store.get(thread_id)
    except Exception:
        return False
    return bool(session and session.get("df") is not None)


def is_file_scoped_turn(store: Any, thread_id: str, messages: list | None) -> bool:
    """True when the turn must stay on the loaded file (hide EcoTaxa routes).

    A file is loaded AND the latest user message carries no explicit EcoTaxa
    signal → the request is about the file.
    """
    if not is_file_loaded(store, thread_id):
        return False
    return not ecotaxa_signal(latest_user_text(messages))


def filter_tools_for_scope(tools: list, file_scoped: bool) -> list:
    """Drop EcoTaxa/EcoPart source tools when the turn is file-scoped."""
    if not file_scoped:
        return tools
    return [t for t in tools if not is_ecotaxa_scoped_tool(getattr(t, "name", ""))]


FILE_SCOPE_REDIRECT = (
    "Périmètre fichier : un fichier est chargé et la demande ne mentionne pas "
    "EcoTaxa/EcoPart. Reste sur le fichier — utilise `filter_dataframe_by_zone` "
    "pour une zone nommée, puis `run_pandas` / `run_graph` sur le DataFrame "
    "chargé. Pour passer sur EcoTaxa, l'utilisateur doit nommer explicitement "
    "EcoTaxa, un projet, ou le cache."
)
