from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Iterable, Iterator
from typing import Any


_MARKDOWN_PY_FENCE_RE = re.compile(
    r"```(?:python|py)\b[^\n]*\n[\s\S]*?```",
    re.DOTALL,
)
_MARKDOWN_PY_FENCE_OPEN_RE = re.compile(r"```(?:python|py)\b")
# Some LLMs emit OI's JSON tool call wrapped in a ```json fence:
#   ```json
#   {"language":"python","code":"..."}
#   ```
# OI parses the JSON internally for execution, but the markdown text still
# leaks to the UI and gets rendered as a code block. Detect and strip it too.
_MARKDOWN_JSON_TOOLCALL_FENCE_RE = re.compile(
    r"```json\b[^\n]*\n\s*\{\s*\"language\"\s*:[\s\S]*?\}\s*\n?```",
    re.DOTALL,
)
_MARKDOWN_JSON_TOOLCALL_OPEN_RE = re.compile(
    r"```json\b[^\n]*\n\s*\{\s*\"language\"\s*:",
)


def _path_to_static_url(path: str) -> str:
    """Convert /app/static/... or ./static/... to /static/... for browser download."""
    path = path.strip()
    if path.startswith("/app/static/"):
        return path[len("/app"):]
    if path.startswith("./static/"):
        return path[1:]
    if path.startswith("static/"):
        return "/" + path
    return ""


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
    if stripped.startswith("to=execute") or stripped.startswith('{"language":'):
        return True
    # LLM sometimes emits raw Python (no fences) for the inspect_and_report call
    if stripped.startswith("_ir = inspect_and_report("):
        return True
    return False


def _has_python_markdown_fence(content: str) -> bool:
    """True if the content contains a ```python/```py block or a ```json
    block wrapping an OI {"language":...,"code":...} tool call."""
    if _MARKDOWN_PY_FENCE_OPEN_RE.search(content):
        return True
    return bool(_MARKDOWN_JSON_TOOLCALL_OPEN_RE.search(content))


