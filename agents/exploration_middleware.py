"""LangGraph middleware that maintains the exploration checkpoint state."""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.exploration_state import (
    IdeaAgentState,
    finish_exploration_run,
    ingest_tool_evidence,
    latest_user_objective,
    new_exploration_run,
    refresh_exploration_resources,
    reconcile_data_dependencies,
    register_tool_steps,
    request_fingerprint,
    validate_exploration_run,
)


def _tool_call_identity(tool_call: dict[str, Any]) -> str:
    """Canonical identity for an exact tool name + arguments pair."""
    return json.dumps(
        {
            "name": str(tool_call.get("name") or ""),
            "args": tool_call.get("args") or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _successful_duplicate(
    messages: list[Any],
    current_call: dict[str, Any],
) -> ToolMessage | None:
    """Find an identical successful call earlier in the current user turn."""
    last_human = max(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, HumanMessage)
        ),
        default=-1,
    )
    current_id = str(current_call.get("id") or "")
    target = _tool_call_identity(current_call)
    matching_ids: set[str] = set()
    for message in messages[last_human + 1 :]:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                call_id = str(call.get("id") or "")
                if call_id and call_id != current_id and _tool_call_identity(call) == target:
                    matching_ids.add(call_id)
            continue
        if not isinstance(message, ToolMessage):
            continue
        if str(message.tool_call_id or "") not in matching_ids:
            continue
        artifact = message.artifact if isinstance(message.artifact, dict) else {}
        status = str(artifact.get("status") or message.status or "")
        if status == "success":
            return message
    return None


def _reuse_duplicate_result(request, previous: ToolMessage) -> ToolMessage:  # noqa: ANN001
    """Return prior successful evidence without executing the duplicate call."""
    artifact = dict(previous.artifact or {}) if isinstance(previous.artifact, dict) else {}
    metrics = dict(artifact.get("metrics") or {})
    metrics["duplicate_skipped"] = True
    artifact["metrics"] = metrics
    previous_content = (
        previous.content
        if isinstance(previous.content, str)
        else json.dumps(previous.content, ensure_ascii=False, default=str)
    )
    return ToolMessage(
        content=(
            "Appel strictement identique déjà réussi; résultat réutilisé sans "
            f"réexécution.\n{previous_content}"
        ),
        artifact=artifact,
        tool_call_id=str(request.tool_call.get("id") or ""),
        name=str(request.tool_call.get("name") or previous.name or ""),
        status="success",
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
        inventory = self._inventory(messages)
        if current is not None and current.request_fingerprint == fingerprint:
            return {
                "exploration": refresh_exploration_resources(
                    state.get("exploration"), inventory
                )
            }
        return {
            "exploration": new_exploration_run(
                objective,
                inventory,
            )
        }

    def before_model(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        trailing_tools: list[ToolMessage] = []
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                break
            trailing_tools.append(message)
        state_aware = {"load_file", "run_pandas"}
        needs_legacy_refresh = bool(trailing_tools) and any(
            message.name not in state_aware for message in trailing_tools
        )
        if needs_legacy_refresh:
            payload = refresh_exploration_resources(
                state.get("exploration"),
                self._inventory(messages),
            )
        else:
            payload = state.get("exploration")
        if payload is None:
            return None
        payload = ingest_tool_evidence(payload, messages) or payload
        payload = reconcile_data_dependencies(payload) or payload
        return {"exploration": payload}

    def after_model(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        payload = register_tool_steps(state.get("exploration"), messages)
        if payload is None:
            return None
        latest_ai = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            None,
        )
        if latest_ai is not None:
            from tools.dataframe_cleanup import touch_dataframes
            from tools.session_store import default_store

            tool_calls = getattr(latest_ai, "tool_calls", None) or []
            touch_dataframes(
                default_store,
                self.thread_id,
                f"{tool_calls}\n{latest_ai.content}",
            )
        return {"exploration": payload}

    def wrap_tool_call(self, request, handler):  # noqa: ANN001
        previous = _successful_duplicate(
            list(request.state.get("messages") or []),
            request.tool_call,
        )
        if previous is not None:
            return _reuse_duplicate_result(request, previous)
        return handler(request)

    async def awrap_tool_call(self, request, handler):  # noqa: ANN001
        previous = _successful_duplicate(
            list(request.state.get("messages") or []),
            request.tool_call,
        )
        if previous is not None:
            return _reuse_duplicate_result(request, previous)
        return await handler(request)

    def after_agent(self, state: IdeaAgentState, runtime) -> dict[str, Any] | None:  # noqa: ANN001
        messages = list(state.get("messages") or [])
        payload = ingest_tool_evidence(state.get("exploration"), messages)
        payload = reconcile_data_dependencies(payload)
        payload = finish_exploration_run(payload, messages)
        return {"exploration": payload} if payload is not None else None
