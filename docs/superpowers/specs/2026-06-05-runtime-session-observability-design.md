# Runtime Session Observability Design

## Goal

Add exhaustive local backend observability for normal runtime chat sessions, with per-session log files under `logs/sessions/<session_id>/`, mirroring the readability of `scripts/evals` console traces while preserving a machine-readable event stream.

## Scope

This design covers:

- backend-only runtime observability
- per-session log file layout
- event model for append-only runtime traces
- human-readable turn summaries modeled after eval logs
- integration points in the existing chat runtime
- safety constraints such as secret redaction and bounded payload sizes
- test coverage for the new logging layer

This design explicitly does **not** cover:

- frontend log viewers
- database persistence
- Langfuse replacement or removal
- model-generated chain-of-thought capture

## Problem Statement

`IDEA` already has strong observability in two places:

1. `scripts/evals` prints structured, readable traces by phase, round, tool call, and result.
2. runtime tracing exists in Langfuse plus persisted messages/artifacts.

What is missing is a **local filesystem runtime log** for ordinary user sessions that lets an engineer inspect what happened live or after the fact without reconstructing it from multiple systems.

The desired outcome is a backend log system that answers these questions quickly:

- what happened during this session?
- which functions/tools were called and in what order?
- what inputs and outputs were visible at each turn?
- where did retries, errors, or fallbacks happen?
- which artifacts were produced and when?

## Recommended Approach

Implement a dedicated session-scoped runtime logger with **double output**:

1. `events.jsonl` as the append-only machine-readable source of truth
2. `turns.log` as the human-readable narrative log
3. `session_summary.json` as the latest session snapshot

This is preferred over a single text log because:

- JSONL is stable for tooling, grep, replay, and automated debugging
- the text log remains easy for humans to scan during live incidents
- the summary file provides quick status without reading the full history

## File Layout

Each runtime session writes to:

```text
logs/
  sessions/
    <session_id>/
      events.jsonl
      turns.log
      session_summary.json
```

`<session_id>` here means the user-facing session identifier already used by the app transport, not an eval-specific synthetic run id.

If later isolation by user is needed, the layout can evolve to `logs/sessions/<user_id>/<session_id>/` without changing the internal event schema.

## Log Artifacts

### 1. `events.jsonl`

Append-only, one JSON object per line.

Purpose:

- exact event chronology
- scripting and filtering
- incident debugging
- future export or indexing

Representative event types:

- `session_started`
- `turn_started`
- `user_message`
- `system_prompt_set`
- `custom_instructions_set`
- `mcp_tool_run`
- `tool_call_started`
- `tool_call_finished`
- `runtime_event`
- `assistant_chunk`
- `assistant_message_final`
- `artifact_created`
- `retry`
- `route_error`
- `turn_finished`

Baseline fields on every event:

- `timestamp`
- `session_id`
- `session_key`
- `agent_type`
- `turn_index`
- `event_type`
- `source`

Optional fields depending on event type:

- `tool_name`
- `arguments_preview`
- `result_preview`
- `error`
- `duration_ms`
- `artifact_type`
- `artifact_path`
- `message_preview`
- `message_id`
- `metadata`

### 2. `turns.log`

Human-readable rolling trace, inspired by eval logs.

Example shape:

```text
=== TURN 12 session=session-j4o4f22kv agent=copepod ===
--- USER ---
ok je vais tracer profil vertical abondance et temperature

--- TOOL CALLS ---
  [CALL]  round=1 tools=['get_inspection_report', 'graph_readiness']
  [TOOL]  get_inspection_report → ok
  [TOOL]  graph_readiness → status=ready

--- ARTIFACTS ---
  [ARTIFACT] graph path=/app/static/.../plot.png

--- ASSISTANT ---
Je pars du rapport existant pour...

--- TURN END ---
status=ok duration_ms=4621 retries=1
```

Purpose:

- immediate tail-based debugging
- parity with `scripts/evals` readability
- quick incident forensics by engineers

### 3. `session_summary.json`

Latest snapshot rewritten after each turn.

Fields:

- `session_id`
- `session_key`
- `agent_type`
- `turn_count`
- `started_at`
- `last_turn_at`
- `last_status`
- `last_user_message_preview`
- `last_assistant_message_preview`
- `last_tool_calls`
- `last_artifact_paths`
- `last_error`
- `last_duration_ms`
- `retry_count_total`

Purpose:

- fast status check
- operational health visibility
- low-cost inspection without opening full logs

## Integration Points

The new logger should integrate with existing runtime flow instead of inventing a second execution pipeline.

Primary touchpoints:

- `routers/chat_routes.py`
- `core/chat_stream_events.py`
- `core/chat_observability.py`

### `routers/chat_routes.py`

Responsibilities to add:

- instantiate the session logger at the start of a turn
- emit `turn_started`
- capture the incoming user message
- pass the logger through the turn lifecycle
- record retries and route-level failures
- finalize the turn with status and duration

