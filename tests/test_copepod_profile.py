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


def test_system_prompt_mentions_non_repetitive_output():
    prompt = _profile().get_system_message("anything")
    assert "Do not reuse the same sentence opener" in prompt
    assert "Never answer with a bare ellipsis" in prompt


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
    assert "inspect_and_report" in code
    assert "inspect_file" in code
    assert "describe_column" in code
    assert "create_data_understanding_draft" not in code
    assert "activate_graph_context" not in code


def test_custom_instructions_advertise_undefined_columns_section():
    """The `copepod_tool_signatures` block must instruct the LLM about both
    column sections produced by format_inspect_report: "Définitions
    détectées" (RAG-known columns) AND "Colonnes sans définition RAG"
    (columns the RAG does not cover). Without this guidance, the LLM
    ignores the second section and skips columns it should interpret or
    ask about."""
    text = _profile().get_custom_instructions(
        host="http://localhost",
        user_id="u",
        session_id="s",
        static_dir="/static",
        upload_dir="/static/u/s/uploads",
        mcp_tools=[],
    )
    assert "Définitions détectées" in text
    assert "Colonnes sans définition RAG" in text
    # The instruction must reference the two-form plan rule so the LLM
    # knows what to DO with the undefined columns (interpret or ask).
    assert "interpret" in text.lower() or "interpr" in text
    assert "numbered question" in text.lower() or "form (b)" in text.lower()
