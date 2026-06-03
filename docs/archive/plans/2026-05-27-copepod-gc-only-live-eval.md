# Copepod GC-Only Live Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live GC-only eval mode that starts from an already active Data Understanding and validates how the model waits for scientific context, asks targeted questions, and activates Graph Context without reopening Phase 1.

**Architecture:** Reuse the existing eval runner, session store, Langfuse trace handling, and tool registry. Add a dedicated GC-only runner that seeds an active DU before the first user turn, then exercises Phase 2 behavior across rich, poor, off-topic, and adversarial prompts. Keep the contract testable with fake completions and a small set of focused live assertions.

**Tech Stack:** Python, pytest, FastAPI TestClient, in-memory session store, Langfuse eval tracing, existing copepod tool registry.

---

### Task 1: Add GC-only seeding and runner plumbing

**Files:**
- Modify: `scripts/evals/run_copepod_plan_mode_eval.py`
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_dispatches_gc_only_mode(monkeypatch):
    import sys

    calls = {"gc_only": 0, "du_only": 0, "live": 0, "mock": 0}

    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_gc_only_eval",
        lambda **kwargs: calls.__setitem__("gc_only", calls["gc_only"] + 1) or {
            "dataset": "copepod-plan-mode-v1",
            "mode": "live-gc-only",
            "passed": True,
            "passed_count": 1,
            "total_count": 1,
            "results": [],
            "langfuse_trace_url": None,
        },
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_du_only_eval",
        lambda **kwargs: calls.__setitem__("du_only", calls["du_only"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_eval",
        lambda **kwargs: calls.__setitem__("live", calls["live"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_mock_eval",
        lambda **kwargs: calls.__setitem__("mock", calls["mock"] + 1) or None,
    )
    monkeypatch.setattr(sys, "argv", ["run_copepod_plan_mode_eval.py", "--live-gc-only"])

    assert main() == 0
    assert calls == {"gc_only": 1, "du_only": 0, "live": 0, "mock": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_copepod_plan_mode_eval_runner.py::test_cli_dispatches_gc_only_mode -v`
Expected: FAIL because `run_live_gc_only_eval` and the CLI flag are not implemented yet.

- [ ] **Step 3: Write minimal implementation**

```python
def run_live_gc_only_eval(*, push_langfuse=False, completion_fn=None) -> dict:
    ...

parser.add_argument("--live-gc-only", action="store_true", help="Run live LLM evals through Graph Context only.")
...
if args.live_gc_only:
    report = run_live_gc_only_eval(push_langfuse=args.push_langfuse)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_copepod_plan_mode_eval_runner.py::test_cli_dispatches_gc_only_mode -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/evals/run_copepod_plan_mode_eval.py tests/test_copepod_plan_mode_eval_runner.py
git commit -m "feat: add gc-only eval mode plumbing"
```

### Task 2: Seed an active DU before GC-only evaluation

**Files:**
- Modify: `scripts/evals/run_copepod_plan_mode_eval.py`
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.llm_protocol
def test_live_gc_only_runner_starts_from_active_du(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    calls = {"count": 0}

    def fake_completion(*, messages, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": []}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Question ciblée."}}]}

    report = run_live_gc_only_eval(push_langfuse=False, completion_fn=fake_completion)

    assert report["mode"] == "live-gc-only"
    assert report["passed"] is True
    assert calls["count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_runner_starts_from_active_du -v`
Expected: FAIL because the GC-only runner does not exist yet and no DU seeding occurs.

- [ ] **Step 3: Write minimal implementation**

```python
def _seed_active_du_for_session(store, tools, session_key, session_id, path):
    ...

def run_live_gc_only_eval(...):
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"gc-only-eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    ...
    _seed_active_du_for_session(store, tools, session_key, session_id, ECOTAXA)
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_runner_starts_from_active_du -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/evals/run_copepod_plan_mode_eval.py tests/test_copepod_plan_mode_eval_runner.py
git commit -m "feat: seed active du for gc-only eval"
```

### Task 3: Add GC-only behavior checks for context completion and refusal

**Files:**
- Modify: `scripts/evals/run_copepod_plan_mode_eval.py`
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.llm_protocol
def test_live_gc_only_asks_single_targeted_question_when_context_is_poor(monkeypatch):
    ...
    assert scores["gc_only_asked_single_targeted_question_when_missing_fields"]["passed"] is True
    assert scores["gc_only_never_reopened_phase1"]["passed"] is True

@pytest.mark.llm_protocol
def test_live_gc_only_refuses_direct_analysis_request_before_gc(monkeypatch):
    ...
    assert scores["gc_only_refused_direct_analysis_request_before_gc"]["passed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
`pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_asks_single_targeted_question_when_context_is_poor -v`
`pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_refuses_direct_analysis_request_before_gc -v`
Expected: FAIL because the GC-only scoring and prompt flow are not implemented yet.

- [ ] **Step 3: Write minimal implementation**

```python
gc_prompt = (
    "Un DU actif est déjà disponible. "
    "Do not call Phase 1 tools. "
    "First call get_active_data_understanding(session_key). "
    "Ask at most one targeted question when a mandatory GC field is missing. "
    "Never emit [PLAN_READY] before activate_graph_context succeeds."
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
`pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_asks_single_targeted_question_when_context_is_poor -v`
`pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_gc_only_refuses_direct_analysis_request_before_gc -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/evals/run_copepod_plan_mode_eval.py tests/test_copepod_plan_mode_eval_runner.py
git commit -m "feat: add gc-only context behavior checks"
```

### Task 4: Document the new GC-only eval mode

**Files:**
- Modify: `docs/copepod-test-operations.md`
- Modify: `docs/copepod-plan-mode-eval-coverage.md`
- Modify: `docs/copepod-gc-only-live-eval.md`

- [ ] **Step 1: Write the failing documentation assertions**

No automated test is required here; validate by reading the diff and checking the new mode is described consistently.

- [ ] **Step 2: Update docs**

Add the new CLI mode, its purpose, its scenarios, and the no-live-without-explicit-approval rule.

- [ ] **Step 3: Review docs for consistency**

Confirm:
- `--live-gc-only` is listed alongside the other eval modes;
- the DU-only and GC-only scopes are clearly separated;
- the GC-only doc matches the actual runner behavior.

- [ ] **Step 4: Commit**

```bash
git add docs/copepod-test-operations.md docs/copepod-plan-mode-eval-coverage.md docs/copepod-gc-only-live-eval.md
git commit -m "docs: add gc-only eval mode guidance"
```
