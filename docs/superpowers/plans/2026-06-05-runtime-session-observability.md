# Runtime Session Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-only per-session runtime logs under `logs/sessions/<session_id>/` with exhaustive per-turn observability and human-readable traces similar to eval logs.

**Architecture:** Introduce a best-effort `SessionRuntimeLogger` that writes append-only JSONL events, a readable turn log, and a rolling session summary. Wire it into `/chat` turn orchestration and streamed event normalization so it captures user input, tool/runtime events, retries, artifacts, assistant output, and final turn status without changing runtime behavior on failure.

**Tech Stack:** Python, FastAPI, existing streaming chat runtime, filesystem logging, pytest.

---

### Task 1: Implement the session runtime logger utility

**Files:**
- Create: `core/session_runtime_logger.py`
- Test: `tests/test_session_runtime_logger.py`

- [ ] **Step 1: Write the failing logger utility tests**

```python
from pathlib import Path

from core.session_runtime_logger import SessionRuntimeLogger


def test_logger_creates_session_files(tmp_path: Path):
    logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    logger.start_turn(turn_index=1, user_message="hello")
    logger.finish_turn(status="ok", duration_ms=12.5)

    session_dir = tmp_path / "sessions" / "session-abc"
    assert (session_dir / "events.jsonl").exists()
    assert (session_dir / "turns.log").exists()
    assert (session_dir / "session_summary.json").exists()


def test_logger_redacts_sensitive_values(tmp_path: Path):
    logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    logger.record_tool_call_started(
        tool_name="fetch_secret",
        arguments={"api_key": "sk-secret", "token": "Bearer abc"},
    )

    events_text = (tmp_path / "sessions" / "session-abc" / "events.jsonl").read_text()
    assert "sk-secret" not in events_text
    assert "Bearer abc" not in events_text
    assert "[REDACTED]" in events_text


def test_logger_truncates_large_payloads(tmp_path: Path):
    logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
        max_preview_chars=32,
    )

    logger.record_assistant_final("x" * 200)
    events_text = (tmp_path / "sessions" / "session-abc" / "events.jsonl").read_text()
    assert "x" * 80 not in events_text
    assert "..." in events_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest -q tests/test_session_runtime_logger.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.session_runtime_logger'`.

- [ ] **Step 3: Write the minimal logger implementation**

