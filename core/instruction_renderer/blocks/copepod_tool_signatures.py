from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    return f"""## Copepod Runtime Tools
You have access to host Python functions through the IDEA/OpenInterpreter environment. Use only tools relevant to copepod graphing workflows.

### Data loading and profiling (Phase 1)
- `inspect_file(file_path, sample_rows=20)` — read a CSV/TSV, return shape, dtypes, row count, sample rows, encoding, missing-value rates. Call this on every uploaded file at the start of Phase 1.
- `infer_column_roles(columns, metadata=None)` — map each raw column name to a semantic role (depth, sample_volume, profile_id, pixel_calibration, size_or_morphometry, …). Pass the column list from inspect_file.
- `describe_column(column_name, source_hint=None, session_id="{session_id}")` — query the RAG knowledge base for the definition, unit, and critical notes of a column. Call for any column whose role is unknown or ambiguous.
- `check_column_for_calc(column_roles, calculation, session_id="{session_id}")` — verify whether a set of column roles supports a given calculation (e.g. "biovolume", "abundance_m3"). Pass the role dict from infer_column_roles.
- `summarize_understanding(inspect_report, role_report)` — build the structured Data Understanding dict from inspect_file + infer_column_roles outputs.

### Source metadata
- `list_available_sources(auth_token=None, session_id="{session_id}")` — list known copepod data sources (EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE).
- `describe_source(source_id, session_id="{session_id}")` — return full metadata for a source: content summary, join keys, known limitations.

### General
- `get_datetime()` — current date/time when needed.
- `query_knowledge_base(query, "{user_id}", "{session_id}")` — query user-uploaded knowledge documents for definitions, methods, or citations.
- `call_mcp_tool(tool_id, **kwargs)` — use only explicitly available MCP tools relevant to the copepod task.
- `list_mcp_tools()` — discover available MCP tools when needed.

### Rules
- When files are present in the session, always call `inspect_file` first, then `infer_column_roles`, then `describe_column` for unknown columns.
- Do not use station, sea-level, tide-gauge, datum, or climate-index tools for this profile.
- Do not reimplement provided tools when an appropriate tool exists.
- Do not expose credentials, environment variables, tokens, or secrets in outputs.
- Keep tool use proportional to the graphing task.
"""


renderer.register(InstructionBlock(
    name="copepod_tool_signatures",
    tags=frozenset({"copepod", "tools"}),
    render=_render,
))
