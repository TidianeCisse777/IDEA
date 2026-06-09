# Bio-ORACLE Coupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Bio-ORACLE tool family that can list datasets, preview a point, query present/future scenarios, and couple those outputs to zooplankton station tables.

**Architecture:** Introduce a shared Bio-ORACLE backend that talks to ERDDAP and normalizes results for both the registry path and the LangChain tools. Keep the LangChain side thin: one module for Bio-ORACLE tools, one prompt update for routing, and one skill file for post-query interpretation and download links.

**Tech Stack:** Python 3.13, requests, pandas, LangChain tools, LangGraph agent, pytest, unittest.mock, Markdown.

---

### Task 1: Shared Bio-ORACLE backend and registry reuse

**Files:**
- Create: `core/bio_oracle_client.py`
- Modify: `core/tool_registry/tools/copepod_remote_sources.py`
- Modify: `core/tool_registry/tools/copepod_sources_meta.py`
- Test: `tests/test_bio_oracle_client.py`

- [ ] **Step 1: Write the failing test**

```python
def test_plan_bio_oracle_request_requires_explicit_scenario_and_depth_layer():
    from core.bio_oracle_client import plan_bio_oracle_request

    result = plan_bio_oracle_request(
        {
            "latitude": 50.2,
            "longitude": -65.8,
            "variable": "thetao",
            "period": {"start": 2041, "end": 2060},
        }
    )

    assert result["source_id"] == "bio_oracle"
    assert result["missing_fields"] == ["scenario", "depth_layer"]
    assert result["recommended_next_step"] == "ask_clarification"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_bio_oracle_client.py::test_plan_bio_oracle_request_requires_explicit_scenario_and_depth_layer
```

Expected: FAIL because `plan_bio_oracle_request` does not exist yet and the Bio-ORACLE request planner does not enforce explicit `scenario` and `depth_layer`.

- [ ] **Step 3: Write minimal implementation**

Add `core/bio_oracle_client.py` with:

```python
def plan_bio_oracle_request(parameters: dict) -> dict:
    source_id = "bio_oracle"
    missing_fields = []
    if not parameters.get("scenario"):
        missing_fields.append("scenario")
    if not parameters.get("depth_layer"):
        missing_fields.append("depth_layer")
    if parameters.get("latitude") is None or parameters.get("longitude") is None:
        missing_fields.append("zone")
    return {
        "source_id": source_id,
        "parameters": parameters,
        "missing_fields": missing_fields,
        "recommended_next_step": "ask_clarification" if missing_fields else "proceed",
        "clarification_question": "Which Bio-ORACLE scenario, depth layer, and coordinates do you want?",
    }
```

Then update `describe_source("bio_oracle")` metadata in `core/tool_registry/tools/copepod_sources_meta.py` so it explicitly mentions:
- `depth_layer` is required
- `baseline` vs `SSP` comparisons are the intended use
- the join key includes `latitude`, `longitude`, and `depth_layer`

Also extend `plan_remote_source_request()` in `core/tool_registry/tools/copepod_sources_meta.py` so it extracts `depth_layer`, keeps `scenario` user-driven, and returns `missing_fields` when either is absent.

Wire `core/tool_registry/tools/copepod_remote_sources.py` to reuse the shared Bio-ORACLE backend instead of keeping a second copy of the request logic.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_bio_oracle_client.py::test_plan_bio_oracle_request_requires_explicit_scenario_and_depth_layer
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/bio_oracle_client.py core/tool_registry/tools/copepod_remote_sources.py core/tool_registry/tools/copepod_sources_meta.py tests/test_bio_oracle_client.py
git commit -m "feat: add shared Bio-ORACLE backend"
```

### Task 2: Bio-ORACLE LangChain tool family

**Files:**
- Create: `tools/bio_oracle_sources.py`
- Modify: `agent.py`
- Test: `tests/test_bio_oracle_sources.py`

- [ ] **Step 1: Write the failing test**

```python
def test_make_bio_oracle_tools_exposes_list_preview_query_and_couple():
    from tools.bio_oracle_sources import make_bio_oracle_tools

    tools = make_bio_oracle_tools("thread-1")
    tool_names = {tool.name for tool in tools}

    assert "list_bio_oracle_datasets" in tool_names
    assert "preview_bio_oracle_point" in tool_names
    assert "query_bio_oracle" in tool_names
    assert "couple_zooplankton_bio_oracle" in tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_bio_oracle_sources.py::test_make_bio_oracle_tools_exposes_list_preview_query_and_couple
