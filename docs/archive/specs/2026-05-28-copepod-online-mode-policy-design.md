# Copepod Online Mode Policy Design

Date: 2026-05-28
Status: Draft

## Goal

Add an explicit "Mode En Ligne" to IDEA for copepod workflows.

The mode must allow the agent to use online sources only when:
- the user has explicitly enabled the mode;
- the user explicitly asks for a remote source request, such as Bio-ORACLE or OGSL;
- the request is sufficiently clear to execute, or can be clarified with one targeted question.

The design must keep the feature extensible so additional online sources can be added later without rewriting the policy.

## User-Facing Contract

The user should be able to:
- turn Online Mode on from the UI;
- turn it on via an explicit command;
- see which online sources are allowed;
- understand whether the assistant will use local files first or an online source first.

The assistant should:
- never call OGSL or Bio-ORACLE silently;
- only use online sources after an explicit request or after a single targeted clarification;
- prefer local files and local RAG when they already answer the need;
- propose an allowed alternative when the requested source is unavailable or unsupported.

## Policy Principles

### 1. Explicit opt-in

Online sources are disabled by default.

The assistant may only use them when the user has explicitly enabled Online Mode.

### 2. Explicit intent

The assistant may only act on OGSL or Bio-ORACLE when the user explicitly asks for a remote fetch such as:
- "va me chercher Bio-ORACLE..."
- "va me chercher OGSL..."

If the request is only implicit, the assistant must ask one targeted question first.

### 3. One clarification only

If the request is incomplete, the assistant asks one targeted clarification question and then waits.

The assistant must not:
- ask multiple questions at once;
- start a fetch with placeholders;
- silently infer missing source parameters.

### 4. Local-first preference

When local files or local RAG already cover the request, they take priority.

Online sources are used when:
- the user explicitly asks for them;
- or local data does not satisfy the request and an online source adds real value.

### 5. Safe fallback

If the user requests a source that is not active or not supported, the assistant:
- explains briefly why it cannot use that source;
- proposes a supported alternative;
- does not invent a replacement request silently.

## UI Contract

The UI must expose a visible Online Mode state.

Recommended UI behavior:
- a clear `Mode En Ligne: ON/OFF` indicator;
- the current allowlist of sources;
- the source status, at minimum `allowed`, `disabled`, or `experimental`;
- a way to enable or disable the mode from the interface.

The UI state should persist per user or per session, depending on the application’s existing session model. The mode must not be purely ephemeral.

## Policy Model

The policy should be extensible through a hybrid model:

- **code/config** owns the default policy and the built-in allowed sources;
- **UI / DB** owns the current state and administrative activation;
- the source registry owns the per-source metadata and capabilities;
- the fetch tools own the source-specific retrieval logic.

Each source entry should be able to declare:
- `id`
- `label`
- `kind` (`local`, `remote`, `mcp`, or similar)
- `status` (`allowed`, `disabled`, `experimental`)
- `requires_explicit_request`
- `needs_confirmation`
- `supported_parameters`
- `fetch_entrypoint`

This prevents the policy from being hardcoded in multiple places.

## Runtime Decision Flow

When the user sends a request:

1. Check whether Online Mode is enabled.
2. Check whether the request explicitly names a supported online source or clearly implies one.
3. If the request is explicit and sufficiently complete, call the source-specific fetch tool.
4. If the request is explicit but incomplete, ask one targeted clarification question.
5. If local files or local RAG answer the request better, use them first.
6. If the source is unsupported or disabled, propose an allowed alternative.

The assistant must always keep the decision visible in the user-facing response. It should not hide the fact that an online source was requested, clarified, or declined.

## Source Scope

Initial allowlist:
- OGSL
- Bio-ORACLE

The design must remain extensible so future sources can be added later without changing the policy semantics.

## Testing Strategy

The policy must be testable in three layers:

1. **Prompt tests**
   - the assistant only uses online sources on explicit request;
   - the assistant asks one targeted clarification when needed;
   - local-first preference is preserved;
   - unsupported sources trigger a safe alternative.

2. **Policy / routing tests**
   - Online Mode off blocks source usage;
   - Online Mode on allows explicit OGSL / Bio-ORACLE requests;
   - missing parameters trigger clarification;
   - local data is preferred when sufficient.

3. **Source fetch tests**
   - Bio-ORACLE fetch returns a structured preview table;
   - OGSL fetch returns a structured preview table;
   - errors and unsupported requests return a structured clarification payload.

## Non-Goals

This policy does not:
- implement a generic internet search mode;
- authorize all future sources by default;
- replace the existing DU/GC workflow;
- change the scientific validation rules for graphing.

## Implementation Constraints

- No silent calls to online sources.
- No multi-question clarification loops.
- No hardcoded source IDs spread across the codebase.
- No source-specific policy duplicated in the prompt, UI, and fetch layer.
- No bypass of local data when the local files already satisfy the request.

## Success Criteria

The design is successful when:
- the user can visibly enable Online Mode;
- OGSL and Bio-ORACLE are usable only after explicit user intent;
- incomplete requests trigger one targeted question only;
- local data remains the default when it is sufficient;
- the policy can be extended to new sources without redesigning the assistant.

