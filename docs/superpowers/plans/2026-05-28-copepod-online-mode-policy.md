# Copepod Online Mode Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, visible, opt-in "Mode En Ligne" for Copepod workflows so OGSL and Bio-ORACLE are only used after an explicit user request, with a single targeted clarification when parameters are incomplete, a local-first default, and a safe fallback to allowed alternatives.

**Architecture:** Keep the policy layered. Persist the user/session preference server-side, expose it in the UI, and enforce the rule in the copepod prompt/runtime so the assistant only uses online sources when the mode is enabled and the user explicitly asked for them. Keep the source registry extensible so additional online sources can be added without rewriting the policy. Reuse the existing copepod session model, RAG source guidance, and current frontend account/session controls rather than inventing a parallel settings system.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, Redis-backed session store, pytest, jsdom/Jest frontend tests, existing copepod prompt renderer, vanilla frontend JavaScript.

---

## Task 1: Add persistent Online Mode state and API

**Files:**
- Modify: `models/db.py`
- Modify: `models/schemas.py`
- Modify: `core/crud.py`
- Modify: `routers/auth_routes.py`
- Modify: `routers/session_routes.py`
- Modify: `core/session_store.py`
- Test: `tests/test_copepod_online_mode_policy.py`
- Test: `tests/test_session_routes.py`

- [ ] **Step 1: Write the failing tests**

Create backend tests that assert:
- Online Mode defaults to OFF for a new user/session.
- The current user can read and update their Online Mode preference.
- The frontend/session runtime can read the current state through a dedicated route.
- The current state persists across reloads or session re-entry using the existing session model.
- The allowlist is visible in the returned payload.

Suggested test shape:

```python
def test_online_mode_defaults_off_for_new_session(store):
    assert store.get_online_mode("u1:s1:copepod") is False


def test_online_mode_can_be_enabled_and_read_back(client, auth_headers):
    res = client.put("/api/copepod/online-mode", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["enabled"] is True

    res = client.get("/api/copepod/online-mode", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["enabled"] is True
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/test_copepod_online_mode_policy.py tests/test_session_routes.py -q
```

Expected: fail because the policy storage and endpoints do not exist yet.

- [ ] **Step 3: Implement the minimal backend state**

Add a small persistence layer for the Online Mode preference:
- store the active state in the existing session model for runtime reads;
- persist the user default server-side so the UI can restore it;
- keep the default OFF unless explicitly enabled.

Prefer a narrow shape, for example:

```python
{
    "enabled": bool,
    "allowed_sources": ["ogsl", "bio_oracle"],
    "scope": "user" | "session",
    "updated_at": "...",
}
```

Implement the smallest backend surface that lets the UI read and update the preference without coupling it to the chat workflow.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
pytest tests/test_copepod_online_mode_policy.py tests/test_session_routes.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add models/db.py models/schemas.py core/crud.py core/session_store.py routers/auth_routes.py routers/session_routes.py tests/test_copepod_online_mode_policy.py tests/test_session_routes.py
git commit -m "feat: add copepod online mode persistence"
```

---

## Task 2: Enforce the policy in the copepod prompt and runtime

**Files:**
- Modify: `agents/copepod_prompt.py`
- Modify: `core/instruction_renderer/blocks/copepod_mode_plan.py`
- Modify: `core/copepod_rag/docs/sources_en_ligne.md`
- Modify: `core/tool_registry/tools/copepod_sources_meta.py`
- Test: `tests/test_copepod_profile.py`
- Test: `tests/test_copepod_sources_meta.py`

- [ ] **Step 1: Write the failing tests**

Add tests that assert the prompt and source metadata explicitly encode:
- Online Mode is opt-in.
- OGSL/Bio-ORACLE are only used after explicit user intent.
- If a request is only implicit, the assistant asks one targeted clarification.
- If the requested source is unavailable or disabled, the assistant proposes an allowed alternative.
- Local files and local RAG stay the default when they already satisfy the request.

Examples:

```python
def test_copepod_prompt_mentions_online_mode_opt_in():
    prompt = build_prompt(...)
    assert "Mode En Ligne" in prompt
    assert "explicitly asked" in prompt.lower()


def test_sources_metadata_lists_allowed_sources_only_when_enabled():
    result = tools["list_available_sources"](...)
    assert "ogsl" in ids
    assert "bio_oracle" in ids
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/test_copepod_profile.py tests/test_copepod_sources_meta.py -q
```

Expected: fail until the policy wording and source gating are wired in.

- [ ] **Step 3: Implement the minimal prompt/runtime policy**

Update the copepod prompt blocks so the model has a single, consistent contract:
- do not call online tools silently;
- require explicit user request or a single clarification;
- keep local-first behavior when local files answer the task;
- use only the allowlisted sources;
- if a source is disabled, explain briefly and offer a supported alternative.

Keep the source registry extensible by centralizing source metadata instead of duplicating source logic in prompt text, UI code, and tool code.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
pytest tests/test_copepod_profile.py tests/test_copepod_sources_meta.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add agents/copepod_prompt.py core/instruction_renderer/blocks/copepod_mode_plan.py core/copepod_rag/docs/sources_en_ligne.md core/tool_registry/tools/copepod_sources_meta.py tests/test_copepod_profile.py tests/test_copepod_sources_meta.py
git commit -m "feat: encode copepod online mode policy"
```

