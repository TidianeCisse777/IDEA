# Persistent Conversation Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve all tabular conversation state across server restarts and provide one explicit family-wide deletion operation for both session-store adapters.

**Architecture:** Deepen the existing file and PostgreSQL storage modules with `clear_conversation(thread_id)` while keeping `clear(key)` exact. Remove process-local new-thread detection from FastAPI so a stable Open WebUI conversation always resumes persisted state.

**Tech Stack:** Python 3.13, pandas, FastAPI, SQLAlchemy Core, pytest, LangGraph.

## Global Constraints

- TDD for every behavior change: observe the regression test fail before editing production code.
- A request for an existing stable conversation must perform no implicit session deletion.
- `clear_conversation(thread_id)` deletes only the exact key and keys beginning with `thread_id + ":"`.
- No public reset endpoint and no LangGraph checkpoint or long-term-memory deletion.
- Preserve the file and PostgreSQL adapters' existing `set`, `get`, `keys`, `has`, and exact `clear` behavior.

---

### Task 1: File-backed conversation deletion

**Files:**
- Modify: `tests/test_session_store.py`
- Modify: `tools/session_store.py`

**Interfaces:**
- Consumes: `SessionStore.keys(prefix: str | None = None) -> list[str]` and `SessionStore.clear(thread_id: str) -> None`.
- Produces: `SessionStore.clear_conversation(thread_id: str) -> None`.

- [ ] **Step 1: Write the failing family-deletion test**

```python
def test_clear_conversation_removes_exact_and_colon_family_only(tmp_path):
    from tools.session_store import SessionStore

    store = SessionStore(storage_dir=tmp_path / "sessions")
    df = pd.DataFrame({"value": [1]})
    for key in (
        "thread-abc",
        "thread-abc:ecotaxa",
        "thread-abc:dataset:df_ecotaxa",
        "thread-abc-other",
        "thread-abcd:dataset:df_neighbor",
    ):
        store.set(key, df, {"key": key})

    store.clear_conversation("thread-abc")

    assert store.get("thread-abc") is None
    assert store.keys("thread-abc:") == []
    assert store.get("thread-abc-other") is not None
    assert store.get("thread-abcd:dataset:df_neighbor") is not None
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_session_store.py::test_clear_conversation_removes_exact_and_colon_family_only -v`

Expected: FAIL with `AttributeError: 'SessionStore' object has no attribute 'clear_conversation'`.

- [ ] **Step 3: Implement the minimal file-backed operation**

Add to `SessionStore`:

```python
def clear_conversation(self, thread_id: str) -> None:
    prefix = f"{thread_id}:"
    family = [
        key for key in self.keys()
        if key == thread_id or key.startswith(prefix)
    ]
    for key in family:
        self.clear(key)
```

- [ ] **Step 4: Verify GREEN and exact-clear compatibility**

Run: `pytest tests/test_session_store.py -v`

Expected: all tests pass, including `test_session_store_clear_removes_persisted_state`.

- [ ] **Step 5: Commit the adapter change**

```bash
git add tools/session_store.py tests/test_session_store.py
git commit -m "feat(session): clear complete conversation families"
```

---

### Task 2: PostgreSQL conversation deletion

**Files:**
- Modify: `tests/test_session_store_pg.py`
- Modify: `tools/session_store_pg.py`

**Interfaces:**
- Consumes: the `sessions(session_key, storage_path, meta)` persistence schema and `_cache`.
- Produces: `SessionStorePG.clear_conversation(session_key: str) -> None` with the same observable contract as Task 1.

- [ ] **Step 1: Write a non-opt-in SQLite contract test for the SQLAlchemy implementation**

