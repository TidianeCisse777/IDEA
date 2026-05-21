from __future__ import annotations
from typing import Optional
from agents.base import AssistantProfile
from agents.registry import register
from utils.custom_functions import custom_tool
from utils.custom_instructions import get_custom_instructions as _get_ci
from utils.system_prompt import sys_prompt


class GenericProfile(AssistantProfile):
    agent_type = "generic"

    def get_system_message(self, active_user_prompt: str) -> str:
        return sys_prompt + active_user_prompt

    def get_tool_code(self) -> str:
        return custom_tool

    def get_custom_instructions(
        self,
        host: str,
        user_id: str,
        session_id: str,
        static_dir: str,
        upload_dir: str,
        mcp_tools: Optional[list[str]] = None,
    ) -> str:
        return _get_ci(
            host=host,
            user_id=user_id,
            session_id=session_id,
            static_dir=static_dir,
            upload_dir=upload_dir,
            mcp_tools=mcp_tools,
        )


register(GenericProfile())
