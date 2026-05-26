# Copepod Session Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned Redis-backed Data Understanding and Graph Context artifacts for the `copepod` profile, with draft/active transitions, explicit LLM tools, backend transition guards, and debug visibility.

**Architecture:** Extend `SessionStore` with generic session artifact operations keyed by `session_key` and artifact type. Expose artifact writes to the LLM through copepod-only tool functions, expose debug reads through authenticated session routes, and make `/session/mode` refuse `analyse` unless both active artifacts exist. Keep the visible chat summaries as renderings of canonical artifacts, not the canonical state.

**Tech Stack:** FastAPI, Redis via `redis-py`, in-memory test store, pytest, existing IDEA tool registry, vanilla frontend JavaScript.

---

## File Structure

- Create `tests/test_session_artifacts_store.py`: store-level TDD for draft creation, activation, active lookup, version isolation, and graph/data linking fields.
- Modify `core/session_store.py`: add artifact methods to `SessionStore`, `RedisSessionStore`, and `InMemorySessionStore`.
- Create `tests/test_copepod_session_artifacts_tools.py`: executable tool-code tests for copepod-only artifact tool functions.
- Create `core/tool_registry/tools/copepod_session_artifacts.py`: LLM-callable functions for creating and activating Data Understanding / Graph Context drafts.
- Modify `core/tool_registry/tools/__init__.py`: import the new tool module.
- Modify `agents/copepod_profile.py`: add the new artifact tag and render the existing copepod data/column/source/RAG tools that the instructions already mention.
- Modify `core/instruction_renderer/blocks/copepod_tool_signatures.py`: document the artifact tools and `[PLAN_READY]` ordering.
- Modify `core/instruction_renderer/blocks/copepod_mode_plan.py`: require draft creation, user validation, activation, and `[PLAN_READY]` only after active Graph Context.
- Modify `tests/test_copepod_profile.py`: regression tests for new instructions and tool tag.
- Modify `tests/test_session_routes.py`: route-level TDD for `409 Conflict` and debug endpoints.
- Modify `routers/session_routes.py`: enforce analyse preconditions for `copepod`; add debug/admin read endpoints.
- Modify `tests/test_chat_stream_events.py` and `core/chat_stream_events.py`: rename the action button label to `Passer en Mode Analyse`.
- Modify `frontend/assistant.js`: fallback label and `409` error message for missing active artifacts.

---

### Task 1: Store Versioned Session Artifacts

**Files:**
- Create: `tests/test_session_artifacts_store.py`
- Modify: `core/session_store.py`

- [ ] **Step 1: Write failing tests for artifact storage**

Create `tests/test_session_artifacts_store.py`:

```python
from core.session_store import InMemorySessionStore


def test_create_data_understanding_draft_version():
    store = InMemorySessionStore()

    version = store.create_artifact_version(
        "u1:s1:copepod",
        "data_understanding",
        {"files": [{"file_path": "static/u1/s1/uploads/a.csv"}]},
    )

    assert version["artifact_type"] == "data_understanding"
    assert version["status"] == "draft"
    assert version["version_id"].startswith("du-")
    assert version["payload"]["files"][0]["file_path"].endswith("a.csv")
    assert store.get_active_artifact("u1:s1:copepod", "data_understanding") is None


def test_activate_artifact_sets_single_active_version():
    store = InMemorySessionStore()
    first = store.create_artifact_version("u1:s1:copepod", "data_understanding", {"files": ["old"]})
    second = store.create_artifact_version("u1:s1:copepod", "data_understanding", {"files": ["new"]})

    activated = store.activate_artifact_version(
        "u1:s1:copepod",
        "data_understanding",
        second["version_id"],
    )

    assert activated["status"] == "active"
    assert store.get_active_artifact("u1:s1:copepod", "data_understanding")["version_id"] == second["version_id"]
    versions = store.get_artifact_versions("u1:s1:copepod", "data_understanding")
    statuses = {v["version_id"]: v["status"] for v in versions}
    assert statuses[first["version_id"]] == "superseded"
    assert statuses[second["version_id"]] == "active"


def test_active_artifacts_required_for_analyse():
    store = InMemorySessionStore()
    du = store.create_artifact_version("u1:s1:copepod", "data_understanding", {"files": []})
    gc = store.create_artifact_version(
        "u1:s1:copepod",
        "graph_context",
        {"data_understanding_version_id": du["version_id"], "objective": "vertical distribution"},
    )

    assert store.has_active_copepod_plan_artifacts("u1:s1:copepod") is False
    store.activate_artifact_version("u1:s1:copepod", "data_understanding", du["version_id"])
    assert store.has_active_copepod_plan_artifacts("u1:s1:copepod") is False
    store.activate_artifact_version("u1:s1:copepod", "graph_context", gc["version_id"])
    assert store.has_active_copepod_plan_artifacts("u1:s1:copepod") is True


def test_artifact_versions_are_isolated_by_session_key():
    store = InMemorySessionStore()
    v1 = store.create_artifact_version("u1:s1:copepod", "data_understanding", {"session": "s1"})
    store.activate_artifact_version("u1:s1:copepod", "data_understanding", v1["version_id"])

    assert store.get_active_artifact("u1:s2:copepod", "data_understanding") is None
    assert store.get_artifact_versions("u1:s2:copepod", "data_understanding") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_session_artifacts_store.py -q
```

