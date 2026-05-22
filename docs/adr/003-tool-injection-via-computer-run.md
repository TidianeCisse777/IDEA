# ADR 003 — Tool injection via computer.run()

**Status:** Accepted — 2026-05-21 · Superseded-in-part by ToolRegistry (planned)

## Context

OpenInterpreter exposes `interpreter.computer.run("python", code_string)` to inject
arbitrary Python code into the interpreter's execution environment at startup.
IDEA uses this to make custom tools (`get_datetime`, `web_search`, `get_climate_index`,
`call_mcp_tool`, etc.) available to the LLM during code generation.

The alternative — importing a Python module into the interpreter's namespace — requires
the module to be on the interpreter's sys.path and introduces import-time side effects.

## Decision

Tool injection is done exclusively via `computer.run("python", profile.get_tool_code())`.

`get_tool_code()` returns a raw Python source string. The string is executed in the
interpreter's sandboxed Python environment. Functions defined in the string become
first-class callables for the LLM.

`AssistantProfile.get_tool_code()` is the seam: each profile returns whatever string
is appropriate for its agent type.

## Consequences

**Positive:**
- Zero import-path coupling between IDEA and the tool implementations.
- Tools can be added/removed per agent type without touching the interpreter config.
- The executed string is auditable as plain Python.

**Negative (current limitations):**
- `get_tool_code()` returns the entire tool set as one string — no selective composition.
  A copepod profile cannot include a subset of generic tools without string concatenation.
- Individual tools cannot be unit-tested without executing the full string in a live interpreter.
- No schema or type information on the tools — the LLM infers signatures from docstrings.

**Planned improvement:** A `ToolRegistry` (Candidate C2) will replace the monolithic string
with composable `Tool` objects (name, tags, code). `get_tool_code()` becomes
`registry.render(tags=profile.tool_tags)`. This ADR remains valid for the injection
mechanism itself — only the source of the string changes.