---

## Task 3: Expose the policy in the UI

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assistant.js`
- Modify: `frontend/account-settings.js`
- Modify: `frontend/styles.css`
- Test: `frontend/__tests__/online_mode_ui.test.js`

- [ ] **Step 1: Write the failing UI test**

Add a jsdom test that asserts:
- the UI renders a visible `Mode En Ligne: ON/OFF` badge or equivalent indicator;
- the user can toggle the mode from the account/settings surface;
- the allowlist is visible in the UI;
- the UI state survives refresh through the backend read endpoint.

Suggested shape:

```javascript
test('online mode badge reflects backend state and toggle updates it', async () => {
  renderApp();
  expect(screen.getByText(/Mode En Ligne/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('switch', { name: /Mode En Ligne/i }));
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/online-mode'), expect.any(Object));
});
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
npm test -- frontend/__tests__/online_mode_ui.test.js
```

Expected: fail because the UI control and endpoint wiring are not implemented yet.

- [ ] **Step 3: Implement the UI surface**

Add:
- a visible Online Mode indicator in the header or account settings area;
- a toggle that writes through to the backend;
- a source allowlist view so the user can see what the mode authorizes;
- a graceful fallback state when the backend is unavailable.

Keep the design consistent with existing account/settings and session-mode UI:
- reuse the existing modal/navigation patterns;
- do not invent a separate preferences experience if the current account settings surface can host it cleanly.

- [ ] **Step 4: Run the test and confirm it passes**

Run:

```bash
npm test -- frontend/__tests__/online_mode_ui.test.js
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/assistant.js frontend/account-settings.js frontend/styles.css frontend/__tests__/online_mode_ui.test.js
git commit -m "feat: add copepod online mode ui"
```

---

## Task 4: Add end-to-end policy coverage and update docs

**Files:**
- Modify: `tests/test_copepod_online_mode_policy.py`
- Modify: `tests/test_copepod_profile.py`
- Modify: `tests/test_session_routes.py`
- Modify: `docs/copepod-test-operations.md`
- Modify: `docs/copepod-plan-mode-eval-coverage.md`
- Modify: `docs/REPO_GUIDE.md` or `docs/CONTEXT.md` if the new policy needs to be indexed

- [ ] **Step 1: Write the failing end-to-end tests**

Add coverage for the exact user contract:
- explicit request -> direct allowed-source usage;
- implicit request -> one clarification only;
- unsupported source -> safe alternative;
- local files take priority when they already satisfy the request;
- Online Mode OFF blocks online source usage.

If the repo already has an eval harness for copepod policy behaviour, add one focused scenario that checks the state machine without introducing a new noisy live path.

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/test_copepod_online_mode_policy.py tests/test_copepod_profile.py tests/test_session_routes.py -q
```

Expected: fail until the policy, UI, and runtime wiring are complete.

- [ ] **Step 3: Update the docs**

Document:
- what `Mode En Ligne` means;
- how to enable it in the UI;
- which sources are allowed initially;
- what the assistant does when the request is explicit, incomplete, or unsupported;
- how to add a new source to the registry later without rewriting the policy.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
pytest tests/test_copepod_online_mode_policy.py tests/test_copepod_profile.py tests/test_session_routes.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_copepod_online_mode_policy.py tests/test_copepod_profile.py tests/test_session_routes.py docs/copepod-test-operations.md docs/copepod-plan-mode-eval-coverage.md docs/REPO_GUIDE.md docs/CONTEXT.md
git commit -m "docs: cover copepod online mode policy"
```

---

## Out of Scope

- A general-purpose internet search mode.
- Silent background calls to OGSL or Bio-ORACLE.
- Automatic activation of new sources without explicit allowlist changes.
- Redesigning the existing DU/GC workflow.
- Adding unsupported sources to the prompt without policy review.

## Acceptance Criteria

The change is done when:
- the user can visibly enable and disable Online Mode;
- OGSL and Bio-ORACLE are only used after explicit user intent;
- incomplete requests trigger one targeted clarification only;
- local files and local RAG remain the default when they already answer the request;
- unsupported sources produce a safe alternative, not a silent fallback;
- the source registry remains extensible without duplicating policy logic across prompt, UI, and backend.
