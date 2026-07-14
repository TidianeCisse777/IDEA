# Central Tool Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated tool construction and SSE presentation lists with one validated bilingual catalog covering all 55 mandatory and 3 optional SQL tools.

**Architecture:** `tools/tool_catalog.py` is a deep Module that composes existing thread-scoped factories and exposes immutable presentation metadata keyed by stable LangChain tool name. `agent.py` consumes its real `BaseTool` list; `serve.py` consumes localized projections and retains only source-specific rendering such as EcoTaxa linkification.

**Tech Stack:** Python 3.11+, LangChain tools, LangGraph agent factory, FastAPI, Pydantic, pytest.

## Global Constraints

- Preserve one LangGraph ReAct agent; do not introduce modes or routing code outside `agents/copepod_system_prompt.py`.
- Preserve all internal tool names, schemas, scientific behavior, thread-scoped dependencies, and optional read-only SQL behavior.
- Provide French and English presentation labels; resolve explicit request metadata, then `Accept-Language`, then French fallback.
- Never expose internal tool names in user-visible tool-call or tool-result summaries.
- Keep latency, costly-operation confirmation, and source-result visibility as separate concepts.
- Follow red-green-refactor for every production change.
- Do not modify or stage `scripts/sim_mcp_cache.py`.

---

### Task 1: Catalog metadata model, localization, and validation

**Files:**
- Create: `tools/tool_catalog.py`
- Create: `tests/test_tool_catalog.py`

**Interfaces:**
- Produces: `LocalizedText(fr: str, en: str)` with `for_language(language: str) -> str`.
- Produces: `ToolPresentation(label, family, source_result, slow, progress, source_label, source_url)`.
- Produces: `resolve_user_language(metadata: dict | None, accept_language: str | None) -> Literal["fr", "en"]`.
- Produces: `get_tool_presentation(name: str) -> ToolPresentation | None`.
- Produces: `validate_catalog(tool_names: Collection[str], *, optional_names: Collection[str] = ()) -> None`.

- [ ] **Step 1: Write failing localization tests**

```python
@pytest.mark.parametrize(
    ("metadata", "header", "expected"),
    [
        ({"language": "en"}, "fr-CA", "en"),
        ({"locale": "fr-CA"}, "en-US", "fr"),
        (None, "en-US,en;q=0.9", "en"),
        (None, "de-DE", "fr"),
        (None, None, "fr"),
    ],
)
def test_resolve_user_language(metadata, header, expected):
    assert resolve_user_language(metadata, header) == expected
```

- [ ] **Step 2: Run the localization tests and verify RED**

Run: `pytest tests/test_tool_catalog.py -v`

Expected: collection error because `tools.tool_catalog` does not exist.

- [ ] **Step 3: Implement the immutable types and locale resolver**

```python
@dataclass(frozen=True)
class LocalizedText:
    fr: str
    en: str

    def for_language(self, language: str) -> str:
        return self.en if language == "en" else self.fr


def resolve_user_language(metadata=None, accept_language=None):
    candidates = []
    if isinstance(metadata, dict):
        candidates.extend((metadata.get("language"), metadata.get("locale")))
    candidates.append(accept_language)
    for candidate in candidates:
        normalized = _normalize_supported_language(candidate)
        if normalized:
            return normalized
    return "fr"
```

- [ ] **Step 4: Run localization tests and verify GREEN**

Run: `pytest tests/test_tool_catalog.py -v`

Expected: localization tests pass.

- [ ] **Step 5: Write failing metadata validation tests**

```python
def test_validate_catalog_rejects_missing_metadata(monkeypatch):
    monkeypatch.setattr(tool_catalog, "TOOL_PRESENTATION", {})
    with pytest.raises(ValueError, match="missing metadata"):
        tool_catalog.validate_catalog({"load_file"})


def test_validate_catalog_rejects_orphan_metadata(monkeypatch):
    monkeypatch.setattr(
        tool_catalog,
        "TOOL_PRESENTATION",
        {"ghost_tool": ToolPresentation(label=LocalizedText("Fantôme", "Ghost"), family="core")},
    )
    with pytest.raises(ValueError, match="orphan metadata"):
        tool_catalog.validate_catalog(set())
```

