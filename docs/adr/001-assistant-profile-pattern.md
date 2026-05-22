# ADR 001 — AssistantProfile ABC + Registry pattern

**Status:** Accepted — 2026-05-21

## Context

IDEA had all agent-specific logic hardcoded in `app.py` (1817L God File):
- `interpreter.system_message` set directly from `sys_prompt`
- `interpreter.computer.run("python", custom_tool)` called with a single global string
- `interpreter.custom_instructions` set from a single global f-string

Adding a second agent type (copepod science assistant) would require modifying `app.py`
at 5+ locations and duplicating 600+ lines of tool code.

## Decision

Introduce an `AssistantProfile` ABC (`agents/base.py`) with four methods:
- `get_system_message(active_user_prompt) → str`
- `get_tool_code() → str`
- `get_custom_instructions(host, user_id, session_id, static_dir, upload_dir, mcp_tools) → str`
- `configure_interpreter(interpreter) → None` (no-op default)

A global registry (`agents/registry.py`) maps `agent_type: str` → `AssistantProfile` instance.
Profiles self-register on import. `app.py` bootstraps by importing known profiles.

The HTTP layer reads the `X-Agent-Type` request header to select the profile.
Unknown agent types fall back to `"generic"`.

## Consequences

**Positive:**
- Adding a new agent type = one new file + one import line in `app.py`. No other files change.
- Each profile is independently testable without loading FastAPI.
- Registry makes available agent types introspectable at runtime.

**Negative:**
- All profiles must be imported at startup (no lazy loading). Import errors fail silently
  if the bootstrap import is missing.
- `get_tool_code()` still returns a raw Python string — composability is limited until
  a ToolRegistry (ADR 003) is implemented.

**Alternative rejected:** Subclassing `OpenInterpreter` per agent type. Rejected because
OpenInterpreter's constructor is not designed for subclassing and its API is unstable.
