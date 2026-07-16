# Numeric Evidence Routing Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Replace the contradictory “pandas for every number” rule with a deterministic three-way numeric-evidence contract, then prove that an EcoTaxa specialized count is consumed without pandas.

**Architecture:** Keep this change in the model contract. A dedicated module owns one canonical prompt block, the system prompt injects it once, and deterministic tests enforce its three exclusive routes. No response-number parser or tool implementation changes are introduced.

**Tech Stack:** Python, pytest, LangChain/LangGraph prompt composition, existing harness replay utilities.

---

### Task 1: Make numeric evidence routing executable in the prompt

**Files:**
- Create: `agents/numeric_evidence_rules.py`
- Create: `tests/test_numeric_evidence_prompt.py`
- Modify: `agents/copepod_system_prompt.py`
- Modify: `tests/harness_redteam/test_source_and_prompt_contracts.py`

**Step 1: Write the failing prompt-contract tests**

Add tests that import `NUMERIC_EVIDENCE_RULES` and prove:

```python
assert COPEPOD_SYSTEM_PROMPT.count(NUMERIC_EVIDENCE_RULES) == 1
assert "specialized tool" in NUMERIC_EVIDENCE_RULES
assert "derived value" in NUMERIC_EVIDENCE_RULES
assert "report it as unknown" in NUMERIC_EVIDENCE_RULES
assert "Always call `run_pandas` to produce any numeric value" not in COPEPOD_SYSTEM_PROMPT
```

Keep the tests split by behavior: direct specialized evidence, derived table computation, and absent evidence.

**Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest -q tests/test_numeric_evidence_prompt.py tests/harness_redteam/test_source_and_prompt_contracts.py
```

Expected: failure because `agents.numeric_evidence_rules` does not exist and the old absolute rule is still present.

**Step 3: Implement the minimal canonical rule block**

Create `NUMERIC_EVIDENCE_RULES` with exactly these decisions:

```text
## Numeric Evidence Rules
- A numeric value already returned by a specialized tool is authoritative for that request. Use it directly with its provenance; do not call `run_pandas` only to reproduce it.
- Use `run_pandas` for a derived value: any new aggregation, transformation, metric, ratio, ranking, filter count, or statistic computed from a persisted table.
- If the requested numeric value is absent and no persisted structure can produce it, report it as unknown. Never estimate, infer, or invent it.
- Text visible only in conversation is not a calculable table. Materialize the required data first or state the limit.
```

Import and inject the constant once in `COPEPOD_SYSTEM_PROMPT`, replacing the old absolute pandas bullet. Remove the strict `xfail` marker from the red-team test without weakening its assertions.

**Step 4: Run the focused tests and verify GREEN**

Run the same focused pytest command. Expected: all tests pass and no XPASS remains.

**Step 5: Commit the implementation**

```bash
git add agents/numeric_evidence_rules.py agents/copepod_system_prompt.py tests/test_numeric_evidence_prompt.py tests/harness_redteam/test_source_and_prompt_contracts.py
git commit -m "feat: clarify numeric evidence routing"
```

### Task 2: Close the 4A gate with one controlled verification pass

**Files:**
- Modify: `docs/superpowers/specs/2026-07-15-numeric-evidence-routing-design.md`
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `BASELINE_HARNESS_2026-07-15.md`
- Modify: `HARNESS_REDTEAM_CONTRACTS_2026-07-15.md`

**Step 1: Run the targeted regression set once**

Run the prompt, source-policy, and EcoTaxa tool tests selected from the repository. Expected: all pass.

**Step 2: Run the complete suite once**

```bash
pytest -q
```

Expected: no failures and one fewer expected failure than the pre-4A baseline.

**Step 3: Regenerate the offline harness baseline once**

Use the repository's existing baseline command discovered from `IMPLEMENTATION_PLAN.md` or the harness documentation. Expected: level 1 and level 2 remain at 100%; record the new prompt-size metrics without rerunning.

**Step 4: Run one safe real-agent EcoTaxa smoke**

Use an isolated store, disable tracing, expose only safe read-only EcoTaxa tools plus `run_pandas`, and ask for a numeric value explicitly returned by a specialized count/summary tool. Verify from messages that:

```python
assert specialized_numeric_call_succeeded
assert "run_pandas" not in calls_after_specialized_result
assert heavy_tool_names.isdisjoint(visible_tool_names)
```

If the specialized tool fails or omits the requested number, report the smoke as inconclusive; do not rerun it automatically.

**Step 5: Update evidence documents**

Mark the design approved/implemented, close 4A in `IMPLEMENTATION_PLAN.md`, and record exact targeted/full-suite/baseline/smoke evidence in the existing harness documents. Do not mark 4B or 4C complete.

**Step 6: Verify the patch and commit documentation**

```bash
git diff --check
git status --short
git add docs/superpowers/specs/2026-07-15-numeric-evidence-routing-design.md IMPLEMENTATION_PLAN.md BASELINE_HARNESS_2026-07-15.md HARNESS_REDTEAM_CONTRACTS_2026-07-15.md
git commit -m "docs: close numeric evidence routing gate"
```