def _strip_python_markdown_fences(content: str) -> str:
    """Remove executable fenced blocks (```python/```py and ```json tool-call
    wrappers). Surrounding prose is preserved."""
    cleaned = _MARKDOWN_PY_FENCE_RE.sub("", content)
    cleaned = _MARKDOWN_JSON_TOOLCALL_FENCE_RE.sub("", cleaned)
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

    Console output starting with "# RAPPORT D'INSPECTION" is buffered and
    re-emitted as an ASSISTANT MESSAGE (markdown-rendered, outside the
    exec-block) instead of as raw computer/console output. This makes the
    inspection report appear AFTER the "Code exécuté" wrapper, properly
    rendered as a markdown document.

    Non-assistant-message chunks pass through unchanged.
    """
    msg_buf_content = ""           # accumulated content for current assistant message
    in_assistant_msg = False
    console_buf_content = ""       # accumulated content for current computer console message
    in_console_msg = False
    console_fmt = ""
    pending_assistant_tail = ""
    backend_closing_emitted = False  # True after %%CLOSING%% — suppress subsequent LLM messages

    def _is_fixed_upload_question(text: str) -> bool:
        return text.strip() == "Quel graphique souhaitez-vous ?"

    def _emit_pending_assistant_tail():
        nonlocal pending_assistant_tail
        if pending_assistant_tail:
            yield {"start": True, "end": True, "role": "assistant",
                   "type": "message", "content": pending_assistant_tail}
            pending_assistant_tail = ""

    def _emit_or_defer_assistant_text(original: str):
        nonlocal pending_assistant_tail
        if backend_closing_emitted:
            return
        cleaned = _clean_assistant_text(original)
        if not cleaned:
            return
        if _is_fixed_upload_question(cleaned) and (
            _is_raw_code_block(original) or _has_python_markdown_fence(original)
        ):
            pending_assistant_tail = cleaned.strip()
            return
        yield {"start": True, "end": True, "role": "assistant",
               "type": "message", "content": cleaned}

    def _flush_assistant_buf():
        nonlocal msg_buf_content, in_assistant_msg
        if in_assistant_msg and msg_buf_content and not backend_closing_emitted:
            yield from _emit_or_defer_assistant_text(msg_buf_content)
        msg_buf_content = ""
        in_assistant_msg = False

    def _emit_console_buf():
        """Yield the buffered console content. Reports go out as assistant
        markdown messages; everything else stays as a normal console chunk
        so the frontend routes it into the exec-block.

        Multiple RAPPORT D'INSPECTION blocks in a single console output are
        split and each emitted as a separate assistant message so the frontend
        renders them as individual collapsible bubbles.
        """
        nonlocal console_buf_content, in_console_msg, console_fmt, backend_closing_emitted
        buf = console_buf_content
        if buf and "# RAPPORT D'INSPECTION" in buf:
            # Split on every RAPPORT header so each file gets its own bubble.
            parts = console_buf_content.split("# RAPPORT D'INSPECTION")
            preamble = parts[0].strip()
            if preamble:
                yield {"start": True, "end": True, "role": "computer",
                       "type": "console", "format": console_fmt or "output",
                       "content": preamble}
            backend_owns_closing = False
            for i, part in enumerate(parts[1:]):
                is_last = (i == len(parts) - 2)
                if is_last and "%%SUMMARY%%" in part:
                    rapport_part, rest = part.split("%%SUMMARY%%", 1)
                    yield {"start": True, "end": True, "role": "assistant",
                           "type": "message",
                           "content": "# RAPPORT D'INSPECTION" + rapport_part}
                    if "%%CLOSING%%" in rest:
                        summary_part, closing_part = rest.split("%%CLOSING%%", 1)
                        summary_text = summary_part.strip()
                        closing_text = closing_part.strip()
                    else:
                        summary_text = rest.strip()
                        closing_text = ""
                    if summary_text:
                        yield {"start": True, "end": True, "role": "assistant",
                               "type": "message", "content": summary_text}
                    if closing_text:
                        yield {"start": True, "end": True, "role": "assistant",
                               "type": "message", "content": closing_text}
                        backend_owns_closing = True
                        backend_closing_emitted = True
                else:
                    yield {"start": True, "end": True, "role": "assistant",
                           "type": "message",
                           "content": "# RAPPORT D'INSPECTION" + part}
            if backend_owns_closing:
                pending_assistant_tail = ""
            else:
                yield from _emit_pending_assistant_tail()
        elif buf:
            yield {"start": True, "end": True, "role": "computer",
                   "type": "console", "format": console_fmt or "output",
                   "content": buf}
        # Detect CSV saves and emit a download link for each one
        # Detect DELIVERABLE: JSON lines and emit structured result cards
        for line in buf.splitlines():
            line = line.strip()
            if line.startswith("Saved CSV:"):
                csv_path = line[len("Saved CSV:"):].strip()
                csv_url = _path_to_static_url(csv_path)
                if csv_url:
                    filename = os.path.basename(csv_path)
                    yield {"start": True, "end": True, "role": "computer",
                           "type": "file", "format": "csv-download",
                           "content": csv_url, "filename": filename}
            elif line.startswith("DELIVERABLE:"):
                raw = line[len("DELIVERABLE:"):].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    if "file" in data:
                        url = _path_to_static_url(data["file"])
                        if url:
                            data["file_url"] = url
                            data["filename"] = os.path.basename(data["file"])
                    yield {"start": True, "end": True, "role": "computer",
                           "type": "deliverable", "content": json.dumps(data)}
        console_buf_content = ""
        in_console_msg = False
        console_fmt = ""

    for chunk in interpreter_chunks:
        _get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)

        # Drop bare tool_call chunks
        if _get("tool_calls") is not None and _get("type") is None:
            continue

        role = _get("role") or ""
        ctype = _get("type") or ""
        fmt = _get("format") or ""
        is_start = bool(_get("start"))
        is_end = bool(_get("end"))
        content = _get("content") or ""
        if not isinstance(content, str):
            content = ""

        # Buffer console outputs so the full content is available before
        # deciding the routing. OpenInterpreter emits console start/end flags
        # without `format`, while the content chunks carry format=output.
        if role == "computer" and ctype == "console" and fmt != "active_line":
            if in_assistant_msg:
                yield from _flush_assistant_buf()
            if is_start:
                console_buf_content = content
                console_fmt = fmt or "output"
                in_console_msg = True
                if is_end:
                    yield from _emit_console_buf()
            elif in_console_msg:
                console_buf_content += content
                if fmt:
                    console_fmt = fmt
                if is_end:
                    yield from _emit_console_buf()
            elif fmt == "output":
                # OI can omit the start flag from transformed/replayed streams.
                # Treat output content as the start of a console buffer so
                # inspection reports can still be routed out of the exec-block.
                console_buf_content = content
                console_fmt = fmt
                in_console_msg = True
                if is_end:
                    yield from _emit_console_buf()
            else:
                # Non-output stray console metadata — pass through.
                yield chunk
            continue

        if role == "assistant" and ctype == "message":
            if in_console_msg:
                yield from _emit_console_buf()
            if is_start:
                msg_buf_content = content
                in_assistant_msg = True
                # Don't yield the start marker yet — wait until end so we can
                # decide whether the cleaned content is non-empty.
                if is_end:
                    yield from _emit_or_defer_assistant_text(msg_buf_content)
                    msg_buf_content = ""
                    in_assistant_msg = False
            elif in_assistant_msg:
                msg_buf_content += content
                if is_end:
                    yield from _emit_or_defer_assistant_text(msg_buf_content)
                    msg_buf_content = ""
                    in_assistant_msg = False
            else:
                # Stray message chunk outside a start/end pair — pass through
                yield chunk
        else:
            # Non-assistant-message, non-console-output chunk
            if in_assistant_msg and msg_buf_content:
                yield from _flush_assistant_buf()
            if in_console_msg:
                yield from _emit_console_buf()

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
        yield from _emit_or_defer_assistant_text(msg_buf_content)
    if in_console_msg:
        yield from _emit_console_buf()
    yield from _emit_pending_assistant_tail()