Expected: FAIL with `AttributeError: 'InMemorySessionStore' object has no attribute 'create_artifact_version'`.

- [ ] **Step 3: Implement store methods**

Modify `core/session_store.py`.

Add imports:

```python
from datetime import datetime, timezone
from uuid import uuid4
```

Add constants and helpers near the imports:

```python
VALID_ARTIFACT_TYPES = {"data_understanding", "graph_context"}
ARTIFACT_PREFIX = {
    "data_understanding": "du",
    "graph_context": "gc",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_artifact_version(artifact_type: str, payload: dict) -> dict:
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValueError(f"Invalid artifact_type: {artifact_type}")
    return {
        "version_id": f"{ARTIFACT_PREFIX[artifact_type]}-{uuid4().hex}",
        "artifact_type": artifact_type,
        "status": "draft",
        "created_at": _utc_now_iso(),
        "activated_at": None,
        "payload": payload,
    }
```

Add abstract methods to `SessionStore`:

```python
    @abstractmethod
    def create_artifact_version(self, session_key: str, artifact_type: str, payload: dict) -> dict:
        """Create a draft artifact version for a session."""
        ...

    @abstractmethod
    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        """Return artifact versions for session_key and artifact_type."""
        ...

    @abstractmethod
    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        """Return the active artifact version, if any."""
        ...

    @abstractmethod
    def activate_artifact_version(self, session_key: str, artifact_type: str, version_id: str) -> dict:
        """Mark one artifact version active and supersede prior active versions."""
        ...

    @abstractmethod
    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        """Return True when Data Understanding and Graph Context are active."""
        ...
```

Add methods to `RedisSessionStore`:

```python
    def _artifact_versions_key(self, session_key: str, artifact_type: str) -> str:
        return f"{artifact_type}:{session_key}:versions"

    def _artifact_active_key(self, session_key: str, artifact_type: str) -> str:
        return f"{artifact_type}:{session_key}:active"

    def create_artifact_version(self, session_key: str, artifact_type: str, payload: dict) -> dict:
        version = _new_artifact_version(artifact_type, payload)
        key = self._artifact_versions_key(session_key, artifact_type)
        versions = self.get_artifact_versions(session_key, artifact_type)
        versions.append(version)
        self._r.set(key, json.dumps(versions))
        return version

    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        if artifact_type not in VALID_ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact_type: {artifact_type}")
        raw = self._r.get(self._artifact_versions_key(session_key, artifact_type))
        return json.loads(raw) if raw else []

    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        active_id_raw = self._r.get(self._artifact_active_key(session_key, artifact_type))
        if not active_id_raw:
            return None
        active_id = active_id_raw.decode()
        return next(
            (v for v in self.get_artifact_versions(session_key, artifact_type) if v["version_id"] == active_id),
            None,
        )

    def activate_artifact_version(self, session_key: str, artifact_type: str, version_id: str) -> dict:
        versions = self.get_artifact_versions(session_key, artifact_type)
        activated = None
        for version in versions:
            if version["version_id"] == version_id:
                version["status"] = "active"
                version["activated_at"] = _utc_now_iso()
                activated = version
            elif version["status"] == "active":
                version["status"] = "superseded"
        if activated is None:
            raise ValueError(f"Artifact version not found: {version_id}")
        self._r.set(self._artifact_versions_key(session_key, artifact_type), json.dumps(versions))
        self._r.set(self._artifact_active_key(session_key, artifact_type), version_id)
        return activated

    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        return (
            self.get_active_artifact(session_key, "data_understanding") is not None
            and self.get_active_artifact(session_key, "graph_context") is not None
        )
```

