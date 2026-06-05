from agents.copepod_prompt import COPEPOD_SYSTEM_PROMPT


def test_prompt_keeps_core_role_and_style_contract():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Copepod Graphing Assistant" in prompt
    assert "Do not reuse the same sentence opener" in prompt
    assert "Never answer with a bare ellipsis" in prompt
    assert "Wrap every technical identifier in backticks" in prompt
    assert "Never invent numeric values" in prompt


def test_prompt_moves_runtime_orchestration_out_of_model_responsibility():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "The runtime owns session orchestration" in prompt
    assert "file-state bookkeeping" in prompt
    assert "inspection-report storage" in prompt
    assert "Do not expose runtime internals" in prompt
    assert "scan the conversation messages for these two concrete signals" not in prompt
    assert "There is no truncation, ever" not in prompt


def test_prompt_keeps_new_upload_and_report_read_contract():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "call `inspect_and_report` first" in prompt
    assert 'print(inspection["output"])' in prompt
    assert "Inspection reports are stored out-of-context after the turn" in prompt
    assert "Never `print(get_inspection_report(...))`" in prompt
    assert "Do not paraphrase an inspection-report stub" in prompt
    assert "compact readback-ready inspection summary" in prompt
    assert "the priority order is: `working set` and injected file summary first" in prompt
    assert "For any readback request" in prompt
    assert "synthesize a short answer and never replay the report verbatim" in prompt


def test_prompt_prefers_exact_known_columns_over_memory():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "If exact column names are already available" in prompt
    assert "Do not translate, abbreviate, singularize, pluralize, or infer column names from memory" in prompt
    assert "Never answer with hedges such as" in prompt
    assert "Do not force the user to restate or re-upload" not in prompt


def test_prompt_separates_readback_from_action():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Distinguish two modes" in prompt
    assert "Readback: list columns, summarize a report" in prompt
    assert "For readback requests, answer directly from exact known session facts when available" in prompt
    assert "If you must read the report, answer from its facts afterward" in prompt
    assert "For action requests:" in prompt


def test_prompt_keeps_graph_readiness_as_graph_gate():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "Call `graph_readiness(required_columns=[...], user_request=..., graph_type=..., validation_status=...)` before graphing" in prompt
    assert "If `graph_readiness` returns `needs_clarification`" in prompt


def test_prompt_keeps_tool_and_deliverable_execution_rules():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "The copepod helpers are Python functions available in the sandbox" in prompt
    assert "`DELIVERABLE` output must be emitted only from Python code" in prompt
    assert "Do not turn a syntax error, import error, or missing parenthesis into a clarification question" in prompt
    assert "After `emit_deliverable(...)`" in prompt
    assert "Silence is correct" in prompt


def test_prompt_keeps_join_and_domain_guardrails():
    prompt = COPEPOD_SYSTEM_PROMPT
    assert "call `profile_join_keys(left_df, right_df, left_key, right_key)`" in prompt
    assert "If `safe_for_join_deliverable` is false" in prompt
    assert "query_copepod_knowledge_base" in prompt
    assert "SAMPLE_ID + ANALYSIS_ID" in prompt
    assert "resolve_uvp_m5_m6_inputs" in prompt
    assert "calculate_uvp_m5_m6" in prompt
    assert "Do not use OBIS" in prompt
