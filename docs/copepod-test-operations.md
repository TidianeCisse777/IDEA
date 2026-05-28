# Copepod Test Operations

This document explains how to test the Copepod context workflow, how to read Langfuse results, and how to diagnose common failures.

## Testing Philosophy

The context workflow must be tested as a process, not as a final answer.

The LLM is allowed to propose content, but the backend owns the workflow state:

1. Data Understanding draft is created.
2. User validates Data Understanding.
3. Data Understanding is activated.
4. Graph Context draft is created and linked to the active Data Understanding.
5. User validates Graph Context.
6. Graph Context is activated.
7. Only then can `[PLAN_READY]` expose Analyse Mode.

Tests must separate two questions:

- Did the LLM follow the protocol?
- Did the backend block unsafe behavior when the LLM drifted?

If the LLM fails but the backend blocks the action, the application is protected, but the prompt still needs improvement.

## Current State

As of 2026-05-28, the recommended baseline is:

- `--mock`: green
- `--live-du-only --push-langfuse`: green
- `--live-gc-only --push-langfuse`: green on the current pack
- `--live-online-mode --push-langfuse`: green on the current online-policy pack, including a fetch-to-derived-file scenario
- `--live`: still reserved for the final end-to-end workflow check
- `Mode En Ligne` policy is implemented and documented in [`docs/copepod-online-mode-policy.md`](./copepod-online-mode-policy.md)

Current GC-only scope:

- `rich`
- `poor`
- `offtopic`
- `analysis-jump`

`join` is intentionally out of the GC-only pack for now because it was producing a noisy signal relative to the rest of the workflow.

### Canonical test buckets

Use these pytest markers to avoid running the wrong suite:

- `workflow`: end-to-end plan/analyse lifecycle checks
- `tool_contract`: tool semantics, artifact contracts, and source interpretation
- `llm_protocol`: fake-LLM runner and prompt orchestration checks

Recommended routine pack before any live evaluation:

```bash
pytest -m "workflow or tool_contract" -q
```

Run `llm_protocol` only when changing the eval runner, prompt blocks, or LLM-facing orchestration:

```bash
pytest -m llm_protocol -q
```

Avoid running the full suite unless you are changing shared infrastructure or hunting a cross-cutting regression.

## Test Levels

### 1. Unit and Integration Tests

Use these first. They do not call OpenAI or Langfuse.

```bash
pytest -m "workflow or tool_contract" -q
```

Recommended focused regression:

```bash
pytest \
  tests/test_copepod_plan_mode_eval_runner.py \
  tests/test_copepod_plan_to_analyse_integration.py \
  tests/test_session_routes.py::TestPostSessionMode::test_post_mode_copepod_analyse_requires_active_plan_artifacts \
  tests/test_session_routes.py::TestPostSessionMode::test_post_mode_copepod_analyse_allowed_when_active_plan_artifacts_exist \
  -q
```

Expected result: all tests pass.

### How to add a new test without biasing production behavior

Use this decision order:

1. If the behavior must exist in production, change the prompt or backend first.
2. If the behavior is only there to make a test observable, keep it in the harness or scorecard.
3. Avoid test-only prompt injections that make the model behave differently from prod.
4. Prefer a single clear score over multiple overlapping scores for the same behavior.
5. If a scenario is noisy, remove it from the live pack instead of forcing the model to satisfy an overfitted check.

Practical rule:

- prompt change = production contract;
- harness change = test orchestration;
- score change = measurement only.

### Online mode policy checkpoints

When you add a new source or extend the online-mode policy:

1. Update [`docs/copepod-online-mode-policy.md`](./copepod-online-mode-policy.md) first.
2. Update the prompt wording in `agents/copepod_prompt.py` and the relevant mode block.
3. Keep the backend route and session state as the source of truth.
4. Update the UI only after the backend contract is stable.
5. Add one focused test for each layer instead of one large noisy end-to-end test.

### 2. Mock Workflow Eval