Add matching methods to `InMemorySessionStore`:

```python
        self._artifact_versions: dict[tuple[str, str], list[dict]] = {}
        self._artifact_active: dict[tuple[str, str], str] = {}
```

```python
    def create_artifact_version(self, session_key: str, artifact_type: str, payload: dict) -> dict:
        version = _new_artifact_version(artifact_type, payload)
        key = (session_key, artifact_type)
        self._artifact_versions.setdefault(key, []).append(version)
        return version

    def get_artifact_versions(self, session_key: str, artifact_type: str) -> list[dict]:
        if artifact_type not in VALID_ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact_type: {artifact_type}")
        return list(self._artifact_versions.get((session_key, artifact_type), []))

    def get_active_artifact(self, session_key: str, artifact_type: str) -> dict | None:
        active_id = self._artifact_active.get((session_key, artifact_type))
        if active_id is None:
            return None
        return next(
            (v for v in self.get_artifact_versions(session_key, artifact_type) if v["version_id"] == active_id),
            None,
        )

    def activate_artifact_version(self, session_key: str, artifact_type: str, version_id: str) -> dict:
        key = (session_key, artifact_type)
        versions = self._artifact_versions.get(key, [])
        activated = None
        for version in versions:
            if version["version_id"] == version_id:
                version["status"] = "active"
                version["activated_at"] = _utc_now_iso()
                activated = version
            elif version["status"] == "active":
                version["status"] = "superseded"
        if activated is None:
            raise ValueError(f"Artifact version not found: {version_id}")
        self._artifact_active[key] = version_id
        return activated

    def has_active_copepod_plan_artifacts(self, session_key: str) -> bool:
        return (
            self.get_active_artifact(session_key, "data_understanding") is not None
            and self.get_active_artifact(session_key, "graph_context") is not None
        )
```

Update `evict()` in both stores to clear artifact keys for the session. For in-memory:

```python
        for artifact_type in VALID_ARTIFACT_TYPES:
            self._artifact_versions.pop((session_key, artifact_type), None)
            self._artifact_active.pop((session_key, artifact_type), None)
```

For Redis:

```python
        artifact_keys = []
        for artifact_type in VALID_ARTIFACT_TYPES:
            artifact_keys.append(self._artifact_versions_key(session_key, artifact_type))
            artifact_keys.append(self._artifact_active_key(session_key, artifact_type))
        self._r.delete(f"messages:{session_key}", f"last_active:{session_key}", *artifact_keys)
```

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
pytest tests/test_session_artifacts_store.py tests/test_session_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/session_store.py tests/test_session_artifacts_store.py tests/test_session_store.py
git commit -m "feat: add versioned session artifacts store"
```

---

### Task 2: Add Copepod-Only Artifact Tools and Fix Copepod Tool Rendering

**Files:**
- Create: `tests/test_copepod_session_artifacts_tools.py`
- Create: `core/tool_registry/tools/copepod_session_artifacts.py`
- Modify: `core/tool_registry/tools/__init__.py`
- Modify: `agents/copepod_profile.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/test_copepod_session_artifacts_tools.py`:

```python
from unittest.mock import patch

from core.session_store import InMemorySessionStore


def _load_tools():
    from core.tool_registry import registry
    from core.tool_registry.tools import copepod_session_artifacts  # noqa: F401

    code = registry.render({"copepod_artifacts"})
    ns = {}
    exec(code, ns)
    return ns


