# ADR 005 — MCP pre-planner skipped for the copepod profile

**Status:** Accepted — 2026-06-03

## Context

`routers/chat_routes.py::plan_and_run_mcp_tools` is an LLM-router that runs *before* the main chat turn. It receives the user message + the list of available MCP tool definitions (function-calling spec), and the LLM chooses zero or more tools to invoke. Results are exposed to the main turn as preceding context.

This routing is **disabled** for `agent_type == "copepod"`. The skip is intentional but the reason wasn't documented, leading to confusion when reviewing the asymmetry between `generic` and `copepod`.

## Decision

The copepod profile does **not** use the MCP pre-planner. The main LLM turn invokes MCP tools directly from its generated Python via `call_mcp_tool(tool_id, **kwargs)`, alongside the dedicated domain tools (`fetch_remote_source_dataset`, `list_available_sources`, `query_copepod_knowledge_base`, …).

## Rationale

1. **Redundancy.** The copepod profile already exposes domain-specific tools that cover the same use cases (remote dataset fetching, knowledge queries, etc.). A separate LLM-router doing tool selection on top of an LLM that already knows when to call these tools is double work.

2. **Strict turn discipline.** The copepod system prompt mandates "plan + code block in a single response". A pre-router that streams `🔧 Using <connection> · <tool>` events before the main turn would mid-stream the response and break the single-atomic-response contract enforced by the prompt and `_build_copepod_inspect_then_code_note`.

3. **Token budget.** The router uses `LLM_MAX_COMPLETION_TOKENS` per call, plus the cost of resending the full MCP tool catalogue. For a profile that already has high-quality routing via its system prompt, this is wasted tokens.

4. **Latency.** Skipping the router shaves ~1-2s off the time-to-first-token for copepod turns (depending on model).

## Consequences

- **Positive:** Copepod streams remain "main LLM" only — predictable, cheaper, faster, no extra inference round-trip.
- **Negative:** If a user configures MCP connections that the main LLM doesn't natively reach for, those won't surface unless the LLM happens to invoke them via `call_mcp_tool`. There is no "smart routing" hint.
- **Mitigation:** The available MCP tools are still listed in the `mcp_tools_block` instruction block injected into `custom_instructions`, so the main LLM is aware they exist.

## Implementation

`routers/chat_routes.py` — the guard is:

```python
if last_user_message and agent_type != "copepod":
    tool_runs = await plan_and_run_mcp_tools(...)
```

A comment block above this `if` references this ADR.

## Related

- ADR 003 — Tool injection via `computer.run()` (explains how copepod tools reach the sandbox)
- `core/mcp/tools.py` — `call_mcp_tool` implementation invoked directly by the main LLM
