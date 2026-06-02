from core.instruction_renderer.renderer import InstructionBlock, renderer


def _render(ctx: dict) -> str:
    user_id = ctx["user_id"]
    session_id = ctx["session_id"]
    return f"""## Copepod Runtime Tools

**HOW TO CALL THESE.** Every helper listed below is a Python function available in the sandbox. Call it directly from Python code — never as a standalone tool. For example:

```
report = inspect_file("/app/static/.../file.tsv")
print(report)
```

Calling `inspect_file` (or any helper below) outside Python code will fail.

### File exploration
- `inspect_file(file_path, sample_rows=20)` — read a CSV/TSV/Excel/NetCDF and return shape, dtypes, sample rows, encoding, missing-value rates, and a best-guess source type. Call on every uploaded file you have not yet seen.
- `collect_column_definitions(file_report, session_id="{session_id}")` — batch-fetch authoritative RAG definitions for every column. Call right after `inspect_file`; pass the returned list to `format_inspect_report`.
- `format_inspect_report(file_report, column_definitions=None)` — deterministic text rendering of an `inspect_file` result. ALWAYS use this instead of `print(file_report)` for the RAPPORT D'INSPECTION. When `column_definitions` is provided, each column line is followed by its RAG definition, unit and critical notes.
- `infer_column_roles(columns, metadata=None)` — heuristic helper that pattern-matches column names to known semantic roles. Output is provisional — verify with `describe_column` for anything ambiguous.
- `describe_column(column_name, source_hint=None, session_id="{session_id}")` — look up a column definition, unit, and critical notes in the copepod RAG corpus. Use when the column meaning is not obvious.
- `check_column_for_calc(column_roles, calculation, session_id="{session_id}")` — verify whether a set of roles supports a derived calculation (biovolume, abundance per m³, etc.).
- `summarize_understanding(inspect_report, role_report, column_definitions=None)` — assemble a structured per-file summary. Use it as a working note for yourself when several files are loaded.

### Taxonomy
- `lookup_worms_taxonomy(query, include_children=False, marine_only=True, session_id="{session_id}")` — query the WoRMS REST API for the authoritative classification of a marine taxon. Set `marine_only=False` for brackish or freshwater copepods.

### Source metadata
- `list_available_sources(auth_token=None, session_id="{session_id}")` — list known copepod data sources (EcoTaxa, EcoPart, Amundsen CTD, OGSL, Bio-ORACLE).
- `describe_source(source_id, session_id="{session_id}")` — full metadata for a source: content, join keys, limitations. Valid source_ids: `"ecotaxa_1165"`, `"ecotaxa_2331"`, `"ecopart_105"`, `"amundsen_ctd"`, `"ogsl"`, `"bio_oracle"`.
- `plan_remote_source_request(request_text, source_hint=None, session_id="{session_id}")` — normalize an explicit OGSL or Bio-ORACLE request and surface missing parameters. Returns `missing_fields` list and `clarification_question`. Call before `fetch_remote_source_dataset`.
- `fetch_remote_source_dataset(session_key, source_id, parameters, output_filename=None)` — download an online source as a derived CSV into the session uploads folder. `session_key = os.environ.get('IDEA_RUNTIME_SESSION_KEY', '')`. For Bio-ORACLE: `source_id="bio_oracle"`, parameters need `variable`, `scenario`, `latitude`, `longitude`. For OGSL: `source_id="ogsl"`, parameters need `station` or `mission`. Returns `dict` with `status` (`"persisted"` or `"needs_clarification"`) and `file_path` when persisted. Always call `inspect_and_report` on the returned `file_path` before graphing.

### RAG domain knowledge
- `query_copepod_knowledge_base(question, session_id="{session_id}", top_k=3)` — search the copepod RAG corpus for column definitions, source descriptions, variable names, calculation methods, Bio-ORACLE scenarios, OGSL column names, etc. **Use this first** when the user asks about a source (columns, variables, scenarios, how to use it) — even before any file is loaded. Returns a list of chunks with `chunk_id`, `title`, `content`.

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
