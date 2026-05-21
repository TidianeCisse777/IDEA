"""
Tests for Phase 3 wiring — session key format, path parsing, agent-type resolution.

All three behaviours are tested through ``utils.session_utils`` which has no
heavy dependencies and can therefore be imported in any test environment.

These tests must be:
- RED  if utils/session_utils.py does not exist or the functions have the
       old (pre-Phase-3) signatures / logic
- GREEN once Phase 3 is fully wired (make_session_key 3-segment, correct
       path parsing, resolve_agent_type fallback)
"""
from __future__ import annotations

from pathlib import Path
import pytest

from utils.session_utils import (
    make_session_key,
    parse_session_key,
    session_dir_path,
    resolve_agent_type,
)


# ===========================================================================
# TestMakeSessionKey
# ===========================================================================

class TestMakeSessionKey:
    """make_session_key must produce a 3-segment ``user_id:session_id:agent_type`` key."""

    def test_default_agent_type_is_generic(self):
        """
        RED if make_session_key has only 2 params (old signature).
        Expected: "user1:sess1:generic"
        """
        result = make_session_key("user1", "sess1")
        assert result == "user1:sess1:generic", (
            f"Expected 'user1:sess1:generic', got '{result}'. "
            "make_session_key needs a 3rd param agent_type='generic'."
        )

    def test_custom_agent_type_included(self):
        """RED if the 3rd param is missing or ignored."""
        result = make_session_key("user1", "sess1", "copepod")
        assert result == "user1:sess1:copepod"

    def test_integer_user_id_produces_correct_key(self):
        result = make_session_key(42, "abc", "generic")
        assert result == "42:abc:generic"

    def test_key_has_exactly_two_colons(self):
        result = make_session_key("u", "s", "t")
        assert result.count(":") == 2, f"Expected 2 colons in '{result}'"

    def test_empty_agent_type_is_preserved_verbatim(self):
        """The function should not silently replace empty strings — that's resolve_agent_type's job."""
        result = make_session_key("u", "s", "")
        assert result == "u:s:"


# ===========================================================================
# TestClearSessionPathParsing  (via parse_session_key / session_dir_path)
# ===========================================================================

class TestParseSessionKey:
    """parse_session_key must split exactly on position 0, 1, 2."""

    def test_three_segment_key_user_id(self):
        user_id, _, _ = parse_session_key("42:abc123:copepod")
        assert user_id == "42"

    def test_three_segment_key_session_id(self):
        """
        RED if still using split(':', 1) which gives session_id = 'abc123:copepod'.
        """
        _, session_id, _ = parse_session_key("42:abc123:copepod")
        assert session_id == "abc123", (
            f"Expected 'abc123', got '{session_id}'. "
            "parse_session_key must not include agent_type in session_id."
        )

    def test_three_segment_key_agent_type(self):
        _, _, agent_type = parse_session_key("42:abc123:copepod")
        assert agent_type == "copepod"

    def test_two_segment_legacy_key_defaults_agent_type_to_generic(self):
        user_id, session_id, agent_type = parse_session_key("42:abc123")
        assert user_id == "42"
        assert session_id == "abc123"
        assert agent_type == "generic"

    def test_one_segment_key_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_session_key("onlyone")

    def test_old_split_one_would_give_wrong_result(self):
        """
        Documents the BUG that parse_session_key fixes.
        split(':', 1) on a 3-segment key includes the agent_type in segment[1].
        This assertion is GREEN now and must STAY GREEN (regression guard).
        """
        _, raw = "42:abc123:copepod".split(":", 1)
        assert raw == "abc123:copepod"  # this is the wrong (old) behaviour


class TestSessionDirPath:
    """session_dir_path must use only user_id and session_id, not agent_type."""

    def test_three_segment_key_path(self):
        static = Path("./static")
        path = session_dir_path("42:abc123:copepod", static)
        assert path == Path("./static/42/abc123"), (
            f"Expected './static/42/abc123', got '{path}'."
        )

    def test_two_segment_legacy_key_path(self):
        static = Path("./static")
        path = session_dir_path("42:abc123", static)
        assert path == Path("./static/42/abc123")

    def test_agent_type_does_not_appear_in_path(self):
        static = Path("/data/static")
        path = session_dir_path("1:sess:copepod", static)
        assert "copepod" not in str(path), (
            f"agent_type must not appear in filesystem path, got: {path}"
        )


# ===========================================================================
# TestResolveAgentType  (mirrors /chat X-Agent-Type header logic)
# ===========================================================================

class TestResolveAgentType:
    """
    resolve_agent_type implements the validation/fallback the /chat endpoint uses.

    It must:
    - default to "generic" when header is None or absent
    - accept a valid type from registered_types()
    - fall back to "generic" for unknown types
    - fall back to "generic" for empty string
    """

    def test_none_header_defaults_to_generic(self):
        result = resolve_agent_type(None, ["generic", "copepod"])
        assert result == "generic"

    def test_empty_string_header_falls_back_to_generic(self):
        result = resolve_agent_type("", ["generic", "copepod"])
        assert result == "generic"

    def test_valid_copepod_type_is_returned(self):
        result = resolve_agent_type("copepod", ["generic", "copepod"])
        assert result == "copepod"

    def test_unknown_type_falls_back_to_generic(self):
        result = resolve_agent_type("inexistant", ["generic"])
        assert result == "generic"

    def test_valid_generic_is_returned_unchanged(self):
        result = resolve_agent_type("generic", ["generic"])
        assert result == "generic"

    def test_type_not_in_empty_registry_falls_back(self):
        """Edge case: registered_types() returns empty list → fallback."""
        result = resolve_agent_type("copepod", [])
        assert result == "generic"


# ===========================================================================
# Integration: resolve + make_session_key together
# ===========================================================================

class TestChatAgentTypeIntegration:
    """
    Verifies that resolving the header value and building the session key
    produce the expected 3-segment key — exactly what /chat should do.
    """

    def test_session_key_contains_resolved_copepod(self):
        agent_type = resolve_agent_type("copepod", ["generic", "copepod"])
        key = make_session_key("1", "sess42", agent_type)
        assert ":copepod" in key, f"Expected ':copepod' in '{key}'"

    def test_session_key_ends_with_generic_when_no_header(self):
        agent_type = resolve_agent_type(None, ["generic"])
        key = make_session_key("1", "sess42", agent_type)
        assert key.endswith(":generic"), f"Expected key ending ':generic', got '{key}'"

    def test_session_key_ends_with_generic_when_unknown_agent(self):
        agent_type = resolve_agent_type("inexistant", ["generic"])
        key = make_session_key("1", "sess99", agent_type)
        assert key.endswith(":generic"), f"Expected key ending ':generic', got '{key}'"

    def test_full_pipeline_copepod(self):
        """End-to-end: header → resolve → make_session_key → parse → path."""
        static = Path("/static")
        agent_type = resolve_agent_type("copepod", ["generic", "copepod"])
        key = make_session_key(7, "sessionXYZ", agent_type)
        assert key == "7:sessionXYZ:copepod"
        path = session_dir_path(key, static)
        assert path == Path("/static/7/sessionXYZ")