```python
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_preview(value: Any, max_chars: int) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(flag in lowered for flag in ("token", "secret", "password", "api_key", "authorization")):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _safe_preview(item, max_chars)
        return cleaned
    if isinstance(value, list):
        return [_safe_preview(item, max_chars) for item in value]
    text = str(value)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


@dataclass
class SessionRuntimeLogger:
    logs_root: str | Path = "logs"
    session_id: str = ""
    session_key: str = ""
    agent_type: str = "generic"
    max_preview_chars: int = 2000
    _turn_index: int = 0
    _current_tools: list[str] = field(default_factory=list)
    _current_artifacts: list[str] = field(default_factory=list)
    _current_errors: list[str] = field(default_factory=list)
    _last_user_message: str = ""
    _last_assistant_message: str = ""

    def __post_init__(self) -> None:
        self.logs_root = Path(self.logs_root)
        self.session_dir = self.logs_root / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self.turns_path = self.session_dir / "turns.log"
        self.summary_path = self.session_dir / "session_summary.json"

    def _append_event(self, event_type: str, **payload: Any) -> None:
        try:
            data = {
                "timestamp": _utc_now(),
                "session_id": self.session_id,
                "session_key": self.session_key,
                "agent_type": self.agent_type,
                "turn_index": self._turn_index,
                "event_type": event_type,
                **{key: _safe_preview(value, self.max_preview_chars) for key, value in payload.items()},
            }
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception:
            logger.warning("SessionRuntimeLogger append failed", exc_info=True)

    def start_turn(self, *, turn_index: int, user_message: str) -> None:
        self._turn_index = turn_index
        self._current_tools = []
        self._current_artifacts = []
        self._current_errors = []
        self._last_user_message = user_message
        self._append_event("turn_started", user_message=user_message)

    def record_tool_call_started(self, *, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        self._current_tools.append(tool_name)
        self._append_event("tool_call_started", tool_name=tool_name, arguments=arguments or {})

    def record_tool_call_finished(self, *, tool_name: str, result: Any = None, status: str = "ok", duration_ms: float | None = None) -> None:
        self._append_event("tool_call_finished", tool_name=tool_name, result=result, status=status, duration_ms=duration_ms)

    def record_assistant_final(self, content: str) -> None:
        self._last_assistant_message = content
        self._append_event("assistant_message_final", content=content)

    def record_error(self, *, error: str, source: str = "runtime") -> None:
        self._current_errors.append(error)
        self._append_event("error", error=error, source=source)

    def record_artifact_created(self, *, artifact_type: str, artifact_path: str) -> None:
        self._current_artifacts.append(artifact_path)
        self._append_event("artifact_created", artifact_type=artifact_type, artifact_path=artifact_path)

    def finish_turn(self, *, status: str, duration_ms: float) -> None:
        self._append_event("turn_finished", status=status, duration_ms=duration_ms)
        with self.turns_path.open("a", encoding="utf-8") as fh:
            fh.write(
                f"=== TURN {self._turn_index} session={self.session_id} agent={self.agent_type} ===\n"
                f"--- USER ---\n{self._last_user_message}\n\n"
                f"--- TOOL CALLS ---\n  {self._current_tools}\n\n"
                f"--- ARTIFACTS ---\n  {self._current_artifacts}\n\n"
                f"--- ASSISTANT ---\n{self._last_assistant_message}\n\n"
                f"--- TURN END ---\nstatus={status} duration_ms={duration_ms}\n\n"
            )
        summary = {
            "session_id": self.session_id,
            "session_key": self.session_key,
            "agent_type": self.agent_type,
            "turn_count": self._turn_index,
            "last_status": status,
            "last_user_message_preview": _safe_preview(self._last_user_message, self.max_preview_chars),
            "last_assistant_message_preview": _safe_preview(self._last_assistant_message, self.max_preview_chars),
            "last_tool_calls": self._current_tools,
            "last_artifact_paths": self._current_artifacts,
            "last_error": self._current_errors[-1] if self._current_errors else "",
            "last_duration_ms": duration_ms,
            "last_turn_at": _utc_now(),
        }
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest -q tests/test_session_runtime_logger.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/session_runtime_logger.py tests/test_session_runtime_logger.py
git commit -m "feat: add session runtime logger"
```

### Task 2: Integrate the logger into `/chat` turn orchestration

**Files:**
- Modify: `routers/chat_routes.py`
- Modify: `core/chat_observability.py`
- Modify: `core/chat_stream_events.py`
- Test: `tests/test_chat_observability.py`
- Test: `tests/test_chat_routes.py`

- [ ] **Step 1: Add failing integration tests for logger hooks**

```python
def test_chat_runtime_tracer_can_forward_events_to_session_logger():
    trace = FakeTrace()
    sink_calls = []

    class Sink:
        def record_runtime_event(self, event):
            sink_calls.append(event)

    tracer = ChatRuntimeTracer(trace, round_index=2, runtime_logger=Sink())
    list(tracer.observe_stream([
        {"start": True, "end": True, "role": "assistant", "type": "message", "content": "ok"},
    ]))

    assert sink_calls
    assert sink_calls[0]["type"] == "message"


def test_chat_endpoint_writes_session_logs_for_streamed_turn(client, tmp_path):
    from routers import chat_routes
    chat_routes.RUNTIME_LOGS_ROOT = tmp_path

    fake_tracer = MagicMock()
    fake_tracer.observe_stream.side_effect = lambda events: events

    with patch("routers.chat_routes.ChatRuntimeTracer.from_env", return_value=fake_tracer):
        response = client.post(
            "/chat",
            headers={"x-session-id": "session-live", "x-agent-type": "generic"},
            json={"messages": [{"role": "user", "content": "hello"}]},
        )

    assert response.status_code == 200
    assert (tmp_path / "sessions" / "session-live" / "events.jsonl").exists()
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run:

```bash
pytest -q tests/test_chat_observability.py tests/test_chat_routes.py -k "session_logs or forward_events"
```

Expected: FAIL because `ChatRuntimeTracer` has no runtime logger hook and `/chat` does not create session logs yet.

- [ ] **Step 3: Extend tracer and route integration minimally**

```python
# In core/chat_observability.py
class ChatRuntimeTracer:
    def __init__(self, trace=None, *, metadata=None, round_index=1, runtime_logger=None):
        self.trace = trace
        self.metadata = metadata or {}
        self.round_index = round_index
        self.runtime_logger = runtime_logger

    def record_event(self, event):
        if self.runtime_logger is not None:
            try:
                self.runtime_logger.record_runtime_event(event)
            except Exception:
                pass
        ...


