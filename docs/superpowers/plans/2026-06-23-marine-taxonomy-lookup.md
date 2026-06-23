# Marine Taxonomy Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an active taxonomy knowledge tool that resolves taxon terms through local RAG, WoRMS, and Wikipedia fallback, then expose it to the agent and verify it through direct API curls.

**Architecture:** Add a focused `core/taxonomy_lookup` package for deterministic lookup logic, a `tools/taxonomy_tool.py` LangChain wrapper, and route taxonomy knowledge questions in the system prompt. EcoTaxa data requests keep their existing read-only tools.

**Tech Stack:** Python, LangChain `@tool`, `requests`, pytest, FastAPI OpenAI-compatible `/v1/chat/completions`, curl smoke checks.

---

## File Structure

- Create `core/taxonomy_lookup/__init__.py`: exports the public lookup service.
- Create `core/taxonomy_lookup/service.py`: contains RAG, WoRMS, Wikipedia fallback orchestration.
- Create `tools/taxonomy_tool.py`: exposes `lookup_marine_taxonomy` as an active LangChain tool.
- Modify `agent.py`: registers the new tool in `make_agent`.
- Modify `agents/copepod_system_prompt.py`: routes taxon knowledge questions to the new tool, while preserving EcoTaxa data routing.
- Modify `docs/superpowers/specs/2026-06-23-marine-taxonomy-lookup-design.md`: make explicit that the competence is not EcoTaxa-limited.
- Create `tests/test_taxonomy_lookup_tool.py`: behavior tests through the public tool interface.
- Modify `tests/test_agent_factory.py`: assert the active agent tool list and prompt routing include the new tool.

## Task 1: Tracer Bullet, RAG Definition Plus WoRMS Validation

**Files:**
- Create: `tests/test_taxonomy_lookup_tool.py`
- Create: `core/taxonomy_lookup/__init__.py`
- Create: `core/taxonomy_lookup/service.py`
- Create: `tools/taxonomy_tool.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import Mock

from tools.taxonomy_tool import make_taxonomy_tool


def _response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.content = b"{}"
    return response


def test_lookup_marine_taxonomy_prefers_rag_definition_and_validates_worms():
    rag_result = [{
        "title": "Calanus hyperboreus",
        "doc": "copepodes_domaine.md",
        "content": "Calanus hyperboreus est une espece de copepode arctique.",
        "score": 0.12,
    }]

    def fake_get(url, params=None, timeout=10):
        if "AphiaRecordsByName" in url:
            return _response([{
                "AphiaID": 104467,
                "scientificname": "Calanus hyperboreus",
                "status": "accepted",
                "rank": "Species",
                "kingdom": "Animalia",
                "phylum": "Arthropoda",
                "class": "Copepoda",
                "order": "Calanoida",
                "family": "Calanidae",
                "genus": "Calanus",
            }])
        if "AphiaClassificationByAphiaID" in url:
            return _response({
                "scientificname": "Animalia",
                "rank": "Kingdom",
                "AphiaID": 2,
                "child": {
                    "scientificname": "Arthropoda",
                    "rank": "Phylum",
                    "AphiaID": 1065,
                    "child": {
                        "scientificname": "Copepoda",
                        "rank": "Class",
                        "AphiaID": 1080,
                    },
                },
            })
        raise AssertionError(f"unexpected URL: {url}")

    tool = make_taxonomy_tool(rag_query=lambda *_args, **_kwargs: rag_result, http_get=fake_get)
    result = tool.invoke({"term": "Calanus hyperboreus"})

    assert "Calanus hyperboreus est une espece" in result
    assert "RAG local" in result
    assert "AphiaID" in result
    assert "104467" in result
    assert "accepted" in result
    assert "Copepoda" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_taxonomy_lookup_tool.py::test_lookup_marine_taxonomy_prefers_rag_definition_and_validates_worms -q`

