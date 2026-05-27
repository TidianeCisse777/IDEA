import pytest
from unittest.mock import MagicMock

from agents.registry import register, get_profile, get_default_profile, registered_types, _registry
from agents.generic_profile import GenericProfile


@pytest.fixture(autouse=True)
def fresh_registry():
    _registry.clear()
    yield
    _registry.clear()


class TestRegistry:
    def test_register_then_get_profile_returns_correct_profile(self):
        profile = MagicMock()
        profile.agent_type = "test"
        register(profile)
        assert get_profile("test") is profile

    def test_get_unknown_profile_raises_key_error(self):
        with pytest.raises(KeyError):
            get_profile("inexistant")

    def test_registered_types_lists_registered_agents(self):
        p1, p2 = MagicMock(), MagicMock()
        p1.agent_type = "a"
        p2.agent_type = "b"
        register(p1)
        register(p2)
        assert "a" in registered_types()
        assert "b" in registered_types()

    def test_get_default_profile_returns_generic(self):
        p = MagicMock()
        p.agent_type = "generic"
        register(p)
        assert get_default_profile() is p

    def test_get_default_profile_raises_if_generic_not_registered(self):
        with pytest.raises(KeyError):
            get_default_profile()


class TestGenericProfile:
    @pytest.fixture(autouse=True)
    def profile(self):
        self.p = GenericProfile()

    def test_agent_type_is_generic(self):
        assert self.p.agent_type == "generic"

    def test_get_tool_code_contains_get_datetime(self):
        code = self.p.get_tool_code()
        assert isinstance(code, str)
        assert len(code) > 0
        assert "get_datetime" in code

    def test_get_system_message_appends_user_prompt(self):
        msg = self.p.get_system_message("EXTRA_PROMPT")
        assert "EXTRA_PROMPT" in msg

    def test_get_custom_instructions_returns_non_empty_string(self):
        result = self.p.get_custom_instructions(
            host="http://localhost",
            user_id="123",
            session_id="abc",
            static_dir="static",
            upload_dir="uploads",
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_custom_instructions_put_static_blocks_before_session_metadata(self):
        result = self.p.get_custom_instructions(
            host="http://localhost",
            user_id="123",
            session_id="abc",
            static_dir="static",
            upload_dir="uploads",
        )

        assert result.index("VISION SUPPORT") < result.index("The user_id is 123")
        assert result.index("CUSTOM FUNCTIONS") < result.index("The session_id is abc")

    def test_configure_interpreter_is_noop(self):
        mock_interpreter = MagicMock()
        self.p.configure_interpreter(mock_interpreter)  # ne doit pas lever
