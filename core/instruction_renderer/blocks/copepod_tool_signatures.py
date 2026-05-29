from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    return f"""## Copepod Runtime Tools

**HOW TO CALL THESE.** The only callable tool you have is `execute(language="python", code=...)`. Every helper listed below is a **Python function pre-imported inside the execute sandbox** — never as a standalone tool. Always wrap a call in code, e.g.:

```
execute(language="python", code='''
report = inspect_file("/app/static/.../file.tsv")
print(report)
''')
```

Emitting `inspect_file` (or any helper below) as a top-level tool_call will silently fail.

### File exploration
- `inspect_file(file_path, sample_rows=20)` — read a CSV/TSV/Excel/NetCDF and return shape, dtypes, sample rows, encoding, missing-value rates, and a best-guess source type. Call on every uploaded file you have not yet seen.
- `infer_column_roles(columns, metadata=None)` — heuristic helper that pattern-matches column names to known semantic roles. Output is provisional — verify with `describe_column` for anything ambiguous.
- `describe_column(column_name, source_hint=None, session_id="{session_id}")` — look up a column definition, unit, and critical notes in the copepod RAG corpus. Use when the column meaning is not obvious.
- `check_column_for_calc(column_roles, calculation, session_id="{session_id}")` — verify whether a set of roles supports a derived calculation (biovolume, abundance per m³, etc.).
- `summarize_understanding(inspect_report, role_report, column_definitions=None)` — assemble a structured per-file summary. Use it as a working note for yourself when several files are loaded.

### Taxonomy
- `lookup_worms_taxonomy(query, include_children=False, marine_only=True, session_id="{session_id}")` — query the WoRMS REST API for the authoritative classification of a marine taxon. Set `marine_only=False` for brackish or freshwater copepods.

### Source metadata
- `list_available_sources(auth_token=None, session_id="{session_id}")` — list known copepod data sources (EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE).
- `describe_source(source_id, session_id="{session_id}")` — full metadata for a source: content, join keys, limitations.
- `plan_remote_source_request(request_text, source_hint=None, session_id="{session_id}")` — normalize an explicit OGSL or Bio-ORACLE request and surface missing parameters.
- `fetch_remote_source_dataset(session_key, source_id, parameters, output_filename=None)` — download an allowed online source into the session uploads folder as a derived CSV.

### General
- `get_datetime()` — current date/time when needed.
- `query_knowledge_base(query, "{user_id}", "{session_id}")` — query the user's uploaded knowledge documents for definitions, methods, or citations.
- `call_mcp_tool(tool_id, **kwargs)` — use only explicitly available MCP tools relevant to the copepod task.
- `list_mcp_tools()` — discover available MCP tools when needed.

### Rules
- Do not use station, sea-level, tide-gauge, datum, or climate-index tools for this profile.
- Do not reimplement provided tools when an appropriate tool exists.
- Do not expose credentials, environment variables, tokens, or secrets in outputs.
- Keep tool use proportional to the user's request.
"""


renderer.register(InstructionBlock(
    name="copepod_tool_signatures",
    tags=frozenset({"copepod", "tools"}),
    render=_render,
))
