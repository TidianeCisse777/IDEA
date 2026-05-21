from __future__ import annotations
from typing import Dict
from agents.base import AssistantProfile

_registry: Dict[str, AssistantProfile] = {}


def register(profile: AssistantProfile) -> None:
    _registry[profile.agent_type] = profile


def get_profile(agent_type: str) -> AssistantProfile:
    if agent_type not in _registry:
        raise KeyError(f"Unknown agent_type '{agent_type}'. Registered: {list(_registry)}")
    return _registry[agent_type]


def get_default_profile() -> AssistantProfile:
    return get_profile("generic")


def registered_types() -> list[str]:
    return list(_registry.keys())
