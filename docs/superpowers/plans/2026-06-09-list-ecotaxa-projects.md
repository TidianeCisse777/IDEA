# Dynamic EcoTaxa Project Listing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LangChain tool that lists the EcoTaxa projects accessible to the configured account as a compact Markdown table of project IDs and names.

**Architecture:** `EcotaxaClient.list_projects()` owns the authenticated HTTP request and normalizes EcoTaxa's `projid`/`title` response. `make_source_tools()` exposes the normalized data through `list_ecotaxa_projects`, while the system prompt and `ecotaxa_query` skill route discovery requests to the new tool instead of a hardcoded list.

**Tech Stack:** Python 3.13, requests, LangChain tools, pytest, unittest.mock, Markdown prompts.

---

## File Structure

- Modify `tools/ecotaxa_client.py`: authenticated project search and response normalization.
- Modify `tools/copepod_sources.py`: LangChain tool, sorting, Markdown rendering, empty/error handling.
- Modify `tests/test_copepod_sources.py`: client and tool regression tests.
- Modify `tests/test_agent_factory.py`: prompt-routing contract test.
- Modify `agents/copepod_system_prompt.py`: route project-discovery questions.
- Modify `agents/skills/ecotaxa_query.md`: remove hardcoded projects and direct the agent to the live tool.

### Task 1: EcoTaxa Client Project Listing

**Files:**
- Modify: `tools/ecotaxa_client.py`
- Test: `tests/test_copepod_sources.py`

- [ ] **Step 1: Write the failing client test**

Add a test that patches `client._session.get`, invokes `client.list_projects()`, and asserts:

```python
mock_get.assert_called_once_with(
    "https://ecotaxa.obs-vlfr.fr/api/projects/search",
    params={"title_filter": "", "instrument_filter": ""},
    timeout=60,
)
assert projects == [
    {"project_id": 2331, "name": "LOKI ArcticNet"},
    {"project_id": 1165, "name": "UVP5 Amundsen 2018"},
]
```

- [ ] **Step 2: Run the client test and verify RED**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q tests/test_copepod_sources.py::test_ecotaxa_client_list_projects_normalizes_api_response
```

Expected: FAIL because `EcotaxaClient` has no `list_projects`.

- [ ] **Step 3: Implement the minimal client method**

Add:

```python
def list_projects(self) -> list[dict[str, int | str]]:
    resp = self._session.get(
        f"{_BASE_URL}/projects/search",
        params={"title_filter": "", "instrument_filter": ""},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        {"project_id": int(project["projid"]), "name": str(project["title"])}
        for project in resp.json()
    ]
```

- [ ] **Step 4: Run the client test and verify GREEN**

Run the command from Step 2.

Expected: `1 passed`.

### Task 2: LangChain Project Listing Tool

**Files:**
- Modify: `tools/copepod_sources.py`
- Test: `tests/test_copepod_sources.py`

- [ ] **Step 1: Write failing tool tests**

Add tests that assert:

```python
tool_names = {tool.name for tool in make_source_tools("thread-projects")}
assert "list_ecotaxa_projects" in tool_names
```

For unsorted projects, assert `login()` is called, the rendered rows are sorted by numeric ID, and the session store remains empty:

```python
assert result.index("| 42 | Green Edge |") < result.index("| 1165 | UVP5 Amundsen |")
assert not _store.has("thread-projects")
```

Also assert:

```python
assert empty_result == "Aucun projet EcoTaxa accessible."
assert error_result.startswith("Erreur lors de l'accès à EcoTaxa :")
```

- [ ] **Step 2: Run the tool tests and verify RED**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_copepod_sources.py::test_source_tools_include_list_ecotaxa_projects \
  tests/test_copepod_sources.py::test_list_ecotaxa_projects_logs_in_sorts_and_renders_markdown \
  tests/test_copepod_sources.py::test_list_ecotaxa_projects_handles_empty_list \
  tests/test_copepod_sources.py::test_list_ecotaxa_projects_returns_controlled_error
```

Expected: FAIL because the tool is absent.

- [ ] **Step 3: Implement the minimal LangChain tool**

