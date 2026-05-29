"""Tests for chat_stream_events — transformation of OI chunks into UI stream events.

Regression coverage for the markdown-fence leak bug: when the LLM emits code as
markdown ```python ... ``` inside its text response (instead of using the tool_call
API), OI both streams the raw text AND emits a separate type:code event for
execution. The frontend then renders both — the markdown fence becomes a "Voir le
code" collapsible while the type:code becomes a "Code exécuté" exec-block, causing
duplicate displays.

chat_stream_events must strip ```python / ```py fences from assistant text so only
the type:code event remains authoritative.
"""

from __future__ import annotations

from core.chat_stream_events import chat_stream_events


def _stream_message(content: str) -> list[dict]:
    """Build an OI-style stream for a single assistant text message split into chunks."""
    chunks: list[dict] = [
        {"role": "assistant", "type": "message", "start": True},
    ]
    # Stream the content as small chunks (mimicking token-by-token streaming)
    step = 8
    for i in range(0, len(content), step):
        chunks.append({"role": "assistant", "type": "message", "content": content[i:i + step]})
    chunks.append({"role": "assistant", "type": "message", "end": True})
    return chunks


def _concat_message_content(events: list[dict]) -> str:
    """Join the content of every assistant message event in order."""
    return "".join(
        e.get("content") or ""
        for e in events
        if e.get("role") == "assistant" and e.get("type") == "message"
    )


def test_passthrough_plain_text_streams_as_is():
    chunks = _stream_message("Hello, the file looks good.")
    events = list(chat_stream_events(chunks))
    text = _concat_message_content(events)
    assert text == "Hello, the file looks good."


def test_raw_to_execute_block_is_suppressed_no_tail():
    chunks = _stream_message('to=execute code="print(1)"')
    events = list(chat_stream_events(chunks))
    msg_events = [e for e in events if e.get("type") == "message"]
    # Suppressed entirely, no message yielded
    assert msg_events == []


def test_raw_json_block_with_trailing_text_keeps_only_tail():
    chunks = _stream_message('{"language":"python","code":"print(1)"} Now look at the result.')
    events = list(chat_stream_events(chunks))
    text = _concat_message_content(events)
    assert "Now look at the result." in text
    assert "{\"language\"" not in text
    assert "print(1)" not in text


# ─── Regression: markdown ```python fences must not leak through ─────────────


def test_markdown_python_fence_at_start_is_stripped():
    """Fence at very start of message → strip fence, drop empty message."""
    content = "```python\nfile_report = inspect_file('/tmp/x.csv')\nprint(file_report)\n```"
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert "```python" not in text
    assert "```" not in text
    assert "inspect_file" not in text


def test_markdown_python_fence_with_leading_and_trailing_text_keeps_text():
    """Fence with intro and outro → strip fence, keep surrounding text."""
    content = (
        "Voici ce que je vais faire :\n"
        "```python\n"
        "file_report = inspect_file('/tmp/x.csv')\n"
        "print(file_report)\n"
        "```\n"
        "C'est un tableau d'abondances zooplanctoniques."
    )
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert "```python" not in text
    assert "inspect_file" not in text
    assert "Voici ce que je vais faire" in text
    assert "C'est un tableau d'abondances zooplanctoniques." in text


def test_duplicate_markdown_python_fences_both_stripped():
    """LLM duplicates the same code block back-to-back → both stripped."""
    content = (
        "```python\n"
        "file_report = inspect_file('/tmp/x.csv')\n"
        "print(file_report)\n"
        "```\n\n"
        "```python\n"
        "file_report = inspect_file('/tmp/x.csv')\n"
        "print(file_report)\n"
        "```\n"
        "Voilà ce qu'on observe."
    )
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert "```python" not in text
    assert "inspect_file" not in text
    assert "Voilà ce qu'on observe." in text


def test_markdown_py_short_alias_is_also_stripped():
    """LLM might use ```py instead of ```python."""
    content = "Préambule.\n```py\nprint('hi')\n```\nFin."
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert "```py" not in text
    assert "print('hi')" not in text
    assert "Préambule." in text
    assert "Fin." in text


def test_non_python_fence_is_preserved():
    """A ```bash or ```text fence is NOT code-to-execute — should pass through unchanged."""
    content = "Run this in your shell:\n```bash\nls -la\n```\nDone."
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    # bash fence is informational, keep it intact
    assert "```bash" in text
    assert "ls -la" in text


def test_markdown_json_fence_wrapping_oi_toolcall_is_stripped():
    """LLM sometimes wraps OI's JSON tool call in a ```json fence:
        ```json
        {"language":"python","code":"..."}
        ```
    OI parses it internally for execution, but the markdown still leaks to the
    UI. Must be stripped, surrounding prose preserved."""
    content = (
        "Voici le tool call :\n"
        "```json\n"
        '{"language":"python","code":"file_report = inspect_file(\'/tmp/x.csv\')\\nprint(file_report)"}\n'
        "```\n"
        "Analyse terminée."
    )
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert "```json" not in text
    assert '"language"' not in text
    assert "inspect_file" not in text
    assert "Voici le tool call" in text
    assert "Analyse terminée." in text


def test_markdown_json_fence_without_toolcall_is_preserved():
    """A ```json fence containing regular JSON (not an OI tool call) is
    informational — keep it."""
    content = (
        "Voici la config :\n"
        "```json\n"
        '{"name":"NeoLabs","version":1}\n'
        "```\n"
        "Fin."
    )
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    # Regular json blocks survive
    assert "```json" in text
    assert '"name":"NeoLabs"' in text


def test_code_event_passes_through_untouched():
    """type:code chunks emitted by OI for execution must not be altered."""
    chunks = [
        {"role": "assistant", "type": "message", "start": True},
        {"role": "assistant", "type": "message", "content": "Looking at the file."},
        {"role": "assistant", "type": "message", "end": True},
        {"role": "assistant", "type": "code", "format": "python", "start": True},
        {"role": "assistant", "type": "code", "format": "python", "content": "print(1)"},
        {"role": "assistant", "type": "code", "format": "python", "end": True},
        {"role": "computer", "type": "console", "format": "output", "content": "1\n"},
    ]
    events = list(chat_stream_events(chunks))
    code_chunks = [e for e in events if e.get("type") == "code"]
    assert any(e.get("content") == "print(1)" for e in code_chunks)
    console = [e for e in events if e.get("type") == "console"]
    assert console and console[0].get("content") == "1\n"
