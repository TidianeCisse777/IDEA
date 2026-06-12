# Persistent Multi-Dataset Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every downloaded dataset in one agent thread and expose stable explicit pandas variables while keeping latest-source aliases compatible.

**Architecture:** Extend `SessionStore` with prefix discovery across memory and disk. Route EcoPart, EcoTaxa, Amundsen, Bio-ORACLE, file, coupling, and SQL downloads through one dataset registry, inject all stable entries into data-tool execution environments, and let the EcoTaxa/EcoPart join select a project explicitly or fall back to the latest alias.

**Tech Stack:** Python 3.13, pandas, LangChain tools, pytest.

---

### Task 1: Discover Persisted Session Entries

**Files:**
- Modify: `tools/session_store.py`
- Test: `tests/test_session_store.py`

- [ ] **Step 1: Write the failing prefix-discovery tests**

Add tests that store `thread:ecopart:105`, `thread:ecopart:42`, and an unrelated key. Assert that `keys("thread:ecopart:")` returns only the two matching keys. Create a second `SessionStore` on the same temporary directory and assert it discovers both persisted keys.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_session_store.py -k "keys"
```

Expected: failure because `SessionStore.keys` does not exist.

- [ ] **Step 3: Implement prefix discovery**

Add:

```python
def keys(self, prefix: str | None = None) -> list[str]:
    keys = set(self._store)
    for meta_path in self._storage_dir.glob("*.json"):
        keys.add(meta_path.stem)
    if prefix is not None:
        keys = {key for key in keys if key.startswith(prefix)}
    return sorted(keys)
```

Ensure key persistence is reversible: persisted filenames must retain the original session key in metadata because `_safe_thread_id` replaces characters. Store an internal `session_key` field in metadata files and use it when discovering disk entries, without exposing it through returned session metadata.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_session_store.py
```

Expected: all session-store tests pass.

### Task 2: Preserve EcoPart Projects by ID

**Files:**
- Modify: `tools/ecopart_sources.py`
- Test: `tests/test_ecopart_sources.py`

- [ ] **Step 1: Write failing multi-project storage tests**

Invoke `query_ecopart` twice with mocked DataFrames for projects `105` and `42`. Assert:

```python
_store.get(f"{thread}:ecopart:105")["df"].equals(df_105)
_store.get(f"{thread}:ecopart:42")["df"].equals(df_42)
_store.get(f"{thread}:ecopart")["df"].equals(df_42)
_store.get(thread)["df"].equals(df_42)
```

Also assert the tool response names `df_ecopart_105` and `df_ecopart`.

- [ ] **Step 2: Run the test and verify RED**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_ecopart_sources.py -k "preserves_multiple"
```

Expected: project-specific entries are missing.

- [ ] **Step 3: Implement project-specific storage**

After download, write:

```python
meta = {"source": f"ecopart:{project_id}", "project_id": project_id, "n_rows": len(df)}
_store.set(thread_id, df, meta)
_store.set(f"{thread_id}:ecopart", df, meta)
_store.set(f"{thread_id}:ecopart:{project_id}", df, meta)
```

Update the success message to state that the DataFrame is available as both `df_ecopart_<project_id>` and `df_ecopart`.

- [ ] **Step 4: Run EcoPart source tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_ecopart_sources.py
```

Expected: all tests pass.

### Task 3: Expose Explicit DataFrame Variables

**Files:**
- Modify: `tools/data_tools.py`
- Test: `tests/test_data_tools.py`

- [ ] **Step 1: Write failing `run_pandas` test**

Store two project-specific DataFrames plus a latest alias, invoke:

```python
result = run_pandas.invoke({
    "code": "result = (len(df_ecopart_105), len(df_ecopart_42), len(df_ecopart))"
})
```

Assert the returned tuple proves all three variables are available and that `df_ecopart` is the latest project.

- [ ] **Step 2: Write failing `run_graph` environment test**

Execute graph code that reads `df_ecopart_105` and `df_ecopart_42` before creating a small figure. Assert a graph is returned rather than a `NameError`.

