from core.tool_registry.registry import Tool, registry

_code = '''# MCP Tools Support
from core.mcp_tools import call_mcp_tool, list_available_tools as list_mcp_tools'''

registry.register(Tool(name="mcp_tools", tags=frozenset({"mcp"}), code=_code))
