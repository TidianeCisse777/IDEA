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

`thread_isolation` is intentionally included in `FACETS` per the brief but is
not registered in `CAMPAIGNS`; its campaign is deferred to the later task that
uses explicit interleaving of two persistent sessions. Running the default
all-facets command before that task will therefore still fail on that missing
entry.
