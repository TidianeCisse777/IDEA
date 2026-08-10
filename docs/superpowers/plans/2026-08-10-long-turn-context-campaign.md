# Long-Turn Context Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the offline context-projection campaign with real checkpointed conversations that validate context stability, compaction, dynamic resources, graph facts, frontier state, and thread isolation over many turns.

**Architecture:** Reuse the production `create_agent` middleware stack, a local scripted chat model, `MemorySaver`, `InMemoryStore`, and temporary `SessionStore`. Add one generic checkpointed projection runner to the existing campaign script, then build deterministic long-turn and isolation scenarios over its captured model requests. No production module changes and no external evaluation framework are required.

**Tech Stack:** Python 3, LangChain `create_agent`, LangGraph `MemorySaver`/`InMemoryStore`, existing `_SpyChatModel`, existing context middleware, pandas fixtures, argparse, JSON.

## Global Constraints

- Never call a hosted or local LLM.
- Never require an API key, network access, LangSmith, or paid credits.
- Do not execute data, source, RAG, graph, or export tools in this campaign.
- Exercise the production context middleware rather than duplicating renderers.
- Preserve original checkpointed Human messages exactly.
- Keep the permanent system message byte-stable across all turns.
- Report failures with scenario, turn, violated contract, and bounded evidence.
- Keep the existing five projection facets and the original full harness runnable.
- Do not modify runtime behavior to make the harness pass.

---

### Task 1: Add a reusable checkpointed context capture runner

**Files:**
- Modify: `scripts/dev/run_context_projection_campaign.py`

**Interfaces:**
- Consumes: `SessionStore`, `ModelCapture`, `_SpyChatModel`, `build_tool_catalog`, `ExplorationStateMiddleware`, `agent._ContextMiddleware`, `IdeaAgentState`.
- Produces: `TurnSnapshot`, `CheckpointedProjectionSession`, and the convenience
  wrapper `run_checkpointed_projection(...)` for every long-turn scenario.

- [ ] **Step 1: Add the new facet names before implementation**

```python
FACETS = (
    "current_task", "dataframes", "frontier", "graph", "history",
    "long_turns", "thread_isolation",
)
```

- [ ] **Step 2: Run the missing campaign to verify the red state**

Run:

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Expected: non-zero exit because `CAMPAIGNS` does not implement `long_turns`.

- [ ] **Step 3: Add the checkpoint snapshot type**

```python
from dataclasses import replace
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

import agent as agent_module
from agents.exploration_middleware import ExplorationStateMiddleware
from agents.exploration_state import IdeaAgentState
from scripts.dev.inspect_six_dataframe_context import (
    _SpyChatModel,
    _capture_from_model_call,
)
from tools.tool_catalog import build_tool_catalog


@dataclass(frozen=True)
class TurnSnapshot:
    thread_id: str
    turn: int
    question: str
    capture: ModelCapture
    checkpoint_messages: tuple[BaseMessage, ...]
```

- [ ] **Step 4: Add a persistent one-thread session and a sequence wrapper**

Implement:

```python
TurnMutation = Callable[
    [int, SessionStore, Any, dict[str, Any]],
    None,
]

class CheckpointedProjectionSession:
    def __init__(
        self,
        store: SessionStore,
        thread_id: str,
        *,
        response_count: int,
        answer_chars: int = 0,
    ) -> None:
        self.store = store
        self.thread_id = thread_id
        self.turn = 0
        suffix = "R" * max(0, answer_chars)
        responses = [
            AIMessage(content=f"Offline response {index:03d}. {suffix}")
            for index in range(1, response_count + 1)
        ]
        self.spy = _SpyChatModel(responses=responses)
        with patch("tools.session_store.default_store", store):
            catalog = build_tool_catalog(thread_id)
            self.graph = create_agent(
                self.spy,
                list(catalog.tools),
                system_prompt=agent_module._SYSTEM_PROMPT,
                middleware=[
                    ModelCallLimitMiddleware(
                        run_limit=agent_module._MAX_MODEL_CALLS_PER_TURN,
                        exit_behavior="end",
                    ),
                    ExplorationStateMiddleware(thread_id=thread_id),
                    agent_module._ContextMiddleware(
                        user_id="context-campaign",
                        thread_id=thread_id,
                        catalog_names=catalog.names,
                    ),
                ],
                state_schema=IdeaAgentState,
                checkpointer=MemorySaver(),
                store=InMemoryStore(),
            )
        self.config: dict[str, Any] = {
            "configurable": {"thread_id": thread_id}
        }

    def invoke(
        self,
        question: str,
        *,
        mutate_before: TurnMutation | None = None,
    ) -> TurnSnapshot:
        self.turn += 1
        self.spy.current_turn = self.turn
        if mutate_before is not None:
            mutate_before(
                self.turn,
                self.store,
                self.graph,
                self.config,
            )
        calls_before = len(self.spy.calls)
        message = HumanMessage(
            content=question,
            id=f"{self.thread_id}-human-{self.turn:03d}",
        )
        with patch("tools.session_store.default_store", self.store):
            result = self.graph.invoke(
                {"messages": [message]},
                config=self.config,
            )
        new_calls = self.spy.calls[calls_before:]
        if len(new_calls) != 1:
            raise AssertionError(
                f"Expected one model call on turn {self.turn}, got {len(new_calls)}"
            )
        checkpoint_messages = tuple(result.get("messages") or ())
        capture = replace(
            _capture_from_model_call(new_calls[0]),
            audit=agent_module.get_context_audit(self.thread_id),
            state_messages=checkpoint_messages,
            turn=self.turn,
        )
        return TurnSnapshot(
            thread_id=self.thread_id,
            turn=self.turn,
            question=question,
            capture=capture,
            checkpoint_messages=checkpoint_messages,
        )

def run_checkpointed_projection(
    store: SessionStore,
    thread_id: str,
    questions: Sequence[str],
    *,
    answer_chars: int = 0,
    mutate_before_turn: TurnMutation | None = None,
) -> list[TurnSnapshot]:
    session = CheckpointedProjectionSession(
        store,
        thread_id,
        response_count=len(questions),
        answer_chars=answer_chars,
    )
    return [
        session.invoke(question, mutate_before=mutate_before_turn)
        for question in questions
    ]
```

`CheckpointedProjectionSession` must own one `_SpyChatModel`, one production
agent, one `MemorySaver`, one `InMemoryStore`, one stable `thread_id`, and its
current turn counter. `invoke(...)` increments the counter, calls the optional
mutation with `(turn, store, graph, config)` immediately before invoking the
graph, converts the new spy call with `_capture_from_model_call`, and attaches
`result["messages"]` to the returned snapshot. Patch
`tools.session_store.default_store` to the temporary store while the session is
invoked. Fake responses are text-only and never contain tool calls.

`run_checkpointed_projection(...)` is a thin convenience wrapper: construct one
session with `response_count=len(questions)`, invoke each question in order, and
return the snapshots. This makes sequential campaigns concise while allowing
the isolation campaign to interleave two persistent sessions explicitly.

- [ ] **Step 5: Add and run a three-turn smoke scenario**

```python
questions = (
    "Tour 01 — inspecte les ressources.",
    "Tour 02 — résume les DataFrames.",
    "Tour 03 — rappelle la demande courante.",
)
```

Run:

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Expected: three snapshots, three checkpointed Human messages at turn 3, no
network or LangSmith warning.

---

### Task 2: Add the fifty-turn checkpoint stability campaign

**Files:**
- Modify: `scripts/dev/run_context_projection_campaign.py`

**Interfaces:**
- Consumes: `run_checkpointed_projection(...)`, `seed_six_dataframes(...)`, `store_dataset(...)`.
- Produces: `campaign_long_turns(store: SessionStore) -> list[CampaignCheck]`.

- [ ] **Step 1: Define the deterministic turn sequence**

