# Conversation Lifecycle Design

## Context

IDEA persists the active DataFrame and its metadata through `SessionStore` or
`SessionStorePG`. A conversation also owns derived entries whose keys start
with `<thread_id>:` (source aliases, named datasets, selections and enriched
tables).

`serve.py` currently keeps `_known_threads` only in process memory. On the
first request for a stable conversation after every process restart, the
server treats the thread as new and calls `default_store.clear(thread_id)`.
This deletes the active entry even though the store promises persistence. It
does not delete the derived entries, leaving an incoherent mixture of missing
active state and stale aliases.

## Decision

Conversation state is resumed by default. Receiving a request for a stable
`thread_id` must never delete persisted data implicitly.

The existing storage modules are deepened with one explicit operation:
`clear_conversation(thread_id)`. It deletes exactly:

- the active key equal to `thread_id`;
- every derived key beginning with `thread_id + ":"`.

It must not delete a neighboring conversation such as `thread_id-other` or a
longer identifier that merely shares the same characters.

No reset endpoint is added in this change. The operation remains an internal,
tested interface until an authenticated Open WebUI deletion/reset flow needs
it. The existing `clear(key)` retains its exact-key semantics for callers that
delete one dataset or alias.

## Adapters

### File-backed `SessionStore`

`clear_conversation` discovers the exact key and colon-prefixed keys through
the store's public `keys()` interface, then delegates exact deletion to
`clear()`. This removes both cached entries and their `.json`/`.pkl` files.

### PostgreSQL-backed `SessionStorePG`

`clear_conversation` provides the same observable contract. The metadata rows
are selected and deleted as one database operation for the exact key and the
escaped colon-prefixed family. Associated DataFrame files are removed after
the rows cease to be addressable. A missing conversation is a successful
no-op, matching `clear()`.

The SQL prefix must treat `%` and `_` as literals if an arbitrary caller ever
passes them, even though production thread IDs are hexadecimal hashes.

## Server flow

`serve.py` no longer owns `_known_threads`. The request path derives the stable
conversation key and `thread_id`, prepares attachments and invokes the agent
without mutating persisted session data. A new Open WebUI chat naturally gets
a new `thread_id`; an existing `chat_id` naturally resumes its existing
DataFrame family.

LangGraph checkpoint persistence is unchanged. Because the request path stops
deleting the active DataFrame, checkpoint history and tabular session state
remain aligned after a restart.

## Error handling

- Resuming a conversation performs no storage write and therefore introduces
  no new failure mode.
- Explicit family deletion is idempotent.
- File cleanup ignores an already-missing file, consistent with `clear()`.
- PostgreSQL failures propagate to the internal caller; no partial success is
  reported through an HTTP interface because this change adds none.

## Tests

The implementation is driven by these regression tests:

1. A request using an existing stable `chat_id` does not call `clear()` or
   `clear_conversation()` after simulated process startup.
2. A file-backed store created over an existing storage directory reloads the
   active DataFrame and all aliases, proving restart persistence.
3. `clear_conversation()` removes the active key and all `thread_id:*` keys.
4. It preserves keys that only share a textual prefix.
5. The PostgreSQL adapter satisfies the same family-deletion contract when the
   opt-in test database is configured.
6. Existing single-key `clear()` behavior remains unchanged.

## Documentation

`ARCHITECTURE.md` documents the invariant: stable conversations resume by
default; resetting a conversation is explicit and family-wide. No routing rule
or system prompt change is required.

## Out of scope

- Public or unauthenticated reset endpoints.
- Open WebUI delete-event integration.
- Deleting LangGraph checkpoints or long-term user memories.
- Changing dataset key names or persistence formats.
