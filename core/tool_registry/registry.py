"""Minimal tool registry for the copépode tool bank."""
from __future__ import annotations

from dataclasses import dataclass, field


COPEPOD_OBSERVABILITY_CODE = ""


@dataclass
class Tool:
    name: str
    tags: frozenset
    code: str


@dataclass
class ToolRegistry:
    _tools: list[Tool] = field(default_factory=list)

    def register(self, tool: Tool) -> None:
        self._tools.append(tool)

    def render(self) -> str:
        return "\n\n".join(tool.code for tool in self._tools)


registry = ToolRegistry()