Inside `make_source_tools`, add:

```python
@tool
def list_ecotaxa_projects() -> str:
    """Liste les projets EcoTaxa accessibles au compte configuré."""
    try:
        client = EcotaxaClient()
        client.login()
        projects = sorted(client.list_projects(), key=lambda project: project["project_id"])
    except Exception as exc:
        return f"Erreur lors de l'accès à EcoTaxa : {exc}"

    if not projects:
        return "Aucun projet EcoTaxa accessible."

    lines = ["| project_id | name |", "|---:|---|"]
    lines.extend(f"| {project['project_id']} | {project['name']} |" for project in projects)
    return "\n".join(lines)
```

Return both tools:

```python
return [list_ecotaxa_projects, query_ecotaxa]
```

- [ ] **Step 4: Run the tool tests and verify GREEN**

Run the command from Step 2.

Expected: `4 passed`.

### Task 3: Agent Routing and Skill Guidance

**Files:**
- Modify: `agents/copepod_system_prompt.py`
- Modify: `agents/skills/ecotaxa_query.md`
- Test: `tests/test_agent_factory.py`
- Test: `tests/test_copepod_sources.py`

- [ ] **Step 1: Write failing prompt and skill contract tests**

Add:

```python
def test_system_prompt_routes_ecotaxa_project_discovery():
    from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT
    assert "list_ecotaxa_projects" in COPEPOD_SYSTEM_PROMPT
```

Add:

```python
def test_ecotaxa_skill_uses_live_project_listing():
    skill = Path("agents/skills/ecotaxa_query.md").read_text(encoding="utf-8")
    assert "list_ecotaxa_projects" in skill
    assert "UVP5 Amundsen 2018" not in skill
    assert "LOKI ArcticNet" not in skill
    assert "Green Edge 2015 IceCamp" not in skill
```

- [ ] **Step 2: Run contract tests and verify RED**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_agent_factory.py::test_system_prompt_routes_ecotaxa_project_discovery \
  tests/test_copepod_sources.py::test_ecotaxa_skill_uses_live_project_listing
```

Expected: FAIL because routing is missing and the skill is hardcoded.

- [ ] **Step 3: Update prompt and skill**

Add a routing rule before direct project loading:

```text
- When the user asks which EcoTaxa projects are available or accessible: call `list_ecotaxa_projects`. Do not rely on a hardcoded project list.
```

Replace the hardcoded skill table with:

```markdown
## Découvrir les projets accessibles

La liste des projets dépend du compte EcoTaxa configuré et peut changer.
Appelle `list_ecotaxa_projects` pour obtenir en temps réel les `project_id`
et noms accessibles, puis utilise l'identifiant choisi avec `query_ecotaxa`.
Ne présente jamais une liste de projets codée en dur.
```

- [ ] **Step 4: Run contract tests and verify GREEN**

Run the command from Step 2.

Expected: `2 passed`.

### Task 4: Full Verification and Runtime Reload

**Files:**
- Verify: `tools/ecotaxa_client.py`
- Verify: `tools/copepod_sources.py`
- Verify: `agents/copepod_system_prompt.py`
- Verify: `agents/skills/ecotaxa_query.md`

- [ ] **Step 1: Run the focused regression suite**

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_copepod_sources.py \
  tests/test_agent_factory.py \
  tests/test_cli.py
```

Expected: all tests pass; existing LangGraph deprecation warnings are allowed.

- [ ] **Step 2: Run static diff checks**

```bash
git diff --check -- \
  tools/ecotaxa_client.py \
  tools/copepod_sources.py \
  tests/test_copepod_sources.py \
  tests/test_agent_factory.py \
  agents/copepod_system_prompt.py \
  agents/skills/ecotaxa_query.md
```

Expected: no output and exit code 0.

- [ ] **Step 3: Reload the local server**

Restart the `com.neolab.idea.serve` launch agent so Open WebUI receives the new tool definitions.

- [ ] **Step 4: Verify the live server**

```bash
curl -sS -o /tmp/idea_docs.out -w '%{http_code}\n' http://localhost:8000/docs
```

Expected: `200`.

