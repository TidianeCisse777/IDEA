from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    mcp_tools = ctx.get("mcp_tools") or []
    if not mcp_tools:
        return ""
    tools_list = "\n".join(mcp_tools)
    return f"""
6. MCP TOOLS (Model Context Protocol):
You have access to external MCP tools via the call_mcp_tool function. Available tools:

{tools_list}

How to use MCP tools:
- Use the call_mcp_tool(tool_id, **kwargs) function directly in your Python code.
- The tool_id is the function name shown above (e.g., 'mcp_abc123def456_search_repositories').
- Pass tool arguments as keyword arguments.

Example usage:
    # List repositories
    result = call_mcp_tool('mcp_abc123def456_list_repositories', owner='username')
    print(result)

    # Search for datasets
    result = call_mcp_tool('mcp_abc123def456_search_datasets', query='sea surface temperature')
    print(result)

To discover available tools dynamically:
    tools = list_mcp_tools()
    for tool_id, info in tools.items():
        print(f"{{tool_id}}: {{info['description']}}")

Important notes:
- The functions call_mcp_tool and list_mcp_tools are already available in your environment (do not import them).
- Prefer MCP tools over writing your own implementation for the same data source.
- MCP tool results are returned as dictionaries; parse them to extract the data you need.
- If a tool call fails, the result will contain an 'error' key with details."""


renderer.register(InstructionBlock(
    name="mcp_tools_block",
    tags=frozenset({"mcp"}),
    render=_render,
))
