"""Structured result envelope shared by every IDEA tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

ToolStatus: TypeAlias = Literal["success", "empty", "blocked", "error", "cancelled"]
ToolResultSchema: TypeAlias = Literal["legacy_text", "tool_result_v1"]
ToolArtifact: TypeAlias = dict[str, Any]
ToolOutput: TypeAlias = tuple[Any, ToolArtifact]
_DEFAULT_CONTENT = object()


class ToolResult(BaseModel):
    """Machine-readable outcome carried in ``ToolMessage.artifact``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ToolStatus
    summary: str = Field(min_length=1)
    data_ref: str | None = None
    artifact_refs: tuple[str, ...] = ()
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    persisted: bool = False
    retryable: bool = False
    method: str | None = None
    metrics: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def _summary_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value

    def as_tool_output(self) -> ToolOutput:
        """Return LangChain's native content-and-artifact pair."""
        return self.summary, self.model_dump(mode="json")


def _result(
    status: ToolStatus,
    summary: str,
    *,
    content: Any = _DEFAULT_CONTENT,
    **fields: Any,
) -> ToolOutput:
    result = ToolResult(status=status, summary=summary, **fields)
    visible = summary if content is _DEFAULT_CONTENT else content
    return visible, result.model_dump(mode="json")


def success(summary: str, **fields: Any) -> ToolOutput:
    return _result("success", summary, **fields)


def empty(summary: str, **fields: Any) -> ToolOutput:
    return _result("empty", summary, **fields)


def blocked(summary: str, **fields: Any) -> ToolOutput:
    return _result("blocked", summary, **fields)


def error(summary: str, **fields: Any) -> ToolOutput:
    return _result("error", summary, **fields)


def cancelled(summary: str, **fields: Any) -> ToolOutput:
    return _result("cancelled", summary, **fields)


def validate_tool_artifact(value: object) -> ToolResult:
    """Validate one artifact and reject legacy/unstructured outcomes."""
    if not isinstance(value, Mapping):
        raise ValueError("Tool output is not a structured ToolResult artifact")
    try:
        return ToolResult.model_validate(dict(value))
    except Exception as exc:
        raise ValueError("Tool output is not a valid structured ToolResult artifact") from exc