def test_create_and_activate_data_understanding_via_tools():
    store = InMemorySessionStore()
    tools = _load_tools()

    with patch("core.session_store.session_store", store):
        draft = tools["create_data_understanding_draft"](
            "u1:s1:copepod",
            {
                "files": [
                    {
                        "file_path": "static/u1/s1/uploads/a.csv",
                        "original_filename": "a.csv",
                        "size_bytes": 12,
                        "content_hash": "sha256:abc",
                        "uploaded_at": "2026-05-26T10:00:00+00:00",
                        "inspection_tool_version": "inspect_file:v1",
                    }
                ]
            },
        )
        active = tools["activate_data_understanding"]("u1:s1:copepod", draft["version_id"])

    assert draft["status"] == "draft"
    assert active["status"] == "active"
    assert store.get_active_artifact("u1:s1:copepod", "data_understanding")["version_id"] == draft["version_id"]


def test_create_graph_context_requires_data_understanding_version_reference():
    store = InMemorySessionStore()
    tools = _load_tools()

    with patch("core.session_store.session_store", store):
        result = tools["create_graph_context_draft"](
            "u1:s1:copepod",
            {
                "objective": "Distribution verticale",
                "data_understanding_version_id": "du-123",
                "language": "Python",
                "feasibility": "reliable",
            },
        )

    assert result["artifact_type"] == "graph_context"
    assert result["payload"]["data_understanding_version_id"] == "du-123"


def test_create_graph_context_without_data_understanding_version_blocks():
    tools = _load_tools()
    result = tools["create_graph_context_draft"](
        "u1:s1:copepod",
        {"objective": "Distribution verticale"},
    )

    assert result["created"] is False
    assert "data_understanding_version_id" in result["blocking_reason"]


def test_copepod_profile_renders_data_and_artifact_tools():
    import importlib
    import agents.copepod_profile
    from agents.registry import get_profile

    importlib.reload(agents.copepod_profile)
    code = get_profile("copepod").get_tool_code()

    assert "def inspect_file" in code
    assert "def infer_column_roles" in code
    assert "def describe_column" in code
    assert "def create_data_understanding_draft" in code
    assert "def activate_graph_context" in code
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_copepod_session_artifacts_tools.py -q
```

Expected: FAIL with import error for `copepod_session_artifacts`.

- [ ] **Step 3: Implement the tool module**

Create `core/tool_registry/tools/copepod_session_artifacts.py`:

```python
from core.tool_registry.registry import Tool, registry

_code = '''
def create_data_understanding_draft(session_key, artifact):
    """Create a draft Data Understanding artifact version for a copepod session."""
    from core import session_store as session_store_module
    return session_store_module.session_store.create_artifact_version(
        session_key,
        "data_understanding",
        artifact,
    )


def activate_data_understanding(session_key, version_id):
    """Activate a Data Understanding version after user validation."""
    from core import session_store as session_store_module
    try:
        return session_store_module.session_store.activate_artifact_version(
            session_key,
            "data_understanding",
            version_id,
        )
    except ValueError as exc:
        return {"activated": False, "blocking_reason": str(exc)}


def create_graph_context_draft(session_key, artifact):
    """Create a draft Graph Context artifact version for a copepod session."""
    if not artifact.get("data_understanding_version_id"):
        return {
            "created": False,
            "blocking_reason": "Graph Context requires data_understanding_version_id.",
        }
    from core import session_store as session_store_module
    return session_store_module.session_store.create_artifact_version(
        session_key,
        "graph_context",
        artifact,
    )


def activate_graph_context(session_key, version_id):
    """Activate a Graph Context version after user validation."""
    from core import session_store as session_store_module
    try:
        return session_store_module.session_store.activate_artifact_version(
            session_key,
            "graph_context",
            version_id,
        )
    except ValueError as exc:
        return {"activated": False, "blocking_reason": str(exc)}
'''

registry.register(Tool(
    name="copepod_session_artifacts",
    tags=frozenset({"copepod_artifacts"}),
    code=_code,
))
```

Modify `core/tool_registry/tools/__init__.py`:

```python
from . import copepod_session_artifacts
```

Modify `agents/copepod_profile.py`:

```python
    tool_tags = {
        "core",
        "rag",
        "mcp",
        "copepod_data",
        "copepod_columns",
        "copepod_sources_meta",
        "copepod_rag",
        "copepod_artifacts",
    }
