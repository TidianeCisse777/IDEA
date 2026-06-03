# Copepod DU-Only Live Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live eval mode that stops after Data Understanding creation, activation, and Langfuse push, without entering Graph Context or Analyse Mode.

**Architecture:** Extend the existing eval runner with a narrow DU-only path that reuses the current upload, inspection, role inference, DU artifact, and Langfuse plumbing. Keep the full `--live` workflow unchanged so the new mode stays small, cheap, and easy to reason about. The new mode should expose only the minimum checks needed to validate that DU exploration is solid before any token-heavy graph planning runs.

**Tech Stack:** Python, pytest, FastAPI test client, Langfuse SDK, existing Copepod tool registry and session store.

---

### Task 1: Add a DU-only live runner path

**Files:**
- Modify: `scripts/evals/run_copepod_plan_mode_eval.py`
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_live_du_only_runner_stops_after_data_understanding(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "fake-live-model")
    report = run_live_du_only_eval(push_langfuse=False)

    assert report["mode"] == "live-du-only"
    assert report["passed"] is True
    scores = {item["name"]: item for item in report["results"]}
    assert scores["live_du_only_created_data_understanding_draft"]["passed"] is True
    assert scores["live_du_only_activated_data_understanding"]["passed"] is True
    assert scores["live_du_only_payload_has_column_catalogue"]["passed"] is True
    assert scores["live_du_only_payload_has_sufficient_coverage"]["passed"] is True
    assert "live_du_only_created_graph_context_draft" not in scores
    assert "live_du_only_plan_ready_enables_analyse_mode" not in scores
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_du_only_runner_stops_after_data_understanding -q
```

Expected: fail because `run_live_du_only_eval` does not exist yet.

- [ ] **Step 3: Implement the minimal DU-only runner**

```python
def run_live_du_only_eval(*, push_langfuse: bool = False) -> dict:
    store = InMemorySessionStore()
    tools = _load_tools()
    session_id = f"eval-{uuid.uuid4().hex[:10]}"
    session_key = f"eval-user:{session_id}:copepod"
    results: list[dict] = []

    client, stack = _test_client(store)
    with stack:
        upload = _upload_fixture(client, session_id, ECOTAXA)
        uploaded_ecotaxa = _uploaded_path(session_id, upload["filename"])
        du_artifact = _data_understanding_artifact(tools, uploaded_ecotaxa)
        du_draft = tools["create_data_understanding_draft"](session_key, du_artifact)

        results.append(_result(
            "live_du_only_created_data_understanding_draft",
            du_draft["status"] == "draft",
            f"Data Understanding draft {du_draft['version_id']} created.",
            {"case_type": "live", "version_id": du_draft["version_id"]},
        ))

        du_payload = du_draft.get("payload") or {}
        results.append(_result(
            "live_du_only_payload_has_column_catalogue",
            bool(du_payload.get("column_catalogue")),
            f"DU payload contains {len(du_payload.get('column_catalogue') or [])} column_catalogue entries.",
            {"case_type": "edge"},
        ))

        coverage_assessment = du_payload.get("coverage_assessment") or {}
        results.append(_result(
            "live_du_only_payload_has_sufficient_coverage",
            coverage_assessment.get("status") == "sufficient",
            f"DU coverage status is {coverage_assessment.get('status')!r}.",
            {"case_type": "edge", "coverage": coverage_assessment},
        ))

        du_active = tools["activate_data_understanding"](session_key, du_draft["version_id"])
        results.append(_result(
            "live_du_only_activated_data_understanding",
            du_active.get("status") == "active"
            and tools["get_active_data_understanding"](session_key)["version_id"] == du_active["version_id"],
            f"Data Understanding active version is {du_active.get('version_id')}.",
            {"case_type": "live", "version_id": du_active.get("version_id")},
        ))

    trace_url = None
    if push_langfuse:
        trace_url = "Langfuse push handled by the same eval trace helper used in run_live_eval."

    passed_count = sum(1 for result in results if result["passed"])
    report = {
        "dataset": DATASET_NAME,
        "mode": "live-du-only",
        "model": settings.LLM_MODEL,
        "session_id": session_id,
        "session_key": session_key,
        "passed": passed_count == len(results),
        "passed_count": passed_count,
        "total_count": len(results),
        "results": results,
        "langfuse_trace_url": trace_url,
    }
    return report
