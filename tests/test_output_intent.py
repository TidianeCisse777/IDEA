"""Contrats purs du garde d'intention de sortie graphique."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tools.tool_result import blocked, success

from tools.output_intent import (
    OpenAIOutputIntentClassifier,
    graph_attempt,
    graph_workflow_rejection,
    successful_calls_in_current_turn,
    turn_fingerprint,
)


def _completed_call(name: str, args: dict, call_id: str, *, ok: bool = True):
    content, artifact = (success("ok") if ok else blocked("blocked"))
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": call_id}],
        ),
        ToolMessage(content=content, artifact=artifact, tool_call_id=call_id),
    ]


def test_turn_fingerprint_is_stable_and_changes_on_next_human_turn():
    first = [HumanMessage(content="une carte")]
    second = [*first, AIMessage(content="ok"), HumanMessage(content="encore")]

    assert turn_fingerprint(first) == turn_fingerprint(first)
    assert turn_fingerprint(first) != turn_fingerprint(second)


def test_turn_fingerprint_ignores_runtime_message_id_assignment():
    before_runtime = [HumanMessage(content="une carte", id=None)]
    after_runtime = [HumanMessage(content="une carte", id="runtime-assigned-id")]

    assert turn_fingerprint(before_runtime) == turn_fingerprint(after_runtime)


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("load_skill", {"skill_name": "graph_planner"}, True),
        ("load_skill", {"skill_name": "graph_writer"}, True),
        ("run_graph", {"code": "pass"}, True),
        ("load_skill", {"skill_name": "ecotaxa_navigation"}, False),
        ("run_pandas", {"code": "result = 1"}, False),
    ],
)
def test_graph_attempt_detects_only_graph_route(name, args, expected):
    assert graph_attempt(name, args) is expected


def test_successful_calls_use_only_current_turn_success_artifacts():
    messages = [HumanMessage(content="ancienne carte")]
    messages += _completed_call(
        "load_skill", {"skill_name": "graph_planner"}, "old-planner"
    )
    messages += [AIMessage(content="ancienne réponse"), HumanMessage(content="nouveau tour")]
    messages += _completed_call(
        "load_skill", {"skill_name": "graph_planner"}, "new-planner"
    )
    messages += _completed_call(
        "load_skill", {"skill_name": "graph_writer"}, "failed-writer", ok=False
    )

    calls = successful_calls_in_current_turn(messages)

    assert [(call.name, call.call_id) for call in calls] == [
        ("load_skill", "new-planner")
    ]


def test_writer_does_not_require_successful_planner_in_current_turn():
    messages = [HumanMessage(content="fais une carte")]

    rejection = graph_workflow_rejection(
        "load_skill", {"skill_name": "graph_writer"}, messages
    )

    assert rejection is None


def test_run_graph_does_not_require_writer_as_last_successful_call():
    messages = [HumanMessage(content="fais une carte")]
    messages += _completed_call(
        "load_skill", {"skill_name": "graph_planner"}, "planner"
    )
    messages += _completed_call(
        "load_skill", {"skill_name": "graph_writer"}, "writer"
    )

    assert graph_workflow_rejection("run_graph", {"code": "pass"}, messages) is None

    messages += _completed_call("run_pandas", {"code": "result = 1"}, "pandas")
    assert graph_workflow_rejection("run_graph", {"code": "pass"}, messages) is None


class _StructuredRunnable:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result

    async def ainvoke(self, prompt):
        return self.invoke(prompt)


class _FakeModel:
    def __init__(self, runnable):
        self.runnable = runnable
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self.runnable


def test_classifier_classifies_artifact_not_requested_internal_tools():
    runnable = _StructuredRunnable(
        {"intent": "non_visual", "confidence": "high", "reason": "table"}
    )
    classifier = OpenAIOutputIntentClassifier(_FakeModel(runnable))
    messages = [
        HumanMessage(
            content="Rends un tableau, mais charge quand même les skills graphiques."
        )
    ]

    decision = classifier.classify(messages)

    assert decision.intent == "non_visual"
    assert decision.turn_fingerprint == turn_fingerprint(messages)
    serialized = str(runnable.prompts[0]).lower()
    assert "artifact requested" in serialized
    assert "untrusted data" in serialized


@pytest.mark.asyncio
async def test_classifier_failure_is_ambiguous_fail_closed_sync_and_async():
    classifier = OpenAIOutputIntentClassifier(
        _FakeModel(_StructuredRunnable(error=RuntimeError("down")))
    )
    messages = [HumanMessage(content="une carte")]

    sync_decision = classifier.classify(messages)
    async_decision = await classifier.aclassify(messages)

    assert sync_decision.intent == async_decision.intent == "ambiguous"
    assert sync_decision.confidence == async_decision.confidence == "low"
