"""Contrat commun des résultats structurés de l'étape 2B."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from pydantic import ValidationError


def test_tool_result_serializes_the_complete_envelope():
    from tools.tool_result import success, validate_tool_artifact

    content, artifact = success(
        "Table chargée.",
        data_ref="df_ecotaxa",
        artifact_refs=("/downloads/data.tsv",),
        provenance={"source": "ecotaxa", "project_id": 42},
        persisted=True,
        method="EcoTaxa export",
        metrics={"rows": 12},
    )
    result = validate_tool_artifact(artifact)

    assert content == "Table chargée."
    assert result.status == "success"
    assert result.summary == content
    assert result.data_ref == "df_ecotaxa"
    assert result.artifact_refs == ("/downloads/data.tsv",)
    assert result.provenance == {"source": "ecotaxa", "project_id": 42}
    assert result.persisted is True
    assert result.retryable is False
    assert result.method == "EcoTaxa export"
    assert result.metrics == {"rows": 12}
    json.dumps(artifact)


def test_all_five_status_helpers_are_explicit():
    from tools.tool_result import blocked, cancelled, empty, error, success

    outputs = [
        success("ok"),
        empty("vide"),
        blocked("bloqué"),
        error("erreur", retryable=True),
        cancelled("annulé"),
    ]

    assert [artifact["status"] for _, artifact in outputs] == [
        "success",
        "empty",
        "blocked",
        "error",
        "cancelled",
    ]
    assert outputs[3][1]["retryable"] is True


def test_tool_result_rejects_unknown_fields_and_blank_summary():
    from tools.tool_result import ToolResult

    with pytest.raises(ValidationError):
        ToolResult(status="success", summary="")
    with pytest.raises(ValidationError):
        ToolResult(status="success", summary="ok", guessed=True)


def test_langchain_keeps_text_content_and_attaches_structured_artifact():
    from tools.tool_result import success, validate_tool_artifact

    @tool(response_format="content_and_artifact")
    def demo(value: int):
        """Return one structured demonstration result."""
        return success("résumé visible", metrics={"value": value})

    assert demo.invoke({"value": 3}) == "résumé visible"
    message = demo.invoke(
        {"type": "tool_call", "id": "call-1", "name": "demo", "args": {"value": 3}}
    )

    assert isinstance(message, ToolMessage)
    assert message.content == "résumé visible"
    assert validate_tool_artifact(message.artifact).metrics == {"value": 3}


def test_validate_tool_artifact_fails_closed_on_legacy_text():
    from tools.tool_result import validate_tool_artifact

    with pytest.raises(ValueError, match="structured ToolResult"):
        validate_tool_artifact("Erreur historique")