```

- [ ] **Step 4: Run the test and confirm it passes**

Run:

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py::test_live_du_only_runner_stops_after_data_understanding -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/evals/run_copepod_plan_mode_eval.py tests/test_copepod_plan_mode_eval_runner.py
git commit -m "feat: add du-only live eval mode"
```

### Task 2: Wire the CLI flag and reporting path

**Files:**
- Modify: `scripts/evals/run_copepod_plan_mode_eval.py`
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_dispatches_du_only_mode(monkeypatch):
    import sys

    calls = {"du_only": 0, "live": 0, "mock": 0}

    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_du_only_eval",
        lambda **kwargs: calls.__setitem__("du_only", calls["du_only"] + 1) or {
            "dataset": DATASET_NAME,
            "mode": "live-du-only",
            "passed": True,
            "passed_count": 1,
            "total_count": 1,
            "results": [],
            "langfuse_trace_url": None,
        },
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_live_eval",
        lambda **kwargs: calls.__setitem__("live", calls["live"] + 1) or None,
    )
    monkeypatch.setattr(
        "scripts.evals.run_copepod_plan_mode_eval.run_mock_eval",
        lambda **kwargs: calls.__setitem__("mock", calls["mock"] + 1) or None,
    )
    monkeypatch.setattr(sys, "argv", ["run_copepod_plan_mode_eval.py", "--live-du-only"])

    assert main() == 0
    assert calls == {"du_only": 1, "live": 0, "mock": 0}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py -k "du_only and cli" -q
```

Expected: fail because the CLI flag is not wired yet.

- [ ] **Step 3: Implement the routing**

```python
parser.add_argument("--live-du-only", action="store_true", help="Run live eval only through Data Understanding.")

if args.live_du_only:
    report = run_live_du_only_eval(push_langfuse=args.push_langfuse)
elif args.trace_smoke:
    report = run_langfuse_trace_smoke(prompt=args.prompt)
elif args.live:
    report = run_live_eval(push_langfuse=args.push_langfuse)
else:
    report = run_mock_eval(push_langfuse=args.push_langfuse)
```

- [ ] **Step 4: Run the targeted test and confirm it passes**

Run:

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py -k "du_only and cli" -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/evals/run_copepod_plan_mode_eval.py tests/test_copepod_plan_mode_eval_runner.py
git commit -m "feat: wire du-only eval cli"
```

### Task 3: Document the new testing scope

**Files:**
- Modify: `docs/copepod-test-operations.md`
- Modify: `docs/copepod-plan-mode-eval-coverage.md`

- [ ] **Step 1: Write the failing doc expectation**

```markdown
Add a DU-only live eval section that explains:
- it stops after Data Understanding
- it is the cheapest live test
- it is the recommended live preflight before full plan-mode live runs
```

- [ ] **Step 2: Update the docs**

```markdown
## DU-Only Live Eval

Run this when you want to validate Data Understanding only:

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live-du-only --push-langfuse
```

This mode verifies:
- DU draft creation
- DU activation
- `column_catalogue` presence
- `coverage_assessment.status == "sufficient"`

It does not create Graph Context, emit `[PLAN_READY]`, or enable Analyse Mode.
```

- [ ] **Step 3: Review the doc diff for consistency**

Confirm the new mode is described as a narrow preflight, not a replacement for the full live eval.

- [ ] **Step 4: Commit**

```bash
git add docs/copepod-test-operations.md docs/copepod-plan-mode-eval-coverage.md
git commit -m "docs: add du-only live eval guidance"
```

### Task 4: Run the minimal verification set

**Files:**
- Modify: none
- Test: `tests/test_copepod_plan_mode_eval_runner.py`

- [ ] **Step 1: Run the DU-only tests**

Run:

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py -q
```

Expected: all plan mode runner tests pass, including the new DU-only assertions.

- [ ] **Step 2: Run the safe pack**

Run:

```bash
pytest -m "workflow or tool_contract" -q
```

Expected: pass, with no live API calls.

- [ ] **Step 3: Commit any last verification-only changes**

```bash
git add tests/test_copepod_plan_mode_eval_runner.py
git commit -m "test: lock du-only live eval contract"
```