```python
def test_clear_conversation_deletes_literal_family_in_one_transaction(tmp_path):
    from sqlalchemy import create_engine, text
    from tools.session_store_pg import SessionStorePG

    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.sqlite'}")
    exact_path = tmp_path / "exact.pkl"
    child_path = tmp_path / "child.pkl"
    neighbor_path = tmp_path / "neighbor.pkl"
    for path in (exact_path, child_path, neighbor_path):
        pd.DataFrame({"value": [1]}).to_pickle(path)

    rows = [
        ("thread_%", str(exact_path)),
        ("thread_%:dataset:df", str(child_path)),
        ("thread_%other", str(neighbor_path)),
    ]
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE sessions (session_key TEXT PRIMARY KEY, storage_path TEXT)"
        ))
        for key, path in rows:
            conn.execute(
                text("INSERT INTO sessions VALUES (:key, :path)"),
                {"key": key, "path": path},
            )

    store = object.__new__(SessionStorePG)
    store._engine = engine
    store._storage_dir = tmp_path
    store._cache = {key: {"df": None, "meta": {}} for key, _ in rows}

    store.clear_conversation("thread_%")

    with engine.connect() as conn:
        remaining_keys = list(conn.execute(
            text("SELECT session_key FROM sessions ORDER BY session_key")
        ).scalars())

    assert remaining_keys == ["thread_%other"]
    assert not exact_path.exists()
    assert not child_path.exists()
    assert neighbor_path.exists()
    assert "thread_%" not in store._cache
    assert "thread_%:dataset:df" not in store._cache
    assert "thread_%other" in store._cache
```

The literal `%` proves the implementation does not interpret identifiers as SQL `LIKE` patterns.

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_session_store_pg.py::test_clear_conversation_deletes_literal_family_in_one_transaction -v`

Expected: FAIL with `AttributeError: 'SessionStorePG' object has no attribute 'clear_conversation'`.

- [ ] **Step 3: Implement one metadata transaction plus file cleanup**

Add to `SessionStorePG`:

```python
def clear_conversation(self, session_key: str) -> None:
    prefix = f"{session_key}:"
    where = (
        "session_key = :key OR "
        "substr(session_key, 1, length(:prefix)) = :prefix"
    )
    params = {"key": session_key, "prefix": prefix}
    with self._engine.begin() as conn:
        rows = conn.execute(
            text(f"SELECT session_key, storage_path FROM sessions WHERE {where}"),
            params,
        ).fetchall()
        conn.execute(text(f"DELETE FROM sessions WHERE {where}"), params)

    cached_family = [
        key for key in self._cache
        if key == session_key or key.startswith(prefix)
    ]
    for key in cached_family:
        self._cache.pop(key, None)
    for _, storage_path in rows:
        if storage_path:
            with contextlib.suppress(FileNotFoundError):
                Path(storage_path).unlink()
