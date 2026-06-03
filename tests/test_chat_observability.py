from __future__ import annotations

import sys
from types import ModuleType

from core.chat_observability import ChatRuntimeTracer


class FakeSpan:
    def __init__(self, calls, payload):
        self.calls = calls
        self.payload = payload

    def end(self):
        self.calls.append(("span_end", self.payload["name"]))


class FakeTrace:
    def __init__(self):
        self.calls = []

    def span(self, **payload):
        self.calls.append(("span", payload))
        return FakeSpan(self.calls, payload)

    def generation(self, **payload):
        self.calls.append(("generation", payload))

    def update(self, **payload):
        self.calls.append(("update", payload))


def _payloads(trace, call_type):
    return [payload for kind, payload in trace.calls if kind == call_type]


def test_tracer_without_trace_is_disabled_and_passthrough():
    tracer = ChatRuntimeTracer()
    events = [{"role": "assistant", "type": "message", "content": "hello"}]

    assert tracer.enabled is False
    assert list(tracer.observe_stream(events)) == events


def test_observe_stream_captures_assistant_generation_code_and_console_output():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(
        trace,
        metadata={"session_key": "u1:s1:copepod", "session_mode": "analyse"},
        round_index=2,
    )
    events = [
        {"start": True, "role": "assistant", "type": "message", "content": "Je vais exécuter."},
        {"end": True, "role": "assistant", "type": "message", "content": " Résultat validé."},
        {"start": True, "end": True, "role": "assistant", "type": "code", "content": "df.shape"},
        {"start": True, "end": True, "role": "computer", "type": "console", "content": "(50, 12)"},
    ]

    assert list(tracer.observe_stream(events)) == events

    generations = _payloads(trace, "generation")
    spans = _payloads(trace, "span")
    assert generations[0]["name"] == "round-2"
    assert generations[0]["metadata"]["round"] == 2
    assert generations[0]["output"] == "Je vais exécuter. Résultat validé."
    assert any(
        span["name"] == "round-2/runtime/generated_code"
        and span["output"]["content"] == "df.shape"
        for span in spans
    )
    assert any(
        span["name"] == "round-2/runtime/code_output"
        and span["output"]["content"] == "(50, 12)"
        for span in spans
    )


def test_tracer_classifies_traceback_console_as_error_output():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace)

    list(tracer.observe_stream([
        {
            "start": True,
            "end": True,
            "role": "computer",
            "type": "console",
            "content": "Traceback (most recent call last): ValueError: empty result",
        }
    ]))

    spans = _payloads(trace, "span")
    assert any(
        span["name"] == "round-1/runtime/code_output_error"
        and "ValueError" in span["output"]["content"]
        for span in spans
    )


def test_tracer_records_mcp_tool_run_and_route_error():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace, metadata={"agent_type": "copepod"})

    class Connection:
        name = "GitHub"

    tracer.record_mcp_tool_run(
        {
            "connection": Connection(),
            "tool": {"name": "search_repositories"},
            "arguments": {"query": "copepod"},
            "result": {"content": [{"type": "text", "text": "repo"}]},
        }
    )
    tracer.record_route_error("boom")

    spans = _payloads(trace, "span")
    assert any(
        span["name"] == "round-1/mcp/search_repositories"
        and span["metadata"]["observation_type"] == "mcp_tool_call"
        for span in spans
    )
    assert any(
        span["name"] == "round-1/runtime/error"
        and span["output"]["error"] == "boom"
        for span in spans
    )


def test_record_copepod_retry_emits_span_with_attempt_metadata():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace, round_index=3)

    tracer.record_copepod_retry(
        attempt=1,
        error_snippet="KeyError: 'object_depth_min'",
        retry_note="Re-read the inspection reports and normalize the candidate keys.",
    )

    spans = _payloads(trace, "span")
    assert any(
        span["name"] == "round-3/copepod/retry/1"
        and span["metadata"]["observation_type"] == "copepod_retry"
        and span["metadata"]["attempt"] == 1
        and "KeyError" in span["input"]["error_snippet"]
        for span in spans
    )