```

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
pytest tests/test_copepod_session_artifacts_tools.py tests/test_copepod_profile.py -q
```

Expected: `test_copepod_profile_uses_safe_runtime_and_copepod_instruction_blocks` may fail because it expects old `tool_tags`.

- [ ] **Step 5: Update profile test expectation**

In `tests/test_copepod_profile.py`, change:

```python
assert profile.tool_tags == {"core", "rag", "mcp"}
```

to:

```python
assert profile.tool_tags == {
    "core",
    "rag",
    "mcp",
    "copepod_data",
    "copepod_columns",
    "copepod_sources_meta",
    "copepod_rag",
    "copepod_artifacts",
}
```

- [ ] **Step 6: Run tests to verify green**

Run:

```bash
pytest tests/test_copepod_session_artifacts_tools.py tests/test_copepod_profile.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add core/tool_registry/tools/copepod_session_artifacts.py core/tool_registry/tools/__init__.py agents/copepod_profile.py tests/test_copepod_session_artifacts_tools.py tests/test_copepod_profile.py
git commit -m "feat: render copepod artifact and data tools"
```

---

### Task 3: Enforce Mode Transition Preconditions and Debug Reads

**Files:**
- Modify: `tests/test_session_routes.py`
- Modify: `routers/session_routes.py`

- [ ] **Step 1: Write failing route tests**

Append to `tests/test_session_routes.py`:

```python
class TestCopepodAnalyseModeGuard:
    def test_copepod_analyse_without_active_artifacts_returns_409(self, client):
        tc, _ = client

        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "guarded", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 409
        assert "Data Understanding" in resp.json()["detail"]
        assert "Graph Context" in resp.json()["detail"]

    def test_copepod_analyse_with_active_artifacts_succeeds(self, client):
        tc, store = client
        du = store.create_artifact_version("u1:guarded-ok:copepod", "data_understanding", {"files": []})
        gc = store.create_artifact_version(
            "u1:guarded-ok:copepod",
            "graph_context",
            {"data_understanding_version_id": du["version_id"]},
        )
        store.activate_artifact_version("u1:guarded-ok:copepod", "data_understanding", du["version_id"])
        store.activate_artifact_version("u1:guarded-ok:copepod", "graph_context", gc["version_id"])

        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "guarded-ok", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert resp.json()["mode"] == "analyse"

    def test_generic_analyse_mode_is_not_guarded_by_copepod_artifacts(self, client):
        tc, store = client

        resp = tc.post(
            "/session/mode",
            json={"mode": "analyse"},
            headers={"x-session-id": "generic-s", "x-agent-type": "generic"},
        )

        assert resp.status_code == 200
        assert store.get_session_mode("u1:generic-s:generic") == "analyse"

    def test_copepod_cannot_switch_back_to_plan_after_analyse(self, client):
        tc, store = client
        store.set_session_mode("u1:no-return:copepod", "analyse")

        resp = tc.post(
            "/session/mode",
            json={"mode": "plan"},
            headers={"x-session-id": "no-return", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 409
        assert "irreversible" in resp.json()["detail"].lower()


class TestArtifactDebugRoutes:
    def test_get_data_understanding_debug_returns_versions_and_active(self, client):
        tc, store = client
        du = store.create_artifact_version("u1:debug:copepod", "data_understanding", {"files": [{"file_path": "a.csv"}]})
        store.activate_artifact_version("u1:debug:copepod", "data_understanding", du["version_id"])

        resp = tc.get(
            "/session/artifacts/data-understanding",
            headers={"x-session-id": "debug", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert resp.json()["active"]["version_id"] == du["version_id"]
        assert len(resp.json()["versions"]) == 1

    def test_get_graph_context_debug_returns_versions_and_active(self, client):
        tc, store = client
        gc = store.create_artifact_version("u1:debug:copepod", "graph_context", {"objective": "plot"})
        store.activate_artifact_version("u1:debug:copepod", "graph_context", gc["version_id"])

        resp = tc.get(
            "/session/artifacts/graph-context",
            headers={"x-session-id": "debug", "x-agent-type": "copepod"},
        )

        assert resp.status_code == 200
        assert resp.json()["active"]["version_id"] == gc["version_id"]
        assert resp.json()["artifact_type"] == "graph_context"

    def test_debug_artifacts_are_copepod_only(self, client):
        tc, _ = client

        resp = tc.get(
            "/session/artifacts/data-understanding",
            headers={"x-session-id": "debug", "x-agent-type": "generic"},
        )

        assert resp.status_code == 404
```

