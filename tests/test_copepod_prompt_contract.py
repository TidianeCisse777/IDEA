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


def test_clear_request_executes_without_plan_only_response():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Never output only a plan with no code block when execution is required" in prompt
    assert "If the request is clear, execute" in prompt
    assert "For clear action commands such as" in prompt
    assert "the plan is a commitment to execute, not a waiting state" in prompt
    assert "write the plan and executor code in the same response" in prompt


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
    assert "ask targeted grill questions only while they can change the executable plan" in prompt
    assert "stop asking and execute with explicit assumptions" in prompt


def test_visual_requests_remain_in_planner_executor_and_preserve_source():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "planner/executor" in prompt
    assert "explicit visual request" in prompt
    assert "preserve the source artifact" in prompt
    assert "produce a corrected artifact" in prompt


def test_visual_request_intents_are_named_explicitly():
    prompt = COPEPOD_SYSTEM_PROMPT.lower()
    assert "inspection" in prompt
    assert "zoom" in prompt
    assert "correction" in prompt
    assert "reconstruction" in prompt
