"""Phase 4 — DB migration tests: agent_type field on Conversation model.

These tests do NOT require a running database — they only instantiate SQLModel
classes in Python and verify field defaults and assignments.
"""
import uuid
from datetime import datetime

import pytest

from models import Conversation, ConversationBase, ConversationCreate


class TestAgentTypeDefault:
    """agent_type defaults to 'generic' when not supplied."""

    def test_conversation_base_has_agent_type_field(self):
        base = ConversationBase()
        assert hasattr(base, "agent_type"), "ConversationBase must expose agent_type"

    def test_conversation_base_default_is_generic(self):
        base = ConversationBase()
        assert base.agent_type == "generic"

    def test_conversation_default_is_generic(self):
        conv = Conversation(
            user_id=uuid.uuid4(),
        )
        assert conv.agent_type == "generic"

    def test_conversation_without_explicit_agent_type(self):
        conv = Conversation(user_id=uuid.uuid4(), title="My chat")
        assert conv.agent_type == "generic"


class TestAgentTypeAssignment:
    """agent_type accepts and stores custom values."""

    def test_conversation_custom_agent_type(self):
        conv = Conversation(user_id=uuid.uuid4(), agent_type="copepod")
        assert conv.agent_type == "copepod"

    def test_conversation_create_accepts_agent_type(self):
        create = ConversationCreate(agent_type="copepod")
        assert create.agent_type == "copepod"

    def test_conversation_create_default_agent_type(self):
        create = ConversationCreate()
        assert create.agent_type == "generic"

    def test_conversation_create_optional_agent_type(self):
        """ConversationCreate must work with or without agent_type."""
        without = ConversationCreate(title="no agent")
        with_type = ConversationCreate(title="with agent", agent_type="specialist")
        assert without.agent_type == "generic"
        assert with_type.agent_type == "specialist"
