# MCP EcoTaxa M1 Search Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first end-to-end EcoTaxa catalogue tool, `search_projects`, through the pure core, IDEA LangChain facade, and authenticated FastMCP facade.

**Architecture:** Extend the existing raw `tools.ecotaxa_client.EcotaxaClient` with paginated project search matching EcoTaxa OpenAPI 0.0.45. Keep normalization and validation in `core.ecotaxa_browser.search`, then make both facades delegate to that core function so JSON and Markdown outputs derive from one source.

**Tech Stack:** Python 3.13, requests, VCR.py, LangChain tools, FastMCP 3.4, pytest.

---

### Task 1: Raw EcoTaxa project search

**Files:**
- Modify: `tools/ecotaxa_client.py`
- Create: `tests/test_ecotaxa_browser_search.py`

- [ ] **Step 1: Write the failing raw-client test**

Test `EcotaxaClient.search_projects(title, instrument, window_start, window_size)` sends:

```python
{
    "title_filter": "Calanus",
    "instrument_filter": "UVP5",
    "window_start": 50,
    "window_size": 25,
    "order_field": "projid",
}
```

and returns the unmodified JSON list.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py -q`

Expected: failure because `EcotaxaClient.search_projects` does not exist.

- [ ] **Step 3: Implement the minimal raw method**

Add a request to `GET /projects/search`, call `raise_for_status()`, and return `response.json()`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py -q`

Expected: raw-client test passes.

### Task 2: Pure core normalization and pagination

**Files:**
- Modify: `core/ecotaxa_browser/search.py`
- Modify: `tests/test_ecotaxa_browser_search.py`
- Create: `tests/cassettes/projects_search_minimal.yaml`

- [ ] **Step 1: Write failing core tests**

Cover:

```python
search_projects(title="Calanus", instrument="UVP5", page=2, page_size=25)
```

The core logs in, sends `window_start=25`, and returns dictionaries containing:

```python
{
    "project_id": 123,
    "name": "Calanus project",
    "instrument": "UVP5",
    "status": "Annotate",
    "object_count": 1000,
    "percent_validated": 42.5,
    "percent_classified": 90.0,
}
```

Also assert `page < 1` and `page_size < 1` raise `ValueError`.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py -q`

Expected: failure because core `search_projects` does not exist.

- [ ] **Step 3: Implement core search**

Instantiate `EcotaxaClient`, call `login()`, call the raw method, and normalize optional EcoTaxa fields without depending on LangChain or FastMCP.

- [ ] **Step 4: Record and sanitize a minimal VCR cassette**

Record one official `GET /projects/search` response with `window_size=2`. Filter `Authorization`, login credentials, cookies, and unrelated projects from the cassette. The replay test patches `login()` so it never needs credentials.

- [ ] **Step 5: Run offline replay and verify GREEN**

Run:

```bash
env -u ECOTAXA_TOKEN -u ECOTAXA_USERNAME -u ECOTAXA_PASSWORD \
python -m pytest tests/test_ecotaxa_browser_search.py -q
```

Expected: all core tests pass without network or credentials.

### Task 3: IDEA LangChain facade

**Files:**
- Modify: `tools/copepod_sources.py`
- Modify: `tests/test_ecotaxa_browser_search.py`

- [ ] **Step 1: Write the failing Markdown facade test**

Patch the imported core function, get `find_ecotaxa_projects` from `make_source_tools`, invoke it, and assert the Markdown table contains `project_id`, `name`, `instrument`, and returned values.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py -q`

Expected: failure because the tool is not registered.

- [ ] **Step 3: Implement the LangChain tool**

Add `find_ecotaxa_projects(title=None, instrument=None, page=1, page_size=50)` with a routing docstring, controlled error output, empty-result output, and Markdown rendering.

- [ ] **Step 4: Run and verify GREEN**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py -q`

Expected: Markdown facade test passes.

### Task 4: FastMCP facade and authenticated transport

**Files:**
- Modify: `core/mcp/ecotaxa_server.py`
- Modify: `tests/test_ecotaxa_browser_search.py`
- Modify: `tests/test_mcp_health.py`

- [ ] **Step 1: Write the failing in-memory FastMCP test**

Expose `create_mcp()` and use `fastmcp.Client(create_mcp())`:

```python
result = await client.call_tool(
    "search_projects",
    {"title": "Calanus", "page": 1, "page_size": 50},
)
```

Assert structured data is a list containing the normalized keys.

- [ ] **Step 2: Write the authenticated HTTP initialization test**

POST a valid MCP `initialize` JSON-RPC request to `/mcp` with the configured Bearer token and assert status `200`. Keep the existing missing-token `401` test.

- [ ] **Step 3: Run and verify RED**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py tests/test_mcp_health.py -q`

Expected: failure because `create_mcp` and the MCP tool do not exist.

- [ ] **Step 4: Implement `create_mcp()`**

Register an async-safe FastMCP tool named `search_projects` that delegates to the core function via `anyio.to_thread.run_sync`. Make `create_app()` consume `create_mcp()` and retain the public health route plus static Bearer middleware.

- [ ] **Step 5: Run and verify GREEN**

Run: `python -m pytest tests/test_ecotaxa_browser_search.py tests/test_mcp_health.py -q`

Expected: core, facade, auth, and MCP tests pass.

### Task 5: Validate M1 and update the PRD

**Files:**
- Modify: `docs/PRD_MCP_ECOTAXA.md`

- [ ] **Step 1: Run all MCP-focused tests**

Run:

```bash
python -m pytest \
  tests/test_ecotaxa_browser_search.py \
  tests/test_mcp_health.py \
  tests/test_mcp_compose.py \
  tests/test_requirements.py -q
```

- [ ] **Step 2: Rebuild and probe Docker**

Build `mcp-ecotaxa`, confirm `/health` is `200`, unauthenticated `/mcp` is `401`, and authenticated MCP initialization is `200`.

- [ ] **Step 3: Run the complete suite for comparison**

Run: `python -m pytest tests/ -q`

Expected baseline: no new failures beyond the documented pre-existing `17 failed` and `40 errors`.

- [ ] **Step 4: Update M1 gates**

Mark only demonstrated gates complete, record the architecture Go/No-Go decision, and append the dated journal entry.