- [ ] **Step 6: Run validation tests and verify RED**

Run: `pytest tests/test_tool_catalog.py -k validate -v`

Expected: failure because validation and the complete metadata map are absent.

- [ ] **Step 7: Add family defaults, complete per-tool labels, and validation**

Implement metadata for every known mandatory and optional SQL name. Use `LocalizedText` for every label and source label. Mark all 46 source tools with an explicit `source_result` decision, including the 11 omissions listed in the design spec. Mark current heartbeat operations `slow=True` without moving confirmation rules out of the system prompt.

Validation must compute missing and orphan name sets and raise deterministic `ValueError` messages containing sorted names. A `source_result=True` entry without `source_label` must also fail.

- [ ] **Step 8: Run catalog unit tests and verify GREEN**

Run: `pytest tests/test_tool_catalog.py -v`

Expected: all metadata, locale, and validation tests pass.

- [ ] **Step 9: Commit Task 1**

```bash
git add tools/tool_catalog.py tests/test_tool_catalog.py
git commit -m "feat(tools): add bilingual tool catalog metadata"
```

### Task 2: Exact tool construction through the catalog

**Files:**
- Modify: `tools/tool_catalog.py`
- Modify: `tests/test_tool_catalog.py`

**Interfaces:**
- Consumes: existing `make_*_tools(thread_id)` factories and direct tool constructors.
- Produces: `build_tool_catalog(thread_id: str) -> ToolCatalog`.
- Produces: `ToolCatalog.tools: tuple[BaseTool, ...]`, `ToolCatalog.names: frozenset[str]`, and `ToolCatalog.presentation(name)`.

- [ ] **Step 1: Write failing 55-tool construction test**

```python
def test_build_tool_catalog_has_exact_mandatory_tool_count(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    catalog = build_tool_catalog("catalog-no-sql")
    assert len(catalog.tools) == 55
    assert len(catalog.names) == 55
    assert {tool.name for tool in catalog.tools} == catalog.names
    assert all(catalog.presentation(name) for name in catalog.names)
```

- [ ] **Step 2: Run the construction test and verify RED**

Run: `pytest tests/test_tool_catalog.py::test_build_tool_catalog_has_exact_mandatory_tool_count -v`

Expected: failure because `build_tool_catalog` is undefined.

- [ ] **Step 3: Implement mandatory composition**

Construct the current factories in their existing order:

```python
tools = [
    *make_tools(thread_id),
    *make_source_tools(thread_id),
    *make_bio_oracle_tools(thread_id),
    *make_amundsen_tools(thread_id),
    *make_ogsl_tools(thread_id),
    *make_ecopart_tools(thread_id),
    *make_geo_tools(thread_id),
    make_rag_tool(),
    make_taxonomy_tool(),
    make_skill_tool(thread_id=thread_id),
    export_deliverable,
    get_zone_info,
]
```

Reject duplicate runtime names before constructing the immutable `ToolCatalog`.

- [ ] **Step 4: Run the 55-tool test and verify GREEN**

Run: `pytest tests/test_tool_catalog.py::test_build_tool_catalog_has_exact_mandatory_tool_count -v`

Expected: pass with exactly 55 tools.

- [ ] **Step 5: Write failing optional SQL construction test**

Create a temporary SQLite database, set `DATABASE_URL` and `SQL_WORKSPACE_DIR`, then assert exactly 58 names and the presence of `list_sql_tables`, `preview_sql_table`, and `copy_sql_query_to_workspace`.

- [ ] **Step 6: Run the SQL test and verify RED**

Run: `pytest tests/test_tool_catalog.py -k optional_sql -v`

Expected: failure with 55 rather than 58 tools.

- [ ] **Step 7: Implement lazy optional SQL composition**

Call `make_sql_tools(thread_id)` at catalog-build time and catch only its current missing-configuration `ValueError`. Validate the resulting 58-name collection when configured.

