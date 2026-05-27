from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    return """## Copepod Analyse Mode
Use this mode only after the graph plan is complete enough to execute.

### Session startup — mandatory on every entry into Analyse Mode

Before writing a single line of code, load the locked artefacts:

1. `get_active_data_understanding(session_key)` — read the full payload: columns, roles, source type, joins, quality.
2. `get_active_graph_context(session_key)` — read the full payload: objective, retained columns, filters, units, derived variables, chart type, language, output artefacts, feasibility.

These two artefacts are the **execution contract**. Do not rely on conversation memory to reconstruct this context — load it from the activated artefacts. If either is absent, stop and ask the user to go back through Plan Mode.

### Execution

- Execute the locked plan in the language specified in the Graph Context (Python or R).
- Use only the columns and sources identified in the Data Understanding.
- Create named working copies for transformations — never modify raw input files.
- Generate the graph and save the output artefact.
- Save coupled working tables when multiple sources are combined.
- At the end of execution, report: source, columns, filters, units, method, reliability level, quality limits.
- Do not add scientific or biological interpretation.

### Execution feedback loop

Use this validation loop for every code-driven analysis:

1. Run code in small executable steps. Do not generate a large script and assume it works.
2. After each execution, inspect the actual runtime output: traceback, dataframe shape, expected columns, saved file path, and figure/object existence.
3. If execution raises a Python/R error, read the exact traceback, explain the technical cause briefly, rewrite only the failing step, and rerun.
4. If execution succeeds but the result is empty, all-NaN, missing expected columns, missing the saved artefact, or visually/structurally invalid, treat it as a failed execution and correct it.
5. Retry at most 3 correction attempts for the same failing step. After 3 failed attempts, stop and report a precise execution blocker with the last error/output and the required user/data action.
6. Do not present an analysis, graph, table, or downloadable artefact as complete until validation confirms the output is non-empty, uses the locked columns/sources, and the expected file exists.
7. When the fix requires changing the locked graph objective, source, columns, units, language, or output type, stop and report that the locked plan is invalid instead of silently changing it.

### New file in Analyse Mode

Call `inspect_file` + `infer_column_roles` on the file and integrate the results into the current execution context. Do not switch back to Plan Mode unless the new file reveals a blocker that invalidates the locked plan.

### Execution blockers

If execution reveals missing data, invalid joins, unknown validation status, or another real blocker — stop and report the blocker precisely. Do not approximate.
"""


renderer.register(InstructionBlock(
    name="copepod_mode_analyse",
    tags=frozenset({"copepod", "mode", "analyse"}),
    render=_render,
))
