# Central Tool Catalog Design

## Context

IDEA constructs one LangGraph ReAct agent with thread-scoped LangChain tools. Tool construction currently lives in `agent.py`, while presentation and observability metadata are split across several lists and conditional branches in `serve.py`.

The runtime currently builds 55 unique tools without SQL and 58 when the optional SQL workspace is configured. The duplicated metadata has drifted:

- 11 data-source tools are not recognized as source results;
- only 20 of 25 EcoTaxa tools have user-facing labels;
- other tool families can expose internal names in the Open WebUI details panels;
- slow-operation and progress metadata are maintained separately;
- `TOOLS.md` and some construction tests no longer describe the complete tool set.

This conflicts with the product requirement that internal tool names are not exposed to users.

## Goal

Introduce a deep central Module that composes the runtime tool collection and exposes validated presentation metadata, while preserving each source family as an Adapter and keeping all LLM routing rules in `agents/copepod_system_prompt.py`.

## Scope

The refactor covers:

- runtime construction of the 55 mandatory tools and 3 optional SQL tools;
- user-facing French and English labels;
- source-family identity and source-result visibility;
- progress and slow-operation presentation metadata;
- source references needed by the existing result renderer;
- deterministic validation of uniqueness and metadata completeness;
- SSE rendering without internal tool names;
- synchronization of the tool inventory and construction tests.

The refactor does not:

- rename LangChain tool names;
- change tool arguments, results, scientific behavior, or routing;
- move routing rules out of the system prompt;
- add a session mode or a second agent;
- introduce biological interpretation;
- make SQL mandatory;
- infer or expose credentials.

## Architecture

### Deep Module and Interface

Create `tools/tool_catalog.py` as the single composition Seam. Its public Interface returns real LangChain `BaseTool` objects to the agent and immutable metadata projections to presentation code.

The Module hides:

- thread-scoped factory invocation;
- optional SQL construction;
- family defaults and per-tool overrides;
- metadata validation;
- lookup by stable internal tool name.

`agent.py` consumes only the constructed `BaseTool` list. `serve.py` consumes only catalog lookup and localization helpers. Neither caller reconstructs knowledge of tool families through prefixes or private lists.

### Two-level ownership

The initial migration uses a validated central overlay over the existing factories. This is the smallest safe TDD slice and immediately removes drift from `agent.py` and `serve.py`.

The catalog models family-level defaults separately from per-tool overrides. This preserves a path toward moving family declarations beside their source Adapters without changing the public Interface. The first implementation does not rewrite every factory solely for structural purity.

### Data model

The catalog defines immutable values equivalent to:

```python
@dataclass(frozen=True)
class LocalizedText:
    fr: str
    en: str


@dataclass(frozen=True)
class ToolPresentation:
    label: LocalizedText
    family: str
    source_result: bool = False
    slow: bool = False
    progress: LocalizedText | None = None
    source_label: LocalizedText | None = None
    source_url: str | None = None
```

The final field names may be tightened during the implementation plan, but the separation between stable runtime name and localized presentation label is required.

Slow execution, costly-operation confirmation, and source-result visibility are distinct concepts. The catalog must not reinterpret the system prompt's confirmation rules as a generic `slow` flag.

### Construction

The catalog invokes the existing thread-scoped factories with the current dependencies, including the shared session store. It appends the direct tools and conditionally constructs SQL tools exactly as today.

SQL remains lazy and optional. Absence of `DATABASE_URL` must produce the 55-tool catalog without an error. A configured SQL workspace adds exactly three tools.

Construction validation fails early when:

- two tools share a runtime name;
- a constructed tool has no presentation metadata;
- a metadata entry names no constructed or explicitly optional tool;
- a source-visible tool lacks its source identity.

The catalog returns ordinary LangChain tools rather than wrappers so `create_react_agent` behavior and schemas remain unchanged.

## Localization

User-facing catalog text supports French and English from the first migration.

Language resolution uses the user's explicit locale rather than the LLM's tool name:

1. `language` or `locale` in request metadata, when it identifies French or English;
2. the HTTP `Accept-Language` preference;
3. French fallback.

Regional variants normalize to their base language, for example `fr-CA` to `fr` and `en-US` to `en`. Unsupported and malformed values fall back to French. No new language-detection dependency is introduced.

All catalog-controlled UI strings use the resolved language, including call summaries, result summaries, progress text, and source labels. Scientific tool output is not translated or rewritten by this layer.

## SSE presentation

`serve.py` receives or resolves the request language once and passes it through the streaming presentation functions.

The renderer uses the localized label in every `<summary>`. It must never fall back to the internal runtime name for a constructed catalog tool. Unknown third-party names, if encountered defensively, receive a generic localized label such as `Opération` / `Operation` rather than exposing the unknown identifier.

The current EcoTaxa linkification behavior remains source-specific. A general source URL in the catalog does not replace project/sample URL construction. Other source families receive explicit source labels and URLs only where authoritative links already exist.

Source-result visibility becomes an explicit metadata property. The 11 currently omitted canonical search, grouping, discovery, and enrichment tools are included. Existing result truncation and binary/base64 protections remain in force.

## Tests and TDD sequence

Every behavior change follows red-green-refactor:

1. catalog construction tests fail until the exact 55/58 unique tool sets are returned;
2. validation tests fail until missing, duplicate, and orphan metadata are rejected;
3. localization tests fail until `fr`, `fr-CA`, `en`, and `en-US` resolve correctly with French fallback;
4. rendering tests are changed first to require human labels and prohibit internal names in French and English;
5. source visibility tests enumerate the 11 formerly omitted tools;
6. agent-factory tests fail until `agent.py` delegates construction to the catalog;
7. documentation consistency is verified against the final catalog or updated explicit counts.

Focused tests run after each cycle. The complete test suite runs before completion.

## Documentation

Update `ARCHITECTURE.md` to identify the catalog as the construction and presentation Seam. Update `TOOLS.md` to state the correct mandatory and optional totals and repair family counts. Update stale OGSL wording in `CONTEXT.md`.

The first version keeps the narrative inventory human-maintained and adds executable consistency checks. Automatic generation of the whole document is outside scope.

## Migration and compatibility

The migration preserves runtime names, tool schemas, trace identities, thread-scoped captures, and SQL fallback behavior. Existing tests that explicitly expect internal names in UI summaries are intentionally rewritten because they encode the product violation being fixed.

No source Adapter or client is replaced. The Module increases Depth by hiding composition and validation, increases Leverage because agent/SSE/tests share one truth, and improves Locality because presentation facts are no longer spread across unrelated server branches.

## Acceptance criteria

- The catalog constructs exactly 55 unique tools without SQL and 58 with SQL.
- Every constructed tool has complete validated presentation metadata.
- French and English user locales render localized labels.
- Unsupported or absent locales render French labels.
- No constructed internal tool name appears in tool-call or tool-result summaries.
- All 46 data-source tools have an explicit visibility decision; the 11 known omissions are visible where their results are useful.
- Slow-operation presentation no longer depends on `_SLOW_TOOLS` in `serve.py`.
- Source-result selection no longer depends on name prefixes in `serve.py`.
- EcoTaxa project and sample links continue to work.
- SQL remains optional and read-only.
- `agent.py` no longer owns the manual factory concatenation.
- `TOOLS.md`, `ARCHITECTURE.md`, and `CONTEXT.md` reflect the implemented catalog.
- Focused tests and the full test suite pass.
