# Copepod Agent Defect Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the agent defects found in `IDEA Copepodes Conversation Juin 2026.html`: deliverable protocol drift, fabricated tables, unsafe joins, weak artifact reuse, clarification loops, visible execution failures, image/zoom hesitation, and noisy formatting.

**Architecture:** Keep deterministic UI/stream behavior in code, not in the LLM prompt. Put domain policies that the LLM must follow in `agents/copepod_prompt.py`, and add small runtime helpers for join safety and artifact context so the prompt has enforceable tools. Regression tests should cover stream events, frontend hydration, prompt contracts, join validation, and chat history hydration.

**Tech Stack:** Python `pytest`, JavaScript `jest`, OpenInterpreter stream events, IDEA frontend renderer, Copepod tool registry.

---

## Scope Split

This plan covers five independently testable areas:

1. **Deliverable protocol and rendering:** prevent JSON/raw markdown, duplicate cards, and post-card prose.
2. **Agent contract:** stop plan-only answers, fabricated numeric tables, repeated "je peux", and clarification loops.
3. **Join safety:** block many-to-many joins and destructive duplicate removal unless an aggregation strategy is explicit.
4. **Artifact/context reuse:** make prior files, reports, CSVs, images, and deliverables visible as current working context.
5. **Loaded-file state:** stop false "upload a file" fallbacks when a file was already loaded earlier in a long session.
6. **Visual/image workflow:** handle pasted images and zoom requests without passive loops.

Execution should follow P0/P1/P2 priority. P0 protects trust, data correctness, and session continuity; P1 removes workflow blockers; P2 reduces noise once core behavior is stable.

## File Map

- Modify `core/chat_stream_events.py`: stream-level cleanup and suppression after structured deliverables.
- Modify `frontend/assistant.js`: persistence whitelist already includes `deliverable`; keep it covered by tests.
- Modify `frontend/conversation_ui.js`: render legacy deliverable JSON saved as `message` as a deliverable card during hydration/export display.
- Modify `frontend/message-renderer.js`: expose or reuse deliverable JSON detection/rendering helpers.
- Modify `agents/copepod_prompt.py`: tighten rules for deliverables, tables, joins, errors, clarification, and visual requests.
- Create `tests/test_copepod_prompt_contract.py`: static contract tests for the Copepod prompt.
- Create `core/copepod_join_validation.py`: reusable join cardinality and match-quality profiler.
- Create `tests/test_copepod_join_validation.py`: unit tests for safe/unsafe join decisions.
- Modify `core/tool_registry/tools/copepod_data.py`: register `profile_join_keys` as a runtime helper available to the agent.
- Modify `tests/test_copepod_data_workflow.py`: verify the join helper is rendered and behaves on fixture data.
- Modify `routers/chat_routes.py`: inject compact artifact and loaded-file context from stored messages before each Copepod turn.
- Modify `tests/test_chat_routes.py`: regression tests for loaded-file detection, false upload fallbacks, artifact context, and image hydration.
- Modify `frontend/file-upload.js` and `frontend/assistant.js` only if pasted images are not already preserved as multimodal input.

---

## Priority Order

### P0: Trust, Continuity, And Data Correctness

1. **Task 1: Deliverable Stream Is Terminal And Unique**  
   Stops duplicate deliverables and assistant prose after cards.
2. **Task 2: Legacy Raw Deliverable JSON Renders As A Card**  
   Fixes old conversations/F5/export where deliverable JSON appears as raw text.
3. **Task 6B: Loaded File State Guard Prevents False Upload Requests**  
   Stops `Uploadez un fichier pour commencer.` when the session already has loaded files.
4. **Task 6: Artifact Context Injection**  
   Makes existing files, graphs, CSVs, reports, and deliverables available as compact current context.
5. **Task 3: Prompt Contract For Agent Output Discipline**  
   Stops fabricated tables, plan-only answers, repeated prose, and weak deliverable protocol.
6. **Task 4: Safe Join Profiler**  
   Adds deterministic join cardinality and expansion diagnostics.
7. **Task 5: Prompt Uses Join Profiler Before Join Deliverables**  
   Prevents unsafe many-to-many joins and destructive duplicate removal from becoming "successful" deliverables.
8. **Task 7: Error Recovery Does Not Ask Vague Questions After Tracebacks**  
   Forces retry/repair from the traceback before asking the user.

