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
    """Executable source authorization for one user turn."""

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
    "amundsen": re.compile(r"\bamundsen(?:\s+ctd)?\b", re.IGNORECASE),
    "bio_oracle": re.compile(r"\bbio[\s-]*oracle\b", re.IGNORECASE),
    "ogsl": re.compile(r"\bogsl\b", re.IGNORECASE),
    "sql": re.compile(r"\bsql\b|\b(?:workspace|espace)\s+sql\b", re.IGNORECASE),
}
_NEGATION_BEFORE_SOURCE = re.compile(
    r"(?:sans|without|except|sauf|n['’]?utilise\s+pas|ne\s+pas\s+utiliser|do\s+not\s+use)\s*$",
    re.IGNORECASE,
)
_COMBINE_SIGNAL = re.compile(
    r"\b(?:compare|comparer|croise|croiser|combine|combiner|enrichis|enrichir)\b"
    r"|\b(?:compare|combine|enrich)\s+with\b",
    re.IGNORECASE,
)
_SWITCH_SIGNAL = re.compile(
    r"\b(?:passe\s+[àa]|switch\s+to|uniquement|only|utilise\s+plut[oô]t)\b",
    re.IGNORECASE,
)

# Skills that drive the remote EcoTaxa navigation/query flows.
_ECOTAXA_SKILLS = {"ecotaxa_navigation", "ecotaxa_query"}
_SOURCE_AFFINITY_SUFFIX = "source_affinity"
_EXTERNAL_SOURCES = frozenset({
    "ecotaxa",
    "ecopart",
    "amundsen",
    "bio_oracle",
    "ogsl",
    "sql",
})
_SOURCE_SKILLS: dict[str, SourceName] = {
    "ecotaxa_navigation": "ecotaxa",
    "ecotaxa_query": "ecotaxa",
    "ecopart_query": "ecopart",
    "amundsen_ctd_query": "amundsen",
    "bio_oracle_query": "bio_oracle",
    "sql_workspace_query": "sql",
}
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
Apply this gateway before every domain, graph, or source-specific rule.
- A loaded file is the default source for generic requests about samples, positions, stations, taxa, maps, analyses, or named zones.
- Generic words are never external-source signals: sample, échantillon, station, zone, project, temperature, environment, map, where, and their variants do not authorize an online source.
- On first use, an external source must be named explicitly. Selectable external sources are: {external_labels}.
- Once explicitly selected, that source remains active on following turns. The user does not need to repeat its name for grounded follow-ups.
- The active source changes only when the user asks to name another source, explicitly combines sources, or a newly loaded file becomes the active source.
- A project number alone is not an EcoTaxa signal. With no active source owning it, ask which source owns it.
- With no loaded file, no active affinity, and no explicitly named source, ask the user to provide a file or choose a source. Do not select an online source yourself.
- If a file is loaded and an external source is explicitly requested, keep the file primary and use that source only for the requested secondary operation. Never replace or relabel the file as external-source data.
- Explicit exclusions such as \"without EcoTaxa\" remove that source and never activate it.
- An explicit source restriction persists across turns until the user explicitly releases it. Passive mentions, quotations, tool history, and assistant text do not release it.
- Source-specific rules below apply only after this gateway authorizes that source. Examples inside a source section illustrate procedures; they are not activation triggers."""


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

    if file_loaded and selected and "file" not in selected:
        selected = ("file", *selected)
    selected = tuple(source for source in selected if source not in excluded)
    primary = "file" if "file" in selected else (selected[0] if selected else None)
    return SourceDecision(
        primary_source=primary,
        authorized_sources=selected,
        explicit_sources=explicit,
        evidence=evidence,
        needs_clarification=not selected,
        reason=(
            "Source autorisée par la sélection explicite ou son affinité."
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


def source_for_tool_call(
    name: str | None,
    args: dict | None,
    policies: Any,
) -> SourceName | None:
    """Classify an external-source tool call from the catalog policy."""
    normalized_name = str(name or "")
    if normalized_name == "load_skill":
        skill_name = str((args or {}).get("skill_name", "")).strip().lower()
        return _SOURCE_SKILLS.get(skill_name)
    policy = policies.get(normalized_name) if policies is not None else None
    source = getattr(policy, "source", None)
    if source in _EXTERNAL_SOURCES:
        return cast(SourceName, source)
    return None


def filter_tools_for_decision(
    tools: list,
    decision: SourceDecision,
    policies: Any,
) -> list:
    """Hide tools belonging to external sources not authorized this turn."""
    authorized = set(decision.authorized_sources)
    return [
        item
        for item in tools
        if (
            (source := source_for_tool_call(getattr(item, "name", ""), {}, policies))
            is None
            or source in authorized
        )
    ]


def source_rejection_for_call(
    decision: SourceDecision,
    name: str | None,
    args: dict | None,
    policies: Any,
) -> str | None:
    """Return a clinical refusal for an unauthorized external source call."""
    source = source_for_tool_call(name, args, policies)
    if source is None or source in decision.authorized_sources:
        return None
    label = _SOURCE_LABELS[source]
    active = ", ".join(
        _SOURCE_LABELS[item] for item in decision.authorized_sources
    ) or "aucune"
    return (
        f"Source bloquée : {label} n'est pas autorisée pour ce tour. "
        f"Source active : {active}. L'utilisateur doit nommer {label} "
        "explicitement avant sa première utilisation."
    )


def ecotaxa_signal(text: str | None) -> bool:
    """Compatibility facade for an explicit EcoTaxa/EcoPart source name."""
    return bool({"ecotaxa", "ecopart"}.intersection(parse_explicit_sources(text)))


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
