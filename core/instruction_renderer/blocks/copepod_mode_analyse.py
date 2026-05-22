from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    return """## Copepod Analyse Mode
Use this mode only after the graph plan is complete enough to execute.

In Analyse Mode:
- execute the locked plan with Python or R;
- use identified columns and activated sources only;
- create named working copies or derived tables for transformations;
- never modify raw input files;
- generate the graph;
- save the graph artifact;
- save coupled working tables when multiple sources are combined;
- report source, columns, filters, units, method, reliability level, and quality limits;
- do not add scientific or biological interpretation.

If execution reveals missing data, invalid joins, unknown validation status, or another real blocker, stop and report the blocker instead of approximating.
"""


renderer.register(InstructionBlock(
    name="copepod_mode_analyse",
    tags=frozenset({"copepod", "mode", "analyse"}),
    render=_render,
))