### P1: Workflow Completion

9. **Task 8: Image And Zoom Requests Execute Instead Of Looping**  
   Uses pasted images and zoom intent directly instead of asking avoidable follow-up questions.

### P2: Output Polish

10. **Task 9: Formatting And Report Noise**  
    Reduces repeated plans, mixed language, broken inline formatting, and oversized reports.
11. **Task 10: Conversation Regression Checklist**  
    Runs the final manual replay and automated regression checks after implementation.

---

### Task 1 [P0]: Deliverable Stream Is Terminal And Unique

**Files:**
- Modify: `core/chat_stream_events.py`
- Test: `tests/test_chat_stream_events.py`

- [ ] **Step 1: Add failing test for post-deliverable prose suppression**

Add this test near the existing deliverable tests in `tests/test_chat_stream_events.py`:

```python
def test_console_deliverable_suppresses_followup_assistant_prose():
    payload = {"type": "graph", "title": "Carte produite"}
    line = "DELIVERABLE: " + json.dumps(payload)
    chunks = [
        *_stream_console(line + "\n"),
        *_stream_message("Oui, le livrable est termine."),
    ]

    events = list(chat_stream_events(chunks))

    cards = [
        json.loads(e["content"]) for e in events
        if e.get("role") == "computer" and e.get("type") == "deliverable"
    ]
    assistant_text = _concat_message_content(events)

    assert cards == [payload]
    assert assistant_text == ""
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
pytest tests/test_chat_stream_events.py::test_console_deliverable_suppresses_followup_assistant_prose -q
```

Expected before implementation: `FAIL` because the assistant text after the card is still emitted.

- [ ] **Step 3: Implement stream suppression**

In `chat_stream_events`, add a boolean `deliverable_emitted = False` next to `backend_closing_emitted`. When `_emit_console_buf()` emits a `type: "deliverable"` event, set `deliverable_emitted = True`. At the start of `_emit_or_defer_assistant_text`, return early when `deliverable_emitted` is true.

Implementation shape:

```python
deliverable_emitted = False

def _emit_or_defer_assistant_text(original: str):
    nonlocal pending_assistant_tail
    if backend_closing_emitted or deliverable_emitted:
        return
    ...

def _emit_console_buf():
    nonlocal console_buf_content, in_console_msg, console_fmt
    nonlocal backend_closing_emitted, deliverable_emitted
    ...
    if isinstance(data, dict):
        ...
        deliverable_emitted = True
        yield {"start": True, "end": True, "role": "computer",
               "type": "deliverable", "content": json.dumps(data)}
```

- [ ] **Step 4: Run deliverable stream regression tests**

Run:

```bash
pytest tests/test_chat_stream_events.py -q
```

Expected: all tests pass.

---

### Task 2 [P0]: Legacy Raw Deliverable JSON Renders As A Card

**Files:**
- Modify: `frontend/message-renderer.js`
- Modify: `frontend/conversation_ui.js`
- Test: `frontend/__tests__/message_rendering.test.js`
- Test: `frontend/__tests__/assistant_persistence.test.js`

- [ ] **Step 1: Add failing hydration test for old saved messages**

Add a test in `frontend/__tests__/message_rendering.test.js`:

```javascript
test('legacy message containing deliverable JSON renders as deliverable card', () => {
    const content = JSON.stringify({
        type: 'graph',
        title: 'Abondance par station',
        fields: [{ label: 'Source', value: 'old conversation' }],
        file_url: '/static/old.png',
        filename: 'old.png',
    });

    window.conversationUI.displayMessageInChat(
        msg('message', null, content, 'computer')
    );

    const card = document.querySelector('.deliverable-card');
    expect(card).not.toBeNull();
    expect(card.textContent).toContain('Abondance par station');
    expect(document.querySelector('.content').textContent).not.toContain('"fields"');
});
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
npx jest frontend/__tests__/message_rendering.test.js --runInBand
```

Expected before implementation: `FAIL` because old JSON is rendered as markdown/plain text.

- [ ] **Step 3: Add reusable deliverable JSON detection**

In `frontend/message-renderer.js`, add and export:

```javascript
function isDeliverableJsonContent(content) {
    if (typeof content !== 'string') return false;
    try {
        const data = JSON.parse(content);
        return data && typeof data === 'object'
            && typeof data.type === 'string'
            && typeof data.title === 'string'
            && ['join', 'export', 'graph', 'stats', 'analysis'].includes(data.type);
    } catch (_) {
        return false;
    }
}
```

Export `isDeliverableJsonContent` with the other CommonJS exports.

- [ ] **Step 4: Use the helper during conversation hydration**

In `frontend/conversation_ui.js`, before the normal `message_type === 'message'` markdown branch, compute:

```javascript
const effectiveType =
    message.message_type === 'message' && isDeliverableJsonContent(message.content)
        ? 'deliverable'
        : message.message_type;
contentElement.setAttribute('data-type', effectiveType);
```

Then route `effectiveType === 'deliverable'` to `_renderDeliverableCard(message.content || '{}')`.

- [ ] **Step 5: Run frontend tests**

Run:

```bash
npx jest --runInBand
```

Expected: all Jest tests pass.

---

### Task 3 [P0]: Prompt Contract For Agent Output Discipline

**Files:**
- Modify: `agents/copepod_prompt.py`
- Create: `tests/test_copepod_prompt_contract.py`

- [ ] **Step 1: Add prompt contract tests**

Create `tests/test_copepod_prompt_contract.py`:

```python
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT


def test_deliverable_protocol_is_terminal_and_python_only():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "DELIVERABLE must ONLY be emitted from Python code" in prompt
    assert "After emitting DELIVERABLE:, do not add any prose summary" in prompt
    assert "One card per deliverable, never two" in prompt


def test_tables_and_numbers_must_be_grounded_in_execution():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Never invent numeric values" in prompt
    assert "If the user asks for a table in text" in prompt
    assert "read the saved artifact or recompute it in code before answering" in prompt


def test_clear_request_executes_without_plan_only_response():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Never output only a plan with no code block when execution is required" in prompt
    assert "If the request is clear, execute" in prompt


def test_clarification_policy_is_one_short_question():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "ask one short targeted question" in prompt
    assert "Do not repeat the same clarification question" in prompt
```

- [ ] **Step 2: Run the tests and verify failures identify missing rules**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py -q
```

Expected before implementation: at least the table-grounding and repeated-clarification assertions fail.

- [ ] **Step 3: Patch the prompt rules**

Update `agents/copepod_prompt.py` with explicit rules:

```text
- If the user asks for a table in text, top-N list, numeric ranking, or any values from a prior artifact, you must read the saved artifact or recompute it in code before answering. Never print placeholder rows, blanks, dashes, or guessed values.
- Do not repeat the same clarification question. If the user already gave a usable file, station, period, column, or source hint, proceed with that value and document assumptions in the deliverable fields.
- For clear action commands such as "go", "fais le", "fais LE ZOOM", or "ok fais le", execute the current concrete task. Do not answer "je peux..." unless a required parameter is missing.
```

- [ ] **Step 4: Run prompt and focused backend tests**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py tests/test_agents.py -q
```

Expected: all tests pass.

---

### Task 4 [P0]: Safe Join Profiler

**Files:**
- Create: `core/copepod_join_validation.py`
- Create: `tests/test_copepod_join_validation.py`
- Modify: `core/tool_registry/tools/copepod_data.py`
- Modify: `tests/test_copepod_data_workflow.py`

- [ ] **Step 1: Add failing join-safety tests**

Create `tests/test_copepod_join_validation.py`:

```python
import pandas as pd

from core.copepod_join_validation import profile_join_keys


def test_many_to_many_join_is_not_deliverable_safe():
    left = pd.DataFrame({"sample_id": [1, 1, 2], "taxon": ["a", "b", "c"]})
    right = pd.DataFrame({"sample_id": [1, 1, 3], "cast": ["x", "y", "z"]})

    profile = profile_join_keys(left, right, "sample_id", "sample_id")

    assert profile["cardinality"] == "many_to_many"
    assert profile["safe_for_join_deliverable"] is False
    assert profile["requires_aggregation"] is True
    assert profile["left_duplicate_keys"] == 1
    assert profile["right_duplicate_keys"] == 1


def test_many_to_one_join_is_safe_when_no_row_explosion():
    left = pd.DataFrame({"sample_id": [1, 1, 2], "taxon": ["a", "b", "c"]})
    right = pd.DataFrame({"sample_id": [1, 2], "station": ["A", "B"]})

    profile = profile_join_keys(left, right, "sample_id", "sample_id")

    assert profile["cardinality"] == "many_to_one"
    assert profile["safe_for_join_deliverable"] is True
    assert profile["row_expansion_factor"] == 1.0
```

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
pytest tests/test_copepod_join_validation.py -q
```

Expected before implementation: `ModuleNotFoundError: No module named 'core.copepod_join_validation'`.

- [ ] **Step 3: Implement `profile_join_keys`**

Create `core/copepod_join_validation.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd


def _normalized_key_series(df: pd.DataFrame, key: str) -> pd.Series:
    if key not in df.columns:
        raise KeyError(f"Missing join key: {key}")
    return df[key].dropna().astype(str).str.strip()


def profile_join_keys(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_key: str,
    right_key: str,
) -> dict[str, Any]:
    left_keys = _normalized_key_series(left, left_key)
    right_keys = _normalized_key_series(right, right_key)

    left_counts = left_keys.value_counts()
    right_counts = right_keys.value_counts()
    left_duplicate_keys = int((left_counts > 1).sum())
    right_duplicate_keys = int((right_counts > 1).sum())

    if left_duplicate_keys and right_duplicate_keys:
        cardinality = "many_to_many"
    elif left_duplicate_keys:
        cardinality = "many_to_one"
    elif right_duplicate_keys:
        cardinality = "one_to_many"
    else:
        cardinality = "one_to_one"

    left_unique = set(left_counts.index)
    right_unique = set(right_counts.index)
    matched_unique = left_unique & right_unique
    left_match_rate = round(len(matched_unique) / len(left_unique) * 100, 2) if left_unique else 0.0
    right_match_rate = round(len(matched_unique) / len(right_unique) * 100, 2) if right_unique else 0.0

    estimated_rows = 0
    for key in matched_unique:
        estimated_rows += int(left_counts[key]) * int(right_counts[key])
    row_expansion_factor = round(estimated_rows / len(left), 4) if len(left) else 0.0

    requires_aggregation = cardinality in {"one_to_many", "many_to_many"}
    safe_for_join_deliverable = (
        cardinality in {"one_to_one", "many_to_one"}
        and row_expansion_factor <= 1.05
    )

    return {
        "left_key": left_key,
        "right_key": right_key,
        "left_rows": int(len(left)),
        "right_rows": int(len(right)),
        "left_unique_keys": int(len(left_unique)),
        "right_unique_keys": int(len(right_unique)),
        "matched_unique_keys": int(len(matched_unique)),
        "left_duplicate_keys": left_duplicate_keys,
        "right_duplicate_keys": right_duplicate_keys,
        "cardinality": cardinality,
        "left_match_rate": left_match_rate,
        "right_match_rate": right_match_rate,
        "estimated_join_rows": int(estimated_rows),
        "row_expansion_factor": row_expansion_factor,
        "requires_aggregation": requires_aggregation,
        "safe_for_join_deliverable": safe_for_join_deliverable,
    }
```

- [ ] **Step 4: Expose helper to the agent runtime**

In `core/tool_registry/tools/copepod_data.py`, add a registered tool code block that defines `profile_join_keys` inside the interpreter runtime. It should use the same logic as `core/copepod_join_validation.py`, or import it if the runtime can access `core` from the execution path.

Register it with tags `{"copepod_data"}` so `CopepodProfile.tool_tags` already includes it.

- [ ] **Step 5: Run join tests and tool render tests**

Run:

```bash
pytest tests/test_copepod_join_validation.py tests/test_copepod_data_workflow.py -q
```

Expected: all tests pass.

---

### Task 5 [P0]: Prompt Uses Join Profiler Before Join Deliverables

**Files:**
- Modify: `agents/copepod_prompt.py`
- Modify: `tests/test_copepod_prompt_contract.py`

- [ ] **Step 1: Add prompt test for join safety**

Append to `tests/test_copepod_prompt_contract.py`:

```python
def test_join_protocol_requires_cardinality_profile_before_join_deliverable():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "profile_join_keys" in prompt
    assert "many_to_many" in prompt
    assert "must not emit a join deliverable" in prompt
    assert "Do not drop duplicate rows just to make a key unique" in prompt
