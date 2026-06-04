from __future__ import annotations

import re


_PUNCTUATION_SPACE_RE = re.compile(r"([,;:!?])(?=[A-Za-zÀ-ÿ])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_THREE_PLUS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_SOURCE_TYPE_JOIN_RE = re.compile(r"\bsource_type([A-Za-z][A-Za-z0-9_]*)(?=;|,|\.|\s|$)")
_COMMON_TECH_TOKEN_RE = re.compile(
    r"\b(entre|et|avec|sur|pour|via)"
    r"(profile_join_keys|safe_for_join_deliverable|[A-Z][A-Z0-9_]{2,}|[a-z][a-z0-9_]*_[a-z0-9_]+)"
    r"\b"
)
_ENCODING_JOIN_RE = re.compile(r"\ben(Windows-\d+|utf-8|UTF-8|cp\d+|latin1|iso8859-\d+)\b")
_COLON_TECH_LIST_RE = re.compile(
    r"(: )(`?[A-Za-z][A-Za-z0-9_]*(?:`?\s*,\s*`?[A-Za-z][A-Za-z0-9_]*)+`?)(?=\.|;|$)"
)
_FILENAME_RE = re.compile(r"\b(?P<filename>[\w()’’+-][\w .()’’+-]*\.(?:csv|tsv|txt))\b", re.IGNORECASE)
_DIMENSIONS_RE = re.compile(
    r"(?P<rows>[\d\s\u202f]+)\s*(?:lignes?|rows?)?\s*×\s*(?P<cols>\d+)\s*(?:colonnes?|cols?)?",
    re.IGNORECASE,
)
_SOURCE_RE = re.compile(
    r"source\s+d[ée]tect[ée]e?\s*`?(?P<source>[A-Za-z][A-Za-z0-9_]*)`?",
    re.IGNORECASE,
)
_CONFIDENCE_RE = re.compile(
    r"(?:confiance|confidence)\s*[:=]?\s*`?(?P<confidence>[A-Za-z][A-Za-z0-9_]*)`?",
    re.IGNORECASE,
)
_ENCODING_RE = re.compile(r"encodage\s*`?(?P<encoding>[A-Za-z0-9_-]+)`?", re.IGNORECASE)
_INSPECTION_COLUMNS_RE = re.compile(
    r"Colonnes\s+(?:cl[ée]s\s+d[ée]j[àa]\s+reconnues|de\s+r[ée]f[ée]rence\s+disponibles|utiles|cl[ée]s)\s*:\s*(?P<columns>[^.]+)",
    re.IGNORECASE,
)
_UNCLEAR_RE = re.compile(
    r"(?:Colonne\s+(?:encore\s+)?[àa]\s+clarifier\s+si\s+n[ée]cessaire\s*:\s*`?(?P<label>[A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+|[A-Za-z][A-Za-z0-9_]*)`?)"
    r"|(?:Blocage\s+restant\s*:\s*`?(?P<blocker>[A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+|[A-Za-z][A-Za-z0-9_]*)`?)"
    r"|(?:`?(?P<prose>[A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+)`?\s+reste\s+[àa]\s+clarifier)",
    re.IGNORECASE,
)


def _wrap_technical_token(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        return value
    return f"`{value.strip('`')}`"


def _wrap_technical_list(match: re.Match[str]) -> str:
    prefix, raw_items = match.groups()
    items = [item.strip().strip("`") for item in raw_items.split(",")]
    return prefix + ", ".join(_wrap_technical_token(item) for item in items if item)


def _repair_copepod_plan_spacing(line: str) -> str:
    """Repair common LLM spacing misses around copepod technical identifiers."""
    line = _SOURCE_TYPE_JOIN_RE.sub(
        lambda m: f"source_type {_wrap_technical_token(m.group(1))}",
        line,
    )
    line = _COMMON_TECH_TOKEN_RE.sub(
        lambda m: f"{m.group(1)} {_wrap_technical_token(m.group(2))}",
        line,
    )
    line = _ENCODING_JOIN_RE.sub(
        lambda m: f"en {_wrap_technical_token(m.group(1))}",
        line,
    )
    line = _COLON_TECH_LIST_RE.sub(_wrap_technical_list, line)
    return line


def _format_compact_inspection_summary(text: str) -> str | None:
    if "inspection terminée" not in text.lower():
        return None

    normalized = _PUNCTUATION_SPACE_RE.sub(r"\1 ", text)
    normalized = re.sub(r"\bde(?=\d)", "de ", normalized)
    normalized = re.sub(r"\bdétectée(?=[A-Za-z_])", "détectée ", normalized)
    normalized = re.sub(r"\bconfiance(?=[A-Za-z_])", "confiance ", normalized)
    normalized = re.sub(r"\bencodage(?=[A-Za-z0-9_-])", "encodage ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    filename_match = _FILENAME_RE.search(normalized)
    dimensions_match = _DIMENSIONS_RE.search(normalized)
    if not filename_match or not dimensions_match:
        return None

    source_match = _SOURCE_RE.search(normalized)
    confidence_match = _CONFIDENCE_RE.search(normalized)
    encoding_match = _ENCODING_RE.search(normalized)
    columns_match = _INSPECTION_COLUMNS_RE.search(normalized)
    unclear_match = _UNCLEAR_RE.search(normalized)
    no_blocker = bool(re.search(r"aucune\s+erreur\s+bloquante|pas\s+d[’']erreur\s+bloquante", normalized, re.IGNORECASE))

    rows = re.sub(r"\s+", "", dimensions_match.group("rows"))
    filename = re.sub(
        r"^Inspection\s+termin[ée]e?\s+(?:pour\s+)?",
        "",
        filename_match.group("filename").strip(),
        flags=re.IGNORECASE,
    ).strip()
    key_columns = []
    if columns_match:
        key_columns = [
            item.strip().strip("`")
            for item in columns_match.group("columns").split(",")
            if item.strip()
        ]

    lines = [
        "**Inspection**",
        f"- Fichier : {_wrap_technical_token(filename)}",
    ]
    if re.search(r"\best un CSV\b|format\s*:\s*csv", normalized, re.IGNORECASE):
        format_label = "Format : CSV"
    elif re.search(r"\best un TSV\b|format\s*:\s*tsv", normalized, re.IGNORECASE):
        format_label = "Format : TSV"
    else:
        format_label = "Dimensions"
    if format_label.startswith("Format"):
        lines.append(f"- {format_label}, {rows} × {dimensions_match.group('cols')}")
    else:
        lines.append(f"- {format_label} : {rows} × {dimensions_match.group('cols')}")
    if source_match:
        source_line = f"- Source détectée : {_wrap_technical_token(source_match.group('source'))}"
        if confidence_match:
            confidence = confidence_match.group("confidence")
            if confidence.lower() in {"high", "medium", "low", "reliable", "unknown"}:
                confidence = _wrap_technical_token(confidence)
            source_line += f" (confiance : {confidence})"
        lines.append(source_line)
    if encoding_match:
        lines.append(f"- Encodage : {_wrap_technical_token(encoding_match.group('encoding'))}")
    if key_columns:
        lines.append("- Colonnes clés : " + ", ".join(_wrap_technical_token(col) for col in key_columns))
    if unclear_match:
        unclear = unclear_match.group("label") or unclear_match.group("blocker") or unclear_match.group("prose")
        lines.append(f"- À clarifier si nécessaire : {_wrap_technical_token(unclear)}")
    if no_blocker:
        lines.append("- Statut : aucune erreur bloquante.")
    return "\n".join(lines)


def format_assistant_text(text: str) -> str:
    """Normalize assistant prose without touching fenced code blocks.

    The formatter is intentionally conservative: it trims trailing whitespace,
    collapses repeated blank lines, removes exact consecutive duplicate prose
    lines, and restores obvious punctuation-spacing misses such as
    ``bonjour,monde`` → ``bonjour, monde``.
    """
    if not isinstance(text, str):
        return ""

    compact_inspection = _format_compact_inspection_summary(text)
    if compact_inspection:
        return compact_inspection

    out: list[str] = []
    in_fence = False
    previous_text_line = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if line.startswith("```"):
            out.append(line)
            in_fence = not in_fence
            continue

        if in_fence:
            out.append(line)
            continue

        if not line:
            if out and out[-1] == "":
                continue
            out.append("")
            continue

        normalized = _PUNCTUATION_SPACE_RE.sub(r"\1 ", line)
        normalized = _repair_copepod_plan_spacing(normalized)
        normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()

        if normalized == previous_text_line:
            continue

        out.append(normalized)
        previous_text_line = normalized

    formatted = "\n".join(out).strip()
    formatted = _THREE_PLUS_BLANK_LINES_RE.sub("\n\n", formatted)
    return formatted
