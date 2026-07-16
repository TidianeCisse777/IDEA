"""Strict Pydantic boundaries for LangChain tool arguments."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, create_model


@lru_cache(maxsize=None)
def _strict_model(source: type[BaseModel]) -> type[BaseModel]:
    """Clone an inferred LangChain schema without its coercive defaults."""
    config = dict(source.model_config)
    config.update(strict=True, extra="forbid")
    fields = {
        name: (field.annotation, deepcopy(field))
        for name, field in source.model_fields.items()
    }
    return create_model(
        f"{source.__name__}Strict",
        __config__=ConfigDict(**config),
        __module__=source.__module__,
        **fields,
    )


def strict_tool_args_schema(tool: BaseTool) -> type[BaseModel]:
    """Return the strict, extra-forbid schema for one LangChain tool."""
    schema = tool.args_schema
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise ValueError(f"Tool {tool.name} has no Pydantic args schema")
    return _strict_model(schema)


def apply_strict_tool_schema(tool: BaseTool) -> BaseTool:
    """Apply the strict schema in place while preserving the tool identity."""
    tool.args_schema = strict_tool_args_schema(tool)
    return tool
