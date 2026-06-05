import json

import pytest

from core.copepod_observability import (
    record_copepod_tool_call_finish,
    record_copepod_tool_call_start,
    trace_copepod_event,
)


def test_trace_copepod_event_never_raises_when_langfuse_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("langfuse unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    trace_copepod_event(
        "data_understanding_draft_created",
        session_key="u1:s1:copepod",
        output={"version_id": "du-test"},
    )


def test_runtime_tool_call_logging_populates_session_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    session_key = "u1:session-abc:copepod"
    monkeypatch.setenv("IDEA_RUNTIME_ROUND", "5")

    record_copepod_tool_call_start(
        "graph_readiness",
        session_key=session_key,
        input={"required_columns": ["abundance", "temperature"]},
    )
    record_copepod_tool_call_finish(
        "graph_readiness",
        session_key=session_key,
        input={"required_columns": ["abundance", "temperature"]},
        output={"status": "ready"},
        metadata={"elapsed_ms": 12.4},
    )

    session_dir = tmp_path / "logs" / "sessions" / "session-abc"
    events = [
        json.loads(line)
        for line in (session_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads((session_dir / "session_summary.json").read_text(encoding="utf-8"))

    assert any(event["event_type"] == "tool_call_started" for event in events)
    assert any(event["event_type"] == "tool_call_finished" for event in events)
    assert all(event["turn_index"] == 5 for event in events if event["event_type"].startswith("tool_call_"))
    assert summary["last_tool_calls"] == ["graph_readiness"]


@pytest.mark.tool_contract
def test_wrapped_copepod_tool_logs_locally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IDEA_RUNTIME_SESSION_KEY", "u1:session-xyz:copepod")
    monkeypatch.setenv("IDEA_RUNTIME_ROUND", "2")

    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_data  # noqa: F401

    ns = {}
    exec(registry.render({"copepod_data"}), ns)
    fixture = tmp_path / "mini.tsv"
    fixture.write_text("a\tb\n1\t2\n", encoding="utf-8")

    result = ns["inspect_file"](str(fixture))

    summary = json.loads(
        (tmp_path / "logs" / "sessions" / "session-xyz" / "session_summary.json").read_text(encoding="utf-8")
    )
    assert result["format"] == "tsv"
    assert "inspect_file" in summary["last_tool_calls"]
