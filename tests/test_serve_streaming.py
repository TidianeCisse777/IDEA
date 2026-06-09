"""TDD — streaming SSE endpoint pour Open WebUI.

On vérifie :
1. _make_sse_chunk  → format JSON correct
2. _format_tool_line → contient 🔧 + nom de l'outil
3. _stream_agent_sse → émet tool_call puis réponse finale, termine par [DONE]
4. _stream_agent_sse → image base64 remplacée par URL hébergée
"""
import json
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, ToolMessage


# ── helpers purs ───────────────────────────────────────────────────────────────

def test_sse_chunk_contains_content():
    from serve import _make_sse_chunk
    line = _make_sse_chunk("cid-001", "bonjour")
    assert line.startswith("data: ")
    payload = json.loads(line[len("data: "):])
    assert payload["choices"][0]["delta"]["content"] == "bonjour"
    assert payload["choices"][0]["finish_reason"] is None


def test_sse_chunk_stop_has_no_content_key():
    from serve import _make_sse_chunk
    line = _make_sse_chunk("cid-001", "", finish_reason="stop")
    payload = json.loads(line[len("data: "):])
    assert "content" not in payload["choices"][0]["delta"]
    assert payload["choices"][0]["finish_reason"] == "stop"


def test_format_tool_line_contains_icon_and_name():
    from serve import _format_tool_line
    line = _format_tool_line("load_file")
    assert "🔧" in line
    assert "load_file" in line


def test_format_tool_line_skill():
    from serve import _format_tool_line
    line = _format_tool_line("skill_tool")
    assert "skill_tool" in line


def test_format_tool_line_run_graph_with_code_uses_details():
    """run_graph avec code → bloc <details> collapsible avec le code Python."""
    from serve import _format_tool_line
    code = "plt.scatter(df['lon'], df['lat'])\nplt.show()"
    line = _format_tool_line("run_graph", {"code": code})
    assert "🔧" in line
    assert "run_graph" in line
    assert "plt.scatter" in line
    assert "```python" in line
    assert "<details>" not in line  # pas de HTML — pas rendu par Open WebUI en stream


def test_format_tool_line_run_graph_shows_loading_indicator():
    """run_graph avec code → inclut un indicateur visuel de génération du graphique."""
    from serve import _format_tool_line
    code = "plt.scatter(df['lon'], df['lat'])"
    line = _format_tool_line("run_graph", {"code": code})
    assert "Génération du graphique" in line


def test_format_tool_line_run_pandas_no_loading_indicator():
    """run_pandas → pas d'indicateur graphique (aucune image à attendre)."""
    from serve import _format_tool_line
    line = _format_tool_line("run_pandas", {"code": "result = df.mean()"})
    assert "Génération" not in line


def test_format_tool_line_run_graph_without_code_no_loading_indicator():
    """run_graph sans code → pas d'indicateur (pas de génération en cours)."""
    from serve import _format_tool_line
    line = _format_tool_line("run_graph", {})
    assert "Génération" not in line


def test_format_tool_line_run_pandas_with_code_uses_details():
    """run_pandas avec code → bloc <details> avec le code."""
    from serve import _format_tool_line
    code = "df.groupby('station').mean()"
    line = _format_tool_line("run_pandas", {"code": code})
    assert "🔧" in line
    assert "run_pandas" in line
    assert "df.groupby" in line
    assert "<details>" not in line


def test_format_tool_line_run_graph_without_code_fallback():
    """run_graph sans args → fallback simple avec 🔧."""
    from serve import _format_tool_line
    line = _format_tool_line("run_graph", {})
    assert "🔧" in line
    assert "run_graph" in line
    assert "<details>" not in line


def test_format_tool_line_load_file_shows_filename():
    """load_file avec path → affiche le nom de fichier, pas le chemin complet."""
    from serve import _format_tool_line
    line = _format_tool_line("load_file", {"path": "/tmp/webui_uploads/stations.tsv"})
    assert "load_file" in line
    assert "stations.tsv" in line


def test_format_tool_line_skill_shows_skill_name():
    """load_skill avec skill_name → affiche le nom du skill."""
    from serve import _format_tool_line
    line = _format_tool_line("load_skill", {"skill_name": "map_stations"})
    assert "load_skill" in line
    assert "map_stations" in line


# ── streaming async ────────────────────────────────────────────────────────────

def _make_mock_agent(updates: list):
    """Renvoie un agent mock dont .astream() yield les updates donnés."""
    mock = MagicMock()

    async def _astream(*args, **kwargs):
        for u in updates:
            yield u

    mock.astream = _astream
    return mock


@pytest.mark.asyncio
async def test_stream_tool_call_then_final_response():
    """Le stream émet 🔧 nom_outil puis la réponse finale."""
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(
            content="Je vais charger le fichier.",
            tool_calls=[{"name": "load_file", "args": {"path": "/tmp/x.tsv"}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content="Fichier chargé", tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content="Voici les données.", tool_calls=[])]}},
    ]

    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "🔧" in full
    assert "load_file" in full
    assert "Voici les données." in full


@pytest.mark.asyncio
async def test_stream_ends_with_done():
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(content="Réponse simple.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]

    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_multiple_tool_calls():
    """Deux tool calls consécutifs apparaissent dans l'ordre."""
    from serve import _stream_agent_sse

    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[
                {"name": "load_file", "args": {}, "id": "tc1", "type": "tool_call"},
                {"name": "run_graph", "args": {}, "id": "tc2", "type": "tool_call"},
            ],
        )]}},
        {"tools": {"messages": [
            ToolMessage(content="ok", tool_call_id="tc1"),
            ToolMessage(content="ok", tool_call_id="tc2"),
        ]}},
        {"agent": {"messages": [AIMessage(content="Voilà.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    idx_load = full.index("load_file")
    idx_graph = full.index("run_graph")
    assert idx_load < idx_graph


@pytest.mark.asyncio
async def test_stream_image_in_agent_response_replaced():
    """Le base64 dans la réponse finale de l'agent est remplacé par une URL /graphs/."""
    from serve import _stream_agent_sse
    import base64

    tiny_png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode()

    content_with_image = f"Voici la carte.\n\n![carte](data:image/png;base64,{tiny_png})"
    updates = [
        {"agent": {"messages": [AIMessage(content=content_with_image, tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "data:image/png;base64," not in full
    assert "/graphs/" in full


@pytest.mark.asyncio
async def test_stream_image_in_tool_result_replaced():
    """Le base64 dans le résultat d'un outil est extrait et hébergé."""
    from serve import _stream_agent_sse
    import base64

    tiny_png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    ).decode()

    tool_content = f"![graph](data:image/png;base64,{tiny_png})"
    updates = [
        {"agent": {"messages": [AIMessage(
            content="",
            tool_calls=[{"name": "run_graph", "args": {}, "id": "tc1", "type": "tool_call"}],
        )]}},
        {"tools": {"messages": [ToolMessage(content=tool_content, tool_call_id="tc1")]}},
        {"agent": {"messages": [AIMessage(content="Voici la carte.", tool_calls=[])]}},
    ]
    agent = _make_mock_agent(updates)
    chunks = [c async for c in _stream_agent_sse(agent, {}, {}, "tid-test")]
    full = "".join(chunks)

    assert "data:image/png;base64," not in full
    assert "/graphs/" in full