```

Expected: FAIL because `tools/bio_oracle_sources.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `tools/bio_oracle_sources.py` with thin `@tool` wrappers that:
- call the shared Bio-ORACLE backend from `core/bio_oracle_client.py`
- format list output as a Markdown table
- format preview output as a short Markdown summary
- persist query/coupling results as downloadable TSV/CSV files in the session upload area
- return a stable download URL in the final string

Update `agent.py` so the tool list becomes:

```python
tools = (
    make_tools(thread_id)
    + make_source_tools(thread_id)
    + make_bio_oracle_tools(thread_id)
    + [make_rag_tool(), make_skill_tool()]
)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_bio_oracle_sources.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/bio_oracle_sources.py agent.py tests/test_bio_oracle_sources.py
git commit -m "feat: add Bio-ORACLE LangChain tools"
```

### Task 3: Prompt and skill routing

**Files:**
- Modify: `agents/copepod_system_prompt.py`
- Create: `agents/skills/bio_oracle_query.md`
- Modify: `tests/test_agent_factory.py`

- [ ] **Step 1: Write the failing test**

```python
def test_system_prompt_routes_bio_oracle_list_preview_query_and_coupling():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT

    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "list_bio_oracle_datasets" in prompt
    assert "preview_bio_oracle_point" in prompt
    assert "query_bio_oracle" in prompt
    assert "couple_zooplankton_bio_oracle" in prompt
    assert "only if `query_bio_oracle` succeeds" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_agent_factory.py::test_system_prompt_routes_bio_oracle_list_preview_query_and_coupling
```

Expected: FAIL because the prompt does not yet route Bio-ORACLE actions or load a dedicated skill after a successful query.

- [ ] **Step 3: Write minimal implementation**

Update `agents/copepod_system_prompt.py` with explicit Bio-ORACLE rules:
- `list_bio_oracle_datasets` for availability questions
- `preview_bio_oracle_point` for quick overview/detail questions
- `query_bio_oracle` for explicit load/export/download/future-scenario requests
- `couple_zooplankton_bio_oracle` for station-table coupling and batch comparisons
- load `bio_oracle_query` only after a successful `query_bio_oracle`

Create `agents/skills/bio_oracle_query.md` with guidance that:
- tells the agent to include the download link in replies
- explains that the result is a comparison table, not biological interpretation
- reminds the agent to respect explicit `scenario` and `depth_layer` choices

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_agent_factory.py::test_system_prompt_routes_bio_oracle_list_preview_query_and_coupling
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/copepod_system_prompt.py agents/skills/bio_oracle_query.md tests/test_agent_factory.py
git commit -m "feat: route Bio-ORACLE requests in prompt"
```

### Task 4: Open WebUI streaming and end-to-end verification

**Files:**
- Modify: `serve.py`
- Modify: `tests/test_serve_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
def test_format_tool_line_query_bio_oracle_shows_waiting_message():
    from serve import _format_tool_line

    line = _format_tool_line(
        "query_bio_oracle",
        {"scenario": "SSP245", "depth_layer": "depthsurf"},
    )

    assert "query_bio_oracle" in line
    assert "Export Bio-ORACLE en cours" in line
    assert "%" not in line
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_serve_streaming.py::test_format_tool_line_query_bio_oracle_shows_waiting_message
```

Expected: FAIL because `_format_tool_line()` does not yet special-case Bio-ORACLE tool names.

- [ ] **Step 3: Write minimal implementation**

Update `serve.py` so:
- `query_bio_oracle` emits a static waiting indicator while a remote export is running
- `couple_zooplankton_bio_oracle` uses the same waiting style when it triggers a remote fetch
- the line does not fake progress percentages

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_serve_streaming.py::test_format_tool_line_query_bio_oracle_shows_waiting_message
```

Expected: PASS.

- [ ] **Step 5: Full verification and commit**

Run:
```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_bio_oracle_client.py tests/test_bio_oracle_sources.py tests/test_agent_factory.py tests/test_serve_streaming.py
git diff --check
```

Expected: all tests pass and `git diff --check` is clean.

Then commit:

```bash
git add core/bio_oracle_client.py core/tool_registry/tools/copepod_remote_sources.py core/tool_registry/tools/copepod_sources_meta.py tools/bio_oracle_sources.py agent.py agents/copepod_system_prompt.py agents/skills/bio_oracle_query.md serve.py tests/test_bio_oracle_client.py tests/test_bio_oracle_sources.py tests/test_agent_factory.py tests/test_serve_streaming.py
git commit -m "feat: add Bio-ORACLE coupling tools"
```
