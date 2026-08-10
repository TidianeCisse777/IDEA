"""LangGraph middleware that maintains the exploration checkpoint state."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage

from agents.exploration_state import (
    IdeaAgentState,
    active_data_dependencies,
    capture_prospective_plan,
    finish_exploration_run,
    increment_forced_dependency_continuation,
    ingest_tool_evidence,
    latest_user_objective,
    new_exploration_run,
    refresh_exploration_resources,
    reconcile_data_dependencies,
    register_tool_steps,
    request_fingerprint,
    validate_exploration_run,
)


class ExplorationStateMiddleware(AgentMiddleware):
    """Track objective, resources, steps, dependencies and evidence in state."""

    state_schema = IdeaAgentState

    def __init__(self, *, thread_id: str) -> None:
        super().__init__()
        self.thread_id = thread_id

    def _inventory(self, messages: list[Any]):
        from tools.dataframe_cleanup import hidden_dataframes
        from tools.resource_inventory import build_resource_inventory
        from tools.session_store import default_store
        from tools.source_scope import source_decision_for_turn

        try:
            decision = source_decision_for_turn(
                default_store,
                self.thread_id,
                messages,
                persist=False,
            )
            authorized = decision.authorized_sources
        except Exception:
            authorized = ()
        return build_resource_inventory(
            default_store,
            self.thread_id,
            authorized_sources=authorized,
            excluded_variables=hidden_dataframes(default_store, self.thread_id),
        )

    def before_agent(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        objective = latest_user_objective(messages)
        if not objective:
            return None
        from tools.dataframe_cleanup import advance_dataframe_cleanup
        from tools.session_store import default_store

        humans = [message for message in messages if isinstance(message, HumanMessage)]
        marker = str(getattr(humans[-1], "id", None) or f"human-{len(humans)}")
        advance_dataframe_cleanup(
            default_store,
            self.thread_id,
            marker=marker,
            referenced_text=objective,
        )
        current = validate_exploration_run(state.get("exploration"))
        fingerprint = request_fingerprint(objective)
        if current is not None and current.request_fingerprint == fingerprint:
            return None
        return {
            "exploration": new_exploration_run(
                objective,
                self._inventory(messages),
            )
        }

    def before_model(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        payload = refresh_exploration_resources(
            state.get("exploration"),
            self._inventory(messages),
        )
        if payload is None:
            return None
        payload = ingest_tool_evidence(payload, messages) or payload
        payload = reconcile_data_dependencies(payload) or payload
        return {"exploration": payload}

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        payload = capture_prospective_plan(
            state.get("exploration"),
            messages,
        )
        payload = register_tool_steps(payload, messages)
        if payload is None:
            return None
        latest_ai = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            None,
        )
        if latest_ai is not None and (getattr(latest_ai, "tool_calls", None) or []):
            from tools.dataframe_cleanup import touch_dataframes
            from tools.session_store import default_store

            touch_dataframes(
                default_store,
                self.thread_id,
                str(latest_ai.tool_calls),
            )
        run = validate_exploration_run(payload)
        attempted_final_answer = bool(
            latest_ai is not None
            and not (getattr(latest_ai, "tool_calls", None) or [])
        )
        if (
            attempted_final_answer
            and active_data_dependencies(payload)
            and run is not None
            and run.forced_dependency_continuations < 2
        ):
            payload = increment_forced_dependency_continuation(payload) or payload
            return {"exploration": payload, "jump_to": "model"}
        return {"exploration": payload}

    def after_agent(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        payload = ingest_tool_evidence(state.get("exploration"), messages)
        payload = reconcile_data_dependencies(payload)
        payload = finish_exploration_run(payload, messages)
        return {"exploration": payload} if payload is not None else None
