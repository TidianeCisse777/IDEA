from __future__ import annotations

from typing import Optional

from agents.base import AssistantProfile
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
from agents.registry import register
from core.instruction_renderer import renderer as instruction_renderer
from core.session_store import session_store
from core.tool_registry import registry as tool_registry
from utils.session_utils import make_session_key

_BLOCKS_PLAN = [
    "session_metadata",
    "output_format",
    "cli_reference",
    "copepod_tool_signatures",
    "copepod_mode_plan",
    "copepod_mode_analyse",
    "mcp_tools_block",
]

_BLOCKS_ANALYSE = [
    "session_metadata",
    "output_format",
    "cli_reference",
    "copepod_tool_signatures",
    "copepod_mode_analyse",
    "mcp_tools_block",
]


class CopepodProfile(AssistantProfile):
    agent_type = "copepod"
    tool_tags = {"core", "rag", "mcp"}

    # instruction_blocks is dynamic — resolved per session in get_custom_instructions
    instruction_blocks = _BLOCKS_PLAN

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
        session_key = make_session_key(user_id, session_id, self.agent_type)
        mode = session_store.get_session_mode(session_key)
        blocks = _BLOCKS_ANALYSE if mode == "analyse" else _BLOCKS_PLAN

        context = {
            "host": host,
            "user_id": user_id,
            "session_id": session_id,
            "static_dir": static_dir,
            "upload_dir": upload_dir,
            "mcp_tools": mcp_tools or [],
        }
        return instruction_renderer.render(blocks, context)


register(CopepodProfile())
