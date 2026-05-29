from __future__ import annotations

import base64
import os
import re
from collections.abc import Iterable, Iterator
from typing import Any


_MARKDOWN_PY_FENCE_RE = re.compile(
    r"```(?:python|py)\b[^\n]*\n[\s\S]*?```",
    re.DOTALL,
)
_MARKDOWN_PY_FENCE_OPEN_RE = re.compile(r"```(?:python|py)\b")


def _text_after_execute_block(content: str) -> str:
    """Return any text that follows a to=execute code='...' block."""
    # Matches to=execute code='''...''' or to=execute code='...'
    m = re.search(r"^to=execute\s+code=(?:'{3}.*?'{3}|\"\"\".*?\"\"\"|'[^']*'|\"[^\"]*\")",
                  content.lstrip(), re.DOTALL)
    if m:
        tail = content.lstrip()[m.end():].strip()
        return tail
    return ""


def _salvage_tail(content: str) -> str:
    """Return trailing text after a suppressed code block (either format)."""
    tail = _text_after_execute_block(content)
    if not tail:
        tail = _text_after_json_code_block(content)
    return tail


def _is_raw_code_block(content: str) -> bool:
    """True if the assistant message is a raw OI code block that should be hidden."""
    stripped = content.lstrip()
    return stripped.startswith("to=execute") or stripped.startswith('{"language":')


def _has_python_markdown_fence(content: str) -> bool:
    """True if the content contains a ```python or ```py fenced code block."""
    return bool(_MARKDOWN_PY_FENCE_OPEN_RE.search(content))


def _strip_python_markdown_fences(content: str) -> str:
    """Remove ```python / ```py fenced blocks. Surrounding prose is preserved."""
    cleaned = _MARKDOWN_PY_FENCE_RE.sub("", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clean_assistant_text(content: str) -> str:
    """Strip raw OI code blocks and python markdown fences. Returns prose only.

    Order matters: raw blocks (to=execute / JSON) are detected from the start
    of the message; if present, only the salvaged tail is returned. Otherwise
    we strip any ```python / ```py fences and keep the surrounding text.
    """
    if _is_raw_code_block(content):
        return _salvage_tail(content)
    if _has_python_markdown_fence(content):
        return _strip_python_markdown_fences(content)
    return content


def _text_after_json_code_block(content: str) -> str:
    """Return any text that follows a {"language":"...","code":"..."} block."""
    stripped = content.lstrip()
    if not stripped.startswith('{"language":'):
        return ""
    depth = 0
    in_string = False
    escape = False
    for i, c in enumerate(stripped):
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return stripped[i + 1:].strip()
    return ""


def chat_stream_events(interpreter_chunks: Iterable[Any]) -> Iterator[Any]:
    """Transform interpreter chunks into UI stream events.

    Assistant text messages are buffered to completion, then any embedded code
    representation is stripped from the displayable text. Three formats are
    handled:
      * OI native:        to=execute code="..."          → entire block dropped, trailing prose kept
      * JSON tool call:   {"language":"python","code":"..."} → entire block dropped, trailing prose kept
      * Markdown fence:   ```python ... ``` / ```py ... ``` → fence dropped, prose around it kept

    The type:code event emitted by OI for execution is the single authoritative
    code surface — keeping fences in the prose duplicates it on screen as
    "Voir le code" alongside "Code exécuté".

    Non-assistant-message chunks pass through unchanged.
    """
    msg_buf_content = ""           # accumulated content for current assistant message
    in_assistant_msg = False

    for chunk in interpreter_chunks:
        _get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)

        # Drop bare tool_call chunks
        if _get("tool_calls") is not None and _get("type") is None:
            continue

        role = _get("role") or ""
        ctype = _get("type") or ""
        is_start = bool(_get("start"))
        is_end = bool(_get("end"))
        content = _get("content") or ""
        if not isinstance(content, str):
            content = ""

        if role == "assistant" and ctype == "message":
            if is_start:
                msg_buf_content = content
                in_assistant_msg = True
                # Don't yield the start marker yet — wait until end so we can
                # decide whether the cleaned content is non-empty.
                if is_end:
                    cleaned = _clean_assistant_text(msg_buf_content)
                    if cleaned:
                        yield {"start": True, "end": True, "role": "assistant",
                               "type": "message", "content": cleaned}
                    msg_buf_content = ""
                    in_assistant_msg = False
            elif in_assistant_msg:
                msg_buf_content += content
                if is_end:
                    cleaned = _clean_assistant_text(msg_buf_content)
                    if cleaned:
                        yield {"start": True, "end": True, "role": "assistant",
                               "type": "message", "content": cleaned}
                    msg_buf_content = ""
                    in_assistant_msg = False
            else:
                # Stray message chunk outside a start/end pair — pass through
                yield chunk
        else:
            # Non-assistant-message chunk — close any open assistant buffer first
            if in_assistant_msg and msg_buf_content:
                cleaned = _clean_assistant_text(msg_buf_content)
                if cleaned:
                    yield {"start": True, "end": True, "role": "assistant",
                           "type": "message", "content": cleaned}
                msg_buf_content = ""
                in_assistant_msg = False

            # Auto-display PNG saved via plt.savefig when model prints "Saved figure: /path"
            if role == "computer" and ctype == "console" and is_end is False and not is_start:
                if isinstance(content, str) and "Saved figure:" in content:
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("Saved figure:"):
                            png_path = line[len("Saved figure:"):].strip()
                            if png_path.endswith(".png") and os.path.isfile(png_path):
                                try:
                                    with open(png_path, "rb") as f:
                                        b64 = base64.b64encode(f.read()).decode()
                                    yield {"start": True, "end": True, "role": "computer", "type": "image", "format": "base64.png", "content": b64}
                                except Exception:
                                    pass

            yield chunk

    # Flush trailing assistant buffer if the stream ended mid-message
    if in_assistant_msg and msg_buf_content:
        cleaned = _clean_assistant_text(msg_buf_content)
        if cleaned:
            yield {"start": True, "end": True, "role": "assistant",
                   "type": "message", "content": cleaned}