Update the existing `test_post_mode_sets_analyse` so it uses `x-agent-type: generic`, or preload active copepod artifacts before posting. Update `test_post_mode_sets_plan` to expect `409` for copepod after analyse, and add a separate generic test if needed.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_session_routes.py -q
```

Expected: FAIL because analyse is not guarded and debug routes do not exist.

- [ ] **Step 3: Implement route guard and debug endpoints**

Modify `routers/session_routes.py`.

Add helper:

```python
def _session_key_from_request(request: Request, user_id: str) -> tuple[str, str]:
    session_id = request.headers.get("x-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Session ID required")

    agent_type = request.headers.get("x-agent-type", "generic")
    if agent_type not in registered_types():
        agent_type = "generic"

    return make_session_key(user_id, session_id, agent_type), agent_type
```

Use this helper in `get_mode()` and `set_mode()`.

In `set_mode()`, before setting mode:

```python
    current_mode = session_store.get_session_mode(session_key)
    if agent_type == "copepod" and current_mode == "analyse" and body.mode == "plan":
        raise HTTPException(
            status_code=409,
            detail="Mode Analyse is irreversible for copepod sessions.",
        )

    if agent_type == "copepod" and body.mode == "analyse":
        if not session_store.has_active_copepod_plan_artifacts(session_key):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot enter Mode Analyse without active Data Understanding "
                    "and active Graph Context artifacts."
                ),
            )
```

Add debug endpoint helper and routes:

```python
def _require_copepod_artifact_request(request: Request, token: str) -> str:
    user = get_current_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    session_key, agent_type = _session_key_from_request(request, user.id)
    if agent_type != "copepod":
        raise HTTPException(status_code=404, detail="Copepod artifacts are not available for this agent type")
    return session_key


def _artifact_response(session_key: str, artifact_type: str) -> dict:
    return {
        "artifact_type": artifact_type,
        "session_key": session_key,
        "active": session_store.get_active_artifact(session_key, artifact_type),
        "versions": session_store.get_artifact_versions(session_key, artifact_type),
    }


@router.get("/artifacts/data-understanding")
async def get_data_understanding_artifacts(
    request: Request,
    token: str = Depends(get_auth_token),
):
    session_key = _require_copepod_artifact_request(request, token)
    return _artifact_response(session_key, "data_understanding")


@router.get("/artifacts/graph-context")
async def get_graph_context_artifacts(
    request: Request,
    token: str = Depends(get_auth_token),
):
    session_key = _require_copepod_artifact_request(request, token)
    return _artifact_response(session_key, "graph_context")
```

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
pytest tests/test_session_routes.py tests/test_session_artifacts_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routers/session_routes.py tests/test_session_routes.py
git commit -m "feat: guard copepod analyse mode with active artifacts"
```

---

### Task 4: Update Copepod Instructions for Artifact Workflow

**Files:**
- Modify: `tests/test_copepod_profile.py`
- Modify: `core/instruction_renderer/blocks/copepod_tool_signatures.py`
- Modify: `core/instruction_renderer/blocks/copepod_mode_plan.py`

- [ ] **Step 1: Write failing instruction tests**

Append to `tests/test_copepod_profile.py`:

```python
def test_copepod_instructions_require_artifact_tools_before_plan_ready():
    import_copepod_profile()
    profile = get_profile("copepod")

    instructions = profile.get_custom_instructions(
        host="http://localhost",
        user_id="user-1",
        session_id="session-1",
        static_dir="static",
        upload_dir="uploads",
    )

    assert "create_data_understanding_draft" in instructions
    assert "activate_data_understanding" in instructions
    assert "create_graph_context_draft" in instructions
    assert "activate_graph_context" in instructions
    assert "Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded" in instructions
    assert "Passer en Mode Analyse" in instructions
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_copepod_profile.py::test_copepod_instructions_require_artifact_tools_before_plan_ready -q
```

