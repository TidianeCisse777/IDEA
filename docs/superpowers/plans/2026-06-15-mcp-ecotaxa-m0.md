# MCP EcoTaxa M0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the M0 scaffold for a standalone EcoTaxa MCP service with a public health endpoint and Bearer-protected MCP endpoint.

**Architecture:** Keep all future EcoTaxa browsing logic in a framework-independent `core/ecotaxa_browser` package. Build the HTTP facade in `core/mcp/ecotaxa_server.py` with FastMCP's ASGI application, a public custom health route, and narrowly scoped middleware that protects only `/mcp`.

**Tech Stack:** Python 3.13, FastMCP 3, Starlette ASGI middleware, Uvicorn, Docker Compose, pytest/httpx.

---

### Task 1: Define the M0 HTTP contract

**Files:**
- Create: `tests/test_mcp_health.py`

- [ ] **Step 1: Write the failing health test**

```python
from httpx import ASGITransport, AsyncClient

from core.mcp.ecotaxa_server import create_app


async def test_health_is_public_and_reports_empty_cache(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "cache": None}
```

- [ ] **Step 2: Write failing authentication tests**

```python
async def test_mcp_rejects_missing_bearer_token(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/mcp")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_app_requires_auth_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        create_app()
```

- [ ] **Step 3: Run the focused test and verify RED**

Run: `pytest tests/test_mcp_health.py -q`

Expected: collection fails because `core.mcp.ecotaxa_server` does not exist.

### Task 2: Implement the minimal MCP ASGI service

**Files:**
- Create: `core/mcp/__init__.py`
- Create: `core/mcp/ecotaxa_server.py`

- [ ] **Step 1: Add a constant-time Bearer middleware**

The middleware reads `MCP_AUTH_TOKEN` at application construction, rejects missing configuration, protects `/mcp` and `/mcp/`, compares credentials with `secrets.compare_digest`, and leaves `/health` public.

- [ ] **Step 2: Add FastMCP and health route**

Create `FastMCP("EcoTaxa Browser")`, register `GET /health` returning `{"status": "ok", "cache": None}`, build `mcp.http_app(path="/mcp")`, and wrap it with the Bearer middleware.

- [ ] **Step 3: Run the focused test and verify GREEN**

Run: `pytest tests/test_mcp_health.py -q`

Expected: all M0 HTTP tests pass.

### Task 3: Add the pure browser package scaffold

**Files:**
- Create: `core/ecotaxa_browser/__init__.py`
- Create: `core/ecotaxa_browser/search.py`
- Create: `core/ecotaxa_browser/projects.py`
- Create: `core/ecotaxa_browser/samples.py`
- Create: `core/ecotaxa_browser/acquisitions.py`
- Create: `core/ecotaxa_browser/objects.py`
- Create: `core/ecotaxa_browser/taxonomy.py`
- Create: `core/ecotaxa_browser/schema.py`

- [ ] **Step 1: Add importable empty modules**

Each module contains a concise module docstring only. The package must import without requiring LangChain or FastMCP.

- [ ] **Step 2: Verify framework independence**

Run:

```bash
python -c "import core.ecotaxa_browser; import core.ecotaxa_browser.search"
```

Expected: exit code 0 with no output.

### Task 4: Wire dependencies and Docker Compose

**Files:**
- Modify: `requirements.txt`
- Modify: `docker-compose.yml`
- Modify: `tests/test_requirements.py`
- Create: `tests/test_mcp_compose.py`

- [ ] **Step 1: Add failing dependency assertions**

Assert that `requirements.txt` contains pinned major ranges for `fastmcp`, `apscheduler`, and `vcrpy`.

- [ ] **Step 2: Add failing Compose assertions**

Parse `docker-compose.yml` with PyYAML and assert that `mcp-ecotaxa` exposes port `8001`, runs `uvicorn core.mcp.ecotaxa_server:app`, and receives `MCP_AUTH_TOKEN` plus the existing EcoTaxa environment variables.

- [ ] **Step 3: Run configuration tests and verify RED**

Run: `pytest tests/test_requirements.py tests/test_mcp_compose.py -q`

Expected: failures for missing dependencies and service.

- [ ] **Step 4: Add dependencies and service**

Add `fastmcp>=3.0.0,<4.0.0`, `apscheduler>=3.11.0,<4.0.0`, and `vcrpy>=7.0.0,<8.0.0`. Add `mcp-ecotaxa` using the existing image/build, port `8001:8001`, `.env`, the required environment entries, source/data mounts, and an HTTP healthcheck.

- [ ] **Step 5: Run configuration tests and verify GREEN**

Run: `pytest tests/test_requirements.py tests/test_mcp_compose.py -q`

Expected: all configuration tests pass.

### Task 5: Verify M0 and update the PRD

**Files:**
- Modify: `docs/PRD_MCP_ECOTAXA.md`

- [ ] **Step 1: Install the new dependencies**

Run: `python -m pip install "fastmcp>=3.0.0,<4.0.0" "apscheduler>=3.11.0,<4.0.0" "vcrpy>=7.0.0,<8.0.0"`

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/test_mcp_health.py tests/test_mcp_compose.py tests/test_requirements.py -q`

Expected: all focused tests pass.

- [ ] **Step 3: Validate Docker Compose**

Run: `docker compose config`

Expected: exit code 0 and a rendered `mcp-ecotaxa` service.

- [ ] **Step 4: Start and probe the service**

Run: `docker compose up -d --build mcp-ecotaxa`, then verify `/health` returns 200 and `/mcp` without Bearer returns 401.

- [ ] **Step 5: Run the complete test suite**

Run: `pytest tests/ -q`

Expected: no regressions.

- [ ] **Step 6: Update milestone gates**

Set M0 status to complete and check only gates demonstrated by the verification commands. Add a dated journal entry summarizing M0.
