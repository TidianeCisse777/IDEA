# ADR 002 — 3-segment session keys

**Status:** Accepted — 2026-05-21

## Context

Before multi-agent support, session keys were `"{user_id}:{session_id}"` (2 segments).
They keyed both `interpreter_instances` (in-memory dict) and Redis message lists.

With multiple agent types, the same `(user_id, session_id)` pair must be able to host
independent interpreters — one generic, one copepod — without state leakage between them.
A single user browsing two tabs with different agents must not share interpreter state.

## Decision

Session keys are now 3 segments: `"{user_id}:{session_id}:{agent_type}"`.

Pure functions in `utils/session_utils.py` own the key contract:
- `make_session_key(user_id, session_id, agent_type="generic") → str`
- `parse_session_key(key) → (user_id, session_id, agent_type)`
- `session_dir_path(key, static_dir) → Path`
- `resolve_agent_type(requested, registered) → str`

The filesystem path uses only the first two segments: `STATIC_DIR/{user_id}/{session_id}/`
so files are shared across agent types for the same session (intentional — a user's uploaded
files are agent-agnostic).

Redis keys follow the same 3-segment pattern: `messages:{session_key}` and `last_active:{session_key}`.

**Migration:** Existing 2-segment Redis keys become unreachable after deployment. Sessions
are abandoned cleanly on the first request post-deploy. Postgres conversation history is unaffected.

## Consequences

**Positive:**
- Zero state leakage between agent types in the same user session.
- Key contract is testable without FastAPI (pure functions, no side effects).
- Filesystem layout unchanged — uploaded files remain accessible across agent types.

**Negative:**
- A user switching agent type mid-session loses their interpreter context (messages buffered
  in Redis are not migrated). Context is preserved only in Postgres if the user saved the conversation.
- Old Redis sessions (2-segment keys) silently expire rather than failing loudly.
