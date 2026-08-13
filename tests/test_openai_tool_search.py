"""Offline contracts for the OpenAI hosted Tool Search projection."""

from __future__ import annotations

from tools.openai_tool_search import (
    build_openai_tool_search_projection,
    openai_tool_search_enabled,
)
from tools.tool_catalog import build_tool_catalog


def test_activation_requires_flag_direct_openai_and_gpt_5_4(monkeypatch):
    monkeypatch.setenv("OPENAI_TOOL_SEARCH_ENABLED", "true")

    assert openai_tool_search_enabled(
        model="gpt-5.4-mini",
        base_url="https://api.openai.com/v1",
    )
    assert not openai_tool_search_enabled(
        model="gpt-5.3-mini",
        base_url="https://api.openai.com/v1",
    )
    assert not openai_tool_search_enabled(
        model="gpt-5.4-mini",
        base_url="https://openrouter.ai/api/v1",
    )


def test_projection_keeps_core_immediate_and_defers_specialized_families():
    catalog = build_tool_catalog("tool-search-projection")
    projection = build_openai_tool_search_projection(
        catalog.tools,
        catalog.policies,
    )

    assert {
        "load_file",
        "query_copepod_knowledge_base",
        "run_pandas",
        "run_graph",
    } <= set(projection.immediate_names)
    assert {namespace.name for namespace in projection.namespaces} == {
        "ecotaxa",
        "ecopart",
        "geography",
        "environmental_enrichment",
        "deliverable",
    }
    assert "export_deliverable" not in projection.immediate_names
    assert "export_deliverable" in projection.searchable_member_names
    assert all(len(namespace.member_names) < 10 for namespace in projection.namespaces)
    assert projection.excluded_names == ()
    assert set(projection.immediate_names) | set(
        projection.searchable_member_names
    ) == set(catalog.names)

    for namespace in projection.namespaces:
        assert namespace.schema["type"] == "namespace"
        for member in namespace.schema["tools"]:
            assert member["type"] == "function"
            assert member["defer_loading"] is True
            assert "function" not in member
            assert member["parameters"]["type"] == "object"


def test_forced_recovery_tool_is_immediate_and_not_duplicated_in_namespace():
    catalog = build_tool_catalog("tool-search-forced-recovery")
    projection = build_openai_tool_search_projection(
        catalog.tools,
        catalog.policies,
        force_immediate=("query_ecotaxa_cache",),
    )

    assert "query_ecotaxa_cache" in projection.immediate_names
    assert "query_ecotaxa_cache" not in projection.searchable_member_names
    assert projection.provider_surface_names.count("query_ecotaxa_cache") == 1


def test_context_budget_counts_namespace_identity_not_deferred_member_schemas():
    from agent import _tool_schema_tokens

    namespace = {
        "type": "namespace",
        "name": "large_family",
        "description": "Searchable source family.",
        "tools": [{
            "type": "function",
            "name": "large_member",
            "description": "X" * 20_000,
            "defer_loading": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }],
    }

    assert _tool_schema_tokens([namespace]) < 100


def test_real_middleware_projects_the_exact_tool_search_surface(monkeypatch, tmp_path):
    from scripts.dev.inspect_six_dataframe_context import capture_model_request
    from tools.session_store import SessionStore

    monkeypatch.setenv("OPENAI_TOOL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")

    thread_id = "tool-search-middleware"
    capture = capture_model_request(
        SessionStore(tmp_path),
        thread_id,
        "Enrichis les profils EcoTaxa avec Bio-ORACLE puis fais une carte.",
        "tool-search-message",
    )

    assert capture.audit["openai_tool_search_enabled"] is True
    assert capture.tool_names == tuple(capture.audit["tools_exposed"])
    assert capture.tool_names[-1] == "tool_search"
    assert {
        "ecotaxa",
        "ecopart",
        "geography",
        "environmental_enrichment",
        "deliverable",
    } <= set(capture.tool_names)
    assert capture.audit["openai_tool_search_namespaces"]["ecotaxa"] == [
        "query_ecotaxa",
        "export_ecotaxa_samples",
        "list_ecotaxa_cache_tables",
        "describe_ecotaxa_cache_table",
        "query_ecotaxa_cache",
    ]
    assert "enrich_with_bio_oracle" in capture.audit[
        "openai_tool_search_namespaces"
    ]["environmental_enrichment"]
    assert capture.audit["approx_tokens_tool_schemas_after"] < capture.audit[
        "approx_tokens_tool_schemas_before"
    ]


def test_namespace_member_still_executes_through_langgraph_tool_node(
    monkeypatch,
    tmp_path,
):
    from unittest.mock import patch

    import agent as agent_module
    from agents.exploration_state import IdeaAgentState
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.store.memory import InMemoryStore
    from scripts.dev.inspect_six_dataframe_context import _SpyChatModel
    from tools.session_store import SessionStore

    monkeypatch.setenv("OPENAI_TOOL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")

    thread_id = "tool-search-tool-node"
    catalog = build_tool_catalog(thread_id)
    spy = _SpyChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "get_zone_info",
                    "args": {"zone_name": "Baie de Baffin"},
                    "id": "namespace-call",
                }],
            ),
            AIMessage(content="Zone trouvée."),
        ]
    )
    store = SessionStore(tmp_path)
    graph = create_agent(
        spy,
        list(catalog.tools),
        system_prompt=agent_module._SYSTEM_PROMPT,
        middleware=[
            agent_module._ContextMiddleware(
                user_id="tool-search-test",
                thread_id=thread_id,
                catalog_names=catalog.names,
            )
        ],
        state_schema=IdeaAgentState,
        store=InMemoryStore(),
    )

    with patch("tools.session_store.default_store", store):
        result = graph.invoke({
            "messages": [HumanMessage(content="Décris la baie de Baffin.")]
        })

    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == "get_zone_info"
    assert tool_messages[0].status == "success"
    assert "Baie de Baffin" in str(tool_messages[0].content)
