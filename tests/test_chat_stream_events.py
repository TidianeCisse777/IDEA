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

import json

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


def test_assistant_text_is_conservatively_formatted_before_emit():
    content = "Bonjour,monde.\n\n\nBonjour,monde.\n\nFin."
    events = list(chat_stream_events(_stream_message(content)))
    text = _concat_message_content(events)
    assert text == "Bonjour, monde.\n\nFin."


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


def _stream_console(content: str, fmt: str = "output") -> list[dict]:
    """Build an OI-style stream for a single computer/console output."""
    chunks: list[dict] = [
        {"role": "computer", "type": "console", "format": fmt, "start": True},
    ]
    step = 16
    for i in range(0, len(content), step):
        chunks.append({"role": "computer", "type": "console", "format": fmt,
                       "content": content[i:i + step]})
    chunks.append({"role": "computer", "type": "console", "format": fmt, "end": True})
    return chunks


def _stream_oi_console_with_unformatted_flags(content: str) -> list[dict]:
    """Build the real OI pattern: console start/end flags have no format,
    but content chunks carry format=output."""
    chunks: list[dict] = [
        {"role": "computer", "type": "console", "start": True},
    ]
    step = 16
    for i in range(0, len(content), step):
        chunks.append({"role": "computer", "type": "console", "format": "output",
                       "content": content[i:i + step]})
    chunks.append({"role": "computer", "type": "console", "end": True})
    return chunks


def test_text_deliverable_is_not_duplicated_when_console_prints_card():
    """If the LLM also writes DELIVERABLE in assistant text, the printed
    console DELIVERABLE remains the single authoritative card."""
    payload = {
        "type": "export",
        "title": "Export CSV",
        "fields": [{"label": "Lignes", "value": "42"}],
    }
    line = "DELIVERABLE: " + json.dumps(payload)
    chunks = [
        *_stream_message(line),
        *_stream_console(line + "\n"),
    ]

    events = list(chat_stream_events(chunks))

    cards = [
        json.loads(e["content"]) for e in events
        if e.get("role") == "computer" and e.get("type") == "deliverable"
    ]
    assistant_text = _concat_message_content(events)

    assert cards == [payload]
    assert "DELIVERABLE:" not in assistant_text


def test_console_deliverable_suppresses_followup_assistant_prose():
    payload = {"type": "graph", "title": "Carte produite"}
    line = "DELIVERABLE: " + json.dumps(payload)
    chunks = [
        *_stream_console(line + "\n"),
        *_stream_message("Oui, le livrable est termine."),
    ]

    events = list(chat_stream_events(chunks))

    cards = [
        json.loads(e["content"]) for e in events
        if e.get("role") == "computer" and e.get("type") == "deliverable"
    ]
    assistant_text = _concat_message_content(events)

    assert cards == [payload]
    assert assistant_text == ""


# ─── Inspection report re-routing: rapport must be assistant-message, not console ─


def test_console_output_with_inspection_report_is_emitted_as_assistant_markdown():
    """Console output containing # RAPPORT D'INSPECTION must be re-emitted
    as a `type:message` assistant chunk so the frontend renders it OUTSIDE
    the exec-block as a markdown document."""
    report = (
        "# RAPPORT D'INSPECTION\n"
        "\n"
        "- **file_path** : `/tmp/x.csv`\n"
        "- **format** : `csv`\n"
        "\n"
        "## Columns (1)\n"
        "\n"
        "| # | Column |\n"
        "|---|--------|\n"
        "| 1 | `a` |\n"
    )
    events = list(chat_stream_events(_stream_console(report)))
    # No console chunks emitted for the rapport
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    assert console_chunks == [], f"rapport leaked into console chunks: {console_chunks}"
    # Exactly one assistant message with the rapport content
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    assert len(msg_chunks) == 1
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "| `a` |" in msg_chunks[0]["content"]


def test_oi_console_output_with_unformatted_flags_routes_rapport_to_assistant():
    """OpenInterpreter emits console start/end flags without format, then
    content chunks with format=output. The report must still be routed out
    of the exec-block."""
    report = (
        "# RAPPORT D'INSPECTION\n"
        "\n"
        "- **file_path** : `/tmp/x.csv`\n"
        "\n"
        "## Synthèse\n"
    )
    events = list(chat_stream_events(_stream_oi_console_with_unformatted_flags(report)))
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    assert console_chunks == []
    assert len(msg_chunks) == 1
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "## Synthèse" in msg_chunks[0]["content"]