- [ ] **Step 8: Run all catalog tests and verify GREEN**

Run: `pytest tests/test_tool_catalog.py -v`

Expected: all tests pass for both 55 and 58 tool variants.

- [ ] **Step 9: Commit Task 2**

```bash
git add tools/tool_catalog.py tests/test_tool_catalog.py
git commit -m "refactor(tools): centralize runtime tool construction"
```

### Task 3: Delegate agent construction to the catalog

**Files:**
- Modify: `agent.py`
- Modify: `tests/test_agent_factory.py`

**Interfaces:**
- Consumes: `build_tool_catalog(thread_id).tools`.
- Preserves: `make_agent(thread_id: str, user_id: str = "anonymous")`.

- [ ] **Step 1: Replace the incomplete construction test with a failing delegation test**

Patch `agent.build_tool_catalog` to return a catalog containing a sentinel tool and patch `agent.create_agent` to capture its tools. Assert the captured list is exactly the catalog list and that `build_tool_catalog` received the thread id.

- [ ] **Step 2: Run delegation test and verify RED**

Run: `pytest tests/test_agent_factory.py -k catalog -v`

Expected: failure because `agent.py` still invokes individual factories.

- [ ] **Step 3: Replace manual imports and concatenation**

Import `build_tool_catalog` from `tools.tool_catalog`; remove all factory imports used only by `make_agent`; replace the concatenation and SQL `try/except` with:

```python
catalog = build_tool_catalog(thread_id)
return create_agent(llm, list(catalog.tools), ...)
```

- [ ] **Step 4: Run agent factory tests and verify GREEN**

Run: `pytest tests/test_agent_factory.py tests/test_tool_catalog.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add agent.py tests/test_agent_factory.py
git commit -m "refactor(agent): consume central tool catalog"
```

### Task 4: Localize SSE tool calls and source results

**Files:**
- Modify: `serve.py`
- Modify: `tests/test_serve_streaming.py`
- Modify: `tests/test_serve_chat_metadata.py`

**Interfaces:**
- Consumes: `resolve_user_language`, `get_tool_presentation`.
- Changes: `_format_tool_line(name, args=None, *, language="fr")`.
- Changes: `_format_tool_result_details(name, content, args=None, *, language="fr")`.
- Changes: `_stream_agent_sse(..., language="fr")`.

- [ ] **Step 1: Write failing bilingual call-summary tests**

```python
def test_format_tool_line_uses_localized_label_without_internal_name():
    french = _format_tool_line("load_file", {"path": "/tmp/a.tsv"}, language="fr")
    english = _format_tool_line("load_file", {"path": "/tmp/a.tsv"}, language="en")
    assert "load_file" not in french + english
    assert "Chargement" in french
    assert "Loading" in english
```

- [ ] **Step 2: Run call-summary tests and verify RED**

Run: `pytest tests/test_serve_streaming.py -k localized_label -v`

Expected: failure because the internal name is still the summary.

- [ ] **Step 3: Route tool-call labels and progress through metadata**

Delete `_ENRICHMENT_PROGRESS_LABELS` and ensure `_format_tool_call_details` receives localized display text. Preserve code blocks, safe argument formatting, secrets masking, and conditional EcoTaxa dry-run notices. Unknown tool names use generic `Opération` / `Operation` summaries.

- [ ] **Step 4: Run call formatting tests and verify GREEN**

Run: `pytest tests/test_serve_streaming.py -k "format_tool_line or tool_call" -v`

Expected: all relevant formatting tests pass without internal names.

- [ ] **Step 5: Write failing source visibility and bilingual result tests**

Parameterize the 11 formerly omitted names and assert they are source-visible through catalog metadata. Assert an EcoPart or Amundsen result has localized source/result text and no runtime name in French and English. Retain existing EcoTaxa link assertions.

- [ ] **Step 6: Run source-result tests and verify RED**

Run: `pytest tests/test_serve_streaming.py -k "data_source or result_details" -v`