# In routers/chat_routes.py
from core.session_runtime_logger import SessionRuntimeLogger

RUNTIME_LOGS_ROOT = Path("logs")

...
runtime_logger = SessionRuntimeLogger(
    logs_root=RUNTIME_LOGS_ROOT,
    session_id=session_id,
    session_key=session_key,
    agent_type=agent_type,
)
runtime_logger.start_turn(
    turn_index=max(1, user_turns),
    user_message=last_user_message or "",
)
tracer = ChatRuntimeTracer.from_env(...)
tracer.runtime_logger = runtime_logger

...
for result in stream_events:
    tracer.record_event(result)
    if isinstance(result, dict) and result.get("role") == "assistant" and result.get("type") == "message":
        runtime_logger.record_assistant_final(str(result.get("content") or ""))
    if isinstance(result, dict) and result.get("error"):
        runtime_logger.record_error(error=str(result["error"]))

...
runtime_logger.finish_turn(status="ok", duration_ms=summary["elapsed_ms"])
```

- [ ] **Step 4: Add explicit logging for retries, route errors, and artifacts**

```python
# In routers/chat_routes.py retry branch
runtime_logger.record_error(
    error=current_attempt_last_error_text or retry_error_text or "retry requested",
    source="retry_gate",
)

# When deliverable/image/file appears
runtime_logger.record_artifact_created(
    artifact_type=str(result.get("type") or "artifact"),
    artifact_path=str(result.get("content") or ""),
)

# In exception path
runtime_logger.record_error(error=user_msg, source="route_exception")
runtime_logger.finish_turn(status="error", duration_ms=round((_time.monotonic() - _t0) * 1000, 1))
```

- [ ] **Step 5: Run tests to verify integration passes**

Run:

```bash
pytest -q tests/test_chat_observability.py tests/test_chat_routes.py -k "session_logs or forward_events"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/chat_observability.py routers/chat_routes.py core/chat_stream_events.py tests/test_chat_observability.py tests/test_chat_routes.py
git commit -m "feat: log runtime chat sessions by turn"
```

### Task 3: Enrich runtime logger with eval-style readability and event coverage

**Files:**
- Modify: `core/session_runtime_logger.py`
- Modify: `routers/chat_routes.py`
- Test: `tests/test_session_runtime_logger.py`
- Test: `tests/test_chat_routes.py`

- [ ] **Step 1: Add failing tests for human-readable turn logs and summary state**

```python
def test_turns_log_uses_eval_style_sections(tmp_path):
    logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    logger.start_turn(turn_index=2, user_message="plot this")
    logger.record_tool_call_started(tool_name="graph_readiness", arguments={"required_columns": ["x", "y"]})
    logger.record_tool_call_finished(tool_name="graph_readiness", result={"status": "ready"}, status="ok", duration_ms=12.1)
    logger.record_assistant_final("Je pars du rapport existant.")
    logger.finish_turn(status="ok", duration_ms=55.0)

    text = (tmp_path / "sessions" / "session-abc" / "turns.log").read_text()
    assert "=== TURN 2" in text
    assert "--- TOOL CALLS ---" in text
    assert "graph_readiness" in text
    assert "--- TURN END ---" in text