def test_plain_inspection_report_with_json_synthesis_emits_compact_summary():
    report = (
        "# RAPPORT D'INSPECTION\n"
        "\n"
        "- **file_path** : `/tmp/IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv`\n"
        "- **format** : `csv`  •  **n_rows** : `5047`  •  **n_columns** : `93`\n"
        "- **source_type_guess** : `likely_neolabs_taxon` (confidence: `high`)\n"
        "- **encoding** : `iso8859-3`  •  **delimiter** : `,`\n"
        "\n"
        "## Synthèse\n"
        "```json\n"
        "{\n"
        '  "file": "IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv",\n'
        '  "format": "csv",\n'
        '  "n_rows": 5047,\n'
        '  "n_columns": 93,\n'
        '  "source_type": "likely_neolabs_taxon",\n'
        '  "source_confidence": "high",\n'
        '  "missing": {\n'
        '    "n_columns_with_missing": 38,\n'
        '    "worst": {"column": "COPEPODID_BIOMASS (µg C m-3 flowmeter vol.)", "rate": 0.198}\n'
        "  },\n"
        '  "column_grounding": {"rag_defined": 93, "auto_resolved": 0, "needs_clarification": 0, "unresolved": []},\n'
        '  "warnings": 0\n'
        "}\n"
        "```\n"
    )
    events = list(chat_stream_events(_stream_console(report)))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]

    assert len(msg_chunks) == 2
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert msg_chunks[1]["content"] == (
        "**Synthèse d'inspection**\n"
        "- Fichier : `IDEA Taxonomy Samples and Analyses Data Metadata May 26 2026.csv`\n"
        "- Format : CSV, 5047 × 93\n"
        "- Source détectée : `likely_neolabs_taxon` (confiance : `high`)\n"
        "- Colonnes définies : 93 RAG, 0 auto-résolues, 0 à clarifier\n"
        "- Valeurs manquantes : 38 colonnes; maximum `COPEPODID_BIOMASS (µg C m-3 flowmeter vol.)` à 19.8%\n"
        "- Warnings : 0"
    )


def test_upload_question_tail_is_emitted_after_routed_rapport():
    """When the LLM emits executable code plus the fixed follow-up question in
    one assistant text message, the UI must not show the question before the
    inspection report."""
    assistant = (
        "```python\n"
        "file_report = inspect_file('/tmp/x.csv')\n"
        "print(format_inspect_report(file_report))\n"
        "```\n\n"
        "Quel graphique souhaitez-vous ?"
    )
    report = (
        "# RAPPORT D'INSPECTION\n"
        "\n"
        "- **file_path** : `/tmp/x.csv`\n"
        "\n"
        "## Synthèse\n"
    )
    chunks = [
        *_stream_message(assistant),
        {"role": "assistant", "type": "code", "format": "python", "start": True},
        {"role": "assistant", "type": "code", "format": "python", "content": "print('report')"},
        {"role": "assistant", "type": "code", "format": "python", "end": True},
        *_stream_oi_console_with_unformatted_flags(report),
    ]
    events = list(chat_stream_events(chunks))
    assistant_messages = [
        e["content"] for e in events
        if e.get("role") == "assistant" and e.get("type") == "message"
    ]
    assert assistant_messages == [
        report,
        "Quel graphique souhaitez-vous ?",
    ]


def test_console_output_without_rapport_passes_through_as_console():
    """Plain stdout (no rapport marker) stays a computer/console chunk so it
    keeps appearing inside the exec-block."""
    events = list(chat_stream_events(_stream_console("Some plain output line\n")))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    assert msg_chunks == []
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    assert len(console_chunks) == 1
    assert console_chunks[0]["content"] == "Some plain output line\n"


