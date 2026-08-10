# Context Projection Campaign Design

Date: 2026-08-10
Status: approved design, pending implementation plan

## Goal

Create a deterministic, zero-network campaign that validates the exact context
projected to the model by IDEA. The campaign tests context construction only. It
does not evaluate model judgment, tool selection, scientific reasoning, or final
answer quality.

## Constraints

- Never call a hosted or local LLM.
- Never require an API key, network access, LangSmith, or paid credits.
- Exercise production context builders and middleware rather than duplicated
  rendering logic.
- Keep the original user message unchanged in checkpointed state.
- Report failures by context facet so a regression identifies the broken layer.
- Reuse the existing spy model and in-memory persistence from
  `scripts/dev/inspect_six_dataframe_context.py`.
- Do not add AgentEvals, Inspect AI, YAML, or another evaluation framework for
  this campaign.

## Scope

The campaign covers five projected context facets.

### 1. CURRENT TASK

Validate that:

- the current objective matches the latest user request;
- required deliverables are represented;
- the DataFrame selection contract is present;
- source preference is presented as a hint, not a restriction;
- a later turn replaces the current objective without rewriting history;
- CURRENT TASK precedes AVAILABLE DATAFRAMES.

### 2. AVAILABLE DATAFRAMES

Validate sessions containing one, six, and twenty-six DataFrames:

- every live DataFrame appears in the complete index;
- status, source, row count, and grain appear in the compact index;
- detailed cards contain description, grain, typed columns by role, schema
  visibility, keys, scope, filters, and lineage when available;
- an explicitly named DataFrame receives a detailed card;
- detailed cards remain bounded while the complete index remains complete;
- active status and recency do not remove alternatives or define a mandatory
  source;
- row values and large raw samples are not injected;
- the rendered block remains within its configured character budget.

### 3. EXPLORATION FRONTIER

Validate that:

- pending steps and their dependencies are visible;
- collected evidence is visible and bounded;
- unresolved data dependencies are visible;
- resolved dependencies disappear from active work;
- completed or irrelevant workflow state is not projected;
- frontier state follows AVAILABLE DATAFRAMES in the projected order.

### 4. LAST GRAPH

Validate that:

- verified rendering facts are projected after AVAILABLE DATAFRAMES;
- the graph-generation script and raw plotting payload are absent;
- graph facts survive into the next turn when still relevant;
- graph facts remain transient and do not alter the permanent system prompt or
  checkpointed user messages;
- LAST GRAPH precedes EXPLORATION FRONTIER.

### 5. HISTORY

Validate that:

- the current original user request is the final unchanged content block;
- `<application_turn_context>` is injected only into the provider-bound copy;
- synthetic context is not checkpointed as a user or system message;
- Human, AI, and Tool message chronology is preserved;
- old tool results are compacted according to configured limits;
- recent tool evidence required by the current turn remains intact;
- successive turns keep useful history while replacing transient CURRENT TASK.

## Architecture

Keep one production-faithful capture path:

```text
scenario fixture
  -> SessionStore + optional checkpoint/history/graph facts
  -> production middleware and context renderers
  -> local spy chat model
  -> exact model-bound messages
  -> deterministic facet validators
  -> terminal and JSON reports
```

The existing harness remains the source for DataFrame fixtures and model-bound
capture. New campaign code should separate three concerns:

1. scenario construction;
2. capture execution;
3. facet validation and reporting.

No validator may reconstruct the expected context with the same production
renderer it is testing. Validators assert externally observable contracts such
as required labels, ordering, visibility, absence, counts, and budgets.

## Campaign Interface

Provide one command with optional facet selection:

```bash
python scripts/dev/run_context_projection_campaign.py
python scripts/dev/run_context_projection_campaign.py --facet dataframes
python scripts/dev/run_context_projection_campaign.py --facet history --json
```

Default execution runs all five facets. Exit code is `0` only when every check
passes. Human output groups checks by facet and prints `PASS` or `FAIL`. JSON
output contains the scenario, facet, check name, status, and concise evidence.

## Scenario Set

The initial campaign includes:

1. one ordinary DataFrame;
2. six heterogeneous DataFrames with a misleading active table;
3. twenty-six DataFrames to exercise bounded expansion;
4. an explicit DataFrame reference;
5. a wide DataFrame with more than seventy columns;
6. pending, failed, and resolved frontier states;
7. graph facts in the producing turn and the following turn;
8. a multi-turn history containing Human, AI, and Tool messages;
9. old tool results that require compaction;
10. a clean conversation with no graph or frontier state.

## Failure Reporting

Each failure must identify:

- scenario ID;
- facet;
- violated contract;
- expected condition;
- observed concise evidence.

The report must not dump complete DataFrames, credentials, raw row values, or
the entire permanent system prompt.

## Success Criteria

- All initial scenarios execute without network access or model credentials.
- Each of the five facets has at least one positive and one absence/boundary
  check.
- Multi-turn scenarios use one in-memory checkpointer and stable `thread_id`.
- The campaign detects deliberate removal or misordering of each major context
  block.
- The existing full context harness remains runnable.
- No production behavior changes are required to introduce the campaign.

## Explicit Non-goals

- Determining whether a real LLM selects the best DataFrame.
- Scoring final prose or scientific interpretation.
- Enforcing one exact valid tool trajectory.
- Calling real source APIs or executing expensive exports.
- Replacing future, occasional real-model evaluations.
