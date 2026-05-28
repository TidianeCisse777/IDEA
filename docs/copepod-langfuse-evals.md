# Copepod Langfuse Evals

This application should evaluate the Plan Mode context workflow as a process, not only as a final text answer.

## Recommended First Approach

Use deterministic workflow-gate evaluations for the context phase.

Why:
- The critical behavior is structural: the LLM must create a Data Understanding draft, wait for validation, activate it, create a Graph Context draft linked to the active Data Understanding, wait for validation, activate it, then emit `[PLAN_READY]`.
- The backend now owns the phase state. A premature or stale LLM action must return a blocking result instead of silently advancing the workflow.
- These checks are stable and can run in CI or locally without needing an LLM judge.
- Scores are easy to inspect in Langfuse because each gate maps to a boolean score.

Run:

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --mock
python scripts/evals/run_copepod_plan_mode_eval.py --live --push-langfuse
python scripts/evals/run_copepod_plan_mode_eval.py --live-online-mode --push-langfuse
```

The live eval uses `LLM_MODEL` from the environment.

Do not run `--live`, `--trace-smoke`, or `--push-langfuse` unless live OpenAI and Langfuse calls are intended.

## Analysis, Evaluation, Fix Loop

1. Analyse failed scores in Langfuse and group them by failure type:
   - LLM protocol drift: the model emitted `[PLAN_READY]`, activated an artifact, or created Graph Context before confirmation.
   - Backend guard failure: a premature action exposed Analyse or changed active artifacts.
   - Scientific context gap: the Data Understanding or Graph Context is structurally valid but scientifically incomplete.
2. Evaluate locally first with `--mock` and pytest. This confirms backend gates and common edge cases without API calls.
3. Run the live eval only on explicit signal. Push boolean scores to Langfuse and inspect the trace by `session_key`.
4. Fix the smallest layer that owns the failure:
   - Prompt fix when the backend blocked the action but the LLM still drifted.
   - Tool or route fix when a blocked action changed state or exposed Analyse.
   - Evaluation fixture or judge rubric fix when the failure is scientific quality rather than workflow order.
5. Re-run the same eval and compare score deltas. A fix is accepted only when the failed gate becomes green and no existing gate regresses.

## Evaluation Methods

### 1. Workflow Gates

Use for the current context phase.

Scores:
- `live_llm_created_data_understanding_draft`
- `live_llm_waited_for_data_understanding_confirmation`
- `live_llm_activated_data_understanding`
- `live_llm_created_graph_context_draft_linked_to_active_du`
- `live_llm_did_not_emit_plan_ready_before_graph_context_confirmation`
- `live_backend_blocked_premature_plan_ready_button`
- `live_llm_waited_for_graph_context_confirmation`
- `live_llm_activated_graph_context`
- `live_plan_ready_enables_analyse_mode`

Decision rule:
- Block release if any gate fails.
- If only an LLM protocol score fails and the backend guard score passes, the workflow is protected but the prompt still needs improvement before release.

### 2. Human Annotation

Use when the structure passes but scientific quality is uncertain.

Annotate:
- column-role correctness
- taxonomic interpretation correctness
- feasibility assessment correctness
- blocker quality
- whether the graph context is scientifically sufficient

Decision rule:
- Use a small labelled set first, then convert recurrent failures into workflow gates or judge prompts.

### 3. LLM-as-a-Judge

Use after human labels exist.

Good targets:
- "Does the Data Understanding correctly explain the source type and key columns?"
- "Does the Graph Context include all mandatory fields?"
- "Are blockers explicit and actionable?"

Do not use this first for release gating. Calibrate the judge against human-labelled examples before trusting it.

### 4. Online Mode Policy Checks

Use this when the prompt/runtime policy around OGSL and Bio-ORACLE needs to be validated.

```bash
python scripts/evals/run_copepod_plan_mode_eval.py --live-online-mode --push-langfuse
```

What it checks:

- `Mode En Ligne` is visible in the rendered session metadata.
- Disabled online mode does not silently call remote source tools.
- Explicit incomplete requests trigger a single targeted clarification.
- Explicit complete requests route through the source-planner helper instead of inventing a fetch path.
- Scores and trace are written to Langfuse for inspection by `session_key`.

## Langfuse Setup Notes

The live runner uses:
- LiteLLM callbacks for LLM traces when `--push-langfuse` is enabled and `LANGFUSE_PUBLIC_KEY` is set.
- Boolean Langfuse scores for each workflow gate.
- `session_key` as the Langfuse session identifier, so all live eval steps can be inspected together.

The installed Langfuse skill is available at:

```text
~/.codex/skills/langfuse
```

Restart Codex to pick up the new skill automatically in future sessions.