def test_preamble_noise_before_rapport_stays_in_console():
    """If chromadb noise or other prints arrive before the rapport, they are
    kept as console (visible in exec-block) while the rapport itself is
    extracted as an assistant message."""
    mixed = (
        "tqdm: 100%|███| 79M/79M\n"
        "Some warning\n"
        "# RAPPORT D'INSPECTION\n"
        "\n"
        "- **file_path** : `/tmp/x.csv`\n"
    )
    events = list(chat_stream_events(_stream_console(mixed)))
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    # Preamble survives as console; rapport goes to assistant message
    assert len(console_chunks) == 1
    assert "tqdm: 100%" in console_chunks[0]["content"]
    assert "RAPPORT" not in console_chunks[0]["content"]
    assert len(msg_chunks) == 1
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")


def test_multiple_rapports_each_emitted_as_separate_assistant_message():
    """Three concatenated RAPPORT D'INSPECTION blocks in one console output
    must each become a separate assistant message so the frontend renders
    them as individual collapsible bubbles."""
    r1 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/file1.csv`\n## Columns (1)\n"
    r2 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/file2.csv`\n## Columns (5)\n"
    r3 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/file3.csv`\n## Columns (30)\n"
    events = list(chat_stream_events(_stream_console(r1 + r2 + r3)))
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    assert console_chunks == [], f"no console chunks expected, got: {console_chunks}"
    assert len(msg_chunks) == 3, f"expected 3 messages, got {len(msg_chunks)}"
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "file1.csv" in msg_chunks[0]["content"]
    assert "file2.csv" in msg_chunks[1]["content"]
    assert "file3.csv" in msg_chunks[2]["content"]


def test_preamble_noise_plus_multiple_rapports():
    """Env warnings + 2 rapports → 1 console chunk (preamble) + 2 assistant messages."""
    preamble = "onnxruntime warning\ntqdm: 100%\n"
    r1 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/a.csv`\n"
    r2 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/b.csv`\n"
    events = list(chat_stream_events(_stream_console(preamble + r1 + r2)))
    console_chunks = [e for e in events if e.get("role") == "computer" and e.get("type") == "console"]
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    assert len(console_chunks) == 1
    assert "onnxruntime" in console_chunks[0]["content"]
    assert "RAPPORT" not in console_chunks[0]["content"]
    assert len(msg_chunks) == 2
    assert "a.csv" in msg_chunks[0]["content"]
    assert "b.csv" in msg_chunks[1]["content"]


def test_llm_message_after_closing_is_suppressed():
    """Any LLM assistant message that arrives after the backend emitted %%CLOSING%%
    must be dropped — the pipeline owns the closing, the LLM should be silent."""
    rapport = (
        "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/a.csv`\n"
        "%%SUMMARY%%\n**a** (50 × 41).\n"
        "%%CLOSING%%\nQuel graphique ou livrable souhaitez-vous ?\n"
    )
    llm_after = "Oui : l'inspection est terminée, indiquez le graphique souhaité."
    chunks = [
        *_stream_console(rapport),
        *_stream_message(llm_after),
    ]
    events = list(chat_stream_events(chunks))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    # closing from backend is present, LLM tail is dropped
    closing_msgs = [m for m in msg_chunks if "graphique" in m["content"].lower() or "livrable" in m["content"].lower()]
    assert len(closing_msgs) == 1, f"expected exactly 1 closing message, got: {[m['content'][:50] for m in msg_chunks]}"
    llm_msgs = [m for m in msg_chunks if "Oui" in m["content"] or "terminée" in m["content"]]
    assert llm_msgs == [], f"LLM message after closing should be suppressed, got: {llm_msgs}"


