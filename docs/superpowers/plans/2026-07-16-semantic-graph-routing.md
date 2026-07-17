# Semantic Graph Routing Implementation Plan

**Status:** completed on 2026-07-16.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route graph skills from the requested output intent, so non-visual analysis avoids them while implied visual outputs still execute a figure.

**Architecture:** Keep routing semantic and model-driven. A canonical prompt block defines the two output intents; `graph_planner.md` and `graph_writer.md` align with that contract without a Python classifier or keyword regex. Existing `run_graph` guards remain unchanged.

**Tech Stack:** Python, pytest, LangChain/LangGraph prompt composition, Markdown skills, existing replay isolation.

## Global Constraints

- Do not add a Python intent classifier, regex router, or middleware branch.
- General presentation verbs do not determine the route by themselves.
- Implied visual structures such as a mapped spatial representation or a plotted vertical profile remain visual without requiring a specific keyword.
- A visual route remains `graph_planner → graph_writer → run_graph` in the same turn.
- Every behavior change receives deterministic TDD plus one controlled real-agent smoke; do not loop replays.

---

### Task 1: Align the system prompt and graph skills on semantic output intent

**Files:**
- Create: `agents/graph_output_routing_rules.py`
- Create: `tests/test_graph_output_routing_prompt.py`
- Modify: `agents/copepod_system_prompt.py:32-116`
- Modify: `agents/skills/graph_planner.md:1-150`
- Modify: `agents/skills/graph_writer.md:1-45`
- Modify: `tests/test_agent_factory.py:645-668`

**Interfaces:**
- Produces: `GRAPH_OUTPUT_ROUTING_RULES: str`, a canonical block injected exactly once.
- Preserves: `load_skill("graph_planner") → load_skill("graph_writer") → run_graph` for visual output.

- [x] **Step 1: Write the failing routing tests**

Create tests with these exact behavioral assertions:

```python
from pathlib import Path

from agents.copepod_system_prompt import COPEPOD_SYSTEM_PROMPT


def test_graph_output_rules_are_canonical_and_injected_once():
    from agents.graph_output_routing_rules import GRAPH_OUTPUT_ROUTING_RULES

    assert COPEPOD_SYSTEM_PROMPT.count(GRAPH_OUTPUT_ROUTING_RULES) == 1
    assert "For ANY data analysis or visualization request" not in COPEPOD_SYSTEM_PROMPT


def test_general_presentation_verbs_do_not_force_visual_output():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "general presentation verb" in prompt
    assert "does not establish visual intent by itself" in prompt


def test_visual_intent_is_inferred_from_requested_representation():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "requested output intent" in prompt
    assert "representation of the data" in prompt
    assert "vertical profile" in prompt


def test_non_visual_outputs_skip_both_graph_skills():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "number, calculation, ranking, summary, coordinates, or table" in prompt
    assert "do not load `graph_planner` or `graph_writer`" in prompt


def test_graph_planner_uses_semantics_instead_of_closed_keyword_list():
    planner = Path("agents/skills/graph_planner.md").read_text(encoding="utf-8").lower()
    assert "decide from the requested output intent" in planner
    assert "not from a closed list of words" in planner
    assert "if the prompt explicitly mentions" not in planner


def test_graph_writer_is_visual_only():
    writer = Path("agents/skills/graph_writer.md").read_text(encoding="utf-8").lower()
    assert "produce the planned visual output" in writer
    assert "## if the plan says output: table" not in writer
```

