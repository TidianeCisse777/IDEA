from __future__ import annotations

from typing import Optional

from agents.base import AssistantProfile
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
from agents.registry import register
from core import session_store as session_store_module
from core.instruction_renderer import renderer as instruction_renderer
from core.session_store import SessionStore
from core.tool_registry import registry as tool_registry
from utils.session_utils import make_session_key

_BLOCKS = [
    "output_format",
    "copepod_tool_signatures",
    "mcp_tools_block",
    "session_metadata",
]


class CopepodProfile(AssistantProfile):
    agent_type = "copepod"
    tool_tags = {
        "core",
        "rag",
        "mcp",
        "copepod_data",
        "copepod_columns",
        "copepod_sources_meta",
        "copepod_remote_sources",
        "copepod_rag",
        "copepod_taxonomy",
    }
    instruction_blocks = _BLOCKS

    def __init__(self, session_store: SessionStore | None = None):
        self._session_store = session_store

    @property
    def session_store(self) -> SessionStore:
        return self._session_store or session_store_module.session_store

    def get_system_message(self, active_user_prompt: str) -> str:
        return COPEPOD_SYSTEM_PROMPT

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
        context = {
            "host": host,
            "user_id": user_id,
            "session_id": session_id,
            "static_dir": static_dir,
            "upload_dir": upload_dir,
            "mcp_tools": mcp_tools or [],
            "online_mode_enabled": self.session_store.get_online_mode(session_key),
        }
        return instruction_renderer.render(_BLOCKS, context)


register(CopepodProfile())