This route already owns per-session orchestration, retry handling, and session identity, so it is the right place to define turn boundaries.

### `core/chat_stream_events.py`

Responsibilities to add:

- emit normalized runtime events derived from the stream
- identify finalized assistant text blocks
- identify code, console, inspection report routing, and deliverable events
- forward structured events to the session logger

This preserves a single normalization layer for streamed output and avoids duplicating event parsing logic.

### `core/chat_observability.py`

Responsibilities to add:

- share event classification helpers where practical
- optionally mirror selected runtime-tracer observations into local logs
- keep Langfuse tracing and local session logging aligned in naming where possible

The local logger should not depend on Langfuse availability, but both systems should describe the same runtime truth using similar labels.

## Runtime Logger Component

Introduce a backend utility, for example:

- `core/session_runtime_logger.py`

Responsibilities:

- create per-session directories
- append JSONL events safely
- append human-readable turn summaries safely
- update `session_summary.json`
- redact sensitive values
- truncate oversized payload previews
- never raise fatal errors into user runtime

Suggested public interface:

- `start_turn(...)`
- `record_user_message(...)`
- `record_system_prompt(...)`
- `record_custom_instructions(...)`
- `record_tool_call_started(...)`
- `record_tool_call_finished(...)`
- `record_runtime_event(...)`
- `record_assistant_chunk(...)`
- `record_assistant_final(...)`
- `record_artifact_created(...)`
- `record_retry(...)`
- `record_error(...)`
- `finish_turn(...)`

All methods must be best-effort. Logging failure must never break the chat request.

## Data Handling Rules

### Redaction

Must redact or omit:

- auth tokens
- API keys
- cookies
- authorization headers
- raw credentials from MCP or env-backed tools

Use a shared sanitizer for:

- dict keys like `token`, `api_key`, `authorization`, `secret`, `password`
- obvious bearer strings
- known app credentials

### Bounded Payloads

Do not write unbounded large fields into log lines.

Rules:

- store previews, not full binary payloads
- truncate long message/tool payloads to configured limits
- never inline base64 images into session logs
- artifact references should prefer file paths and metadata over content

### Chain-of-Thought

The system must **not** attempt to log hidden model chain-of-thought.

Allowed:

- visible user input
- visible assistant output
- tool-call order
- retries/fallback notes
- route and runtime decisions observable from code paths

Not allowed:

- fabricated “internal reasoning” fields
- hidden prompt-thought dumps

## Event Semantics

The logger should represent **observable decisions**, not inferred thoughts.

Examples of useful observable decision events:

- retry after tool mismatch
- fallback when a helper returns unusable data
- graph blocked until readiness confirmation
- inspection report re-read before graph selection

These are derived from actual runtime behavior and make incidents debuggable without pretending to reveal hidden reasoning.

## Failure Model

If filesystem logging fails:

- continue user request normally
- emit standard backend logger warning
- do not retry excessively inside the request path

If a session log directory cannot be created:

- disable session-file logging for that turn
- keep the rest of runtime intact

If individual events cannot be serialized:

- replace payload with sanitized string fallback
- continue appending later events

## Testing Strategy

### Unit Tests

Add focused tests for the logger utility:

- creates session directory
- appends valid JSONL events
- updates session summary correctly
- truncates oversized payloads
- redacts sensitive fields
- tolerates serialization edge cases

### Integration Tests

Add runtime tests that simulate chat turns and assert:

- per-session folder created under `logs/sessions/<session_id>/`
- `events.jsonl` contains expected event types
- `turns.log` contains readable turn sections
- `session_summary.json` reflects final state
- tool call events recorded in correct order
- retries and route errors recorded when triggered

### Regression Cases

Include explicit tests for:

- turn with no tools
- turn with tool calls
- turn with routed inspection report
- turn with artifact creation
- turn with retry/fallback
- turn ending in backend error

## Rollout Plan

Implementation should be incremental:

1. create logger utility and file schemas
2. wire turn boundaries in `chat_routes.py`
3. wire stream event forwarding in `chat_stream_events.py`
4. wire tool/runtime metadata capture
5. add tests
6. validate on a real local session with `tail -f`

## Acceptance Criteria

The design is successful when:

- every normal chat session gets a local log directory
- engineers can inspect a session live with `tail -f logs/sessions/<session_id>/turns.log`
- engineers can parse `events.jsonl` programmatically
- tool calls, retries, errors, and artifacts are visible per turn
- runtime behavior remains unchanged if logging fails
- no secrets or huge blobs leak into log files

## Open Questions Resolved

- **DB persistence:** deferred out of scope
- **Frontend viewer:** out of scope
- **Live local observability:** in scope and primary goal
- **Reasoning capture:** limited to observable runtime decisions only

## Recommendation

Proceed with the double-output runtime logger and integrate it at turn orchestration plus stream normalization boundaries. This gives the closest practical equivalent to eval `print` observability for real user sessions without changing model behavior or introducing LLM cost.
