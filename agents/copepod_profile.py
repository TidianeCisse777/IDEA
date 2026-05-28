from __future__ import annotations

import json
from typing import Optional

from agents.base import AssistantProfile
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
from agents.registry import register
from core import session_store as session_store_module
from core.instruction_renderer import renderer as instruction_renderer
from core.session_store import SessionStore
from core.tool_registry import registry as tool_registry
from utils.session_utils import make_session_key

_BLOCKS_PLAN = [
    "output_format",
    "copepod_tool_signatures",
    "copepod_mode_plan",
    "mcp_tools_block",
    "session_metadata",
]

_BLOCKS_ANALYSE = [
    "output_format",
    "copepod_tool_signatures",
    "copepod_mode_analyse",
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
        "copepod_artifacts",
        "copepod_taxonomy",
    }

    # Plan-mode default exposed for tests and introspection. Rendering NEVER reads this
    # attribute directly — get_custom_instructions() selects _BLOCKS_PLAN or _BLOCKS_ANALYSE
    # based on session mode. Do not use self.instruction_blocks for rendering.
    instruction_blocks = _BLOCKS_PLAN

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
        mode = self.session_store.get_session_mode(session_key)
        blocks = _BLOCKS_ANALYSE if mode == "analyse" else _BLOCKS_PLAN

        context = {
            "host": host,
            "user_id": user_id,
            "session_id": session_id,
            "static_dir": static_dir,
            "upload_dir": upload_dir,
            "mcp_tools": mcp_tools or [],
            "online_mode_enabled": self.session_store.get_online_mode(session_key),
        }
        instructions = instruction_renderer.render(blocks, context)
        if mode != "analyse":
            return instructions

        active_data_understanding = self.session_store.get_active_artifact(
            session_key, "data_understanding"
        )
        active_graph_context = self.session_store.get_active_artifact(
            session_key, "graph_context"
        )
        locked_context = {
            "data_understanding": active_data_understanding,
            "graph_context": active_graph_context,
        }
        return (
            f"{instructions}\n\n"
            "## Locked Analyse Context\n"
            "This JSON is the active execution contract for Analyse Mode. "
            "Use it as the starting context, then call "
            "`get_active_data_understanding(session_key)` and "
            "`get_active_graph_context(session_key)` if you need to verify the "
            "latest active versions before executing code.\n\n"
            "```json\n"
            f"{json.dumps(locked_context, ensure_ascii=False, indent=2, sort_keys=True)}\n"
            "```"
        )


register(CopepodProfile())