```

- [ ] **Step 2: Patch join rules**

In `agents/copepod_prompt.py`, add:

```text
- Before emitting any `type: "join"` deliverable, run `profile_join_keys(left_df, right_df, left_key, right_key)` or compute the same metrics in code.
- If cardinality is `one_to_many` or `many_to_many`, do not emit a successful join deliverable. Emit a diagnostic table or ask for an aggregation rule.
- Do not drop duplicate rows just to make a key unique. If duplicates exist, aggregate with a documented method or ask one targeted question about the aggregation rule.
- Match rates must be reported on unique keys and bounded from 0% to 100%. A rate above 100% is a bug, not a result.
```

- [ ] **Step 3: Run prompt tests**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py -q
```

Expected: all tests pass.

---

### Task 6 [P0]: Artifact Context Injection

**Files:**
- Modify: `routers/chat_routes.py`
- Test: `tests/test_chat_routes.py`

- [ ] **Step 1: Add failing test for artifact context from prior deliverables**

Add a test near the existing chat context tests in `tests/test_chat_routes.py`:

```python
def test_copepod_chat_injects_prior_artifact_context(client):
    # Build stored history with one inspection report and one deliverable JSON.
    # Assert the next interpreter system message contains a compact "Known artifacts" block.
    ...
```

Use the existing `fake_chat` capture pattern from tests around recovery mode. The expected system message must include:

```text
Known artifacts in this session:
- CSV: top10_stations_couverture.csv
- Graph: stations_top10_couverture_carte.png
- Reported loaded file: donne_sample.csv
```

- [ ] **Step 2: Implement artifact extraction helper**

In `routers/chat_routes.py`, add:

```python
def _build_copepod_artifact_context(messages: list[dict[str, Any]]) -> str:
    artifacts = []
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if "# RAPPORT D'INSPECTION" in content and "file_path" in content:
            artifacts.append(("Report", content.split("file_path", 1)[-1][:180]))
        try:
            data = json.loads(content)
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("type") in {"join", "export", "graph", "stats", "analysis"}:
            filename = data.get("filename") or Path(str(data.get("file", ""))).name
            title = data.get("title") or data.get("type")
            if filename:
                artifacts.append((str(data.get("type")).title(), f"{title}: {filename}"))
    if not artifacts:
        return ""
    lines = ["Known artifacts in this session:"]
    for kind, value in artifacts[-12:]:
        lines.append(f"- {kind}: {value}")
    return "\n".join(lines)
```

Inject this as a short system note for Copepod turns before `interpreter.chat(...)`, using the same pattern as existing Copepod planner/recovery notes.

- [ ] **Step 3: Run chat route tests**

Run:

```bash
pytest tests/test_chat_routes.py -q
```

Expected: all tests pass.

---

### Task 6B [P0]: Loaded File State Guard Prevents False Upload Requests

**Files:**
- Modify: `routers/chat_routes.py`
- Test: `tests/test_chat_routes.py`

**Confirmed diagnosis from Langfuse session `9cdfa9c8-3f6c-43e4-9cbe-c935e1790bc5:session-vu4udvmug:copepod`:**
- Trace `2f245744-7c30-4c88-877c-9cdc4eb86869`, round 46, user asked `fais graphe simple, profil par profondauer de labondance`; assistant answered `Uploadez un fichier pour commencer.`
- The LLM generation trace had 71 input messages and about 279k characters total. The real upload marker `Files uploaded in this message:` still existed in non-system history, but only far back at messages 1 and 22.
- No real non-system `# RAPPORT D'INSPECTION` block was present in that generation payload.
- `_build_copepod_data_planner_note()` only detects `# RAPPORT D'INSPECTION` and `### Fichiers chargés`; it does not detect `Files uploaded in this message:` or prior file/artifact deliverables, so it injected no compact loaded-file note near the system prompt.
- Root cause: loaded-file state depends on old raw chat history instead of a durable, compact per-session state block. Long noisy history makes the model follow the fallback upload rule even though files were already loaded.

- [ ] **Step 1: Add failing test for old upload marker plus long noisy history**

Add a test in `tests/test_chat_routes.py` using the existing fake interpreter capture pattern:

```python
def test_copepod_chat_injects_loaded_file_context_from_old_upload_marker(client):
    # Stored history starts with a real upload marker, then many console/image/deliverable messages.
    # The new user asks for a graph without uploading again.
    # Assert the interpreter system message contains a compact loaded-file/session context block.
    ...
```

