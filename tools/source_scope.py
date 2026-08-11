"""Source-scope gate — a loaded file is the default target of searches/analyses.

Principle (see docs/e2e/cartes-samples-labrador-2026): if a file is loaded, every
"samples / échantillons / positions / stations / zone / analyse / carte" request
operates on that file. External routes are reachable when the user names a
source explicitly for its first use, then remain reachable through the
persisted source affinity until an explicit switch or a successful file load.

Generic words like "samples", "échantillons", "zone", "positions" are NOT signals
— a loaded file has samples too. This gate is enforced in code because prompt
prose alone does not hold: the model kept drifting to EcoTaxa on file-scoped
requests (scenario turns 3 & 5) despite an explicit override rule.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias, cast

SourceName: TypeAlias = Literal[
    "file",
    "ecotaxa",
    "ecopart",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
]
SourceEvidence: TypeAlias = Literal[
    "explicit_name",
    "file_loaded",
    "inherited_affinity",
    "loaded_file_default",
    "none",
]


@dataclass(frozen=True)
class SourceAffinity:
    """Persisted user selection reused by later turns."""

    active_sources: tuple[SourceName, ...]
    evidence: Literal["explicit_name", "file_loaded"]
    origin_user_text: str
    updated_at: str


@dataclass(frozen=True)
class SourceDecision:
    """Preferred source route for one turn; never a tool authorization gate."""

    primary_source: SourceName | None
    authorized_sources: tuple[SourceName, ...]
    explicit_sources: tuple[SourceName, ...]
    evidence: SourceEvidence
    needs_clarification: bool
    reason: str


_SOURCE_ORDER: tuple[SourceName, ...] = (
    "file",
    "ecotaxa",
    "ecopart",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
)
_SOURCE_PATTERNS: dict[SourceName, re.Pattern[str]] = {
    "file": re.compile(
        r"\b(?:fichier|file|tsv|csv|excel|json|parquet)\b",
        re.IGNORECASE,
    ),
    "ecotaxa": re.compile(
        r"\beco[\s-]*taxa\b|ecotaxa\.obs-vlfr\.fr",
        re.IGNORECASE,
    ),
    "ecopart": re.compile(
        r"\beco[\s-]*part\b|ecopart\.obs-vlfr\.fr",
        re.IGNORECASE,
    ),
    "amundsen": re.compile(
        r"\b(?:amundsen|amudnsen|amdunsen|amudnsne|amdunse)(?:\s+ctd)?\b|\bctd\b|"
        r"\b(?:donn\w*|ajout\w*|enrich\w*|compl[eè]t\w*|int[eé]gr\w*|"
        r"assoc\w*|reli\w*|fusion\w*|add\w*|append\w*|augment\w*|"
        r"attach\w*|merge\w*|join\w*|populate\w*|fill\w*)\b.{0,45}"
        r"\b(?:donn[eé]es?|data|measurements?\s+)?(?:env(?:iron\w*)?|"
        r"environmental\w*|hydrographi\w*|physico[- ]?chimi\w*)\b",
        re.IGNORECASE,
    ),
    # Accept common compact spellings/typos as an explicit source choice:
    # ``bioracle`` and ``bioroacle`` both mean Bio-ORACLE.
    "bio_oracle": re.compile(r"\bbio(?:[\s-]*oracle|r(?:o)?acle)\b", re.IGNORECASE),
    "ogsl": re.compile(r"\bogsl\b", re.IGNORECASE),
    "sql": re.compile(r"\bsql\b|\b(?:workspace|espace)\s+sql\b", re.IGNORECASE),
}
_NEGATION_BEFORE_SOURCE = re.compile(
    r"(?:sans|without|except|sauf|n['’]?utilise\s+pas|ne\s+pas\s+utiliser|do\s+not\s+use)\s*$",
    re.IGNORECASE,
)
_COMBINE_SIGNAL = re.compile(
    r"\b(?:compare|comparer|croise|croiser|combine|combiner)\b"
    r"|\b(?:compare|combine)\s+with\b",
    re.IGNORECASE,
)
_SWITCH_SIGNAL = re.compile(
    r"\b(?:passe\s+[àa]|switch\s+to|uniquement|only|utilise\s+plut[oô]t)\b",
    re.IGNORECASE,
)

_SOURCE_AFFINITY_SUFFIX = "source_affinity"
_EXTERNAL_SOURCES = frozenset({
    "ecotaxa",
    "ecopart",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
})
# Source tools are visible only when their source is active.  A persisted
# EcoTaxa selection keeps that source affinity for a follow-up export; a plain
# local-file turn must not carry an unrelated remote export schema.
_ALWAYS_EXPOSED_SOURCE_TOOLS = frozenset()
_SOURCE_LABELS: dict[SourceName, str] = {
    "file": "fichier",
    "ecotaxa": "EcoTaxa",
    "ecopart": "EcoPart",
    "amundsen": "Amundsen CTD",
    "bio_oracle": "Bio-ORACLE",
    "ogsl": "OGSL",
    "sql": "SQL",
}


def render_source_selection_gateway() -> str:
    """Render the model-facing explanation of the executable source policy."""
    external_labels = ", ".join(
        _SOURCE_LABELS[source]
        for source in ("ecotaxa", "ecopart", "amundsen", "bio_oracle", "ogsl", "sql")
    )
    return f"""## Source Selection Gateway
