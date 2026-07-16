"""Garde exécutable d'intention graphique dans le middleware agent."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tools.output_intent import OutputIntentDecision, turn_fingerprint
from tools.tool_result import success, validate_tool_artifact


class FakeClassifier:
    def __init__(self, intent="visual", *, raises=False):
        self.intent = intent
        self.raises = raises
        self.calls = 0

    def classify(self, messages):
        self.calls += 1
        if self.raises:
            raise RuntimeError("classifier down")
        return OutputIntentDecision(
            intent=self.intent,
            confidence="high",
            reason="fixture",
            turn_fingerprint=turn_fingerprint(messages),
        )

    async def aclassify(self, messages):
        return self.classify(messages)


class BlockingClassifier(FakeClassifier):
    def __init__(self):
        super().__init__(intent="visual")
        self.entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()

    def classify(self, messages):
        self.calls += 1
        self.entered.set()
        if self.calls > 1:
            self.second_entered.set()
        self.release.wait(timeout=2)
        return OutputIntentDecision(
            intent="visual",
            confidence="high",
            reason="fixture",
            turn_fingerprint=turn_fingerprint(messages),
        )


class AsyncBlockingClassifier(FakeClassifier):
    def __init__(self):
        super().__init__(intent="visual")
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def aclassify(self, messages):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return OutputIntentDecision(
            intent="visual",
            confidence="high",
            reason="fixture",
            turn_fingerprint=turn_fingerprint(messages),
        )


def _request(name, args, call_id, messages):
    return SimpleNamespace(
        tool_call={"name": name, "args": args, "id": call_id},
        state={"messages": messages},
    )


def _successful_handler(request):
    content, artifact = success("ok")
    return ToolMessage(
        content=content,
        artifact=artifact,
        tool_call_id=request.tool_call["id"],
    )


async def _async_successful_handler(request):
    return _successful_handler(request)


def _append_completed(messages, request, result):
    return [
        *messages,
        AIMessage(content="", tool_calls=[request.tool_call]),
        result,
    ]


def test_non_visual_graph_skill_is_blocked(monkeypatch, tmp_path):
    import agent as agent_module
    from tools.session_store import SessionStore

    store = SessionStore(tmp_path)
    monkeypatch.setattr("tools.session_store.default_store", store)
    classifier = FakeClassifier(intent="non_visual")
    middleware = agent_module._ContextMiddleware(
        thread_id="non-visual", output_intent_classifier=classifier
    )
    request = _request(
        "load_skill",
        {"skill_name": "graph_planner"},
        "planner",
        [HumanMessage(content="Donne un tableau")],
    )

    result = middleware.wrap_tool_call(request, _successful_handler)

    artifact = validate_tool_artifact(result.artifact)
    assert artifact.status == "blocked"
    assert artifact.provenance["source"] == "output_intent_guard"
    assert classifier.calls == 1
    audit = (store.get("non-visual") or {}).get("meta", {}).get(
        "output_intent_decision"
    )
    assert audit["intent"] == "non_visual"


def test_one_decision_is_reused_for_planner_writer_and_render(monkeypatch, tmp_path):
    import agent as agent_module
    from tools.session_store import SessionStore

    monkeypatch.setattr("tools.session_store.default_store", SessionStore(tmp_path))
    classifier = FakeClassifier(intent="visual")
    middleware = agent_module._ContextMiddleware(
        thread_id="visual", output_intent_classifier=classifier
    )
    messages = [HumanMessage(content="Fais une carte")]

    planner = _request(
        "load_skill", {"skill_name": "graph_planner"}, "planner", messages
    )
    planner_result = middleware.wrap_tool_call(planner, _successful_handler)
    messages = _append_completed(messages, planner, planner_result)

    writer = _request(
        "load_skill", {"skill_name": "graph_writer"}, "writer", messages
    )
    writer_result = middleware.wrap_tool_call(writer, _successful_handler)
    messages = _append_completed(messages, writer, writer_result)

    render = _request("run_graph", {"code": "pass"}, "render", messages)
    render_result = middleware.wrap_tool_call(render, _successful_handler)

    assert validate_tool_artifact(planner_result.artifact).status == "success"
    assert validate_tool_artifact(writer_result.artifact).status == "success"
    assert validate_tool_artifact(render_result.artifact).status == "success"
    assert classifier.calls == 1


def test_parallel_graph_attempts_share_one_sync_classification(monkeypatch, tmp_path):
    import agent as agent_module
    from tools.session_store import SessionStore

    monkeypatch.setattr("tools.session_store.default_store", SessionStore(tmp_path))
    classifier = BlockingClassifier()
    middleware = agent_module._ContextMiddleware(
        thread_id="sync-single-flight", output_intent_classifier=classifier
    )
    messages = [HumanMessage(content="Fais une carte")]
    requests = [
        _request("load_skill", {"skill_name": "graph_planner"}, "planner-1", messages),
        _request("load_skill", {"skill_name": "graph_planner"}, "planner-2", messages),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(middleware.wrap_tool_call, requests[0], _successful_handler)
        assert classifier.entered.wait(timeout=1)
        second = executor.submit(middleware.wrap_tool_call, requests[1], _successful_handler)
        classifier.second_entered.wait(timeout=0.2)
        classifier.release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert classifier.calls == 1


@pytest.mark.asyncio
async def test_parallel_graph_attempts_share_one_async_classification(monkeypatch, tmp_path):
    import agent as agent_module
    from tools.session_store import SessionStore

    monkeypatch.setattr("tools.session_store.default_store", SessionStore(tmp_path))
    classifier = AsyncBlockingClassifier()
    middleware = agent_module._ContextMiddleware(
        thread_id="async-single-flight", output_intent_classifier=classifier
    )
    messages = [HumanMessage(content="Fais une carte")]
    requests = [
        _request("load_skill", {"skill_name": "graph_planner"}, "planner-1", messages),
        _request("load_skill", {"skill_name": "graph_planner"}, "planner-2", messages),
    ]

    first = asyncio.create_task(
        middleware.awrap_tool_call(requests[0], _async_successful_handler)
    )
    await classifier.entered.wait()
    second = asyncio.create_task(
        middleware.awrap_tool_call(requests[1], _async_successful_handler)
    )
    await asyncio.sleep(0)
    classifier.release.set()
    await asyncio.gather(first, second)

    assert classifier.calls == 1


@pytest.mark.parametrize("intent", ["non_visual", "ambiguous"])
def test_non_visual_and_ambiguous_decisions_fail_closed(intent):
    import agent as agent_module

    middleware = agent_module._ContextMiddleware(
        output_intent_classifier=FakeClassifier(intent=intent)
    )
    request = _request(
        "run_graph", {"code": "pass"}, "render", [HumanMessage(content="table")]
    )
    result = middleware.wrap_tool_call(request, _successful_handler)
    assert validate_tool_artifact(result.artifact).status == "blocked"


def test_classifier_exception_fails_closed():
    import agent as agent_module

    middleware = agent_module._ContextMiddleware(
        output_intent_classifier=FakeClassifier(raises=True)
    )
    request = _request(
        "load_skill",
        {"skill_name": "graph_planner"},
        "planner",
        [HumanMessage(content="carte")],
    )
    result = middleware.wrap_tool_call(request, _successful_handler)
    assert validate_tool_artifact(result.artifact).status == "blocked"


def test_writer_requires_current_turn_planner():
    import agent as agent_module

    middleware = agent_module._ContextMiddleware(
        output_intent_classifier=FakeClassifier(intent="visual")
    )
    request = _request(
        "load_skill",
        {"skill_name": "graph_writer"},
        "writer",
        [HumanMessage(content="carte")],
    )
    result = middleware.wrap_tool_call(request, _successful_handler)
    assert validate_tool_artifact(result.artifact).status == "blocked"
    assert "planner" in result.content.lower()


def test_old_turn_skills_do_not_authorize_render():
    import agent as agent_module

    content, artifact = success("ok")
    messages = [HumanMessage(content="ancienne carte")]
    for skill in ("graph_planner", "graph_writer"):
        call_id = f"old-{skill}"
        messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "load_skill",
                            "args": {"skill_name": skill},
                            "id": call_id,
                        }
                    ],
                ),
                ToolMessage(content=content, artifact=artifact, tool_call_id=call_id),
            ]
        )
    messages.extend([AIMessage(content="ancienne image"), HumanMessage(content="nouveau tour")])
    middleware = agent_module._ContextMiddleware(
        output_intent_classifier=FakeClassifier(intent="visual")
    )
    request = _request("run_graph", {"code": "pass"}, "render", messages)

    result = middleware.wrap_tool_call(request, _successful_handler)

    assert validate_tool_artifact(result.artifact).status == "blocked"
    assert "current turn" in result.content.lower()


@pytest.mark.asyncio
async def test_async_guard_matches_sync_guard():
    import agent as agent_module

    classifier = FakeClassifier(intent="non_visual")
    middleware = agent_module._ContextMiddleware(
        output_intent_classifier=classifier
    )
    request = _request(
        "load_skill",
        {"skill_name": "graph_planner"},
        "planner",
        [HumanMessage(content="tableau")],
    )

    result = await middleware.awrap_tool_call(request, _async_successful_handler)

    assert validate_tool_artifact(result.artifact).status == "blocked"
    assert classifier.calls == 1
