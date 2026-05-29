from __future__ import annotations

import base64
import os
from collections.abc import Iterable, Iterator
from typing import Any


def chat_stream_events(interpreter_chunks: Iterable[Any]) -> Iterator[Any]:
    """Transform interpreter chunks into UI stream events.

    - Drops raw LLM tool_call chunks that open-interpreter failed to execute.
    - Suppresses assistant text messages that are OI's to=execute code="..." format.
      These arrive as streaming chunks, so we buffer the start of each assistant
      message until we can decide: if the accumulated content starts with "to=execute",
      the entire message is dropped; otherwise the buffer is flushed and we yield live.
    """
    _PROBE_LEN = 20          # characters to accumulate before deciding
    _PREFIX = "to=execute"

    buf: list[Any] = []
    buf_content = ""
    suppressing = False
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
                # New assistant text message — start buffering
                buf = [chunk]
                buf_content = content
                suppressing = False
                in_assistant_msg = True
                if len(buf_content) >= _PROBE_LEN or is_end:
                    # Enough content already (or single-chunk message)
                    suppressing = buf_content.lstrip().startswith(_PREFIX)
                    if not suppressing:
                        yield from buf
                        buf = []
                    elif is_end:
                        buf = []
                        in_assistant_msg = False
            elif in_assistant_msg:
                if suppressing:
                    if is_end:
                        buf = []
                        in_assistant_msg = False
                        suppressing = False
                    continue  # drop chunk
                elif buf:
                    # Still accumulating the probe window
                    buf.append(chunk)
                    buf_content += content
                    if len(buf_content) >= _PROBE_LEN or is_end:
                        suppressing = buf_content.lstrip().startswith(_PREFIX)
                        if not suppressing:
                            yield from buf
                        buf = []
                        if is_end:
                            in_assistant_msg = False
                            suppressing = False
                else:
                    # Buffer already flushed — yield live
                    if is_end:
                        in_assistant_msg = False
                    yield chunk
            else:
                yield chunk
        else:
            # Non-assistant-message chunk — flush any pending buffer first
            if buf:
                if not suppressing:
                    yield from buf
                buf = []
            suppressing = False
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
