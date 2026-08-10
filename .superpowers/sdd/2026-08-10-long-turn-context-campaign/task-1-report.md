# Task 1 report — reusable checkpointed context capture runner

## Implementation

Modified only `scripts/dev/run_context_projection_campaign.py` for the code
change:

- Added the exact `FACETS` entries `long_turns` and `thread_isolation`.
- Added the frozen `TurnSnapshot` type.
- Added `TurnMutation`, `CheckpointedProjectionSession`, and
  `run_checkpointed_projection(...)`.
- The session owns one offline spy model, one production agent, one
  `MemorySaver`, one `InMemoryStore`, one stable thread id, and its turn
  counter.
- `invoke(...)` applies the optional pre-turn mutation, invokes the graph with
  the temporary `SessionStore`, captures exactly one new model call, and
  attaches checkpointed messages to the snapshot.
- Added the exact three-turn `long_turns` smoke scenario and registered it in
  `CAMPAIGNS`.

The production runtime was not modified.

## Exact checks and results

### RED

Command:

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Result: exit code `1` as expected. The failure was:

```text
KeyError: 'long_turns'
```

This confirmed the missing campaign entry before implementation.

### GREEN

Command:

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Result: exit code `0`.

```text
=== LONG_TURNS ===
[PASS] three-turn-checkpointed-context :: three snapshots preserve sequential turns
[PASS] three-turn-checkpointed-context :: turn three checkpoint retains three human messages

SUMMARY: 2 passed, 0 failed, 2 total
```

No network or LangSmith warning appeared.

## Files changed

- `scripts/dev/run_context_projection_campaign.py`
- `.superpowers/sdd/2026-08-10-long-turn-context-campaign/task-1-report.md`

## Self-review

- The exact facet names and smoke questions from the brief are present.
- The runner uses the required production middleware and state schema while
  substituting only the local spy model and temporary stores.
- Fake responses are text-only and contain no tool calls.
- The session patches `tools.session_store.default_store` during construction
  and invocation.
- One stable session and checkpoint are reused across the three turns.
- The optional mutation receives `(turn, store, graph, config)` immediately
  before graph invocation.
- The captured model call is converted with `_capture_from_model_call`, then
  receives the audit, checkpoint messages, and current turn.
- The focused RED/GREEN command was run exactly as required.
- No production runtime file was changed.

## Concerns

The original Task 1 implementation left `thread_isolation` intentionally
unregistered in `CAMPAIGNS`; that sequencing concern is fixed in Fix round 1
by excluding only the deferred facet from the default selection. Explicit
`--facet thread_isolation` remains deferred to the later task.

## Fix round 1

### Exact changed behavior

- Preserved the exact required `FACETS` tuple.
- Added `DEFAULT_FACETS = FACETS[:-1]`, so the default command runs every
  executable campaign, including `long_turns`, while leaving the future
  `thread_isolation` selection available for its later task without adding
  Task 4 early.
- The long-turn smoke now compares the complete ordered tuple of checkpointed
  Human contents to all three original questions using exact string equality.
- The long-turn smoke now compares every captured permanent system message to
  the first captured system message using exact equality and reports unstable
  turns.
- Added `turn_range` and `violated_contract` to `CampaignCheck`, with defaults
  that preserve existing `_check(...)` call sites. Both text and JSON failure
  output now include the fields; evidence is bounded to 1,000 characters in
  both renderers.

### Focused offline tests and commands

No new test file was required; the amended campaign and an inline Python
contract check were used.

RED command before the fixes:

```bash
python - <<'PY'
import subprocess
import sys
script = "scripts/dev/run_context_projection_campaign.py"
full = subprocess.run([sys.executable, script], capture_output=True, text=True)
assert full.returncode == 0, full.stderr
PY
```

Result: exit code `1`; the default command raised `KeyError:
'thread_isolation'`.

GREEN commands:

```bash
python scripts/dev/run_context_projection_campaign.py
```

Output: exit code `0`; `41 passed, 0 failed, 41 total`.

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns
```

Output: exit code `0`; `3 passed, 0 failed, 3 total`, including the complete
checkpointed-Human and permanent-system checks.

```bash
python scripts/dev/run_context_projection_campaign.py --facet long_turns --json
```

Output: exit code `0`; JSON summary `{"passed": 3, "failed": 0, "total": 3}`.
Each record contains `turn_range` and `violated_contract`.

Inline reporting/default-facet contract command:

```bash
python - <<'PY'
import contextlib
import io
import json
from scripts.dev import run_context_projection_campaign as campaign

assert campaign.FACETS == (
    "current_task", "dataframes", "frontier", "graph", "history",
    "long_turns", "thread_isolation",
)
assert campaign.DEFAULT_FACETS == campaign.FACETS[:-1]
failed = campaign.CampaignCheck(
    scenario="focused-reporting-test", facet="long_turns",
    name="contract failure", passed=False, evidence="E" * 2_000,
    turn_range="turns 2-3",
    violated_contract="checkpoint messages remain exact",
)
text_buffer = io.StringIO()
with contextlib.redirect_stdout(text_buffer):
    campaign._print_text([failed])
text_output = text_buffer.getvalue()
assert "turn_range: turns 2-3" in text_output
assert "violated_contract: checkpoint messages remain exact" in text_output
assert len(text_output.split("evidence: ", 1)[1].splitlines()[0]) == 1_000
json_buffer = io.StringIO()
with contextlib.redirect_stdout(json_buffer):
    campaign._print_json([failed])
record = json.loads(json_buffer.getvalue())["checks"][0]
assert record["turn_range"] == "turns 2-3"
assert record["violated_contract"] == "checkpoint messages remain exact"
assert len(record["evidence"]) == 1_000
legacy = campaign._check("s", "f", "legacy contract", False, "evidence")
assert legacy.turn_range == "not applicable"
assert legacy.violated_contract == "legacy contract"
print("focused reporting/default-facet assertions: PASS")
PY
```

Output: exit code `0`; `focused reporting/default-facet assertions: PASS`.

All commands were offline; no network or LangSmith warning appeared.

### Fix round 1 concerns

The default full harness is executable. Explicit `--facet thread_isolation`
remains intentionally deferred until the task that implements that campaign.
