from __future__ import annotations

import json
from pathlib import Path

from core.session_runtime_logger import SessionRuntimeLogger


def _session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions" / "session-abc"


def test_logger_creates_session_files(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    runtime_logger.start_turn(turn_index=1, user_message="hello")
    runtime_logger.finish_turn(status="ok", duration_ms=12.5)

    session_dir = _session_dir(tmp_path)
    assert (session_dir / "events.jsonl").exists()
    assert (session_dir / "turns.log").exists()
    assert (session_dir / "session_summary.json").exists()


def test_logger_redacts_sensitive_values(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    runtime_logger.record_tool_call_started(
        tool_name="fetch_secret",
        arguments={"api_key": "sk-secret", "token": "Bearer abc", "safe": "yes"},
    )

    text = (_session_dir(tmp_path) / "events.jsonl").read_text(encoding="utf-8")
    assert "sk-secret" not in text
    assert "Bearer abc" not in text
    assert "[REDACTED]" in text
    assert "yes" in text


def test_logger_truncates_large_payloads(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
        max_preview_chars=32,
    )

    runtime_logger.record_assistant_final("x" * 200)
    text = (_session_dir(tmp_path) / "events.jsonl").read_text(encoding="utf-8")
    assert "x" * 60 not in text
    assert "..." in text


def test_turns_log_uses_eval_style_sections(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    runtime_logger.start_turn(turn_index=2, user_message="plot this")
    runtime_logger.record_tool_call_started(
        tool_name="graph_readiness",
        arguments={"required_columns": ["x", "y"]},
    )
    runtime_logger.record_tool_call_finished(
        tool_name="graph_readiness",
        result={"status": "ready"},
        status="ok",
        duration_ms=12.1,
    )
    runtime_logger.record_tool_call_started(
        tool_name="inspect_and_report",
        arguments={"file_paths": ["bad.tsv"]},
    )
    runtime_logger.record_tool_call_finished(
        tool_name="inspect_and_report",
        result={"error": "file not found"},
        status="error",
        duration_ms=4.2,
    )
    runtime_logger.record_runtime_event(
        {
            "role": "assistant",
            "type": "message",
            "content": "Je pars du rapport existant.",
            "start": True,
            "end": True,
        }
    )
    runtime_logger.finish_turn(status="ok", duration_ms=55.0)

    text = (_session_dir(tmp_path) / "turns.log").read_text(encoding="utf-8")
    assert "=== TURN 2" in text
    assert "--- TOOL CALLS ---" in text
    assert "[CALL]  graph_readiness" in text
    assert "[ARGS]  {\"required_columns\": [\"x\", \"y\"]}" in text
    assert "[RESULT] {\"status\": \"ready\"}" in text
    assert "[CALL]  inspect_and_report" in text
    assert "[ERROR] {\"error\": \"file not found\"}" in text
    assert "[DURATION_MS] 12.1" in text
    assert "--- TURN END ---" in text


def test_session_summary_tracks_last_tool_and_error(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    runtime_logger.start_turn(turn_index=1, user_message="hello")
    runtime_logger.record_tool_call_started(tool_name="inspect_file", arguments={})
    runtime_logger.record_error(error="boom", source="runtime")
    runtime_logger.finish_turn(status="error", duration_ms=21.0)

    summary = json.loads((_session_dir(tmp_path) / "session_summary.json").read_text(encoding="utf-8"))
    assert summary["last_tool_calls"] == ["inspect_file"]
    assert summary["last_error"] == "boom"
    assert summary["last_status"] == "error"


def test_finish_turn_preserves_tool_calls_recorded_by_helper_logger(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("IDEA_RUNTIME_ROUND", "3")

    main_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )
    main_logger.start_turn(turn_index=3, user_message="show columns")

    helper_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )
    helper_logger.record_tool_call_started(
        tool_name="get_inspection_report",
        arguments={"args": ["sample.tsv"], "kwargs": {}},
    )
    helper_logger.record_tool_call_finished(
        tool_name="get_inspection_report",
        result={"status": "ok"},
        status="ok",
        duration_ms=18.2,
    )

    main_logger.finish_turn(status="ok", duration_ms=41.0)

    summary = json.loads((_session_dir(tmp_path) / "session_summary.json").read_text(encoding="utf-8"))
    turns = (_session_dir(tmp_path) / "turns.log").read_text(encoding="utf-8")

    assert summary["turn_count"] == 3
    assert summary["last_tool_calls"] == ["get_inspection_report"]
    assert "[CALL]  get_inspection_report" in turns
    assert "[DURATION_MS] 18.2" in turns


def test_runtime_code_chunks_are_grouped_into_single_block(tmp_path: Path):
    runtime_logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    runtime_logger.start_turn(turn_index=4, user_message="inspect")
    runtime_logger.record_runtime_event(
        {"role": "assistant", "type": "code", "format": "python", "content": "", "start": True, "end": False}
    )
    runtime_logger.record_runtime_event(
        {"role": "assistant", "type": "code", "format": "python", "content": "inspection = inspect_and_report(", "start": False, "end": False}
    )
    runtime_logger.record_runtime_event(
        {"role": "assistant", "type": "code", "format": "python", "content": '["/tmp/a.tsv"])\nprint(inspection["output"])', "start": False, "end": True}
    )
    runtime_logger.finish_turn(status="ok", duration_ms=10.0)

    text = (_session_dir(tmp_path) / "turns.log").read_text(encoding="utf-8")
    assert text.count("[CODE]") == 1
    assert 'inspection = inspect_and_report(["/tmp/a.tsv"])' in text
    assert 'print(inspection["output"])' in text
