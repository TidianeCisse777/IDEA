"""User-visible SSE and response-rendering contracts for Open WebUI."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest


def _mock_agent(updates):
    agent = MagicMock()

    async def _astream(*_args, **_kwargs):
        for update in updates:
            yield update

    agent.astream = _astream
    return agent


def _visible_text(chunks: list[str]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if not line.startswith("data: {"):
                continue
            payload = json.loads(line.removeprefix("data: "))
            choices = payload.get("choices") or []
            if choices:
                parts.append(choices[0].get("delta", {}).get("content", ""))
    return "".join(parts)


def test_sse_chunks_follow_openai_format():
    from serve import _make_sse_chunk

    content = json.loads(_make_sse_chunk("cid", "Bonjour").removeprefix("data: "))
    stop = json.loads(
        _make_sse_chunk("cid", "", finish_reason="stop").removeprefix("data: ")
    )

    assert content["choices"][0]["delta"] == {"content": "Bonjour"}
    assert content["choices"][0]["finish_reason"] is None
    assert stop["choices"][0]["delta"] == {}
    assert stop["choices"][0]["finish_reason"] == "stop"


def test_tool_panel_uses_public_label_and_hides_secrets():
    from serve import _format_tool_line

    panel = _format_tool_line(
        "query_ecotaxa",
        {"project_id": 42, "api_token": "super-secret-token"},
    )

    assert "query_ecotaxa" not in panel
    assert "super-secret-token" not in panel
    assert "api_token=`[secret]`" in panel
    assert "<details>" in panel and "<summary>" in panel


def test_rag_panel_keeps_the_complete_question():
    from serve import _format_tool_line

    question = (
        "Contexte complet de la demande utilisateur avec les contraintes, les "
        "ressources disponibles et la méthode exacte à rechercher avant le calcul."
    )
    panel = _format_tool_line(
        "query_copepod_knowledge_base",
        {"question": question},
    )

    assert f"question=`{question}`" in panel
    assert "…" not in panel


def test_source_result_panel_preserves_table_and_hides_base64():
    from serve import _format_tool_result_details

    content = (
        "| station | profils |\n|---|---:|\n| A01 | 4 |\n"
        "data:image/png;base64,AAAABBBBCCCCDDDD=="
    )
    panel = _format_tool_result_details("query_ecotaxa_cache", content)

    assert "| A01 | 4 |" in panel
    assert "AAAABBBB" not in panel
    assert "[image data]" in panel
    assert "query_ecotaxa_cache" not in panel


@pytest.mark.asyncio
async def test_stream_displays_agent_text_usage_and_done():
    from serve import _stream_agent_sse

    answer = AIMessage(content="Résultat final visible.", tool_calls=[])
    answer.usage_metadata = {
        "input_tokens": 12,
        "output_tokens": 4,
        "input_token_details": {
            "cache_read": 8,
            "cache_creation": 3,
        },
    }
    chunks = [
        chunk
        async for chunk in _stream_agent_sse(
            _mock_agent([{"model": {"messages": [answer]}}]),
            {},
            {},
            "sse-text",
        )
    ]

    assert _visible_text(chunks) == "Résultat final visible."
    assert chunks[-1] == "data: [DONE]\n\n"
    stop_payload = json.loads(chunks[-2].removeprefix("data: "))
    assert stop_payload["choices"][0]["finish_reason"] == "stop"
    assert stop_payload["usage"]["total_tokens"] == 16
    assert stop_payload["usage"]["prompt_tokens_details"] == {
        "cached_tokens": 8,
        "cache_creation_tokens": 3,
    }


@pytest.mark.asyncio
async def test_stream_accepts_openai_response_content_blocks_and_null_token_usage():
    from serve import _stream_agent_sse

    answer = AIMessage(
        content=[{"type": "text", "text": "Bonjour depuis OpenAI."}],
        response_metadata={"token_usage": None},
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 5,
            "total_tokens": 17,
        },
        tool_calls=[],
    )
    chunks = [
        chunk
        async for chunk in _stream_agent_sse(
            _mock_agent([{"model": {"messages": [answer]}}]),
            {},
            {},
            "sse-openai-content-blocks",
        )
    ]

    assert _visible_text(chunks) == "Bonjour depuis OpenAI."
    stop_payload = json.loads(chunks[-2].removeprefix("data: "))
    assert stop_payload["usage"]["total_tokens"] == 17
    assert "Erreur" not in _visible_text(chunks)


@pytest.mark.asyncio
async def test_stream_ignores_langgraph_updates_without_node_state():
    from serve import _stream_agent_sse

    answer = AIMessage(content="Réponse après update vide.", tool_calls=[])
    chunks = [
        chunk
        async for chunk in _stream_agent_sse(
            _mock_agent(
                [
                    {"model": None},
                    {"model": {"messages": [answer]}},
                ]
            ),
            {},
            {},
            "sse-none-node-state",
        )
    ]

    assert _visible_text(chunks) == "Réponse après update vide."
    assert "Erreur" not in _visible_text(chunks)


@pytest.mark.asyncio
async def test_stream_shows_tool_panel_before_final_answer():
    from serve import _stream_agent_sse

    updates = [
        {"model": {"messages": [AIMessage(
            content="Plan court.",
            tool_calls=[{
                "name": "load_file",
                "args": {"path": "/tmp/stations.tsv"},
                "id": "load-1",
                "type": "tool_call",
            }],
        )]}},
        {"tools": {"messages": [ToolMessage(
            content="Fichier chargé",
            name="load_file",
            tool_call_id="load-1",
        )]}},
        {"model": {"messages": [AIMessage(
            content="Le fichier est prêt.",
            tool_calls=[],
        )]}},
    ]
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            _mock_agent(updates), {}, {}, "sse-tool-order"
        )
    ]
    visible = _visible_text(chunks)

    assert visible.index("Plan court.") < visible.index("Chargement de fichier")
    assert visible.index("Chargement de fichier") < visible.index("Le fichier est prêt.")
    assert "stations.tsv" in visible
    assert "load_file" not in visible


@pytest.mark.asyncio
async def test_display_followup_streams_run_pandas_table_rows():
    from serve import _stream_agent_sse

    updates = [
        {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df_station_summary"},
                "id": "display-1",
                "type": "tool_call",
            }],
        )]}},
        {"tools": {"messages": [ToolMessage(
            content=(
                "2 lignes × 2 colonnes\n"
                "Persistence: persisted=false; variable=null\n\n"
                "Aperçu du résultat :\n"
                "| station | copepoda |\n"
                "|:---|---:|\n"
                "| M1b | 161 |\n"
                "| M2b | 818 |"
            ),
            name="run_pandas",
            tool_call_id="display-1",
        )]}},
        {"model": {"messages": [AIMessage(
            content="Le tableau est affiché.",
            tool_calls=[],
        )]}},
    ]

    chunks = [
        chunk
        async for chunk in _stream_agent_sse(
            _mock_agent(updates),
            {},
            {},
            "sse-display-table",
            last_user_text="affuche les",
        )
    ]
    visible = _visible_text(chunks)

    assert "| M1b | 161 |" in visible
    assert "| M2b | 818 |" in visible
    assert "Persistence:" not in visible


@pytest.mark.asyncio
async def test_run_pandas_raw_output_is_hidden_but_final_table_is_visible():
    from serve import _stream_agent_sse

    raw_tool_table = "| raw_internal |\n|---:|\n| 999 |"
    final_table = "| station | profils |\n|---|---:|\n| A01 | 4 |"
    updates = [
        {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "run_pandas",
                "args": {"code": "result = df.groupby('station').size()"},
                "id": "pandas-1",
                "type": "tool_call",
            }],
        )]}},
        {"tools": {"messages": [ToolMessage(
            content=raw_tool_table,
            name="run_pandas",
            tool_call_id="pandas-1",
        )]}},
        {"model": {"messages": [AIMessage(
            content=f"Résultat :\n\n{final_table}",
            tool_calls=[],
        )]}},
    ]
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            _mock_agent(updates), {}, {}, "sse-pandas"
        )
    ]
    visible = _visible_text(chunks)

    assert "Analyse du tableau" in visible
    assert raw_tool_table not in visible
    assert final_table in visible
    assert "run_pandas" not in visible


@pytest.mark.asyncio
async def test_data_source_result_is_visible_in_collapsible_panel():
    from serve import _stream_agent_sse

    source_table = "| station | profils |\n|---|---:|\n| A01 | 4 |"
    updates = [
        {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "query_ecotaxa_cache",
                "args": {"sql": "SELECT station, COUNT(*) AS profils FROM samples_cache"},
                "id": "eco-1",
                "type": "tool_call",
            }],
        )]}},
        {"tools": {"messages": [ToolMessage(
            content=source_table,
            name="query_ecotaxa_cache",
            tool_call_id="eco-1",
        )]}},
        {"model": {"messages": [AIMessage(
            content="Résultat EcoTaxa prêt.",
            tool_calls=[],
        )]}},
    ]
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            _mock_agent(updates), {}, {}, "sse-source"
        )
    ]
    visible = _visible_text(chunks)

    assert source_table in visible
    assert "<details>" in visible
    assert "Résultat EcoTaxa prêt." in visible
    assert "query_ecotaxa_cache" not in visible


@pytest.mark.asyncio
async def test_graph_is_streamed_once_when_final_answer_repeats_it():
    from serve import _stream_agent_sse

    image = "![graph](https://example.test/graphs/map.png)"
    updates = [
        {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "run_graph",
                "args": {"code": "plt.plot([1, 2])"},
                "id": "graph-1",
                "type": "tool_call",
            }],
        )]}},
        {"tools": {"messages": [ToolMessage(
            content=f"{image}\n\nCarte générée.",
            name="run_graph",
            tool_call_id="graph-1",
        )]}},
        {"model": {"messages": [AIMessage(
            content=f"{image}\n\nCarte des stations.",
            tool_calls=[],
        )]}},
    ]
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            _mock_agent(updates), {}, {}, "sse-graph"
        )
    ]
    visible = _visible_text(chunks)

    assert visible.count(image) == 1
    assert "Carte générée." in visible
    assert "Carte des stations." in visible


@pytest.mark.asyncio
async def test_stale_graph_url_from_model_is_not_displayed():
    from serve import _stream_agent_sse

    stale = "![graph](http://localhost:8000/graphs/old.png)"
    updates = [{"model": {"messages": [AIMessage(
        content=f"Aucun nouveau graphe.\n\n{stale}",
        tool_calls=[],
    )]}}]
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            _mock_agent(updates), {}, {}, "sse-stale-graph"
        )
    ]

    assert "/graphs/old.png" not in _visible_text(chunks)


@pytest.mark.asyncio
async def test_slow_tool_emits_invisible_keepalive(monkeypatch):
    from serve import _stream_agent_sse

    monkeypatch.setattr("serve._HEARTBEAT_INTERVAL", 0.005)

    async def _astream(*_args, **_kwargs):
        yield {"model": {"messages": [AIMessage(
            content="",
            tool_calls=[{
                "name": "enrich_with_bio_oracle",
                "args": {},
                "id": "slow-1",
                "type": "tool_call",
            }],
        )]}}
        await asyncio.sleep(0.02)
        yield {"tools": {"messages": [ToolMessage(
            content="Enrichissement terminé",
            name="enrich_with_bio_oracle",
            tool_call_id="slow-1",
        )]}}
        yield {"model": {"messages": [AIMessage(content="Terminé.", tool_calls=[])]}}

    agent = MagicMock()
    agent.astream = _astream
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            agent, {}, {}, "sse-keepalive"
        )
    ]

    assert ": keepalive\n\n" in chunks
    assert ": keepalive" not in _visible_text(chunks)
    assert "Terminé." in _visible_text(chunks)


@pytest.mark.asyncio
async def test_stream_error_is_visible_and_connection_closes_cleanly():
    from serve import _stream_agent_sse

    agent = MagicMock()

    async def _astream(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover

    agent.astream = _astream
    chunks = [
        chunk async for chunk in _stream_agent_sse(
            agent, {}, {}, "sse-error"
        )
    ]

    assert "[Erreur : provider unavailable]" in _visible_text(chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_closing_sse_stream_cancels_the_detached_agent_task():
    from serve import _stream_agent_sse

    agent_started = asyncio.Event()
    agent_cancelled = asyncio.Event()
    agent = MagicMock()

    async def _astream(*_args, **_kwargs):
        try:
            agent_started.set()
            yield {"model": {"messages": [AIMessage(content="début", tool_calls=[])]}}
            await asyncio.Event().wait()
        finally:
            agent_cancelled.set()

    agent.astream = _astream
    stream = _stream_agent_sse(agent, {}, {}, "sse-client-disconnect")

    first_chunk = await anext(stream)
    assert "début" in first_chunk
    await agent_started.wait()
    await stream.aclose()

    await asyncio.wait_for(agent_cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_closing_public_sse_wrapper_propagates_to_agent_task():
    from serve import _coordinated_agent_sse, _stream_with_request_origin

    agent_cancelled = asyncio.Event()
    agent = MagicMock()

    async def _astream(*_args, **_kwargs):
        try:
            yield {"model": {"messages": [AIMessage(
                content="début",
                tool_calls=[],
            )]}}
            await asyncio.Event().wait()
        finally:
            agent_cancelled.set()

    agent.astream = _astream
    coordinated = _coordinated_agent_sse(
        agent,
        {},
        {},
        "sse-public-client-disconnect",
        "message-1",
        last_user_text="",
        user_id="user-1",
        language="fr",
    )
    stream = _stream_with_request_origin("http://test", coordinated)

    first_chunk = await anext(stream)
    assert "début" in first_chunk
    await stream.aclose()

    await asyncio.wait_for(agent_cancelled.wait(), timeout=0.2)


def test_non_stream_response_keeps_only_current_turn_graph():
    from serve import _append_generated_graph_images

    old = "![graph](http://localhost:8000/graphs/old.png)"
    new = "![graph](http://localhost:8000/graphs/new.png)"
    response = _append_generated_graph_images(
        "Graphique prêt.",
        [
            ToolMessage(content=old, name="run_graph", tool_call_id="old"),
            HumanMessage(content="Refais le graphique"),
            ToolMessage(content=new, name="run_graph", tool_call_id="new"),
        ],
    )

    assert old not in response
    assert new in response
