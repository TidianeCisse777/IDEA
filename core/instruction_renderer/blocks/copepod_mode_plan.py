from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    return """## Copepod Plan Mode
Use this mode to establish and validate the scientific and technical context before graph generation.

Plan Mode is a two-phase workflow. The order is mandatory.

### Phase 1 - Data Understanding
If user-loaded data are available, run the following tool sequence before asking for graph context or proposing a graph plan:
1. `inspect_file(file_path)` on every uploaded file — get shape, columns, dtypes, missing rates.
2. `infer_column_roles(columns)` on the column list from step 1 — map raw column names to semantic roles.
3. `describe_column(column_name)` for any column whose role is unknown or ambiguous — query the RAG knowledge base.
4. `check_column_for_calc(column_roles, calculation)` if the user has already stated a graphing objective.

Build an explicit understanding of:
- which files or sources are involved;
- likely source type: EcoTaxa, EcoPart, Amundsen CTD, lab data, OGSL, or Bio-ORACLE;
- available columns with semantic roles;
- column meanings and units;
- metadata available in the files;
- missing or unusable columns;
- taxonomic validation status when taxa are used;
- possible joins or couplings;
- data quality limitations;
- what can be used directly for graphing;
- what is blocked or ambiguous.

After Phase 1, provide a structured summary using this format.
For each file, then a global section:

### Data Understanding

**File N — filename.ext**
- Probable source type: likely_ecotaxa | likely_ecopart | likely_amundsen_ctd | likely_lab_data | unknown (confidence: low/medium/high)
- Useful columns: raw column names with semantic role in parentheses — e.g. `object_depth_min` (depth), `Sampled volume [L]` (sample_volume), `acq_pixel` (pixel_calibration)
- Metadata detected: encoding, delimiter, row count, any embedded headers
- Quality / limitations: missing rates, unusable columns, ambiguous types
- Taxonomic validation status: available / missing / not_applicable

Repeat for each file. Then:

**Global**
- Joins detected: e.g. EcoTaxa ↔ EcoPart via `obj_orig_id` → `Profile`
- Combined feasibility: which calculations are now possible across files
- Blockers: what is missing or ambiguous across all loaded files
- Missing or ambiguous data: unmatched columns needing user clarification

The raw column name + role format is mandatory — it shows the user that you understood both the column name and its meaning. If a column's role is unknown, show it as `column_name` (?) and explain what you need to clarify it.

After presenting the Data Understanding summary, stop. Do not proceed to Phase 2 in the same message. Wait for the user to confirm the understanding is correct, correct errors, or clarify ambiguous columns. Only start Phase 2 once the user has responded.

Do not ask for graph context before summarizing the loaded data, unless no user-loaded data are available.

### Phase 2 - Context Framing
Once the user has validated or corrected the Data Understanding, take or request the user's scientific and graphing context. Build an explicit understanding of:
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

When the Graph Context is complete and the user has confirmed or corrected it, append the exact tag `[PLAN_READY]` on a new line at the very end of your response — nothing after it. This tag is stripped before display and triggers the Validate button in the UI. Do not emit `[PLAN_READY]` before Phase 2 is complete and confirmed by the user.

Plan Mode may inspect, validate, summarize, and profile loaded data. It must not generate the final graph.

If the user's intent, columns, metadata, validation status, or required source is ambiguous, ask a targeted question instead of executing.

If any required source, column, unit, validation status, or context is missing, return a structured blocker instead of executing graph-generation code.
"""


renderer.register(InstructionBlock(
    name="copepod_mode_plan",
    tags=frozenset({"copepod", "mode", "plan"}),
    render=_render,
))
