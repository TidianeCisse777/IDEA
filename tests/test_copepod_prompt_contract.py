from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT


def test_deliverable_protocol_is_terminal_and_python_only():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "DELIVERABLE must ONLY be emitted from Python code" in prompt
    assert "After emitting DELIVERABLE:, do not add any prose summary" in prompt
    assert "One card per deliverable, never two" in prompt


def test_tables_and_numbers_must_be_grounded_in_execution():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Never invent numeric values" in prompt
    assert "If the user asks for a table in text" in prompt
    assert "read the saved artifact or recompute it in code before answering" in prompt


def test_plan_output_shape_uses_clean_markdown_plan_contract():
    prompt = COPEPOD_SYSTEM_PROMPT
    # Two-form HARD RULE: either plan+code (form a) or plan+numbered questions (form b),
    # but the visible heading should be clean Markdown, not a literal debug label.
    assert "HARD RULE on output shape" in prompt
    assert 'Start the visible plan with exactly `**Plan**`' in prompt
    assert "Do not print legacy all-caps plan labels" in prompt
    assert "numbered questions" in prompt
    assert "technical identifiers in backticks" in prompt
    assert "PLAN + CODE BLOCK" not in prompt
    assert "PLAN + NUMBERED QUESTIONS" not in prompt
    assert "capped at 4 per response" in prompt
    # Generic prose without numbering does NOT qualify as form (b).
    assert "neither** a code block **nor** a numbered question list is a failure" in prompt
    # Clear commands still go straight to execution (form a).
    assert "If the request is clear, execute" in prompt
    assert "For clear action commands such as" in prompt


def test_user_stop_signals_collapse_to_execution_form():
    prompt = COPEPOD_SYSTEM_PROMPT
    # When the user explicitly says "go" / "fais au mieux" / "assez de questions",
    # the LLM must switch to form (a) and document its assumptions.
    assert "fais au mieux" in prompt
    assert "assez de questions" in prompt
    assert "collapse to form (a) immediately" in prompt
    assert "document the assumptions" in prompt


def test_execute_wrapper_is_not_part_of_the_prompt_surface():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "execute(language=\"python\"" not in prompt
    assert "execute(language='python'" not in prompt


def test_session_working_set_is_the_file_state_source_of_truth():
    prompt = COPEPOD_SYSTEM_PROMPT
    lower_prompt = prompt.lower()
    assert "session working set" in lower_prompt
    assert "source of truth for file state" in lower_prompt
    assert "seen_files" in prompt
    assert "active_files" in prompt
    assert "current_user_goal" in prompt
    # `latest_inspection_by_file` is intentionally NOT exposed to the LLM —
    # the rendered "Files already inspected in this session" section replaces it
    # to prevent the model from paraphrasing the compact summary as user-visible prose.
    assert "latest_inspection_by_file" not in prompt
    assert "Files already inspected in this session" in prompt


def test_new_uploads_must_trigger_inspect_and_report():
    prompt = COPEPOD_SYSTEM_PROMPT
    lower_prompt = prompt.lower()
    assert "new uploaded file" in lower_prompt
    assert "next work item" in lower_prompt
    assert "call `inspect_and_report`" in prompt


def test_session_dedup_is_about_already_inspected_files_not_seen_files():
    prompt = COPEPOD_SYSTEM_PROMPT
    lower_prompt = prompt.lower()
    assert "Files already inspected in this session" in prompt
    assert "pending inspection" in lower_prompt
    assert "already inspected" in lower_prompt
    assert "if a filename already exists" not in lower_prompt


def test_inspection_reports_are_not_in_history_and_tool_is_documented():
    """The LLM must learn that reports live out-of-context and require a tool call.

    See `_scrub_inspection_reports_for_llm` in routers/chat_routes.py.
    """
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Inspection reports are not in your conversation history" in prompt
    assert "get_inspection_report" in prompt
    # Make sure the prompt explicitly forbids paraphrasing the stub.
    assert "Do not paraphrase the stub" in prompt
    assert "inspecte le rapport" in prompt
    assert "call `get_inspection_report('filename.csv')` immediately" in prompt
    assert "do not answer that you need to relire/read the report first" in prompt.lower()
    assert "read the `# RAPPORT D'INSPECTION` block for that file from the conversation history" not in prompt


def test_output_formatting_contract_is_concise_and_single_language():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Use one primary language per response when possible" in prompt
    assert "Keep visible prose clean" in prompt
    assert "avoid doubled blank lines" in prompt
    assert "repeated adjacent lines" in prompt


def test_clarification_policy_is_one_short_question():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "ask one short targeted question" in prompt
    assert "Do not repeat the same clarification question" in prompt


def test_execution_error_policy_requires_retry_from_traceback():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "If code execution fails" in prompt
    assert "use the crash output to refine the next attempt" in prompt
    assert "Do not turn a syntax error into a clarification question" in prompt


def test_join_protocol_requires_cardinality_profile_before_join_deliverable():
    prompt = COPEPOD_SYSTEM_PROMPT
    lower_prompt = prompt.lower()
    assert "profile_join_keys" in prompt
    assert "many_to_many" in prompt
    assert "must not emit a join deliverable" in prompt
    assert "Do not drop duplicate rows just to make a key unique" in prompt
    assert "the join workflow is mandatory and ordered" in lower_prompt
    assert "do not write a join merge before computing and reading `profile_join_keys`" in lower_prompt
    assert "never print a `deliverable` card for a join unless the code has already computed `profile_join_keys`" in lower_prompt


def test_column_selection_must_use_exact_inspection_spellings():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "verify the exact spellings in the inspection reports" in prompt
    assert "Do not translate, abbreviate, singularize, pluralize, or infer column names" in prompt
    # New plan rule: column names must be copied verbatim from the reports.
    assert "copy-paste verbatim from the inspection report" in prompt


def test_plan_must_be_grounded_in_inspection_reports():
    prompt = COPEPOD_SYSTEM_PROMPT
    # The plan is built FROM the inspection reports, not from LLM memory.
    assert "Plan grounded in inspection" in prompt
    assert "scan the conversation history for `# RAPPORT D'INSPECTION` blocks" in prompt
    assert "transcription of decisions grounded in those reports" in prompt
    assert "never a generic outline written from memory" in prompt
    # Missing facts → no inclusion; inspect first.
    assert "do NOT include it in the plan — run `inspect_and_report` on it first" in prompt


def test_visual_requests_remain_in_inspect_then_code_and_preserve_source():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "inspect-then-code" in prompt
    assert "explicit visual request" in prompt
    assert "preserve the source artifact" in prompt
    assert "produce a corrected artifact" in prompt


def test_visual_request_intents_are_named_explicitly():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "inspection" in prompt
    assert "zoom" in prompt
    assert "correction" in prompt
    assert "reconstruction" in prompt
