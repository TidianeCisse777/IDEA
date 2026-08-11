"""Observabilité du harness curl, appel modèle par appel modèle."""

from langchain_core.messages import HumanMessage, ToolMessage


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