```python
LONG_TURN_COUNT = 50
PENDING_WINDOW_QUESTION = (
    "Tours 20–25 — reprends la même analyse avec la dépendance en cours."
)

def _long_turn_questions(count: int = LONG_TURN_COUNT) -> tuple[str, ...]:
    return tuple(
        PENDING_WINDOW_QUESTION
        if 20 <= turn <= 25
        else f"Tour {turn:02d} — décris les ressources pertinentes pour l’analyse {turn}."
        for turn in range(1, count + 1)
    )
```

Turns outside the pending window remain unique. Turns 20–25 deliberately use
the same exact question and therefore the same exploration fingerprint: the
production middleware starts a new exploration run when the user objective
changes, so changing the question during this window would test legitimate
reset behavior rather than pending-frontier persistence.

- [ ] **Step 2: Add controlled session mutations**

Implement `_mutate_long_turn_context(...)` through a closure with this timeline:

- turn 5: persist `last_graph_grounding` with `LONG_TURN_GRAPH_FACT`;
- turn 10: add `df_long_turn_added` with `sample_id`, `station`, `value`, plus
  complete description, grain, primary key, and source metadata;
- turn 20: create a pending payload with
  `build_frontier_payload(store, thread_id, PENDING_WINDOW_QUESTION)` and call
  `graph.update_state(config, {"exploration": pending_payload})`;
- turn 25: resolve the same payload with `resolve_frontier_payload(...)` and
  update the checkpoint;
- never rewrite the permanent prompt or prior messages.

- [ ] **Step 3: Run fifty real turns**

```python
snapshots = run_checkpointed_projection(
    store,
    thread_id,
    _long_turn_questions(),
    answer_chars=800,
    mutate_before_turn=mutation,
)
```

- [ ] **Step 4: Add stability invariants**

Assert:

```python
len(snapshots) == 50
len({snapshot.capture.system for snapshot in snapshots}) == 1
all(snapshot.capture.exact_user_request == snapshot.question for snapshot in snapshots)
all(f"Objective: {snapshot.question}" in snapshot.capture.task_context for snapshot in snapshots)
```

Also check:

- checkpoint Human counts are 1, 10, 25, and 50 at those turns;
- no checkpointed message contains `<application_turn_context>`;
- provider-bound context appears exactly once, on the current Human message;
- `df_long_turn_added` is absent at turn 9 and present from turn 10;
- graph facts are absent at turn 4 and present from turn 5;
- a pending dependency exists at turns 20–24 and is empty from turn 25;
- DataFrame context stays at or below 12,000 characters;
- frontier context stays at or below 4,500 characters;
- turn-50 message chronology remains valid.

- [ ] **Step 5: Run the long-turn facet**

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Expected: every check passes with zero external calls.

---

### Task 3: Add a heavy-history pressure scenario

**Files:**
- Modify: `scripts/dev/run_context_projection_campaign.py`

**Interfaces:**
- Consumes: `_capture(...)`, `_content_text(...)`.
- Produces: trimming and preservation checks inside `campaign_long_turns(...)`.

- [ ] **Step 1: Build a large pre-existing history**

```python
def _large_history(turns: int = 120, answer_chars: int = 5_000) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for turn in range(1, turns + 1):
        messages.extend([
            HumanMessage(
                content=f"Historique {turn:03d} — demande synthétique.",
                id=f"pressure-human-{turn}",
            ),
            AIMessage(
                content=f"Réponse {turn:03d} " + ("P" * answer_chars),
                id=f"pressure-ai-{turn}",
            ),
        ])
    messages.append(HumanMessage(
        content="Demande actuelle sous forte pression de contexte.",
        id="pressure-current-human",
    ))
    return messages
```

- [ ] **Step 2: Capture through production middleware**

Call `_capture(..., input_messages=_large_history())` with six seeded
DataFrames. Do not lower production context budgets.

- [ ] **Step 3: Validate safe degradation**

Check that the current exact request and CURRENT TASK survive; the current
request remains the final Human block; approximate request tokens stay within
`_MAX_CONTEXT_TOKENS`; `messages_trimmed > 0`; model-bound history does not
start with an AI or Tool orphan; all six current DataFrame names remain visible;
and the permanent system prompt remains present and unchanged.

