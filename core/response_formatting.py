from __future__ import annotations

import re


_PUNCTUATION_SPACE_RE = re.compile(r"([,;:!?])(?=[A-Za-zÀ-ÿ])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_THREE_PLUS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def format_assistant_text(text: str) -> str:
    """Normalize assistant prose without touching fenced code blocks.

    The formatter is intentionally conservative: it trims trailing whitespace,
    collapses repeated blank lines, removes exact consecutive duplicate prose
    lines, and restores obvious punctuation-spacing misses such as
    ``bonjour,monde`` → ``bonjour, monde``.
    """
    if not isinstance(text, str):
        return ""

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
        normalized = _MULTI_SPACE_RE.sub(" ", normalized).strip()

        if normalized == previous_text_line:
            continue

        out.append(normalized)
        previous_text_line = normalized

    formatted = "\n".join(out).strip()
    formatted = _THREE_PLUS_BLANK_LINES_RE.sub("\n\n", formatted)
    return formatted
