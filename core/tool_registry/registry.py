from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tool:
    name: str
    tags: frozenset
    code: str  # source Python (sera exécuté via computer.run)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def render(self, tags: set | None = None) -> str:
        """Retourne le code Python de tous les tools matchant les tags."""
        tools = list(self._tools.values())
        if tags:
            tools = [t for t in tools if t.tags & tags]
        return "\n\n".join(t.code for t in tools)


registry = ToolRegistry()