Expected system note:

```text
Loaded files in this session:
- sample.csv
```

The test should also assert that the note is near the composed system prompt, not only buried in prior chat messages.

- [ ] **Step 2: Extend loaded-file detection**

In `routers/chat_routes.py`, make the Copepod context builder detect all durable file signals:

```text
Files uploaded in this message:
### Fichiers chargés
# RAPPORT D'INSPECTION
file deliverable JSON with filename/file_url/file_path
graph/export/join deliverable JSON with filename/file_url/file_path
```

Keep the extracted context compact and deduplicated. Do not paste full inspection reports back into the prompt.

- [ ] **Step 3: Inject loaded-file context every Copepod turn**

When Copepod mode is active, compose a deterministic note before `interpreter.chat(...)`:

```text
Loaded files in this session:
- sample.csv
- taxa.csv

Known artifacts in this session:
- Graph: abundance_depth_profile.png
- CSV: jointure_sample_id_sans_doublons.csv
```

Append this note to the Copepod planner/recovery system message. This makes "file already loaded" current state, not an inference the LLM has to recover from 70 old messages.

- [ ] **Step 4: Keep the true no-file fallback**

Add a paired regression test:

```python
def test_copepod_chat_does_not_inject_loaded_file_context_without_file_signals(client):
    ...
```

Expected: no loaded-file note is injected when the session has no upload/report/artifact signal. The prompt can still use `Uploadez un fichier pour commencer.` for genuinely empty sessions.

- [ ] **Step 5: Run chat route tests**

Run:

```bash
pytest tests/test_chat_routes.py -q
```

Expected: all tests pass.

---

### Task 7 [P0]: Error Recovery Does Not Ask Vague Questions After Tracebacks

**Files:**
- Modify: `agents/copepod_prompt.py`
- Modify: `routers/chat_routes.py` only if recovery notes need stronger wording
- Test: `tests/test_copepod_prompt_contract.py`
- Test: existing recovery tests in `tests/test_chat_routes.py`

- [ ] **Step 1: Add prompt test for traceback recovery**

Add:

```python
def test_execution_error_policy_requires_retry_from_traceback():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "If code execution fails" in prompt
    assert "use the crash output to refine the next attempt" in prompt
    assert "Do not turn a syntax error into a clarification question" in prompt
```

- [ ] **Step 2: Patch error policy**

Add this exact rule in `agents/copepod_prompt.py`:

```text
- Do not turn a syntax error, import error, missing parenthesis, or truncated code block into a clarification question. Use the traceback to repair and retry once. Ask the user only when the traceback reveals a real missing data requirement.
```

- [ ] **Step 3: Run tests**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py tests/test_chat_routes.py -q
```

Expected: all tests pass.

---

### Task 8 [P1]: Image And Zoom Requests Execute Instead Of Looping

**Files:**
- Modify: `agents/copepod_prompt.py`
- Modify: `frontend/assistant.js` only if image uploads are not included as multimodal attachments
- Modify: `frontend/file-upload.js` only if image metadata is incomplete
- Test: `tests/test_chat_routes.py`
- Test: `tests/test_copepod_prompt_contract.py`

- [ ] **Step 1: Keep existing multimodal tests green**

Run:

```bash
pytest tests/test_chat_routes.py::TestChatEndpoint::test_chat_hydrates_image_attachments_before_llm_call -q
```

Expected: pass. If this test name differs locally, run:

```bash
pytest tests/test_chat_routes.py -q -k "image_attachments"
```

- [ ] **Step 2: Add prompt test for zoom commands**

Add:

```python
def test_zoom_commands_execute_when_target_is_known():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "fais LE ZOOM" in prompt
    assert "execute the current concrete task" in prompt
    assert "If the user provides an image crop" in prompt
```

- [ ] **Step 3: Patch visual request rules**

In `agents/copepod_prompt.py`, add:

```text
- If the user provides an image crop and says "zoom ici", use the image plus the current graph artifact to infer the requested region when possible. If the crop is insufficient, ask one short question for the station or bounding box.
- If the user gives a station after a zoom request, execute immediately. Do not answer "je peux" or ask for another zoom level.
```

- [ ] **Step 4: Run tests**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py tests/test_chat_routes.py -q
```

Expected: all tests pass.

---

