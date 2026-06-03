# ADR 006 — Inspection reports stored out-of-context, exposed via tool

**Status:** Accepted — 2026-06-03

## Context

`inspect_and_report` (in `core/tool_registry/tools/copepod_data.py`) produces a `# RAPPORT D'INSPECTION` block per file: shape, dtypes, source type guess, RAG definitions, missingness, join hints. The block is streamed to the user and persisted as a message in the conversation history. On every subsequent turn the LLM sees it in its message history and was paraphrasing it into user-visible prose — leaking the working-set into chat responses.

Five sequential prompt-only fixes (`aad5acf`, `0709e9c`, `95cb76e`, `2081248`, `3c86cf6`) tried to instruct the LLM not to paraphrase. None converged. Each new rule shifted the leak to a different wording. The pattern was unambiguous: as long as the report sat in the LLM's context, the LLM would eventually surface it as prose.

This ADR captures the structural fix.

## Decision

Inspection reports are persisted **out of the LLM-visible conversation history**, in a dedicated session-store namespace, and exposed to the LLM only via an explicit tool call.

Concretely:

1. **Storage.** `SessionStore` gains three methods: `store_inspection_report`, `read_inspection_report`, `list_inspection_reports` — keyed `{session_key}:{filename}`. Both `RedisSessionStore` (Redis hash) and `InMemorySessionStore` (nested dict) implement them.

2. **Scrubbing seam.** In `routers/chat_routes.py`, immediately after `session_store.read_messages(session_key)` and before assigning to `interpreter.messages`, every `# RAPPORT D'INSPECTION ...` block in any message content is replaced by a stub `[Inspection report for FILE — stored out-of-context. Call get_inspection_report('FILE') …]`. The same call persists the extracted report bodies via `store_inspection_report` (idempotent backfill).

3. **Frontend untouched.** The `/history` endpoint returns `stored_messages` as-is — the full report still renders in the chat for the user. Only the in-flight payload to `interpreter.chat` is scrubbed.

4. **Tool.** `get_inspection_report(filename)` is a Python helper available in the sandbox. It reads `IDEA_RUNTIME_SESSION_KEY`, calls `session_store.read_inspection_report(...)`, and returns the full markdown report. The LLM calls it when it needs to ground a plan or code in the report content.

5. **Server-side note builders untouched.** Helpers like `_build_copepod_inspect_then_code_note` still need to read raw report content to extract join hints. They receive the **un-scrubbed** history via a parallel `unscrubbed_history` variable. The scrubber is purely about what the LLM sees.

## Rationale

1. **Structural beats prompt-only.** A rule the LLM can read is a rule the LLM can rationalise around. Material not in context cannot be paraphrased. This is the only reliable form of containment for content the LLM has no legitimate reason to surface unprompted.

2. **UX preserved.** The user still sees the full report once when it streams, and again on chat replay via `/history`. We don't hide information from the human.

3. **Explicit access.** When the LLM does need the report (e.g. to pick the right column name for a graph), it must write `print(get_inspection_report('sample.csv'))` — an explicit, auditable action. This is consistent with the existing `inspect_and_report` discipline.

4. **Self-healing.** The scrubber backfills the store on every load, so legacy sessions (created before this change) migrate transparently on their next turn.

## Consequences

- **Positive:** the recurrent "X est déjà inspecté : N lignes × M colonnes, source détectée Y" leak — and the family of phrasings around it — is now structurally impossible on turns past the one where inspection ran. The "source détectéelikely_neolabs_taxon" glue artifact is killed at the source.
- **Positive:** server-side analysis (join hints, working-set updates) keeps full access through the un-scrubbed reference, so no functionality regresses.
- **Negative:** an extra tool call costs the LLM one round-trip when it does need the full report. Acceptable trade-off — most turns don't need it (the LLM works from the `Files already inspected in this session` summary and column names it has memorised from the synthesis block).
- **Negative:** if Redis loses the `inspection_reports:{session_key}` hash but messages survive, the LLM cannot recover the report through the tool. Recovery path: scrubber idempotently re-populates the store on next read, so a fresh turn after Redis loss restores the surface. Reports created before the message containing them was evicted are not recoverable — but that's the same failure mode as the messages themselves.
- **Negative:** prompt rules added for *paraphrasing* (e.g. `agents/copepod_prompt.py` "Do not paraphrase the stub") are still needed for the current-turn case, when the LLM has just fetched the report into a variable. Belt and braces; the structural fix covers prior turns, the prompt rule covers the immediate turn.

## Implementation map

- `core/session_store.py:20-99` — interface + Redis + InMem impls of the three methods
- `routers/chat_routes.py:_scrub_inspection_report_in_content` — pure helper
- `routers/chat_routes.py:_scrub_inspection_reports_for_llm` — per-message walk + persist
- `routers/chat_routes.py` (chat endpoint, ~L1739) — scrubbing hook, `unscrubbed_history` reference for server-side helpers
- `core/tool_registry/tools/copepod_data.py:get_inspection_report` — sandbox-side accessor
- `core/instruction_renderer/blocks/copepod_tool_signatures.py` — tool documentation block
- `agents/copepod_prompt.py` — prompt rule pointing LLM at the tool, banning stub paraphrase

## Related

- [`ADR 002`](002-session-key-3-segments.md) — `session_key` format used to namespace the new store
- See [[feedback-structural-over-prompt]] (user memory) — the broader principle this ADR exemplifies
