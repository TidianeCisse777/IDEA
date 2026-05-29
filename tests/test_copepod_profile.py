"""Minimal smoke tests for the lean CopepodProfile.

The Plan/Analyse mode machinery has been removed; these tests cover what
the profile still owns: system prompt, tool tags, instruction rendering.
"""
from __future__ import annotations

from agents.copepod_profile import CopepodProfile
from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT
from core.session_store import InMemorySessionStore


def _profile() -> CopepodProfile:
    return CopepodProfile(session_store=InMemorySessionStore())


def test_system_message_is_copepod_prompt():
    assert _profile().get_system_message("anything") == COPEPOD_SYSTEM_PROMPT


def test_instruction_blocks_do_not_include_plan_or_analyse():
    blocks = _profile().instruction_blocks
    assert "copepod_mode_plan" not in blocks
    assert "copepod_mode_analyse" not in blocks
    assert "copepod_tool_signatures" in blocks


def test_tool_tags_do_not_include_artifact_tag():
    assert "copepod_artifacts" not in _profile().tool_tags


def test_custom_instructions_render_without_session_mode():
    text = _profile().get_custom_instructions(
        host="http://localhost",
        user_id="u",
        session_id="s",
        static_dir="/static",
        upload_dir="/static/u/s/uploads",
        mcp_tools=[],
    )
    assert "copepod" in text.lower()
    # Locked Analyse Context block was deleted along with the mode switch.
    assert "Locked Analyse Context" not in text


def test_get_tool_code_renders_copepod_tools():
    code = _profile().get_tool_code()
    assert "inspect_file" in code
    assert "describe_column" in code
    assert "create_data_understanding_draft" not in code
    assert "activate_graph_context" not in code