Apply before any domain/graph/source rule.
- A loaded file is the default source for generic sample, position, station,
  taxon, map, analysis or zone requests. Generic words are never external-source
  signals.
- Prefer an explicitly named external source: {external_labels}. Once selected,
  it remains the preferred route on following turns for grounded follow-ups.
- New file -> sole source for implicit follow-ups. External access resumes only
  when explicitly named. Active source changes when the user names another source,
  explicitly combines sources, or a newly loaded file becomes the active source.
- A source explicitly named in the current request is primary. If a file is
  already loaded, it remains available as a secondary source; it does not
  shadow a new external search. The file is primary only when it is named in
  the request, or when the request is implicit. An enrichment request replaces
  stale external affinity with its named source(s).
- A project number alone is not an EcoTaxa signal. With no owning source, ask.
  With no file, affinity or named source, ask for a file or source; never choose
  an online source.
- This route is guidance, never a tool filter. If an analysis reveals that a
  missing table or column belongs to another available source, retrieve it and
  resume without asking the user to repeat the request.
- Explicit exclusions remove a source from the preferred route. A restriction persists
  across turns until the user explicitly releases it; passive mentions, history
  and assistant text do not release it.
- Source-specific rules apply when the source is selected or needed to satisfy
  a verified data dependency."""


SOURCE_SELECTION_GATEWAY = render_source_selection_gateway()


def _source_mentions(text: str | None) -> tuple[tuple[SourceName, ...], tuple[SourceName, ...]]:
    normalized = text or ""
    explicit: list[SourceName] = []
    excluded: list[SourceName] = []
    for source in _SOURCE_ORDER:
        matches = list(_SOURCE_PATTERNS[source].finditer(normalized))
        if not matches:
            continue
        positive = False
        negative = False
        for match in matches:
            prefix = normalized[max(0, match.start() - 40):match.start()]
            if _NEGATION_BEFORE_SOURCE.search(prefix):
                negative = True
            else:
                positive = True
        if positive:
            explicit.append(source)
        if negative:
            excluded.append(source)
    return tuple(explicit), tuple(excluded)


def parse_explicit_sources(text: str | None) -> tuple[SourceName, ...]:
    """Return only positively and explicitly named sources."""
    explicit, _ = _source_mentions(text)
    return explicit


def _ordered_unique(values: list[SourceName]) -> tuple[SourceName, ...]:
    return tuple(dict.fromkeys(values))


def decide_source(
    text: str | None,
    affinity: SourceAffinity | None,
    file_loaded: bool,
) -> SourceDecision:
    """Compute one deterministic source decision without reading session state."""
    normalized = text or ""
    explicit, excluded = _source_mentions(normalized)
    inherited = [
        source
        for source in (affinity.active_sources if affinity else ())
        if source not in excluded
    ]

    if explicit:
        if _COMBINE_SIGNAL.search(normalized) and not _SWITCH_SIGNAL.search(normalized):
            selected = _ordered_unique([*inherited, *explicit])
        else:
            selected = explicit
        evidence: SourceEvidence = "explicit_name"
    elif inherited:
        selected = tuple(inherited)
        evidence = "inherited_affinity"
    elif file_loaded:
        selected = ("file",)
        evidence = "loaded_file_default"
    else:
        selected = ()
        evidence = "none"

    if file_loaded:
        if explicit:
            # A named source is the user's current focus. Keep a loaded file
            # available for a later comparison/enrichment, but append it so it
            # cannot shadow a new external search (for example a new region
            # after an earlier export remains in the session).
            if "file" not in selected:
                selected = (*selected, "file")
        else:
            # A file loaded *after* an external exploration takes over as
            # usual. Conversely, ``("file", external)`` records an external
            # source explicitly selected to enrich this very file: retain it
            # for terse confirmations such as "oui, 2050".
            inherited_file_enrichment = (
                "file" in inherited
                and any(source in _EXTERNAL_SOURCES for source in inherited)
            )
            if inherited_file_enrichment:
                selected = tuple(inherited)
                evidence = "inherited_affinity"
            else:
                selected = ("file",)
                evidence = "loaded_file_default"
    selected = tuple(source for source in selected if source not in excluded)
    primary = selected[0] if selected else None
    return SourceDecision(
        primary_source=primary,
        authorized_sources=selected,
        explicit_sources=explicit,
        evidence=evidence,
        needs_clarification=not selected,
        reason=(
            "Source préférée par la sélection explicite ou son affinité."
            if selected
            else "Aucune source explicite, active ou fichier chargé."
        ),
    )


def source_affinity_key(thread_id: str) -> str:
    """Return the dedicated metadata key for one conversation affinity."""
    return f"{thread_id}:{_SOURCE_AFFINITY_SUFFIX}"


def read_source_affinity(store: Any, thread_id: str) -> SourceAffinity | None:
    """Load a validated affinity; corrupt or unknown values fail closed."""
    try:
        entry = store.get(source_affinity_key(thread_id))
        raw = ((entry or {}).get("meta") or {}).get("source_affinity")
        if not isinstance(raw, dict):
            return None
        sources = raw.get("active_sources")
        if not isinstance(sources, (list, tuple)) or not sources:
            return None
        if any(source not in _SOURCE_ORDER for source in sources):
            return None
        evidence = raw.get("evidence")
        if evidence not in ("explicit_name", "file_loaded"):
            return None
        origin = raw.get("origin_user_text")
        updated_at = raw.get("updated_at")
        if not isinstance(origin, str) or not isinstance(updated_at, str):
            return None
        return SourceAffinity(
            active_sources=cast(tuple[SourceName, ...], tuple(sources)),
            evidence=cast(Literal["explicit_name", "file_loaded"], evidence),
            origin_user_text=origin,
            updated_at=updated_at,
        )
    except Exception:
        return None


def write_source_affinity(
    store: Any,
    thread_id: str,
    affinity: SourceAffinity,
) -> SourceAffinity:
    """Persist one validated source selection without touching dataset state."""
    if not affinity.active_sources or any(
        source not in _SOURCE_ORDER for source in affinity.active_sources
    ):
        raise ValueError("SourceAffinity contains an unsupported source")
    store.set(
        source_affinity_key(thread_id),
        None,
        {"source_affinity": asdict(affinity)},
    )
    return affinity


def _new_affinity(
    sources: tuple[SourceName, ...],
    evidence: Literal["explicit_name", "file_loaded"],
    origin_user_text: str,
) -> SourceAffinity:
    cleaned = " ".join(str(origin_user_text).split())[:240]
    return SourceAffinity(
        active_sources=sources,
        evidence=evidence,
        origin_user_text=cleaned,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _persist_if_changed(
    store: Any,
    thread_id: str,
    candidate: SourceAffinity,
) -> SourceAffinity:
    current = read_source_affinity(store, thread_id)
    if current and (
        current.active_sources == candidate.active_sources
        and current.evidence == candidate.evidence
        and current.origin_user_text == candidate.origin_user_text
    ):
        return current
    return write_source_affinity(store, thread_id, candidate)


def activate_file_source(
    store: Any,
    thread_id: str,
    *,
    origin_user_text: str = "file loaded",
) -> SourceAffinity:
    """Make a successfully loaded file the new conversation source."""
    return _persist_if_changed(
        store,
        thread_id,
        _new_affinity(("file",), "file_loaded", origin_user_text),
    )


def _canonical_file_is_loaded(store: Any, thread_id: str) -> bool:
    try:
        loaded = store.get(f"{thread_id}:loaded_file")
        if loaded and loaded.get("df") is not None:
            return True
    except Exception:
        return False
    return is_file_loaded(store, thread_id)


def source_decision_for_turn(
    store: Any,
    thread_id: str,
    messages: list | None,
    *,
    persist: bool = True,
) -> SourceDecision:
    """Build and optionally persist the decision for the latest user turn."""
    text = latest_user_text(messages)
    affinity = read_source_affinity(store, thread_id)
    decision = decide_source(
        text,
        affinity,
        file_loaded=_canonical_file_is_loaded(store, thread_id),
    )
    if not persist:
        return decision

    explicit, excluded = _source_mentions(text)
    if explicit or excluded:
        if decision.authorized_sources:
            _persist_if_changed(
                store,
                thread_id,
                _new_affinity(
                    decision.authorized_sources,
                    "explicit_name",
                    text,
                ),
            )
        elif affinity is not None:
            try:
                store.clear(source_affinity_key(thread_id))
            except Exception:
                pass
    return decision


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
        loaded_file = store.get(f"{thread_id}:loaded_file")
        if loaded_file and loaded_file.get("df") is not None:
            return True
        session = store.get(thread_id)
    except Exception:
        return False
    if not session or session.get("df") is None:
        return False
    source = (session.get("meta") or {}).get("source")
    if source is None:
        # Preserve the legacy contract for lightweight stores that only expose
        # a dataframe and no provenance metadata.
        return True
    return str(source).startswith("file:")