- [ ] **Step 4: Run text and JSON reports**

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
python scripts/dev/run_context_projection_campaign.py --facet long_turns --json
```

Expected: identical totals and zero external calls.

---

### Task 4: Add interleaved thread-isolation coverage

**Files:**
- Modify: `scripts/dev/run_context_projection_campaign.py`

**Interfaces:**
- Consumes: `CheckpointedProjectionSession`, `seed_six_dataframes(...)`, `store_dataset(...)`.
- Produces: `campaign_thread_isolation(store: SessionStore) -> list[CampaignCheck]`.

- [ ] **Step 1: Create two distinguishable threads**

```python
thread_a = f"{BASE_THREAD}-isolation-a"
thread_b = f"{BASE_THREAD}-isolation-b"
```

Seed both with six common DataFrames. Add `df_thread_a_private` with description
`THREAD_A_ONLY` and graph fact `GRAPH_A_ONLY` only to A. Add
`df_thread_b_private`, `THREAD_B_ONLY`, and `GRAPH_B_ONLY` only to B.

- [ ] **Step 2: Run twelve turns per thread**

Create one `CheckpointedProjectionSession` for A and one for B, each with
`response_count=12`. Execute A1–A6, B1–B6, A7–A12, B7–B12 by calling the
corresponding session's `invoke(question)`. Each session must retain its own
graph, checkpointer, spy model, current turn, and `thread_id`; both may share the
same temporary `SessionStore` because the thread identifier is the isolation
boundary being tested.

- [ ] **Step 3: Validate isolation**

Every A request must contain A’s private DataFrame, description, and graph fact,
and contain none of B’s sentinels. Apply the symmetric checks to B. At turn 12,
each checkpoint must contain exactly twelve Human messages with its own prefix
and zero questions from the other thread.

- [ ] **Step 4: Register and run the facet**

```python
CAMPAIGNS["thread_isolation"] = campaign_thread_isolation
```

```bash
python scripts/dev/run_context_projection_campaign.py --facet thread_isolation
```

Expected: all isolation checks pass without external calls.

---

### Task 5: Complete reporting and compatibility verification

**Files:**
- Modify: `scripts/dev/run_context_projection_campaign.py`
- Reference: `scripts/dev/inspect_six_dataframe_context.py`

**Interfaces:**
- Consumes: all seven campaign facets.
- Produces: stable terminal and JSON reports.

- [ ] **Step 1: Add bounded campaign metadata to JSON**

```python
"campaign": {
    "long_turn_count": LONG_TURN_COUNT,
    "offline": True,
}
```

Never serialize full messages, DataFrames, system prompts, or raw pressure
payloads.

- [ ] **Step 2: Verify facet selection**

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
python scripts/dev/run_context_projection_campaign.py --facet thread_isolation
python scripts/dev/run_context_projection_campaign.py --facet dataframes --facet history
```

Expected: each command runs only named facets and exits `0`.

- [ ] **Step 3: Verify the complete campaign and JSON**

```bash
python scripts/dev/run_context_projection_campaign.py
python scripts/dev/run_context_projection_campaign.py --json \
  | python -c 'import json,sys; p=json.load(sys.stdin); assert p["offline"]; assert p["llm_calls"] == 0; assert p["network_calls"] == 0; assert p["summary"]["failed"] == 0'
```

Expected: all checks pass and both commands exit `0`.

- [ ] **Step 4: Verify previous harness compatibility**

```bash
python scripts/dev/inspect_six_dataframe_context.py --view dataframes | tail -5
```

Expected: final line `ALL CHECKS PASSED`.

- [ ] **Step 5: Verify syntax and diff quality**

```bash
python -m py_compile \
  scripts/dev/run_context_projection_campaign.py \
  scripts/dev/inspect_six_dataframe_context.py
git diff --check
```

Expected: both commands exit `0` without output.

- [ ] **Step 6: Commit the extension**

```bash
git add scripts/dev/run_context_projection_campaign.py
git add -f docs/superpowers/plans/2026-08-10-long-turn-context-campaign.md
git commit -m "test: stress context projection across long conversations"
```
