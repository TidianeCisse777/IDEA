from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    return f"""## Copepod Runtime Tools
You have access to host Python functions through the IDEA/OpenInterpreter environment. Use only tools relevant to copepod graphing workflows.

Allowed runtime functions for this first increment:
- get_datetime(): use only for current date/time when needed.
- query_knowledge_base(query, "{user_id}", "{session_id}"): use for user-uploaded knowledge documents when a definition, method, limitation, or citation must be grounded.
- call_mcp_tool(tool_id, **kwargs): use only for explicitly available MCP tools relevant to the copepod task.
- list_mcp_tools(): discover available MCP tools when needed.

Rules:
- Do not use station, sea-level, tide-gauge, datum, or climate-index tools for this profile.
- Do not reimplement provided tools when an appropriate tool exists.
- Do not expose credentials, environment variables, tokens, or secrets in outputs.
- Keep tool use proportional to the graphing task.
"""


renderer.register(InstructionBlock(
    name="copepod_tool_signatures",
    tags=frozenset({"copepod", "tools"}),
    render=_render,
))
