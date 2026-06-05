from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "api_key", "authorization", "cookie")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key or "").lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def sanitize_preview(value: Any, max_chars: int) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                cleaned[str(key)] = _REDACTED
            else:
                cleaned[str(key)] = sanitize_preview(item, max_chars)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [sanitize_preview(item, max_chars) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate_text(str(value), max_chars)


def _safe_json_dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@dataclass
class SessionRuntimeLogger:
    logs_root: str | Path = "logs"
    session_id: str = ""
    session_key: str = ""
    agent_type: str = "generic"
    max_preview_chars: int = 8000
    _turn_index: int = 0
    _started_at: str = field(default_factory=_utc_now)
    _last_turn_at: str = ""
    _last_status: str = ""
    _retry_count_total: int = 0
    _current_tools: list[str] = field(default_factory=list)
    _current_tool_records: list[dict[str, Any]] = field(default_factory=list)
    _current_artifacts: list[str] = field(default_factory=list)
    _current_errors: list[str] = field(default_factory=list)
    _current_codes: list[str] = field(default_factory=list)
    _current_code_buffer: str = ""
    _current_status_lines: list[str] = field(default_factory=list)
    _last_user_message: str = ""
    _last_assistant_message: str = ""
    _last_system_prompt: str = ""

    def __post_init__(self) -> None:
        self.logs_root = Path(self.logs_root)
        self.session_dir = self.logs_root / "sessions" / self.session_id
        self.events_path = self.session_dir / "events.jsonl"
        self.turns_path = self.session_dir / "turns.log"
        self.summary_path = self.session_dir / "session_summary.json"
        self._ensure_dir()
        if self._turn_index <= 0:
            self._turn_index = self._infer_turn_index()

    def _ensure_dir(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _read_summary(self) -> dict[str, Any]:
        try:
            if self.summary_path.exists():
                return json.loads(self.summary_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Session summary read failed", exc_info=True)
        return {}

    def _infer_turn_index(self) -> int:
        round_env = str(os.getenv("IDEA_RUNTIME_ROUND") or "").strip()
        if round_env.isdigit():
            return max(0, int(round_env))
        existing = self._read_summary()
        turn_count = existing.get("turn_count")
        if isinstance(turn_count, int):
            return max(0, turn_count)
        return 0

    def _iter_turn_events(self) -> list[dict[str, Any]]:
        if self._turn_index <= 0 or not self.events_path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if int(event.get("turn_index") or 0) == self._turn_index:
                    out.append(event)
        except Exception:
            logger.warning("Session events read failed", exc_info=True)
        return out

    def _hydrate_turn_state_from_events(self) -> None:
        events = self._iter_turn_events()
        if not events:
            return
        if not self._current_tool_records:
            tool_records: list[dict[str, Any]] = []
            pending: dict[str, list[dict[str, Any]]] = {}
            for event in events:
                if event.get("event_type") == "tool_call_started":
                    record = {
                        "tool_name": event.get("tool_name") or "",
                        "arguments": event.get("arguments") or {},
                        "result": None,
                        "status": "started",
                        "duration_ms": None,
                    }
                    tool_records.append(record)
                    pending.setdefault(str(record["tool_name"]), []).append(record)
                elif event.get("event_type") == "tool_call_finished":
                    tool_name = str(event.get("tool_name") or "")
                    result = event.get("result")
                    status = str(event.get("status") or "ok")
                    duration_ms = event.get("duration_ms")
                    queue = pending.get(tool_name) or []
                    if queue:
                        record = queue.pop(0)
                        record["result"] = result
                        record["status"] = status
                        record["duration_ms"] = duration_ms
                    else:
                        tool_records.append({
                            "tool_name": tool_name,
                            "arguments": {},
                            "result": result,
                            "status": status,
                            "duration_ms": duration_ms,
                        })
            if tool_records:
                self._current_tool_records = tool_records
        if not self._current_tools and self._current_tool_records:
            self._current_tools = [str(record.get("tool_name") or "") for record in self._current_tool_records]
        if not self._current_codes:
            code_blocks: list[str] = []
            buf = ""
            in_code = False
            for event in events:
                if event.get("event_type") != "runtime_event":
                    continue
                if str(event.get("role") or "") != "assistant" or str(event.get("type") or "") != "code":
                    continue
                content = event.get("content")
                text = content if isinstance(content, str) else ""
                if event.get("start"):
                    buf = text
                    in_code = True
                elif in_code:
                    buf += text
                elif text:
                    buf += text
                if event.get("end"):
                    if buf.strip():
                        code_blocks.append(buf)
                    buf = ""
                    in_code = False
            if buf.strip():
                code_blocks.append(buf)
            if code_blocks:
                self._current_codes = code_blocks

    def _append_event(self, event_type: str, **payload: Any) -> None:
        try:
            self._ensure_dir()
            data = {
                "timestamp": _utc_now(),
                "session_id": self.session_id,
                "session_key": self.session_key,
                "agent_type": self.agent_type,
                "turn_index": self._turn_index,
                "event_type": event_type,
            }
            for key, value in payload.items():
                data[key] = sanitize_preview(value, self.max_preview_chars)
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(_safe_json_dump(data) + "\n")
        except Exception:
            logger.warning("Session runtime logging failed", exc_info=True)

    def _write_summary(self, *, status: str = "", duration_ms: float | None = None) -> None:
        try:
            self._ensure_dir()
            self._hydrate_turn_state_from_events()
            existing = self._read_summary()
            last_tool_calls = list(self._current_tools)
            if not last_tool_calls:
                fallback_tools = existing.get("last_tool_calls")
                if isinstance(fallback_tools, list):
                    last_tool_calls = [str(item) for item in fallback_tools]
            last_artifact_paths = list(self._current_artifacts)
            if not last_artifact_paths:
                fallback_artifacts = existing.get("last_artifact_paths")
                if isinstance(fallback_artifacts, list):
                    last_artifact_paths = [str(item) for item in fallback_artifacts]
            last_error = self._current_errors[-1] if self._current_errors else str(existing.get("last_error") or "")
            summary = {
                "session_id": self.session_id,
                "session_key": self.session_key,
                "agent_type": self.agent_type,
                "turn_count": self._turn_index,
                "started_at": self._started_at,
                "last_turn_at": self._last_turn_at or _utc_now(),
                "last_status": status or self._last_status,
                "last_user_message_preview": sanitize_preview(self._last_user_message, self.max_preview_chars),
                "last_assistant_message_preview": sanitize_preview(self._last_assistant_message, self.max_preview_chars),
                "last_system_prompt_preview": sanitize_preview(self._last_system_prompt, self.max_preview_chars),
                "last_tool_calls": last_tool_calls,
                "last_artifact_paths": last_artifact_paths,
                "last_error": last_error,
                "last_duration_ms": duration_ms,
                "retry_count_total": self._retry_count_total,
            }
            self.summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Session summary write failed", exc_info=True)

    def start_turn(self, *, turn_index: int, user_message: str) -> None:
        self._turn_index = turn_index
        self._last_turn_at = _utc_now()
        self._current_tools = []
        self._current_tool_records = []
        self._current_artifacts = []
        self._current_errors = []
        self._current_codes = []
        self._current_code_buffer = ""
        self._current_status_lines = []
        self._last_user_message = user_message or ""
        self._last_assistant_message = ""
        self._append_event("turn_started", user_message=user_message)
        self._write_summary()

    def record_user_message(self, content: str) -> None:
        self._last_user_message = content or ""
        self._append_event("user_message", content=content)

    def record_system_prompt(self, content: str, *, components: dict[str, Any] | None = None) -> None:
        self._last_system_prompt = content or ""
        self._append_event("system_prompt_set", content=content, components=components or {})

    def record_custom_instructions(self, content: str) -> None:
        self._append_event("custom_instructions_set", content=content)

    def record_mcp_tool_run(self, run: dict[str, Any]) -> None:
        connection = getattr(run.get("connection"), "name", None)
        tool = (run.get("tool") or {}).get("name") or "unknown"
        tool_name = f"{connection}:{tool}" if connection else tool
        self._current_tools.append(tool_name)
        self._current_tool_records.append({
            "tool_name": tool_name,
            "arguments": run.get("arguments") or {},
            "result": run.get("result"),
            "status": "ok",
            "duration_ms": None,
        })
        self._append_event(
            "mcp_tool_run",
            connection=connection,
            tool_name=tool,
            arguments=run.get("arguments") or {},
            result=run.get("result"),
        )
        self._write_summary()

    def record_tool_call_started(self, *, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        self._current_tools.append(tool_name)
        self._current_tool_records.append({
            "tool_name": tool_name,
            "arguments": arguments or {},
            "result": None,
            "status": "started",
            "duration_ms": None,
        })
        self._append_event("tool_call_started", tool_name=tool_name, arguments=arguments or {})
        self._write_summary()

    def record_tool_call_finished(
        self,
        *,
        tool_name: str,
        result: Any = None,
        status: str = "ok",
        duration_ms: float | None = None,
    ) -> None:
        if tool_name and tool_name not in self._current_tools:
            self._current_tools.append(tool_name)
        for record in reversed(self._current_tool_records):
            if record.get("tool_name") == tool_name and record.get("status") == "started":
                record["result"] = result
                record["status"] = status
                record["duration_ms"] = duration_ms
                break
        else:
            self._current_tool_records.append({
                "tool_name": tool_name,
                "arguments": {},
                "result": result,
                "status": status,
                "duration_ms": duration_ms,
            })
        self._append_event(
            "tool_call_finished",
            tool_name=tool_name,
            result=result,
            status=status,
            duration_ms=duration_ms,
        )
        self._write_summary()

    def record_runtime_event(self, event: Any) -> None:
        if not isinstance(event, dict):
            self._append_event("runtime_event", raw=str(event))
            return

        role = str(event.get("role") or "")
        event_type = str(event.get("type") or "")
        fmt = str(event.get("format") or "")
        content = event.get("content")
        error = event.get("error")
        self._append_event(
            "runtime_event",
            role=role,
            type=event_type,
            format=fmt,
            content=content,
            error=error,
            start=bool(event.get("start")),
            end=bool(event.get("end")),
        )

        if role == "assistant" and event_type == "message" and isinstance(content, str):
            self._last_assistant_message = content
        elif role == "assistant" and event_type == "code" and isinstance(content, str):
            if bool(event.get("start")):
                self._current_code_buffer = content
            elif self._current_code_buffer:
                self._current_code_buffer += content
            else:
                self._current_code_buffer = content
            if bool(event.get("end")):
                if self._current_code_buffer.strip():
                    self._current_codes.append(self._current_code_buffer)
                self._current_code_buffer = ""
        elif role == "computer" and event_type in {"deliverable", "image", "file"} and content:
            self._current_artifacts.append(str(content))
        elif event_type == "message" and fmt == "tool_status" and isinstance(content, str) and content.strip():
            self._current_status_lines.append(content.strip())

        if error:
            self._current_errors.append(str(error))

    def record_assistant_final(self, content: str) -> None:
        self._last_assistant_message = content or ""
        self._append_event("assistant_message_final", content=content)

    def record_artifact_created(self, *, artifact_type: str, artifact_path: str) -> None:
        self._current_artifacts.append(artifact_path)
        self._append_event(
            "artifact_created",
            artifact_type=artifact_type,
            artifact_path=artifact_path,
        )
        self._write_summary()

    def record_retry(self, *, attempt: int, error_snippet: str, retry_note: str) -> None:
        self._retry_count_total += 1
        self._append_event(
            "retry",
            attempt=attempt,
            error_snippet=error_snippet,
            retry_note=retry_note,
        )
        self._write_summary()

    def record_error(self, *, error: str, source: str = "runtime") -> None:
        self._current_errors.append(error)
        self._append_event("error", error=error, source=source)
        self._write_summary()

    def finish_turn(
        self,
        *,
        status: str,
        duration_ms: float,
        usage: dict[str, Any] | None = None,
        context_chars: int | None = None,
    ) -> None:
        self._last_status = status
        self._last_turn_at = _utc_now()
        if self._current_code_buffer.strip():
            self._current_codes.append(self._current_code_buffer)
            self._current_code_buffer = ""
        self._hydrate_turn_state_from_events()
        self._append_event(
            "turn_finished",
            status=status,
            duration_ms=duration_ms,
            usage=usage or {},
            context_chars=context_chars,
        )
        try:
            self._ensure_dir()
            tool_lines = self._format_tool_lines()
            status_lines = "\n".join(f"  [STATUS] {line}" for line in self._current_status_lines) or "  []"
            code_lines = "\n".join(f"  [CODE]  {sanitize_preview(code.strip(), 4000)}" for code in self._current_codes if code.strip()) or "  []"
            artifact_lines = "\n".join(f"  [ARTIFACT] {path}" for path in self._current_artifacts) or "  []"
            error_lines = "\n".join(f"  [ERROR] {line}" for line in self._current_errors) or "  []"
            ctx_tokens = round(context_chars / 4) if context_chars is not None else None
            prompt_tokens = (usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens")
            completion_tokens = (usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens")
            ctx_line = ""
            if ctx_tokens is not None or prompt_tokens is not None:
                parts = []
                if ctx_tokens is not None:
                    parts.append(f"ctx_payload≈{ctx_tokens}tok ({context_chars}ch)")
                if prompt_tokens is not None:
                    parts.append(f"prompt={prompt_tokens}tok")
                if completion_tokens is not None:
                    parts.append(f"completion={completion_tokens}tok")
                ctx_line = " " + " | ".join(parts)
            with self.turns_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"=== TURN {self._turn_index} session={self.session_id} agent={self.agent_type} ===\n"
                    f"--- USER ---\n{self._last_user_message}\n\n"
                    f"--- TOOL CALLS ---\n{tool_lines}\n\n"
                    f"--- TOOL STATUS ---\n{status_lines}\n\n"
                    f"--- GENERATED CODE ---\n{code_lines}\n\n"
                    f"--- ARTIFACTS ---\n{artifact_lines}\n\n"
                    f"--- ERRORS ---\n{error_lines}\n\n"
                    f"--- ASSISTANT ---\n{self._last_assistant_message}\n\n"
                    f"--- TURN END ---\nstatus={status} duration_ms={duration_ms} retries={self._retry_count_total}{ctx_line}\n\n"
                )
        except Exception:
            logger.warning("Turn log write failed", exc_info=True)
        self._write_summary(status=status, duration_ms=duration_ms)

    def _format_tool_lines(self) -> str:
        if not self._current_tool_records:
            return "  []"
        blocks: list[str] = []
        for record in self._current_tool_records:
            tool_name = str(record.get("tool_name") or "")
            args = sanitize_preview(record.get("arguments") or {}, self.max_preview_chars)
            result = sanitize_preview(record.get("result"), self.max_preview_chars)
            call_status = str(record.get("status") or "")
            duration_ms = record.get("duration_ms")
            blocks.append(f"  [CALL]  {tool_name}")
            if args not in ({}, None, ""):
                blocks.append(f"  [ARGS]  {_safe_json_dump(args)}")
            if result not in (None, "", {}):
                label = "[ERROR]" if call_status == "error" else "[RESULT]"
                blocks.append(f"  {label} {_safe_json_dump(result)}")
            if call_status:
                blocks.append(f"  [STATUS] {call_status}")
            if duration_ms is not None:
                blocks.append(f"  [DURATION_MS] {duration_ms}")
        return "\n".join(blocks)
