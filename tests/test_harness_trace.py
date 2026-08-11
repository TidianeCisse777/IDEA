"""Observabilité du harness curl, appel modèle par appel modèle."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_harness_trace_exposes_model_tools_provenance_and_usage():
    import agent
    from serve import debug_harness_trace

    thread_id = "curl-observe-test"
    agent.clear_harness_trace(thread_id)
    agent._begin_harness_turn(thread_id, [HumanMessage(content="Fais une carte")])
    agent._append_harness_model_call(
        thread_id,
        {
            "approx_tokens_model_request": 4321,
            "approx_tokens_base_system": 2896,
            "approx_tokens_tool_schemas": 900,
            "approx_tokens_after_trim": 400,
            "tools_exposed": ["run_pandas", "run_graph"],
            "tool_exposure_groups": ["core", "visualization"],
            "turn_authorized_sources": ["file"],
            "turn_active_variable": "df_file_stations",
        },
    )
    trace_id = agent._start_harness_tool_call(
        thread_id,
        {
            "id": "call-analysis",
            "name": "run_pandas",
            "args": {"code": "result = 1", "api_key": "secret"},
        },
    )
    result = ToolMessage(
        content="1",
        tool_call_id="call-analysis",
        artifact={
            "status": "success",
            "persisted": True,
            "provenance": {
                "source": "controlled pandas execution",
            },
        },
    )
    agent._finish_harness_tool_call(thread_id, trace_id, result)
    agent.record_harness_usage(
        thread_id,
        {"prompt_tokens": 5000, "completion_tokens": 250, "total_tokens": 5250},
    )

    trace = debug_harness_trace(thread_id)["trace"]

    assert trace["model_calls"][0]["tools_exposed"] == ["run_pandas", "run_graph"]
    assert trace["tool_calls"][0]["status"] == "success"
    assert trace["tool_calls"][0]["arguments"]["api_key"] == "[REDACTED]"
    assert trace["tool_calls"][0]["provenance"]["source"] == "controlled pandas execution"
    assert trace["usage"]["total_tokens"] == 5250


def test_harness_trace_records_running_tools_before_completion():
    import agent

    thread_id = "curl-observe-running"
    agent.clear_harness_trace(thread_id)
    agent._begin_harness_turn(thread_id, [HumanMessage(content="Enrichis")])

    agent._start_harness_tool_call(
        thread_id,
        {"id": "call-1", "name": "enrich_with_amundsen_ctd", "args": {}},
    )

    assert agent.get_harness_trace(thread_id)["tool_calls"][0]["status"] == "running"


def test_harness_monitor_preserves_context_and_model_decisions_by_turn():
    import agent
    from serve import debug_harness_turns

    thread_id = "harness-turn-history"
    agent.clear_harness_trace(thread_id)

    agent._begin_harness_turn(
        thread_id,
        [HumanMessage(content="Choisis le meilleur tableau", id="user-turn-1")],
    )
    agent._append_harness_model_call(
        thread_id,
        {
            "approx_tokens_model_request": 900,
            "tools_exposed": ["run_pandas"],
            "harness_context": {
                "current_task": "## CURRENT TASK\nChoisir un tableau",
                "available_dataframes": "## AVAILABLE DATAFRAMES\n- df_summary",
                "last_graph": "",
                "exploration_frontier": "",
            },
        },
    )
    agent._finish_harness_model_call(
        thread_id,
        AIMessage(
            content="Je choisis df_summary.",
            usage_metadata={
                "input_tokens": 900,
                "output_tokens": 20,
                "total_tokens": 920,
            },
        ),
    )
    agent.record_harness_usage(
        thread_id,
        {"prompt_tokens": 900, "completion_tokens": 20, "total_tokens": 920},
        assistant_response="Je choisis df_summary.",
    )

    agent._begin_harness_turn(
        thread_id,
        [HumanMessage(content="Trace-le", id="user-turn-2")],
    )

    turns = agent.get_harness_turns(thread_id)
    assert [turn["turn_index"] for turn in turns] == [1, 2]
    assert turns[0]["model_calls"][0]["response_preview"] == "Je choisis df_summary."
    assert "df_summary" in turns[0]["model_calls"][0]["context"]["available_dataframes"]
    assert turns[0]["assistant_response"] == "Je choisis df_summary."
    assert turns[1]["user_message"] == "Trace-le"

    first_turn = debug_harness_turns(thread_id, turn_index=1)
    assert first_turn["turn"]["turn_index"] == 1
    assert first_turn["total_turns"] == 2


def test_harness_accepts_openai_stream_metadata_with_null_token_usage():
    import agent

    thread_id = "harness-null-token-usage"
    agent.clear_harness_trace(thread_id)
    agent._begin_harness_turn(
        thread_id,
        [HumanMessage(content="Bonjour", id="null-token-usage")],
    )
    agent._append_harness_model_call(thread_id, {})

    agent._finish_harness_model_call(
        thread_id,
        AIMessage(
            content="Bonjour.",
            response_metadata={"token_usage": None},
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "input_token_details": {
                    "cache_read": 6,
                    "cache_creation": 3,
                },
            },
        ),
    )
    agent.record_harness_usage(
        thread_id,
        {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "prompt_tokens_details": {
                "cached_tokens": 6,
                "cache_creation_tokens": 3,
            },
        },
    )

    call = agent.get_harness_trace(thread_id)["model_calls"][0]
    assert call["provider_usage"]["cached_tokens"] == 6
    assert call["provider_usage"]["cache_creation_tokens"] == 3
    assert call["response_preview"] == "Bonjour."
    assert (
        agent.get_harness_trace(thread_id)["usage"]["cumulative_model_calls"][
            "cache_creation_tokens"
        ]
        == 3
    )
