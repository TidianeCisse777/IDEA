from __future__ import annotations

import re


_PUNCTUATION_SPACE_RE = re.compile(r"([,;:!?])(?=[A-Za-zÀ-ÿ])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_THREE_PLUS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_FILENAME_RE = re.compile(r"\b(?P<filename>[\w()''+-][\w .()''+-]*\.(?:csv|tsv|txt))\b", re.IGNORECASE)
_DIMENSIONS_RE = re.compile(
    r"(?P<rows>[\d\s ]+)\s*(?:lignes?|rows?)?\s*×\s*(?P<cols>\d+)\s*(?:colonnes?|cols?)?",
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

# Universal glue-repair patterns.
#
# Pattern A — backtick span fused directly to a preceding word char.
#   Detected during _save() so the space is injected before protection removes visibility.
#
# Pattern B — known domain identifier (snake_case) fused to a preceding word without backticks.
#   Uses a domain prefix whitelist to anchor at a real token boundary rather than greedily
#   matching from the leftmost letter (which would split inside French words).
#
# Pattern C — encoding token (utf-8, Windows-1252, …) fused to a preceding letter.
_BT_SPAN_RE = re.compile(r"`[^`\n]+`")
_GLUED_IDENTIFIER_RE = re.compile(
    r"(?<=[a-zA-ZÀ-ÿ])"
    r"((?:obj|ctd|uvp|acq|lat|lon|sal|vel|id"
    r"|temp|dens|pres|depth|sigma|match|total|valid|count|cast|flow|date|time|file"
    r"|sample|source|profile|station|analysis|project|nearest|interval)"
    r"(?:_[a-zA-Z0-9_.]+)+)",
)
_GLUED_ENCODING_RE = re.compile(
    r"(?<=[a-zA-ZÀ-ÿ])(Windows-\d+|utf-8|UTF-8|cp\d+|latin1|iso8859-\d+)",
)


def _fix_glued_identifiers(line: str) -> str:
    """Insert a space before any backtick span or known identifier fused directly to a preceding word."""
    store: list[str] = []

    def _save(m: re.Match[str]) -> str:
        idx = len(store)
        store.append(m.group(0))
        start = m.start()
        # Pattern A: span directly preceded by a word char → inject space before the placeholder.
        space = " " if start > 0 and line[start - 1].isalnum() else ""
        return f"{space}\x00BT{idx}\x00"

    protected = _BT_SPAN_RE.sub(_save, line)
    # Pattern B: known domain identifier glued to preceding word
    protected = _GLUED_IDENTIFIER_RE.sub(lambda m: f" `{m.group(1)}`", protected)
    # Pattern C: encoding token glued to preceding word
    protected = _GLUED_ENCODING_RE.sub(lambda m: f" `{m.group(1)}`", protected)

    def _restore(m: re.Match[str]) -> str:
        return store[int(m.group(1))]

    return re.sub(r"\x00BT(\d+)\x00", _restore, protected)


def _wrap_technical_token(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        return value
    return f"`{value.strip('`')}`"


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
    no_blocker = bool(re.search(r"aucune\s+erreur\s+bloquante|pas\s+d['’]erreur\s+bloquante", normalized, re.IGNORECASE))

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
    lines, restores obvious punctuation-spacing misses, and repairs identifiers
    fused directly to preceding words.
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
        normalized = _fix_glued_identifiers(normalized)
        normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()

        if normalized == previous_text_line:
            continue

        out.append(normalized)
        previous_text_line = normalized

    formatted = "\n".join(out).strip()
    formatted = _THREE_PLUS_BLANK_LINES_RE.sub("\n\n", formatted)
    return formatted
