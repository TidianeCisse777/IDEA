from core.instruction_renderer.renderer import InstructionRenderer, InstructionBlock, renderer

# Trigger all block registrations by importing the blocks package
from core.instruction_renderer import blocks  # noqa: F401

__all__ = ["InstructionRenderer", "InstructionBlock", "renderer"]
