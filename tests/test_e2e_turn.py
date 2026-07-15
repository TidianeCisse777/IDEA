"""Regression tests for the step-by-step E2E driver."""

from typing import TypedDict

from langgraph.graph import StateGraph

from scripts.dev.e2e_turn import persistent_checkpointer


class _State(TypedDict):
    value: int


def _increment(state: _State) -> _State:
    return {"value": state["value"] + 1}


def _graph(checkpointer):
    builder = StateGraph(_State)
    builder.add_node("increment", _increment)
    builder.set_entry_point("increment")
    builder.set_finish_point("increment")
    return builder.compile(checkpointer=checkpointer)


def test_persistent_checkpointer_survives_driver_process_restart(tmp_path):
    """Two driver invocations must share prior LangGraph conversation state."""
    path = tmp_path / "e2e-checkpoints.sqlite"
    config = {"configurable": {"thread_id": "step-by-step"}}

    with persistent_checkpointer(path) as checkpointer:
        _graph(checkpointer).invoke({"value": 0}, config=config)

    with persistent_checkpointer(path) as checkpointer:
        snapshot = _graph(checkpointer).get_state(config)

    assert snapshot.values == {"value": 1}
