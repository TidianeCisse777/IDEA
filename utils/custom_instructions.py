# Compat shim — sera supprimé une fois GenericProfile migré
from core.instruction_renderer import renderer


def get_custom_instructions(host, user_id, session_id, static_dir, upload_dir, mcp_tools=None):
    context = {
        "host": host,
        "user_id": user_id,
        "session_id": session_id,
        "static_dir": static_dir,
        "upload_dir": upload_dir,
        "mcp_tools": mcp_tools or [],
    }
    block_names = ["session_metadata", "output_format", "cli_reference", "tool_signatures", "mcp_tools_block"]
    return renderer.render(block_names, context)