Use this to test the full workflow with real backend tools but no live LLM.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --mock
```

Expected result: all workflow gates pass.

This is the default command before any live run.

Implementation note:

- the eval harness stages fixtures directly into `static/eval-user/.../uploads`
- it does not depend on the HTTP `/upload` route during eval runs
- this keeps the workflow realistic while avoiding SlowAPI rate-limit noise

### 3. Live Eval

Only run this when live API calls are intended.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse
```

This uses `LLM_MODEL` from the environment, calls OpenAI, and pushes boolean scores to Langfuse.

Do not run `--live`, `--trace-smoke`, or `--push-langfuse` during local-only debugging.

### 3b. DU-Only Live Eval

Use this when you want the cheapest live signal for Data Understanding only.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live-du-only --push-langfuse
```

This mode:

- creates a DU draft
- waits for DU confirmation
- activates the DU
- checks `column_catalogue` and `coverage_assessment`
- stops before Graph Context, `[PLAN_READY]`, and Analyse Mode

It is the right preflight when you want to validate dataset comprehension without spending tokens on the full plan workflow.

Implementation note:

- fixtures are staged locally into the session upload directory before the first DU turn
- the harness avoids the HTTP upload rate limiter so the run stays deterministic

### 3c. GC-Only Live Eval

Use this when the DU is already active and you want to validate only the Graph Context phase and user-context handling.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live-gc-only --push-langfuse
```

This mode:

- seeds an active DU before the first user turn
- keeps Phase 1 disabled
- checks whether the model waits for user scientific context
- checks targeted questions when required fields are missing
- builds and activates Graph Context only after the user provides enough detail
- stops before Analyse Mode

It is the right preflight when you want to test graph-context behavior on rich, poor, off-topic, and direct-analysis prompts without paying for the full workflow.

Current live pack note:

- the active pack currently runs `rich`, `poor`, `offtopic`, and `analysis-jump`;
- `join` has been removed from the pack to keep the signal stable and to avoid overfitting the GC-only tests to one ambiguous case.

Current online-mode pack note:

- the active pack currently runs `online-off-explicit-request`, `online-on-incomplete-request`, `online-on-complete-request`, and `online-on-complete-request-fetch`;
- the fetch scenario checks that a complete Bio-ORACLE request can persist a derived CSV in the session uploads folder.

### Online Mode live-test checklist

Before the first real live online-source test, confirm:

1. `Mode En Ligne` is enabled in the UI.
2. The request names OGSL or Bio-ORACLE explicitly.
3. The request is complete enough to avoid a clarification round.
4. The selected source is listed in the allowlist returned by `/session/online-mode`.
5. The live trace shows the planner and, when appropriate, the fetch tool writing a derived CSV in the session uploads folder.

### 3d. Online-Mode Live Eval

Use this when you want to validate the explicit source-routing policy and the online/offline toggle.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live-online-mode --push-langfuse
```

This mode:

- renders the current `Mode En Ligne` state into the session metadata block;
- checks that disabled online mode does not silently call remote source tools;
- checks that explicit incomplete requests trigger a single targeted clarification;
- checks that explicit complete requests route through the source-planner helper instead of inventing a fetch path;
- records the trace and boolean scores in Langfuse for inspection by `session_key`.

Recommended live command for the end-to-end workflow:

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse
```

For source-specific live validation, turn on `Mode En Ligne` first, then send a single explicit request for OGSL or Bio-ORACLE in the UI.

Implementation note:

- fixtures are staged locally into the session upload directory before the first GC turn
- the harness does not call `/upload` for these evals, so the upload rate limit cannot interfere

## Important Scores

The main live scores are:

- `live_llm_created_data_understanding_draft`
- `live_llm_waited_for_data_understanding_confirmation`
- `live_llm_activated_data_understanding`
- `live_llm_created_graph_context_draft_linked_to_active_du`
- `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation`
- `live_backend_blocked_premature_plan_ready_button`
- `live_llm_waited_for_graph_context_confirmation`
- `live_llm_activated_graph_context`
- `live_du_payload_has_sufficient_coverage`
- `live_plan_ready_enables_analyse_mode`

The DU-only live mode uses:

