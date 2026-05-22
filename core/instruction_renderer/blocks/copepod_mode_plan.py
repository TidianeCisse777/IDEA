from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    return """## Copepod Plan Mode
Use this mode to establish and validate the scientific and technical context before graph generation.

Plan Mode is a two-phase workflow. The order is mandatory.

### Phase 1 - Data Understanding
If user-loaded data are available, inspect and profile them before asking for graph context or proposing a graph plan. Build an explicit understanding of:
- which files or sources are involved;
- likely source type: EcoTaxa, EcoPart, Amundsen CTD, lab data, OGSL, or Bio-ORACLE;
- available columns;
- column meanings and units;
- metadata available in the files;
- missing or unusable columns;
- taxonomic validation status when taxa are used;
- possible joins or couplings;
- data quality limitations;
- what can be used directly for graphing;
- what is blocked or ambiguous.

After Phase 1, provide a short structured summary using this format:

### Data Understanding
- File/source:
- Probable source type:
- Useful columns:
- Metadata detected:
- Quality / limitations:
- Taxonomic validation status:
- Possible joins or couplings:
- Missing or ambiguous data:

Do not ask for graph context before summarizing the loaded data, unless no user-loaded data are available.

### Phase 2 - Context Framing
After the data understanding summary, take or request the user's scientific and graphing context. Build an explicit understanding of:
- what the user wants to do;
- target species, taxon, group, variable, region, campaign, or period if applicable;
- graph family or chart type;
- required columns and filters;
- units;
- derived variables and methods;
- reliability level: reliable, exploratory, or impossible;
- generation language: Python or R;
- output format and artifacts to save;
- blockers or user choices needed.

Before switching to Analyse Mode, validate your understanding with the user in a short structured summary:

### Graph Context
- Objective understood:
- Data/source understood:
- Columns/metadata understood:
- Quality/limitations:
- Proposed graph:
- Language: Python or R
- Output artifacts:
- Feasibility: reliable / exploratory / impossible
- Blockers or choices needed:

Do not switch to Analyse Mode until the user validates or corrects this understanding.

Plan Mode may inspect, validate, summarize, and profile loaded data. It must not generate the final graph.

If the user's intent, columns, metadata, validation status, or required source is ambiguous, ask a targeted question instead of executing.

If any required source, column, unit, validation status, or context is missing, return a structured blocker instead of executing graph-generation code.
"""


renderer.register(InstructionBlock(
    name="copepod_mode_plan",
    tags=frozenset({"copepod", "mode", "plan"}),
    render=_render,
))
