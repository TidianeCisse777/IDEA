"""Provider-facing prompt-cache contracts for GPT-5.6."""

import os
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


def test_explicit_breakpoint_survives_responses_payload_before_dynamic_content():
    from core.llm_config import with_explicit_prompt_cache_breakpoint

    system_message = with_explicit_prompt_cache_breakpoint(
        SystemMessage(content="Permanent IDEA instructions")
    )
    model = ChatOpenAI(
        model="gpt-5.6-luna",
        api_key="test-key",
        use_responses_api=True,
    )

    payload = model._get_request_payload(
        [system_message, HumanMessage(content="variable turn context")]
    )

    stable_block = payload["input"][0]["content"][0]
    dynamic_message = payload["input"][1]
    assert stable_block == {
        "type": "input_text",
        "text": "Permanent IDEA instructions",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }
    assert "prompt_cache_breakpoint" not in str(dynamic_message)


def test_prompt_cache_settings_are_explicit_and_stable_for_same_contract():
    from core.llm_config import openai_prompt_cache_settings

    tools = [
        {
            "type": "function",
            "name": "run_pandas",
            "description": "Calculate from a session DataFrame.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    first = openai_prompt_cache_settings(
        model="gpt-5.6-luna",
        system_prompt="Permanent IDEA instructions",
        tools=tools,
    )
    second = openai_prompt_cache_settings(
        model="gpt-5.6-luna",
        system_prompt="Permanent IDEA instructions",
        tools=tools,
    )

    assert first == second
    assert first["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert first["model_kwargs"]["prompt_cache_key"].startswith(
        "idea-copepod-v1-"
    )


def test_prompt_cache_key_changes_with_prompt_or_tool_contract():
    from core.llm_config import openai_prompt_cache_settings

    @tool("calculate")
    def first_tool(value: int) -> int:
        """Calculate with the first contract."""
        return value

    @tool("calculate")
    def changed_tool(value: int) -> int:
        """Calculate with a changed contract."""
        return value

    baseline = openai_prompt_cache_settings(
        model="gpt-5.6-luna",
        system_prompt="Prompt A",
        tools=[first_tool],
    )
    changed_prompt = openai_prompt_cache_settings(
        model="gpt-5.6-luna",
        system_prompt="Prompt B",
        tools=[first_tool],
    )
    changed_tools = openai_prompt_cache_settings(
        model="gpt-5.6-luna",
        system_prompt="Prompt A",
        tools=[changed_tool],
    )

    baseline_key = baseline["model_kwargs"]["prompt_cache_key"]
    assert changed_prompt["model_kwargs"]["prompt_cache_key"] != baseline_key
    assert changed_tools["model_kwargs"]["prompt_cache_key"] != baseline_key


def test_explicit_prompt_cache_is_enabled_only_for_openai_gpt56_responses():
    from core.llm_config import openai_explicit_prompt_cache_enabled

    assert openai_explicit_prompt_cache_enabled(
        model="gpt-5.6-luna",
        base_url="https://api.openai.com/v1",
        use_responses_api=True,
    )
    assert not openai_explicit_prompt_cache_enabled(
        model="gpt-5.5",
        base_url="https://api.openai.com/v1",
        use_responses_api=True,
    )
    assert not openai_explicit_prompt_cache_enabled(
        model="gpt-5.6-luna",
        base_url="https://openrouter.ai/api/v1",
        use_responses_api=True,
    )
    assert not openai_explicit_prompt_cache_enabled(
        model="gpt-5.6-luna",
        base_url="https://api.openai.com/v1",
        use_responses_api=False,
    )


def test_make_agent_configures_explicit_cache_for_openai_gpt56():
    import agent

    env = {
        "LLM_MODEL": "gpt-5.6-luna",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_TOOL_SEARCH_ENABLED": "true",
    }
    with patch.dict(os.environ, env, clear=False), patch(
        "agent.ChatOpenAI"
    ) as mock_llm:
        mock_llm.return_value = MagicMock()
        graph = agent.make_agent("prompt-cache-agent")

    assert {"model", "tools"} <= set(graph.get_graph().nodes)
    kwargs = mock_llm.call_args.kwargs
    assert kwargs["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert kwargs["model_kwargs"]["prompt_cache_key"].startswith(
        "idea-copepod-v1-"
    )
