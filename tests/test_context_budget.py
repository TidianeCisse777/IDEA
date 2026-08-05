def test_history_budget_subtracts_fixed_request_costs():
    from agent import compute_history_budget

    assert compute_history_budget(
        max_input_tokens=40000,
        system_tokens=12000,
        tool_tokens=9000,
        memory_tokens=1000,
        reserve_tokens=2000,
    ) == 16000


def test_tool_schema_tokens_are_counted():
    from langchain_core.tools import tool
    from agent import _tool_schema_tokens

    @tool
    def example_tool(project_id: int) -> str:
        """Inspect one project using its explicit identifier."""
        return str(project_id)

    assert _tool_schema_tokens([example_tool]) > 0


def test_prior_user_instruction_ledger_keeps_older_directives_verbatim():
    from langchain_core.messages import AIMessage, HumanMessage
    from agent import _build_prior_user_instruction_ledger

    older_directive = "Utilise des bins de 20 m et garde station_id comme clé."
    block, metrics = _build_prior_user_instruction_ledger([
        HumanMessage(content=older_directive),
        AIMessage(content="D'accord."),
        HumanMessage(content="Trace maintenant le profil vertical."),
    ])

    assert older_directive in block
    assert "Trace maintenant" not in block
    assert metrics["prior_user_instruction_count"] == 1
    assert metrics["prior_user_instruction_injected"] is True


def test_context_audit_total_respects_configured_input_budget(monkeypatch):
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.runnables import RunnableLambda

    import agent as agent_module

    monkeypatch.setattr(agent_module, "_MAX_CONTEXT_TOKENS", 2000)
    monkeypatch.setattr(agent_module, "_CONTEXT_RESERVE_TOKENS", 200)
    monkeypatch.setattr(agent_module, "_MAX_HISTORY_TOKENS", 800)
    agent_module.clear_context_audit()

    def model(request):
        return AIMessage(content="ok")

    graph = create_agent(
        RunnableLambda(model),
        [],
        system_prompt="BASE " * 100,
        middleware=[agent_module._ContextMiddleware(thread_id="budget-thread")],
    )
    graph.invoke({
        "messages": [
            message
            for index in range(4)
            for message in (
                HumanMessage(content=f"consigne-{index}"),
                AIMessage(content=(f"ancien-{index} " * 400)),
            )
        ]
    })

    audit = agent_module.get_context_audit("budget-thread")
    assert audit["history_budget_tokens"] == 800
    assert audit["history_budget_capped"] is True
    assert audit["approx_tokens_model_request"] <= 2000
    assert audit["approx_tokens_tool_schemas"] == 0
