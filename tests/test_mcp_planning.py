from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from uuid import uuid4


def _install_optional_dependency_stubs() -> None:
    """Keep these unit tests independent from optional runtime integrations."""
    interpreter_pkg = types.ModuleType("interpreter")
    interpreter_core_pkg = types.ModuleType("interpreter.core")
    interpreter_core_core_pkg = types.ModuleType("interpreter.core.core")

    class OpenInterpreter:
        pass

    interpreter_core_core_pkg.OpenInterpreter = OpenInterpreter
    sys.modules.setdefault("interpreter", interpreter_pkg)
    sys.modules.setdefault("interpreter.core", interpreter_core_pkg)
    sys.modules.setdefault("interpreter.core.core", interpreter_core_core_pkg)

    litellm_pkg = types.ModuleType("litellm")
    litellm_pkg.completion = lambda *args, **kwargs: None
    litellm_pkg.transcription = lambda *args, **kwargs: None
    sys.modules.setdefault("litellm", litellm_pkg)

    rag_store_pkg = types.ModuleType("core.rag_store")
    rag_store_pkg.ensure_user_pqa_settings = lambda *args, **kwargs: None
    sys.modules.setdefault("core.rag_store", rag_store_pkg)


_install_optional_dependency_stubs()

import routers.chat_routes as chat_routes  # noqa: E402


@dataclass
class FakeConnection:
    name: str = "GitHub"

    def __post_init__(self) -> None:
        self.id = uuid4()


class FakeInterpreter:
    def __init__(self) -> None:
        self.llm = types.SimpleNamespace(model="fake-planner")
        self.messages: list[dict] = []


def _planner_response(tool_name: str, arguments: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": tool_name,
                                "arguments": arguments,
                            }
                        }
                    ]
                }
            }
        ]
    }


def _empty_planner_response() -> dict:
    return {"choices": [{"message": {"tool_calls": []}}]}


def test_no_active_tools_skips_planner_and_mcp_execution(monkeypatch):
    async def fake_gather_available_mcp_tools(db):
        return [], {}

    def fail_completion(*args, **kwargs):
        raise AssertionError("planner should not run without MCP tools")

    async def fail_call_tool(*args, **kwargs):
        raise AssertionError("MCP tool should not run without MCP tools")

    monkeypatch.setattr(chat_routes, "gather_available_mcp_tools", fake_gather_available_mcp_tools)
    monkeypatch.setattr(chat_routes, "completion", fail_completion)
    monkeypatch.setattr(chat_routes.mcp_manager, "call_tool", fail_call_tool)

    interpreter = FakeInterpreter()

    executed = asyncio.run(
        chat_routes.plan_and_run_mcp_tools(
            interpreter=interpreter,
            user_message="list my repos",
            db=object(),
        )
    )

    assert executed == []
    assert interpreter.messages == []


def test_invalid_planner_arguments_become_empty_dict(monkeypatch):
    connection = FakeConnection()
    tool = {"name": "list_repos"}
    tool_id = "mcp_fake_list_repos"
    calls = []

    async def fake_gather_available_mcp_tools(db):
        return [{"type": "function", "function": {"name": tool_id}}], {tool_id: (connection, tool)}

    def fake_completion(*args, **kwargs):
        return _planner_response(tool_id, "{not valid json")

    async def fake_call_tool(conn, tool_name, arguments):
        calls.append((conn, tool_name, arguments))
        return {"structuredContent": {"ok": True}}

    monkeypatch.setattr(chat_routes, "gather_available_mcp_tools", fake_gather_available_mcp_tools)
    monkeypatch.setattr(chat_routes, "completion", fake_completion)
    monkeypatch.setattr(chat_routes.mcp_manager, "call_tool", fake_call_tool)

    executed = asyncio.run(
        chat_routes.plan_and_run_mcp_tools(
            interpreter=FakeInterpreter(),
            user_message="list my repos",
            db=object(),
        )
    )

    assert calls == [(connection, "list_repos", {})]
    assert executed[0]["arguments"] == {}


