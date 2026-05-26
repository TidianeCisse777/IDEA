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

## Test Levels

### 1. Unit and Integration Tests

Use these first. They do not call OpenAI or Langfuse.

```bash
pytest tests/test_copepod_plan_mode_eval_runner.py -q
pytest tests/test_copepod_session_artifacts_tools.py -q
pytest tests/test_session_routes.py -q
pytest tests/test_chat_stream_events.py -q
```

Recommended focused regression:

```bash
pytest \
  tests/test_copepod_plan_mode_eval_runner.py \
  tests/test_chat_stream_events.py \
  tests/test_session_routes.py::TestPostSessionMode::test_post_mode_copepod_analyse_requires_plan_ready_phase \
  tests/test_session_routes.py::TestPostSessionMode::test_post_mode_copepod_analyse_allowed_when_active_plan_artifacts_exist \
  -q
```

Expected result: all tests pass.

### 2. Mock Workflow Eval

Use this to test the full workflow with real backend tools but no live LLM.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --mock
```

Expected result: all workflow gates pass.

This is the default command before any live run.

### 3. Live Eval

Only run this when live API calls are intended.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse --model gpt-4o-mini
```

This calls OpenAI and pushes boolean scores to Langfuse.

Do not run `--live`, `--trace-smoke`, or `--push-langfuse` during local-only debugging.

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
- `live_plan_ready_enables_analyse_mode`

Interpretation:

- `live_llm_*` failures usually mean prompt or model behavior needs work.
- `live_backend_*` failures mean the application guard is broken and must be fixed first.
- `live_plan_ready_enables_analyse_mode` confirms the final transition works after validated artifacts exist.

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
