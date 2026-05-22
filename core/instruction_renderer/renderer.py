from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class InstructionBlock:
    name: str
    tags: frozenset
    render: Callable[[dict], str]  # context dict → string


class InstructionRenderer:
    def __init__(self):
        self._blocks: dict[str, InstructionBlock] = {}

    def register(self, block: InstructionBlock) -> None:
        self._blocks[block.name] = block

    def render(self, block_names: list[str], context: dict) -> str:
        parts = []
        for name in block_names:
            if name in self._blocks:
                parts.append(self._blocks[name].render(context))
        return "\n\n".join(parts)


renderer = InstructionRenderer()