- [ ] **Step 3: Run both tests and verify RED**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_data_tools.py -k "multiple_ecopart"
```

Expected: `NameError` for project-specific variables.

- [ ] **Step 4: Implement one shared variable builder**

Add a helper that initializes existing named source aliases, then iterates:

```python
for key in store.keys(f"{thread_id}:ecopart:"):
    project_id = key.rsplit(":", 1)[-1]
    session = store.get(key)
    if project_id.isdigit() and session and session.get("df") is not None:
        local_vars[f"df_ecopart_{project_id}"] = session["df"]
```

Use the helper from both `run_pandas` and `run_graph` to avoid divergent environments. Update both tool docstrings with explicit-variable examples.

- [ ] **Step 5: Run data-tool tests and verify GREEN**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_data_tools.py
```

Expected: all tests pass.

### Task 4: Select an EcoPart Project for Joining

**Files:**
- Modify: `tools/ecopart_sources.py`
- Test: `tests/test_ecopart_sources.py`
- Modify: `agents/copepod_system_prompt.py`

- [ ] **Step 1: Write failing explicit-selection test**

Store one EcoTaxa DataFrame and EcoPart projects `105` and `42` with distinguishable values. Invoke:

```python
join_tool.invoke({"project_id": 105})
```

Assert the joined DataFrame contains project `105` values and metadata source `join:ecotaxa+ecopart:105`.

- [ ] **Step 2: Write failing default-selection and missing-project tests**

Assert `join_tool.invoke({})` uses `<thread>:ecopart`, and `join_tool.invoke({"project_id": 999})` returns an actionable message containing `query_ecopart(project_id=999)`.

- [ ] **Step 3: Run join tests and verify RED**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_ecopart_sources.py -k "join_ecotaxa_ecopart"
```

Expected: the tool schema rejects `project_id` or selects the wrong DataFrame.

- [ ] **Step 4: Implement project selection**

Change the signature to:

```python
def join_ecotaxa_ecopart(project_id: int | None = None) -> str:
```

Use `f"{thread_id}:ecopart:{project_id}"` when provided and the latest alias otherwise. Include the selected project ID in success metadata and text. Preserve the existing missing-EcoTaxa behavior.

- [ ] **Step 5: Update agent guidance**

Document that the agent should pass `project_id` when the user names a specific loaded EcoPart project, and omit it only when the latest project is intended.

- [ ] **Step 6: Run source and prompt-related tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_ecopart_sources.py tests/test_agent_factory.py
```

Expected: all tests pass.

### Task 5: Generalize Stable Downloads

**Files:**
- Create: `tools/dataset_registry.py`
- Test: `tests/test_dataset_registry.py`
- Modify: `tools/copepod_sources.py`
- Modify: `tools/amundsen_sources.py`
- Modify: `tools/bio_oracle_sources.py`
- Modify: `tools/data_tools.py`
- Modify: `tools/sql_workspace.py`
- Test: corresponding source and data-tool tests

- [ ] **Step 1: Test and implement normalized variable names**

Cover integer IDs, punctuation, filenames, stations, casts, and negative
coordinates. Implement `dataset_variable_name(source, *parts)`.

- [ ] **Step 2: Test and implement common persistence**

Implement `store_dataset` to update the current `df`, an optional latest-source
alias, and `<thread>:dataset:<variable_name>` with `variable_name` metadata.

- [ ] **Step 3: Route every download through the registry**

Use stable names for EcoTaxa projects, Amundsen dataset/profile queries,
Bio-ORACLE query identities, uploaded filenames, SQL output stems, and
Bio-ORACLE coupling hashes.

- [ ] **Step 4: Verify multiple downloads coexist**

For every source, load two distinct identities and assert both stable entries
remain while the source alias points to the latest.

### Task 6: Full Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run focused regression suite**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_session_store.py \
  tests/test_ecopart_sources.py \
  tests/test_data_tools.py \
  tests/test_agent_factory.py
```

- [ ] **Step 2: Run syntax and whitespace checks**

```bash
PYTHONPATH=. .venv/bin/python -m py_compile \
  tools/session_store.py tools/ecopart_sources.py tools/data_tools.py
git diff --check
```

- [ ] **Step 3: Run the complete test suite**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Expected: all tests pass, apart from explicitly documented pre-existing warnings.

- [ ] **Step 4: Review the final diff**

Confirm no unrelated files are staged or modified by this implementation and no temporary session artifacts remain.