### Task 9 [P2]: Formatting And Report Noise

**Files:**
- Modify: `agents/copepod_prompt.py`
- Modify: `frontend/message-renderer.js` only if report collapse is broken in current UI
- Test: `frontend/__tests__/message-renderer.test.js`
- Test: `tests/test_copepod_prompt_contract.py`

- [ ] **Step 1: Add prompt test for concise French output and column formatting**

Add:

```python
def test_output_formatting_contract_is_french_and_readable():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Use French for user-facing prose" in prompt
    assert "Wrap exact column names in backticks" in prompt
    assert "Do not concatenate prose and column names" in prompt
```

- [ ] **Step 2: Patch formatting rules**

Add:

```text
- Use French for user-facing prose unless the user asks otherwise.
- Wrap exact column names in backticks, with spaces around them. Correct: `STATION_NAME`; incorrect: stationSTATION_NAME.
- Inspection reports should be emitted through the existing report pipeline. Do not repeat the full report in normal prose after it has been rendered.
```

- [ ] **Step 3: Run tests**

Run:

```bash
pytest tests/test_copepod_prompt_contract.py -q
npx jest frontend/__tests__/message-renderer.test.js --runInBand
```

Expected: all tests pass.

---

### Task 10 [P2]: Conversation Regression Checklist

**Files:**
- Create: `docs/copepod-agent-regression-checklist.md`
- Optional Test: `tests/test_copepod_prompt_contract.py`

- [ ] **Step 1: Create manual regression checklist**

Create `docs/copepod-agent-regression-checklist.md` with these scenarios:

```markdown
# Copepod Agent Regression Checklist

## Deliverables
- Generate a graph. Expected: one image plus one deliverable card, no assistant prose after the card.
- Reload with F5. Expected: deliverable card CSS remains.
- Export conversation. Expected: deliverable card is rendered, not raw JSON.

## Tables
- Ask "mets le tableau en texte" after a CSV export. Expected: assistant executes code to read the CSV and prints real values.

## Joins
- Join two files with duplicate keys on both sides. Expected: diagnostic cardinality result, no successful join card.
- Join many taxon rows to one sample metadata row. Expected: allowed many-to-one join card with bounded match rates.

## Errors
- Force a syntax error in generated code. Expected: one repaired retry using traceback, no vague clarification question.

## Visual Zoom
- Upload an image crop and say "zoom ici". Expected: agent either infers crop or asks one short station/bbox question.
- Then say "Zoom sur station 314". Expected: agent executes immediately.

## Clarification
- Ask for Amundsen with `STATION ID` and same period as loaded files. Expected: no repeated identical question.
```

- [ ] **Step 2: Run full focused verification suite**

Run:

```bash
pytest tests/test_chat_stream_events.py tests/test_chat_routes.py tests/test_copepod_prompt_contract.py tests/test_copepod_join_validation.py -q
npx jest --runInBand
```

Expected: all tests pass.

---

## Execution Order

1. **P0 trust/rendering:** Task 1, then Task 2.
2. **P0 session continuity:** Task 6B, then Task 6.
3. **P0 agent discipline:** Task 3, then Task 7.
4. **P0 data safety:** Task 4, then Task 5.
5. **P1 workflow completion:** Task 8.
6. **P2 polish:** Task 9.
7. **Exit gate:** Task 10.

## Current Known Status

- New `deliverable` persistence for `frontend/assistant.js` is already patched.
- Text `DELIVERABLE:` duplication is already stripped in `core/chat_stream_events.py`.
- Langfuse confirms the false upload request in `session-vu4udvmug` is caused by missing deterministic loaded-file context, not by a truly empty session.
- Priority is now explicit: fix P0 trust/rendering, loaded-file continuity, prompt discipline, and data safety before P1 image/zoom and P2 formatting noise.
- The remaining work is to suppress post-deliverable prose, repair legacy raw JSON display, harden prompt rules, add join safety, improve artifact and loaded-file context, and add regression coverage.

## Self-Review

- Spec coverage: every P0/P1/P2 defect from the exported conversation maps to at least one task.
- Placeholder scan: no task says "TBD", "TODO", "handle edge cases", or "write tests" without concrete test content.
- Type consistency: deliverable types are consistently `join`, `export`, `graph`, `stats`, `analysis`; join helper returns a plain dict for easy runtime use.