```

- [ ] **Step 4: Verify local and opt-in contracts**

Run: `pytest tests/test_session_store_pg.py -v`

Expected without PostgreSQL DSN: the SQLite contract passes and the PostgreSQL integration tests remain explicitly skipped. If `SESSION_STORE_TEST_DATABASE_URL` is set, all adapter tests pass.

- [ ] **Step 5: Commit the PostgreSQL adapter change**

```bash
git add tools/session_store_pg.py tests/test_session_store_pg.py
git commit -m "feat(session): delete PostgreSQL conversation families"
```

---

### Task 3: Resume persisted state in FastAPI

**Files:**
- Modify: `tests/test_serve_chat_metadata.py`
- Modify: `tests/test_feedback.py`
- Modify: `serve.py`

**Interfaces:**
- Consumes: stable `_thread_id(...)`, `SessionStore` persistence, and `make_agent(thread_id, user_id)`.
- Produces: request handling that never mutates session state merely because the process has not seen a thread before.

- [ ] **Step 1: Write the failing restart regression test**

```python
@pytest.mark.asyncio
async def test_chat_completions_resumes_persisted_dataframe_after_restart(
    monkeypatch, tmp_path
):
    import pandas as pd
    import serve as serve_module
    from tools.session_store import SessionStore

    req = serve_module.ChatRequest(
        messages=[serve_module.Message(role="user", content="Continue l'analyse")],
        stream=False,
    )
    chat_id = "restart-chat-123"
    thread_id = serve_module._thread_id(
        req.messages,
        chat_id=chat_id,
        session_id=None,
        metadata=None,
    )
    store_dir = tmp_path / "sessions"
    before_restart = SessionStore(store_dir)
    dataframe = pd.DataFrame({"sample_id": [101], "depth": [12.5]})
    alias = f"{thread_id}:dataset:df_ecotaxa"
    before_restart.set(thread_id, dataframe, {"variable_name": "df"})
    before_restart.set(alias, dataframe, {"variable_name": "df_ecotaxa"})

    restarted_store = SessionStore(store_dir)
    if hasattr(serve_module, "_known_threads"):
        serve_module._known_threads.discard(thread_id)

    mock_msg = MagicMock()
    mock_msg.content = "réponse"
    mock_msg.usage_metadata = {"input_tokens": 1, "output_tokens": 1}
    mock_msg.response_metadata = {}
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": [mock_msg]})
    mock_agent.aget_state = AsyncMock(
        return_value=MagicMock(values={"messages": []})
    )

    monkeypatch.setattr(serve_module, "default_store", restarted_store)
    monkeypatch.setattr(
        serve_module,
        "make_agent",
        lambda thread_id, user_id="anonymous": mock_agent,
    )
    monkeypatch.setattr(serve_module, "_log_turn", lambda *args, **kwargs: None)
    request = MagicMock()
    request.headers = {}

    await serve_module.chat_completions(
        req,
        request,
        x_openwebui_chat_id=chat_id,
    )

    active = restarted_store.get(thread_id)
    derived = restarted_store.get(alias)
    assert active is not None and active["df"].equals(dataframe)
    assert derived is not None and derived["df"].equals(dataframe)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_serve_chat_metadata.py::test_chat_completions_resumes_persisted_dataframe_after_restart -v`

Expected: FAIL because the active `thread_id` entry becomes `None` while the derived alias remains.

- [ ] **Step 3: Remove implicit lifecycle state from the request path**

Delete from `serve.py`:

```python
_known_threads: set[str] = set()
```

and:

```python
if tid not in _known_threads:
    _known_threads.add(tid)
    default_store.clear(tid)
```

Remove obsolete `_known_threads.clear()` calls and `default_store.clear` monkeypatches from the transport/feedback tests. Do not replace them with another implicit write.

- [ ] **Step 4: Verify GREEN and request metadata behavior**

Run: `pytest tests/test_serve_chat_metadata.py tests/test_feedback.py -v`

Expected: all tests pass; stable conversation metadata and feedback run IDs remain unchanged.

- [ ] **Step 5: Commit the server behavior change**

```bash
git add serve.py tests/test_serve_chat_metadata.py tests/test_feedback.py
git commit -m "fix(server): resume persisted conversation state"
```

---

### Task 4: Documentation and completion verification

**Files:**
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents: stable conversation restart behavior and explicit family-wide deletion semantics.

- [ ] **Step 1: Update session architecture documentation**

Add below the session-state table:

```markdown
Une conversation portant le même `chat_id` reprend ses DataFrames et alias
persistés après un redémarrage du serveur. Aucune requête ne réinitialise cet
état implicitement. La remise à zéro interne passe par
`clear_conversation(thread_id)`, qui supprime la clé active et toute sa famille
`thread_id:*`; `clear(key)` reste une suppression ciblée.
```

- [ ] **Step 2: Run focused verification**

Run: `pytest tests/test_session_store.py tests/test_session_store_pg.py tests/test_serve_chat_metadata.py tests/test_feedback.py -v`

Expected: all enabled tests pass; only PostgreSQL tests requiring an absent opt-in DSN may skip.

- [ ] **Step 3: Run full verification**

Run: `LANGCHAIN_TRACING_V2=false pytest tests/ -q`

Expected: zero failures. EcoTaxa live and PostgreSQL integration tests may remain skipped when their explicit environment variables are absent.

- [ ] **Step 4: Run static and repository checks**

```bash
python -m py_compile serve.py tools/session_store.py tools/session_store_pg.py
git diff --check
rg -n "_known_threads|default_store\.clear\(tid\)" serve.py tests
git status --short
```

Expected: compilation and diff checks exit zero; the search returns no obsolete implicit-reset references; only intended files are modified.

- [ ] **Step 5: Commit documentation**

```bash
git add ARCHITECTURE.md
git commit -m "docs: define conversation resume semantics"
```
