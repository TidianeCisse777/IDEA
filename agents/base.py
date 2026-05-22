from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional


class AssistantProfile(ABC):
    agent_type: str
    tool_tags: set | None = None            # None = tous les tools
    instruction_blocks: list | None = None  # None = tous les blocs

    @abstractmethod
    def get_system_message(self, active_user_prompt: str) -> str: ...

    @abstractmethod
    def get_tool_code(self) -> str: ...

    @abstractmethod
    def get_custom_instructions(
        self,
        host: str,
        user_id: str,
        session_id: str,
        static_dir: str,
        upload_dir: str,
        mcp_tools: Optional[list[str]] = None,
    ) -> str: ...

    def configure_interpreter(self, interpreter) -> None:
        pass