def test_session_summary_tracks_last_tool_and_error(tmp_path):
    logger = SessionRuntimeLogger(
        logs_root=tmp_path,
        session_id="session-abc",
        session_key="user-1:session-abc:copepod",
        agent_type="copepod",
    )

    logger.start_turn(turn_index=1, user_message="hello")
    logger.record_tool_call_started(tool_name="inspect_file", arguments={})
    logger.record_error(error="boom", source="runtime")
    logger.finish_turn(status="error", duration_ms=21.0)

    summary = json.loads((tmp_path / "sessions" / "session-abc" / "session_summary.json").read_text())
    assert summary["last_tool_calls"] == ["inspect_file"]
    assert summary["last_error"] == "boom"
    assert summary["last_status"] == "error"
```

- [ ] **Step 2: Run logger-focused tests to verify they fail**

Run:

```bash
pytest -q tests/test_session_runtime_logger.py -k "eval_style or summary"
```

Expected: FAIL until the logger writes the richer turn narrative and summary fields.

- [ ] **Step 3: Upgrade turn rendering and runtime event normalization**

```python
def record_runtime_event(self, event: dict[str, Any]) -> None:
    role = str(event.get("role") or "")
    event_type = str(event.get("type") or "")
    payload = {
        "role": role,
        "type": event_type,
        "format": event.get("format"),
        "content": event.get("content"),
        "error": event.get("error"),
    }
    self._append_event("runtime_event", **payload)


def finish_turn(self, *, status: str, duration_ms: float) -> None:
    tool_lines = "\n".join(f"  [CALL] {name}" for name in self._current_tools) or "  []"
    artifact_lines = "\n".join(f"  [ARTIFACT] {path}" for path in self._current_artifacts) or "  []"
    error_lines = "\n".join(f"  [ERROR] {item}" for item in self._current_errors) or "  []"
    with self.turns_path.open("a", encoding="utf-8") as fh:
        fh.write(
            f"=== TURN {self._turn_index} session={self.session_id} agent={self.agent_type} ===\n"
            f"--- USER ---\n{self._last_user_message}\n\n"
            f"--- TOOL CALLS ---\n{tool_lines}\n\n"
            f"--- ARTIFACTS ---\n{artifact_lines}\n\n"
            f"--- ERRORS ---\n{error_lines}\n\n"
            f"--- ASSISTANT ---\n{self._last_assistant_message}\n\n"
            f"--- TURN END ---\nstatus={status} duration_ms={duration_ms}\n\n"
        )
```

- [ ] **Step 4: Run targeted tests and one realistic route smoke**

Run:

```bash
pytest -q tests/test_session_runtime_logger.py tests/test_chat_observability.py tests/test_chat_routes.py -k "session_runtime_logger or session_logs or forward_events"
```

Expected: PASS.

- [ ] **Step 5: Manual smoke test with live tail**

Run:

```bash
python - <<'PY'
from pathlib import Path
p = Path("logs/sessions")
print(p.exists(), sorted([x.name for x in p.iterdir()])[-3:] if p.exists() else [])
PY
tail -f logs/sessions/session-live/turns.log
```

Expected: session directory exists and `turns.log` shows eval-style turn sections while a chat session runs.

- [ ] **Step 6: Commit**

```bash
git add core/session_runtime_logger.py routers/chat_routes.py tests/test_session_runtime_logger.py tests/test_chat_routes.py
git commit -m "test: cover runtime session observability logs"
```

### Task 4: Verification pass for the end-to-end runtime logging slice

**Files:**
- Test: `tests/test_session_runtime_logger.py`
- Test: `tests/test_chat_observability.py`
- Test: `tests/test_chat_routes.py`

- [ ] **Step 1: Run the full targeted test bundle**

Run:

```bash
pytest -q tests/test_session_runtime_logger.py tests/test_chat_observability.py tests/test_chat_routes.py tests/test_chat_stream_events.py
```

Expected: PASS.

- [ ] **Step 2: Confirm no unintended regressions in nearby runtime behavior**

Run:

```bash
pytest -q tests/test_chat_routes.py -k "deliverable or inspection or retry"
```

Expected: PASS.

- [ ] **Step 3: Commit the verification checkpoint**

```bash
git add tests/test_session_runtime_logger.py tests/test_chat_observability.py tests/test_chat_routes.py
git commit -m "test: verify runtime session observability integration"
```
