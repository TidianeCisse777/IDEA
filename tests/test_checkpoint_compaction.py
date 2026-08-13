"""Durable checkpoint-history bounds for long Open WebUI conversations."""

from __future__ import annotations

import pytest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _long_valid_history(turns: int = 30):
    messages = []
    for turn in range(turns):
        call_id = f"call-{turn}"
        messages.extend([
            HumanMessage(content=f"Demande contradictoire ancienne {turn}", id=f"h-{turn}"),
            AIMessage(
                content="",
                id=f"a-call-{turn}",
                tool_calls=[{
                    "name": "run_pandas",
                    "args": {"code": "result = 1"},
                    "id": call_id,
                    "type": "tool_call",
                }],
            ),
            ToolMessage(
                content="1",
                id=f"tool-{turn}",
                name="run_pandas",
                tool_call_id=call_id,
                artifact={"status": "success"},
            ),
            AIMessage(content=f"Réponse {turn}", id=f"a-{turn}"),
        ])
    return messages


def test_checkpoint_compaction_keeps_a_valid_suffix_under_forty_messages():
    from agent import compact_checkpoint_messages

    compacted = compact_checkpoint_messages(_long_valid_history(), max_messages=40)

    assert len(compacted) <= 40
    assert compacted[0].additional_kwargs["checkpoint_summary"] is True
    assert isinstance(compacted[1], HumanMessage)
    assert isinstance(compacted[-1], AIMessage)
    assert "Demande contradictoire ancienne 0" not in "\n".join(
        str(message.content) for message in compacted
    )


def test_checkpoint_compaction_accumulates_archived_count_without_summary_growth():
    from agent import compact_checkpoint_messages

    first = compact_checkpoint_messages(_long_valid_history(), max_messages=40)
    extended = [
        *first,
        HumanMessage(content="Nouvelle demande", id="h-new"),
        AIMessage(content="Nouvelle réponse", id="a-new"),
    ]

    second = compact_checkpoint_messages(extended, max_messages=20)

    assert len(second) <= 20
    assert sum(
        bool(message.additional_kwargs.get("checkpoint_summary"))
        for message in second
    ) == 1
    assert second[0].additional_kwargs["archived_messages"] > first[0].additional_kwargs[
        "archived_messages"
    ]


def test_completed_langgraph_checkpoint_is_physically_rewritten_under_cap():
    from langchain.agents import create_agent
    from langchain_core.runnables import RunnableLambda
    from langgraph.checkpoint.memory import MemorySaver

    from agent import compact_checkpoint_history

    graph = create_agent(
        RunnableLambda(lambda _request: AIMessage(content="Réponse finale")),
        [],
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "checkpoint-hard-cap"}}
    graph.invoke({"messages": _long_valid_history()}, config=config)

    assert compact_checkpoint_history(graph, config, max_messages=40) is True
    messages = list(graph.get_state(config).values["messages"])
    assert len(messages) <= 40
    assert messages[0].additional_kwargs["checkpoint_summary"] is True
    assert isinstance(messages[1], HumanMessage)


@pytest.mark.asyncio
async def test_async_production_compactor_physically_rewrites_checkpoint():
    from langchain.agents import create_agent
    from langchain_core.runnables import RunnableLambda
    from langgraph.checkpoint.memory import MemorySaver

    from agent import acompact_checkpoint_history

    graph = create_agent(
        RunnableLambda(lambda _request: AIMessage(content="Réponse finale")),
        [],
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "async-checkpoint-hard-cap"}}
    await graph.ainvoke({"messages": _long_valid_history()}, config=config)

    assert await acompact_checkpoint_history(graph, config, max_messages=40) is True
    messages = list((await graph.aget_state(config)).values["messages"])
    assert len(messages) <= 40
    assert messages[0].additional_kwargs["checkpoint_summary"] is True
    assert isinstance(messages[1], HumanMessage)