def test_llm_message_after_plain_inspection_report_is_suppressed():
    """After a routed inspection report, the report is authoritative.

    The model sometimes emits a redundant prose tail such as an onnxruntime warning
    explanation plus a terse "inspection terminée" sentence. That prose should not
    replace or visually compete with the full markdown report.
    """
    rapport = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/a.csv`\n## Synthèse\n"
    llm_after = (
        "Le messageonnxruntime cpuid_info warning est un avertissement technique non bloquant ; "
        "il n’indique pas une erreur de lecture du fichier.\n"
        "Oui, l’inspection du fichier est terminée : 5047 × 93."
    )
    chunks = [
        *_stream_console(rapport),
        *_stream_message(llm_after),
    ]
    events = list(chat_stream_events(chunks))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]

    assert len(msg_chunks) == 1
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "onnxruntime" not in _concat_message_content(events)


def test_summary_marker_emitted_as_separate_assistant_message():
    """%%SUMMARY%% content is extracted from the console buffer and emitted as
    a standalone assistant message, separate from the RAPPORT blocks."""
    content = (
        "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/a.csv`\n"
        "%%SUMMARY%%\n"
        "**export EcoTaxa — a** (50 × 41). Variables : taxon.\n"
        "%%CLOSING%%\n"
        "Quel graphique ou livrable souhaitez-vous ?\n"
    )
    events = list(chat_stream_events(_stream_console(content)))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    summary_msgs = [m for m in msg_chunks if "export EcoTaxa" in m["content"]]
    assert len(summary_msgs) == 1, f"expected 1 summary message, got {len(summary_msgs)}: {msg_chunks}"
    assert "%%SUMMARY%%" not in summary_msgs[0]["content"]
    assert "%%CLOSING%%" not in summary_msgs[0]["content"]


def test_closing_marker_emitted_as_separate_assistant_message():
    """%%CLOSING%% content is emitted as its own assistant message after the summary."""
    content = (
        "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/a.csv`\n"
        "%%SUMMARY%%\n"
        "**export EcoTaxa — a** (50 × 41).\n"
        "%%CLOSING%%\n"
        "Quel graphique ou livrable souhaitez-vous ?\n"
    )
    events = list(chat_stream_events(_stream_console(content)))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    closing_msgs = [m for m in msg_chunks if "graphique" in m["content"].lower() or "livrable" in m["content"].lower()]
    assert len(closing_msgs) == 1, f"expected 1 closing message, got: {msg_chunks}"
    assert "%%CLOSING%%" not in closing_msgs[0]["content"]


def test_markers_order_rapport_then_summary_then_closing():
    """The order of emitted messages must be: rapport(s), then summary, then closing."""
    r1 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/file1.csv`\n"
    r2 = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/file2.csv`\n"
    summary = "**a** (50 × 41). **b** (30 × 10).\n"
    closing = "Quel graphique ou livrable souhaitez-vous ?\n"
    content = r1 + r2 + "%%SUMMARY%%\n" + summary + "%%CLOSING%%\n" + closing
    events = list(chat_stream_events(_stream_console(content)))
    msg_chunks = [e for e in events if e.get("role") == "assistant" and e.get("type") == "message"]
    # Expect: rapport1, rapport2, summary, closing — 4 messages total
    assert len(msg_chunks) == 4, f"expected 4 messages, got {len(msg_chunks)}: {[m['content'][:40] for m in msg_chunks]}"
    assert msg_chunks[0]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "file1.csv" in msg_chunks[0]["content"]
    assert msg_chunks[1]["content"].startswith("# RAPPORT D'INSPECTION")
    assert "file2.csv" in msg_chunks[1]["content"]
    assert "50 × 41" in msg_chunks[2]["content"]
    assert "graphique" in msg_chunks[3]["content"].lower()


def test_raw_inspect_and_report_call_is_suppressed():
    """Raw Python code starting with _ir = inspect_and_report( must not appear
    as an assistant text message — it's an OI internal code emission without fences."""
    raw_code = (
        "_ir = inspect_and_report(\n"
        "    file_paths=['/app/static/session-abc/file.csv'],\n"
        "    session_id='session-abc'\n"
        ")\n"
        "print(_ir['output'])"
    )
    events = list(chat_stream_events(_stream_message(raw_code)))
    msg_events = [e for e in events if e.get("type") == "message"]
    assert msg_events == [], f"raw inspect_and_report code should be suppressed, got: {msg_events}"


def test_raw_inspect_and_report_single_line_is_suppressed():
    """Single-line _ir = inspect_and_report( variant must also be suppressed."""
    raw_code = "_ir = inspect_and_report(file_paths=['/tmp/f.csv'], session_id='s')"
    events = list(chat_stream_events(_stream_message(raw_code)))
    msg_events = [e for e in events if e.get("type") == "message"]
    assert msg_events == [], f"single-line raw code should be suppressed: {msg_events}"


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
