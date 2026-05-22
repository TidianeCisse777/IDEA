from __future__ import annotations

from typing import Optional

from agents.base import AssistantProfile
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
from agents.registry import register
from core.instruction_renderer import renderer as instruction_renderer
from core.tool_registry import registry as tool_registry


class CopepodProfile(AssistantProfile):
    agent_type = "copepod"
    tool_tags = {"core", "rag", "mcp"}
    instruction_blocks = [
        "session_metadata",
        "output_format",
        "cli_reference",
        "copepod_tool_signatures",
        "copepod_mode_plan",
        "copepod_mode_analyse",
        "mcp_tools_block",
    ]

    def get_system_message(self, active_user_prompt: str) -> str:
        return COPEPOD_SYSTEM_PROMPT + active_user_prompt

    def get_tool_code(self) -> str:
        return tool_registry.render(self.tool_tags)

    def get_custom_instructions(
        self,
        host: str,
        user_id: str,
        session_id: str,
        static_dir: str,
        upload_dir: str,
        mcp_tools: Optional[list[str]] = None,
    ) -> str:
        context = {
            "host": host,
            "user_id": user_id,
            "session_id": session_id,
            "static_dir": static_dir,
            "upload_dir": upload_dir,
            "mcp_tools": mcp_tools or [],
        }
        return instruction_renderer.render(self.instruction_blocks, context)


register(CopepodProfile())