Expected: FAIL because these tool names and wording are not in the instructions yet.

- [ ] **Step 3: Update tool signatures block**

Modify `core/instruction_renderer/blocks/copepod_tool_signatures.py`.

Add after `summarize_understanding`:

```python
- `create_data_understanding_draft(session_key, artifact)` — persist the structured Data Understanding draft after file inspection. Include file identity fields (`file_path`, `original_filename`, `size_bytes`, `content_hash`, `uploaded_at`, `inspection_tool_version`), column roles, quality limits, taxonomic validation status, joins, and user overrides when present.
- `activate_data_understanding(session_key, version_id)` — activate a Data Understanding version only after the user has confirmed or corrected it.
- `create_graph_context_draft(session_key, artifact)` — persist the structured Graph Context draft. It must include `data_understanding_version_id`, objective, source/data selection, columns, filters, units, chart type, language, output artifacts, feasibility, and blockers.
- `activate_graph_context(session_key, version_id)` — activate a Graph Context version only after the user has confirmed or corrected the scientific and graphing context.
```

Add to rules:

```python
- Build `session_key` as `{user_id}:{session_id}:copepod` when calling artifact tools.
- Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded.
- `[PLAN_READY]` shows the [Passer en Mode Analyse] button; it does not validate the Graph Context by itself.
```

- [ ] **Step 4: Update Plan Mode block**

Modify `core/instruction_renderer/blocks/copepod_mode_plan.py`.

In Phase 1, after tool sequence, add:

```text
After building the Data Understanding, call `create_data_understanding_draft(session_key, artifact)` before displaying the human summary. The summary shown to the user is a rendering of the draft artifact. After the user confirms or corrects it, call `activate_data_understanding(session_key, version_id)` for the confirmed version.
```

In Phase 2, add:

```text
When Graph Context is complete, call `create_graph_context_draft(session_key, artifact)` and include the active `data_understanding_version_id`. Display the human summary, then stop. After the user confirms or corrects the scientific and graphing context, call `activate_graph_context(session_key, version_id)`.
```

Replace the existing `[PLAN_READY]` rule with:

```text
Do not emit `[PLAN_READY]` until `activate_graph_context` has succeeded. Once it has succeeded, append the exact tag `[PLAN_READY]` on a new line at the very end of your response — nothing after it. This tag is stripped before display and triggers the [Passer en Mode Analyse] button in the UI.
```

- [ ] **Step 5: Run tests to verify green**

Run:

```bash
pytest tests/test_copepod_profile.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/instruction_renderer/blocks/copepod_tool_signatures.py core/instruction_renderer/blocks/copepod_mode_plan.py tests/test_copepod_profile.py
git commit -m "docs: instruct copepod artifact workflow"
```

---

### Task 5: Rename Plan Ready Action and Frontend Error Handling

**Files:**
- Modify: `tests/test_chat_stream_events.py`
- Modify: `core/chat_stream_events.py`
- Modify: `frontend/assistant.js`

- [ ] **Step 1: Write failing stream label test**

In `tests/test_chat_stream_events.py`, replace expected label:

```python
"label": "Valider et passer en Mode Analyse",
```

with:

```python
"label": "Passer en Mode Analyse",
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_chat_stream_events.py::test_single_chunk_plan_ready_strips_tag_and_emits_button_after_three_user_turns -q
```

Expected: FAIL because the emitted label still says `Valider et passer en Mode Analyse`.

- [ ] **Step 3: Update backend action label**

Modify `core/chat_stream_events.py`:

```python
VALIDATE_PLAN_ACTION = {
    "start": True,
    "end": True,
    "role": "computer",
    "type": "action_button",
    "action": "validate_plan",
    "label": "Passer en Mode Analyse",
}
```

- [ ] **Step 4: Update frontend fallback, 409 message, and retry state**

Modify `frontend/assistant.js`.

In `handleActionButtonChunk`, change:

```javascript
const label = chunk.label || 'Valider et passer en Mode Analyse';
```

to:

```javascript
const label = chunk.label || 'Passer en Mode Analyse';
```

In `switchToAnalyseMode`, replace:

```javascript
if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
```

with:

```javascript
if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    if (resp.status === 409) {
        throw new Error(errorData.detail || 'Le contexte validé est incomplet pour passer en Mode Analyse.');
    }
    throw new Error(errorData.detail || `HTTP ${resp.status}`);
}
```

Replace the catch message:

```javascript
appendSystemMessage('Erreur : impossible de passer en Mode Analyse. Veuillez réessayer.');
```

with:

```javascript
appendSystemMessage(`Erreur : impossible de passer en Mode Analyse. ${err.message}`);
```

In `handleActionButtonChunk`, keep the button usable if the backend rejects the transition:

```javascript
btn.addEventListener('click', async () => {
    btn.disabled = true;
    const switched = await switchToAnalyseMode();
    if (!switched) {
        btn.disabled = false;
    }
});
```

Update `switchToAnalyseMode` to return a boolean:

```javascript
        appendSessionModeBandeau();
        return true;
    } catch (err) {
        console.error('Failed to switch to Analyse mode:', err);
        appendSystemMessage(`Erreur : impossible de passer en Mode Analyse. ${err.message}`);
        return false;
    }
```

- [ ] **Step 5: Run tests to verify green**

Run:

```bash
pytest tests/test_chat_stream_events.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/chat_stream_events.py tests/test_chat_stream_events.py frontend/assistant.js
git commit -m "fix: rename analyse mode action"
```

---

### Task 6: End-to-End Regression Slice

**Files:**
- Modify: tests already created in prior tasks only.

- [ ] **Step 1: Run targeted backend regression suite**

Run:

```bash
pytest tests/test_session_artifacts_store.py tests/test_copepod_session_artifacts_tools.py tests/test_session_routes.py tests/test_copepod_profile.py tests/test_chat_stream_events.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader affected suite**

Run:

```bash
pytest tests/test_session_store.py tests/test_phase3_wiring.py tests/test_copepod_data.py tests/test_copepod_data_workflow.py -q
```

Expected: PASS.

- [ ] **Step 3: Manual API smoke test with TestClient or running app**

If the app is already running, use the browser or curl with auth. If not, this step can be satisfied by the route tests. Verify these observable behaviors:

```text
1. POST /session/mode {"mode": "analyse"} with X-Agent-Type: copepod and no active artifacts returns 409.
2. GET /session/artifacts/data-understanding with X-Agent-Type: copepod returns active + versions.
3. GET /session/artifacts/data-understanding with X-Agent-Type: generic returns 404.
4. [PLAN_READY] stream emits label "Passer en Mode Analyse".
```

- [ ] **Step 4: Final git status**

Run:

```bash
git status --short
```

Expected: clean if each task committed; otherwise only intentional uncommitted plan/documentation files remain.

---

## Subagent Execution Strategy

Use fresh worker subagents sequentially per task, not parallel, because the tasks build on each other:

1. Worker A owns Task 1: `core/session_store.py` and `tests/test_session_artifacts_store.py`.
2. Worker B owns Task 2: tool registry files and tool tests.
3. Worker C owns Task 3: `routers/session_routes.py` and route tests.
4. Worker D owns Task 4: instruction blocks and profile tests.
5. Worker E owns Task 5: stream label and frontend error handling.
6. Controller runs Task 6 verification.

After each worker returns:

1. Run the task’s stated tests locally.
2. Review spec compliance against this plan.
3. Review code quality for minimal scope, no unrelated refactors, no secret exposure, and no generic-profile leakage.
4. Only then proceed to the next worker.

## Self-Review

- Spec coverage: covers Redis-backed artifacts, draft/active status, LLM tools, copepod-only scope, active artifact guard for Analyse Mode, debug endpoints, `[PLAN_READY]` semantics, and button rename.
- Placeholder scan: no task contains TBD/TODO/fill-in instructions; code snippets and commands are explicit.
- Type consistency: artifact type strings are consistently `data_understanding` and `graph_context`; version ids use `du-` and `gc-`; route paths are `/session/artifacts/data-understanding` and `/session/artifacts/graph-context`.