Expected: failures until prefix and EcoTaxa-only label logic are removed.

- [ ] **Step 7: Replace prefixes, labels, and slow list with catalog lookups**

Delete `_DATA_SOURCE_TOOL_PREFIXES`, `_ECOTAXA_TOOL_LABELS`, and `_SLOW_TOOLS`. Keep `_ECOTAXA_BASE_URL` and `_linkify_ecotaxa` as the EcoTaxa presentation Adapter. Use metadata for visibility, labels, source line, progress, and heartbeat slow state.

- [ ] **Step 8: Write and run failing request-language propagation tests**

Patch `_stream_agent_sse`, submit a `ChatRequest` with `metadata={"locale": "en-CA"}`, and assert `chat_completions` passes `language="en"`. Add a second case using `Accept-Language: fr-CA` with no metadata.

Run: `pytest tests/test_serve_chat_metadata.py -k language -v`

Expected: failure because language is not yet resolved or propagated.

- [ ] **Step 9: Resolve language once at the HTTP boundary**

In `chat_completions`, call:

```python
language = resolve_user_language(req.metadata, request.headers.get("accept-language"))
```

Pass it to `_stream_agent_sse`; pass it from the streamer to call/result formatting. Non-streaming model output remains unchanged.

- [ ] **Step 10: Run all SSE and metadata tests and verify GREEN**

Run: `pytest tests/test_serve_streaming.py tests/test_serve_chat_metadata.py -v`

Expected: all tests pass and no assertion expects an internal name in UI summaries.

- [ ] **Step 11: Commit Task 4**

```bash
git add serve.py tests/test_serve_streaming.py tests/test_serve_chat_metadata.py
git commit -m "refactor(streaming): localize catalog tool presentation"
```

### Task 5: Inventory documentation and complete regression verification

**Files:**
- Modify: `TOOLS.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CONTEXT.md`
- Modify: `tests/test_tool_schema_budget.py`

**Interfaces:**
- Consumes: final catalog names and family metadata.
- Produces: executable inventory consistency coverage and corrected documentation.

- [ ] **Step 1: Write failing inventory consistency test**

Build the catalog without SQL and assert 55 names, uniqueness, metadata coverage, and family counts matching documented constants in the test. Build with temporary SQLite and assert 58. Keep existing schema-budget checks and extend them to every constructed tool schema.

- [ ] **Step 2: Run inventory test and verify RED**

Run: `pytest tests/test_tool_schema_budget.py -v`

Expected: failure until the suite uses the full catalog and correct totals.

- [ ] **Step 3: Update inventory tests and documentation**

Document 55 mandatory plus 3 optional SQL tools, correct EcoTaxa/Bio-ORACLE/Amundsen counts, mark OGSL as implemented, and show `tools/tool_catalog.py` as the construction/presentation Seam. Do not generate or rewrite unrelated narrative sections.

- [ ] **Step 4: Run focused regression tests**

Run:

```bash
pytest tests/test_tool_catalog.py \
       tests/test_agent_factory.py \
       tests/test_serve_streaming.py \
       tests/test_serve_chat_metadata.py \
       tests/test_tool_schema_budget.py -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Run static checks**

Run:

```bash
python -m compileall -q agent.py serve.py tools/tool_catalog.py tests
git diff --check
```

Expected: exit code 0 with no output from `git diff --check`.

- [ ] **Step 6: Run the complete regression suite**

Run: `pytest tests/`

Expected: no failures; environment-gated tests may skip with their documented reasons.

- [ ] **Step 7: Commit documentation and final verification changes**

```bash
git add TOOLS.md ARCHITECTURE.md CONTEXT.md tests/test_tool_schema_budget.py
git commit -m "docs: synchronize catalog tool inventory"
```

- [ ] **Step 8: Review the complete branch**

Run:

```bash
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
git diff --check main...HEAD
```

Expected: only intended files differ; no unstaged implementation changes remain.

- [ ] **Step 9: Push the feature branch**

Push the final `codex/tool-catalog` branch after the finishing-development and verification-before-completion gates pass.