- `live_du_only_created_data_understanding_draft`
- `live_du_only_waited_for_data_understanding_confirmation`
- `live_du_only_phase1_efficient`
- `live_du_only_payload_has_column_catalogue`
- `live_du_only_payload_has_sufficient_coverage`
- `live_du_only_describe_column_covered_all_unmatched`
- `live_du_only_activated_data_understanding`
- `live_du_only_no_graph_context_created`

The GC-only live mode uses:

- `gc_only_rich_created_graph_context_draft`
- `gc_only_rich_activated_graph_context`
- `gc_only_plan_ready_after_gc_activation`
- `gc_only_poor_asked_single_targeted_question_when_missing_fields`
- `gc_only_offtopic_asked_single_targeted_question_when_missing_fields`
- `gc_only_analysis-jump_refused_direct_analysis_request_before_gc`
- `gc_only_no_internal_terms_in_llm_text`

Interpretation:

- `live_llm_*` failures usually mean prompt or model behavior needs work.
- `live_backend_*` failures mean the application guard is broken and must be fixed first.
- `live_du_payload_has_sufficient_coverage` means the DU summary did not reach the minimum coverage threshold and the Phase 1 analysis should be improved before live runs.
- `live_plan_ready_enables_analyse_mode` confirms the final transition works after validated artifacts exist.
- `gc_only_*` failures usually mean the model is not waiting for user context, is reopening Phase 1, or is skipping the Graph Context validation step.

## Checking Results In Langfuse

After a live run, the script prints a Langfuse trace URL when available.

Use the trace to inspect:

- `session_key`: groups all eval steps for one run.
- generations: each LLM phase and model output.
- scores: boolean gate results.
- tool outputs: whether artifacts were created, activated, or blocked.

The most useful debug pattern:

1. Open the trace URL.
2. Find the first failed score.
3. Inspect the LLM message just before the failure.
4. Inspect the tool result or route response.
5. Classify the failure as prompt drift, backend guard failure, or scientific context gap.

## Common Failures

### 404 With Langfuse OTEL

Likely cause: Langfuse SDK v4 is talking to a Langfuse v2 server.

Fix used locally:

```bash
pip install langfuse==2.60.3
```

The project dependency should stay pinned to the Langfuse v2-compatible SDK while the local Docker service uses `langfuse/langfuse:2`.

### Langfuse Host Uses Docker Service Name

If `.env` contains `http://langfuse:3000`, scripts running from the host shell may not reach it.

Local fallback uses:

```text
http://localhost:3001
```

Check that Langfuse is reachable before live evaluation.

### `2/7` Or Low Live Score

This means the LLM did not follow the full workflow.

Typical causes:

- it emitted `[PLAN_READY]` before Graph Context validation;
- it activated an artifact before user confirmation;
- it created Graph Context without linking the active Data Understanding;
- it skipped a tool call and only wrote text.

Fix order:

1. Confirm backend guard scores pass.
2. Improve the Plan Mode prompt.
3. Re-run the same eval and compare scores.

### Analyse Mode Opens Too Early

This is a backend bug.

Analyse Mode must require both:

- active Data Understanding and active Graph Context;
- backend phase equals `plan_ready`.

Relevant tests:

```bash
pytest tests/test_session_routes.py::TestPostSessionMode::test_post_mode_copepod_analyse_requires_plan_ready_phase -q
pytest tests/test_chat_stream_events.py -q
```

### Pytest Prints Passed But Process Hangs

Observed cause: background tracing or teardown work can keep the process alive after pytest prints the summary.

If the output already shows `100%` and all tests passed, verify no real eval is running before killing the lingering pytest process.

## Analyse, Evaluation, Fix Loop

Use this loop for every workflow improvement:

1. Analyse: identify the first failed score or failing test.
2. Evaluation: reproduce with the smallest local command, preferably pytest or `--mock`.
3. Fix: change the owning layer only.
4. Regression: rerun the same command.
5. Langfuse: run live and push scores only when explicitly intended.

Do not treat prompt changes as sufficient if backend guards fail. The backend must make invalid workflow transitions impossible.
