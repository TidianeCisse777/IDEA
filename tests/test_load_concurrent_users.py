"""Load / concurrency tests — simulate ~10 users at once. NO real LLM calls.

Both tests stub the model layer, so they burn zero provider tokens. They cover
the two concurrency-critical seams:

1. The HTTP request path (``chat_completions``) — isolation between users and
   no cross-request contamination when 10 requests run concurrently.
2. The short-term checkpointer under concurrent writers — the property P1
   (Postgres-first checkpointer) exists to protect. Exercised here on the
   default SQLite backend via a trivial LangGraph (no LLM).
"""

import asyncio
import operator
import time
from typing import Annotated, TypedDict
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage


N_USERS = 10


class _FakeAgent:
    """Stands in for the real LangGraph agent — echoes thread_id + user text.

    Zero tokens: no provider call. ``aget_state`` raises so the pre-invoke
    ``arepair_invalid_tool_history`` short-circuits to a no-op (it catches).
    """

    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id

    async def aget_state(self, config):  # noqa: D401 — repair helper swallows this
        raise RuntimeError("no state in fake agent")

    async def ainvoke(self, messages, config=None):
        incoming = messages["messages"][-1]["content"]
        if not isinstance(incoming, str):
            incoming = str(incoming)
        # Simulate a little async I/O (as a real LLM round-trip would).
        await asyncio.sleep(0.01)
        return {"messages": [AIMessage(content=f"ACK::{self.thread_id}::{incoming}")]}


@pytest.mark.asyncio
async def test_ten_concurrent_users_isolated_zero_tokens(monkeypatch):
    """10 users hit ``chat_completions`` at once; each gets only its own reply."""
    import serve as serve_module

    monkeypatch.setattr(
        serve_module,
        "make_agent",
        lambda thread_id, user_id="anonymous": _FakeAgent(thread_id),
    )
    # Keep the handler offline: no OpenWebUI SQLite lookup for attached files.
    monkeypatch.setattr(serve_module, "resolve_chat_files", lambda *a, **k: ("", []))

    async def _one_user(i: int):
        secret = f"secret-{i}-{time.monotonic_ns()}"
        req = serve_module.ChatRequest(
            model="copepod-agent",
            stream=False,
            chat_id=f"chat-{i}",
            messages=[serve_module.Message(role="user", content=secret)],
        )
        request = MagicMock()
        request.headers = {}
        resp = await serve_module.chat_completions(
            req,
            request,
            x_openwebui_chat_id=f"chat-{i}",
            x_openwebui_user_id=f"uid-{i}",
            x_openwebui_message_id=f"msg-{i}",
            x_openwebui_user_name=None,
            x_openwebui_user_email=None,
            x_openwebui_user_role=None,
        )
        return i, secret, resp

    start = time.monotonic()
    results = await asyncio.gather(*[_one_user(i) for i in range(N_USERS)])
    elapsed = time.monotonic() - start

    all_secrets = {secret for _, secret, _ in results}
    for i, secret, resp in results:
        content = resp["choices"][0]["message"]["content"]
        # Own secret echoed back...
        assert secret in content, f"user {i} lost its own message"
        # ...and NO other user's secret bled into this response.
        foreign = (all_secrets - {secret}) & {s for s in all_secrets if s in content}
        assert not foreign, f"cross-user leak into user {i}: {foreign}"

    # 10 concurrent async requests should overlap, not run serially
    # (10 * 0.01s sleep = 0.1s floor; serial-with-overhead would be far higher).
    assert elapsed < 2.0, f"10 concurrent users took {elapsed:.2f}s — no overlap?"


class _CountState(TypedDict):
    seen: Annotated[list[str], operator.add]


async def _passthrough(state):
    # No-op node: the per-call marker is merged into `seen` by the reducer on
    # input, so state accumulates one marker per invocation for that thread.
    return {"seen": []}


def _build_counter_graph(checkpointer):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_CountState)
    graph.add_node("passthrough", _passthrough)
    graph.add_edge(START, "passthrough")
    graph.add_edge("passthrough", END)
    return graph.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
async def test_checkpointer_handles_concurrent_users(tmp_path):
    """10 threads × 5 turns hammer one SQLite checkpointer — isolation holds.

    This is the exact contention P1 (Postgres checkpointer) removes at scale;
    on SQLite it must at least stay correct: each thread sees only its own
    markers, with no lost writes or cross-thread bleed. No LLM, zero tokens.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    turns_per_user = 5
    db_path = tmp_path / "cp_load.sqlite"

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        app = _build_counter_graph(saver)

        async def _user_session(u: int):
            config = {"configurable": {"thread_id": f"thread-{u}"}}
            for k in range(turns_per_user):
                await app.ainvoke({"seen": [f"thread-{u}#turn{k}"]}, config)
            snapshot = await app.aget_state(config)
            return u, snapshot.values.get("seen", [])

        start = time.monotonic()
        results = await asyncio.gather(*[_user_session(u) for u in range(N_USERS)])
        elapsed = time.monotonic() - start

    for u, seen in results:
        assert len(seen) == turns_per_user, f"thread-{u} lost writes: {seen}"
        # Every marker in this thread's state must belong to this thread.
        assert all(
            m.startswith(f"thread-{u}#") for m in seen
        ), f"cross-thread bleed into thread-{u}: {seen}"

    assert elapsed < 10.0, f"checkpointer load took {elapsed:.2f}s — contention?"