Expected: FAIL because `tools.taxonomy_tool` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `core/taxonomy_lookup/service.py` with a public `lookup_marine_taxonomy_markdown` function that accepts injected `rag_query` and `http_get` callables for tests. Create `tools/taxonomy_tool.py` with `make_taxonomy_tool`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_taxonomy_lookup_tool.py::test_lookup_marine_taxonomy_prefers_rag_definition_and_validates_worms -q`

Expected: PASS.

## Task 2: Wikipedia Fallback When RAG Is Empty

**Files:**
- Modify: `tests/test_taxonomy_lookup_tool.py`
- Modify: `core/taxonomy_lookup/service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_lookup_marine_taxonomy_uses_wikipedia_fallback_when_rag_is_empty():
    calls = []

    def fake_get(url, params=None, timeout=10):
        calls.append((url, params or {}))
        if "AphiaRecordsByName" in url:
            return _response([])
        if "fr.wikipedia.org/w/api.php" in url:
            return _response({
                "query": {
                    "pages": {
                        "123": {
                            "title": "Copépode",
                            "extract": "Les copepodes sont de petits crustaces.",
                        }
                    }
                }
            })
        raise AssertionError(f"unexpected URL: {url}")

    tool = make_taxonomy_tool(rag_query=lambda *_args, **_kwargs: [], http_get=fake_get)
    result = tool.invoke({"term": "copépode gélatineux"})

    assert "Les copepodes sont de petits crustaces." in result
    assert "Wikipédia fallback" in result
    assert "WoRMS n'a pas resolu" in result or "WoRMS n'a pas résolu" in result
    assert any("fr.wikipedia.org/w/api.php" in url for url, _params in calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_taxonomy_lookup_tool.py::test_lookup_marine_taxonomy_uses_wikipedia_fallback_when_rag_is_empty -q`

Expected: FAIL until Wikipedia fallback is implemented.

- [ ] **Step 3: Write minimal implementation**

Add a MediaWiki Action API fallback using `https://fr.wikipedia.org/w/api.php`, `action=query`, `format=json`, `prop=extracts`, `exintro=1`, `explaintext=1`, `redirects=1`, and `titles=<term>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_taxonomy_lookup_tool.py::test_lookup_marine_taxonomy_uses_wikipedia_fallback_when_rag_is_empty -q`

Expected: PASS.

## Task 3: Agent Registration And Prompt Routing

**Files:**
- Modify: `agent.py`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/test_agent_factory.py`
- Modify: `docs/superpowers/specs/2026-06-23-marine-taxonomy-lookup-design.md`

- [ ] **Step 1: Write failing tests**

Add assertions that:

```python
assert "lookup_marine_taxonomy" in tool_names
assert "lookup_marine_taxonomy" in COPEPOD_SYSTEM_PROMPT
assert "combien de X dans le projet Y" in COPEPOD_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_agent_factory.py::test_agent_has_required_tools tests/test_agent_factory.py::test_system_prompt_anti_hallucination -q`

Expected: FAIL because the tool and prompt routing are not registered yet.

- [ ] **Step 3: Register tool and update prompt**

Import `make_taxonomy_tool` in `agent.py`, append `make_taxonomy_tool()` to the active tool list, and add prompt bullets that route taxon definition/classification questions to `lookup_marine_taxonomy` without limiting this capability to EcoTaxa.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agent_factory.py::test_agent_has_required_tools tests/test_agent_factory.py::test_system_prompt_anti_hallucination -q`

Expected: PASS.

## Task 4: Direct Agent Curl Smoke Tests

**Files:**
- No required code files.

- [ ] **Step 1: Start the agent API**

Run: `PORT=8010 python serve.py`

Expected: server starts with `/v1/chat/completions`.

- [ ] **Step 2: Curl taxonomy knowledge question**

Run:

```bash
curl -s http://localhost:8010/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"copepod-agent","stream":false,"messages":[{"role":"user","content":"C’est quoi Calanus hyperboreus ? Donne la classification taxonomique."}]}'
```

Expected: response mentions a definition, WoRMS validation, AphiaID or a clear WoRMS not-found limitation.

- [ ] **Step 3: Curl EcoTaxa data-routing guard**

Run:

```bash
curl -s http://localhost:8010/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"copepod-agent","stream":false,"messages":[{"role":"user","content":"Combien de Calanus dans le projet 42 ?"}]}'
```

Expected: the streamed/tool logs show EcoTaxa routing, not the taxonomy definition tool. If credentials/cache are unavailable, the answer may be a controlled EcoTaxa error, but not a Wikipedia definition.

## Self-Review

- Spec coverage: tool, source order, fallback, prompt routing, and curl smoke tests are covered.
- Completion marker scan: no incomplete markers remain.
- Type consistency: the public tool name is consistently `lookup_marine_taxonomy`; the service returns markdown.
