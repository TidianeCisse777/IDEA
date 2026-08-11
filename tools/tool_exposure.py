"""Canonical tool exposure for providers without hosted Tool Search.

OpenAI Tool Search projects the same catalog into deferred namespaces. Other
providers receive every canonical tool directly. Source selection remains a
model decision informed by the resource context; this module never hides or
blocks a valid catalog tool based on keywords.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Mapping

from tools.source_scope import SourceDecision
from tools.tool_catalog import ToolExposureGroup, ToolPolicy
from tools.turn_context import TurnContext


@dataclass(frozen=True)
class ToolExposureDecision:
    """Provider-facing canonical tools and audit metadata for one model call."""

    tool_names: tuple[str, ...]
    active_groups: tuple[ToolExposureGroup, ...]
    reasons: tuple[str, ...]
    dropped_tool_names: tuple[str, ...]
    source_decision: SourceDecision
    max_tools: int
    policy_overflow: bool = False


def decide_tool_exposure(
    available_names: Collection[str],
    policies: Mapping[str, ToolPolicy],
    turn_context: TurnContext,
    source_decision: SourceDecision,
    messages: list[Any],
    *,
    max_tools: int = 20,
) -> ToolExposureDecision:
    """Expose all canonical catalog tools without a keyword allowlist.

    ``turn_context``, ``messages`` and ``max_tools`` remain in the signature so
    callers and harnesses share one stable seam across provider routes. They do
    not restrict capabilities: Tool Search handles schema deferral on supported
    OpenAI models, while fallback providers receive the full canonical surface.
    """

    del turn_context, messages, max_tools
    names = tuple(
        dict.fromkeys(str(name) for name in available_names if name in policies)
    )
    groups = tuple(
        dict.fromkeys(policies[name].exposure_group for name in names)
    )
    return ToolExposureDecision(
        tool_names=names,
        active_groups=groups,
        reasons=("all canonical tools exposed; model selects the appropriate source",),
        dropped_tool_names=(),
        source_decision=source_decision,
        max_tools=len(names),
        policy_overflow=False,
    )
