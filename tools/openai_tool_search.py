"""OpenAI hosted Tool Search projection for the IDEA tool catalog.

The LangGraph ToolNode is still built with the real ``BaseTool`` instances.
This module only changes the provider-facing declaration: local/core tools stay
immediately visible, while specialized source tools are placed in compact
namespaces whose detailed schemas are loaded by OpenAI only when needed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from tools.tool_catalog import ToolPolicy


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_SUPPORTED_MODEL = re.compile(r"(?:^|/)gpt-(\d+)\.(\d+)(?:-|$)", re.IGNORECASE)


@dataclass(frozen=True)
class ToolSearchNamespace:
    """One searchable provider namespace and its executable member names."""

    name: str
    description: str
    member_names: tuple[str, ...]
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolSearchProjection:
    """Exact OpenAI-facing tools plus an auditable inventory."""

    provider_tools: tuple[BaseTool | dict[str, Any], ...]
    immediate_names: tuple[str, ...]
    namespaces: tuple[ToolSearchNamespace, ...]
    excluded_names: tuple[str, ...]

    @property
    def provider_surface_names(self) -> tuple[str, ...]:
        names = (
            *self.immediate_names,
            *(namespace.name for namespace in self.namespaces),
        )
        return (*names, "tool_search") if self.namespaces else names

    @property
    def searchable_member_names(self) -> tuple[str, ...]:
        return tuple(
            member
            for namespace in self.namespaces
            for member in namespace.member_names
        )


_NAMESPACE_DESCRIPTIONS: Mapping[str, str] = {
    "ecotaxa": (
        "EcoTaxa data access. Inspect the local cache schema, run read-only SQL "
        "over cached samples and mounted session DataFrames, or export confirmed "
        "EcoTaxa samples. Use when the requested evidence lives in EcoTaxa."
    ),
    "ecopart": (
        "EcoPart lookup and enrichment. Find or preview EcoPart counterparts for "
        "EcoTaxa data and enrich a qualified session DataFrame while preserving "
        "join provenance."
    ),
    "geography": (
        "Named-zone geography for session DataFrames. Describe a supported zone, "
        "filter one DataFrame to one or several polygon zones, or split it by zone."
    ),
    "environmental_enrichment": (
        "Environmental source lookup and enrichment for qualified session "
        "DataFrames: Amundsen CTD profiles, Bio-ORACLE layers, and OGSL CTD data. "
        "Choose the source whose coverage and variables answer the user request."
    ),
}


def _namespace_name(policy: ToolPolicy) -> str | None:
    if policy.source in {"ecotaxa", "ecopart", "geography"}:
        return policy.source
    if policy.source in {"amundsen", "bio_oracle", "ogsl"}:
        return "environmental_enrichment"
    return ""


def _is_supported_openai_model(model: str) -> bool:
    match = _SUPPORTED_MODEL.search(str(model or "").strip())
    if match is None:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (5, 4)


def openai_tool_search_enabled(
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> bool:
    """Return true only for an explicitly enabled, compatible OpenAI route."""

    if os.getenv("OPENAI_TOOL_SEARCH_ENABLED", "false").strip().lower() not in _TRUE_VALUES:
        return False
    selected_model = model or os.getenv("LLM_MODEL", "")
    if not _is_supported_openai_model(selected_model):
        return False
    endpoint = base_url if base_url is not None else os.getenv("OPENAI_BASE_URL", "")
    host = urlparse(endpoint).hostname if endpoint else "api.openai.com"
    return host == "api.openai.com"


def _responses_function_schema(tool: BaseTool) -> dict[str, Any]:
    """Flatten a LangChain function schema for a Responses API namespace."""

    converted = convert_to_openai_tool(tool)
    function = dict(converted.get("function") or {})
    if not function:
        raise ValueError(f"Tool {tool.name!r} is not an OpenAI function tool")
    return {
        "type": "function",
        **function,
        "defer_loading": True,
    }


def build_openai_tool_search_projection(
    tools: Sequence[BaseTool],
    policies: Mapping[str, ToolPolicy],
    *,
    force_immediate: Sequence[str] = (),
) -> ToolSearchProjection:
    """Build the compact OpenAI declaration without changing executable tools.

    Only catalogued canonical tools are included in the provider surface.
    A forced retry/recovery tool is temporarily lifted out of its namespace so
    ``tool_choice`` can reference a directly visible function.
    """

    forced = frozenset(str(name) for name in force_immediate)
    immediate: list[BaseTool] = []
    excluded: list[str] = []
    grouped: dict[str, list[BaseTool]] = {
        name: [] for name in _NAMESPACE_DESCRIPTIONS
    }

    for tool in tools:
        policy = policies.get(tool.name)
        if policy is None:
            excluded.append(tool.name)
            continue
        namespace = _namespace_name(policy)
        if namespace is None:
            excluded.append(tool.name)
        elif tool.name in forced or namespace == "":
            immediate.append(tool)
        else:
            grouped[namespace].append(tool)

    namespaces: list[ToolSearchNamespace] = []
    for name, description in _NAMESPACE_DESCRIPTIONS.items():
        members = grouped[name]
        if not members:
            continue
        member_names = tuple(tool.name for tool in members)
        schema = {
            "type": "namespace",
            "name": name,
            "description": description,
            "tools": [_responses_function_schema(tool) for tool in members],
        }
        namespaces.append(
            ToolSearchNamespace(
                name=name,
                description=description,
                member_names=member_names,
                schema=schema,
            )
        )

    provider_tools: tuple[BaseTool | dict[str, Any], ...] = (
        *immediate,
        *(namespace.schema for namespace in namespaces),
        *(({"type": "tool_search"},) if namespaces else ()),
    )
    return ToolSearchProjection(
        provider_tools=provider_tools,
        immediate_names=tuple(tool.name for tool in immediate),
        namespaces=tuple(namespaces),
        excluded_names=tuple(excluded),
    )