Update the two old factory tests so they assert semantic intent and strict execution order instead of requiring `trace`, `affiche`, or `montre` as lexical triggers.

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest -q tests/test_graph_output_routing_prompt.py tests/test_agent_factory.py -k 'graph or visual or output_routing'
```

Expected: failures for the missing canonical module, the old absolute rule, the planner's closed word list, and the writer's table branch.

- [x] **Step 3: Implement the minimal canonical contract**

Create `GRAPH_OUTPUT_ROUTING_RULES` with this content:

```text
## Graph Output Routing Rules
- Decide from the requested output intent, not from individual words. Load graph skills only when the user asks for or clearly implies a visual representation of the data.
- A general presentation verb such as “show”, “display”, or “present” does not establish visual intent by itself. Infer the intended artifact from what is being requested.
- A map, plotted vertical profile, curve, chart, or other graphical encoding is visual even when the user does not use the word “graph”. These are examples of visual intent, not a closed trigger list.
- A number, calculation, ranking, summary, coordinates, or table is non-visual unless the user also requests a graphical representation. Do not load `graph_planner` or `graph_writer`; use the specialized or tabular execution tool only when needed.
- If the output format is genuinely ambiguous, prefer the minimal non-visual answer. Ask only when the choice would materially change the requested result.
- For visual intent, load `graph_planner`, then `graph_writer`; the very next execution call after `graph_writer` must be `run_graph`.
```

Inject it once after routing priority and remove the duplicate absolute graph-loading bullets from `COPEPOD_SYSTEM_PROMPT` while preserving visual safety, contracts, style, and artifact rules.

In `graph_planner.md`, replace the lexical decision step with the same semantic distinction. In `graph_writer.md`, change the introduction to visual-only and remove the table-output section; do not alter graph templates.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the same focused pytest command. Expected: all selected tests pass.

- [x] **Step 5: Run graph contract regressions once**

Run:

```bash
pytest -q tests/test_agent_factory.py tests/test_graph_contracts.py tests/test_eval_graphs.py tests/test_cartography.py
```

Expected: all pass; existing graph execution contracts remain intact.

- [x] **Step 6: Commit the behavior change**

```bash
git add agents/graph_output_routing_rules.py agents/copepod_system_prompt.py agents/skills/graph_planner.md agents/skills/graph_writer.md tests/test_graph_output_routing_prompt.py tests/test_agent_factory.py
git commit -m "feat: route graph skills by output intent"
```

### Task 2: Verify both boundaries on the real agent and close 4B

**Files:**
- Modify: `docs/superpowers/specs/2026-07-16-semantic-graph-routing-design.md`
- Modify: `docs/superpowers/plans/2026-07-16-semantic-graph-routing.md`
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `BASELINE_HARNESS_2026-07-15.md`
- Modify: `HARNESS_REDTEAM_CONTRACTS_2026-07-15.md` only if a graph-routing debt is explicitly represented there
- Modify: `evals/baseline_offline_2026-07-15.json`

**Interfaces:**
- Consumes: canonical graph-output contract from Task 1.
- Produces: recorded deterministic and real-agent evidence for the 4B gate.

- [x] **Step 1: Run the complete suite once**

Run:

```bash
pytest -q
```

Expected: no failures; do not rerun when it passes.

- [x] **Step 2: Regenerate the offline baseline once**

Run:

```bash
python -m evals.replay_harness --lane offline --runs 1 --output evals/baseline_offline_2026-07-15.json
```

Expected: level 1 and level 2 remain `1.0`. Record prompt, schema, and fixed-token counts.

- [x] **Step 3: Run one isolated real-agent smoke with both boundaries**

Use one isolated agent session with `openai/gpt-5.4-mini`, tracing disabled, `data/demo/zooplankton_demo_stations.tsv`, and only these safe tools visible: `load_file`, `run_pandas`, `load_skill`, `run_graph`.

Execute these turns once:

```text
1. Charge data/demo/zooplankton_demo_stations.tsv.
2. Montre le nombre d'observations par station, classé du plus grand au plus petit.
3. Représente maintenant ces stations sur une carte.
```

Capture calls per turn and structured tool results. Assert:

```python
assert "graph_planner" not in skills_loaded_on_turn_2
assert "graph_writer" not in skills_loaded_on_turn_2
assert "run_pandas" in calls_on_turn_2
assert skills_loaded_on_turn_3[:2] == ["graph_planner", "graph_writer"]
assert "run_graph" in calls_on_turn_3
assert run_graph_status == "success"
```

If the smoke fails, diagnose the captured trajectory before any new model call. Do not automatically rerun it.

- [x] **Step 4: Update the evidence documents**

Mark 4B implemented, record the exact targeted/full-suite/baseline/smoke results, and leave 4C open. In the plan, mark every completed checkbox. Do not claim the remaining fail-closed graph automate from step 8 is solved.

- [x] **Step 5: Verify and commit documentation**

Run:

```bash
git diff --check
git status --short
```

Then commit:

```bash
git add docs/superpowers/specs/2026-07-16-semantic-graph-routing-design.md docs/superpowers/plans/2026-07-16-semantic-graph-routing.md IMPLEMENTATION_PLAN.md BASELINE_HARNESS_2026-07-15.md HARNESS_REDTEAM_CONTRACTS_2026-07-15.md evals/baseline_offline_2026-07-15.json
git commit -m "docs: close semantic graph routing gate"
```