def test_duplicate_planner_calls_execute_mcp_once(monkeypatch):
    connection = FakeConnection()
    tool = {"name": "list_repos"}
    tool_id = "mcp_fake_list_repos"
    call_count = 0

    async def fake_gather_available_mcp_tools(db):
        return [{"type": "function", "function": {"name": tool_id}}], {tool_id: (connection, tool)}

    def fake_completion(*args, **kwargs):
        return _planner_response(tool_id, '{"owner": "octo"}')

    async def fake_call_tool(conn, tool_name, arguments):
        nonlocal call_count
        call_count += 1
        return {"structuredContent": {"items": [{"name": "repo"}]}}

    monkeypatch.setattr(chat_routes, "gather_available_mcp_tools", fake_gather_available_mcp_tools)
    monkeypatch.setattr(chat_routes, "completion", fake_completion)
    monkeypatch.setattr(chat_routes.mcp_manager, "call_tool", fake_call_tool)

    executed = asyncio.run(
        chat_routes.plan_and_run_mcp_tools(
            interpreter=FakeInterpreter(),
            user_message="list octo repos",
            db=object(),
        )
    )

    assert call_count == 1
    assert len(executed) == 1
    assert executed[0]["arguments"] == {"owner": "octo"}


def test_mcp_error_is_injected_as_result_without_crashing(monkeypatch):
    connection = FakeConnection()
    tool = {"name": "list_repos"}
    tool_id = "mcp_fake_list_repos"

    async def fake_gather_available_mcp_tools(db):
        return [{"type": "function", "function": {"name": tool_id}}], {tool_id: (connection, tool)}

    def fake_completion(*args, **kwargs):
        return _planner_response(tool_id, "{}")

    async def fake_call_tool(conn, tool_name, arguments):
        raise RuntimeError("MCP unavailable")

    monkeypatch.setattr(chat_routes, "gather_available_mcp_tools", fake_gather_available_mcp_tools)
    monkeypatch.setattr(chat_routes, "completion", fake_completion)
    monkeypatch.setattr(chat_routes.mcp_manager, "call_tool", fake_call_tool)

    interpreter = FakeInterpreter()

    executed = asyncio.run(
        chat_routes.plan_and_run_mcp_tools(
            interpreter=interpreter,
            user_message="list my repos",
            db=object(),
        )
    )

    assert executed[0]["result"] == {"error": "MCP unavailable"}
    assert "CONTEXT (do not expose directly)" in interpreter.messages[0]["content"]
    assert '"error": "MCP unavailable"' in interpreter.messages[0]["content"]


def test_json_mcp_result_is_injected_as_context_with_no_raw_json_instruction(monkeypatch):
    connection = FakeConnection()
    tool = {"name": "list_repos"}
    tool_id = "mcp_fake_list_repos"
    raw_json = '{"items":[{"name":"idea","private":false}]}'

    async def fake_gather_available_mcp_tools(db):
        return [{"type": "function", "function": {"name": tool_id}}], {tool_id: (connection, tool)}

    responses = iter([_planner_response(tool_id, "{}"), _empty_planner_response()])

    def fake_completion(*args, **kwargs):
        return next(responses)

    async def fake_call_tool(conn, tool_name, arguments):
        return {"content": [{"type": "text", "text": raw_json}]}

    monkeypatch.setattr(chat_routes, "gather_available_mcp_tools", fake_gather_available_mcp_tools)
    monkeypatch.setattr(chat_routes, "completion", fake_completion)
    monkeypatch.setattr(chat_routes.mcp_manager, "call_tool", fake_call_tool)

    interpreter = FakeInterpreter()

    executed = asyncio.run(
        chat_routes.plan_and_run_mcp_tools(
            interpreter=interpreter,
            user_message="list my repos",
            db=object(),
        )
    )

    assert len(executed) == 1
    assert len(interpreter.messages) == 1
    content = interpreter.messages[0]["content"]
    assert content.startswith("CONTEXT (do not expose directly): MCP GitHub • list_repos ->")
    assert raw_json in content
    assert "Do NOT output raw JSON" in content