def test_record_round_summary_emits_span_with_kinds_and_retry_count():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace, round_index=2)

    tracer.record_round_summary(
        had_code=True,
        had_error=True,
        had_image=False,
        retry_attempts=1,
        elapsed_ms=3420.5,
    )

    spans = _payloads(trace, "span")
    assert any(
        span["name"] == "round-2/summary"
        and span["metadata"]["observation_type"] == "round_summary"
        and span["metadata"]["retry_attempts"] == 1
        and span["output"]["had_code"] is True
        and span["output"]["had_error"] is True
        and span["output"]["retry_attempts"] == 1
        and "code" in span["output"]["kinds"]
        and "error" in span["output"]["kinds"]
        for span in spans
    )


def test_record_round_summary_kinds_text_only_when_no_code_image_error():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace)

    tracer.record_round_summary(
        had_code=False, had_error=False, had_image=False, retry_attempts=0, elapsed_ms=800.0
    )

    spans = _payloads(trace, "span")
    assert any(span["output"]["kinds"] == ["text"] for span in spans)


def test_record_system_prompt_emits_span_with_component_flags():
    trace = FakeTrace()
    tracer = ChatRuntimeTracer(trace, round_index=1)

    tracer.record_system_prompt(
        "## System\nYou are Copepod.\n\n## Session resources\nfile.tsv",
        components={"has_session_resources": True, "has_inspect_hints": False, "has_retry_note": False},
    )

    spans = _payloads(trace, "span")
    assert any(
        span["name"] == "round-1/system_prompt"
        and span["output"]["has_session_resources"] is True
        and span["output"]["has_inspect_hints"] is False
        for span in spans
    )


def test_from_env_creates_user_session_trace_with_round_metadata(monkeypatch):
    class FakeLangfuse:
        instances = []

        def __init__(self):
            self.traces = []
            FakeLangfuse.instances.append(self)

        def trace(self, **payload):
            trace = FakeTrace()
            trace.payload = payload
            self.traces.append(trace)
            return trace

    fake_module = ModuleType("langfuse")
    fake_module.Langfuse = FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("IDEA_ENABLE_LANGFUSE_IN_TESTS", "1")

    tracer = ChatRuntimeTracer.from_env(
        session_key="user-123:session-abc:copepod",
        user_id="user-123",
        agent_type="copepod",
        model="gpt-test",
        user_input={"role": "user", "content": "trace cette conversation"},
        round_index=4,
    )

    assert tracer.enabled is True
    trace_payload = FakeLangfuse.instances[0].traces[0].payload
    assert trace_payload["user_id"] == "user-123"
    assert trace_payload["session_id"] == "user-123:session-abc:copepod"
    assert trace_payload["name"] == "copepod/round-4"
    assert trace_payload["metadata"]["round"] == 4
    assert trace_payload["metadata"]["agent_type"] == "copepod"

    list(tracer.observe_stream([
        {"start": True, "end": True, "role": "assistant", "type": "code", "content": "inspect_file('x.tsv')"},
        {"start": True, "end": True, "role": "computer", "type": "console", "content": "{'format': 'tsv'}"},
    ]))
    tracer.record_mcp_tool_run(
        {
            "connection": type("Connection", (), {"name": "Example MCP"})(),
            "tool": {"name": "fetch_dataset"},
            "arguments": {"id": "abc"},
            "result": {"ok": True},
        }
    )

    spans = _payloads(tracer.trace, "span")
    assert any(span["name"] == "round-4/runtime/generated_code" for span in spans)
    assert any(span["name"] == "round-4/runtime/code_output" for span in spans)
    assert any(span["name"] == "round-4/mcp/fetch_dataset" for span in spans)
