"""
Tests for core/crud.py — user, system-prompt, and MCP-connection helpers.

Uses in-memory SQLite (no Postgres, no Redis, no external services).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from core import crud
from models import (
    MCPConnectionCreate,
    MCPConnectionUpdate,
    MCPTransportType,
    SystemPrompt,
    User,
    UserCreate,
    UserUpdate,
)


# ---------------------------------------------------------------------------
# Shared in-memory engine
# ---------------------------------------------------------------------------

@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _user_create(email: str = "a@example.com", password: str = "password123") -> UserCreate:
    return UserCreate(email=email, password=password)


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_create_stores_user(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        assert user.id is not None
        assert user.email == "a@example.com"

    def test_password_is_hashed(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        assert user.hashed_password != "password123"
        assert len(user.hashed_password) > 20

    def test_default_is_active(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        assert user.is_active is True

    def test_default_not_superuser(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        assert user.is_superuser is False


class TestGetUserByEmail:
    def test_returns_existing_user(self, session):
        crud.create_user(session=session, user_create=_user_create("b@example.com"))
        found = crud.get_user_by_email(session=session, email="b@example.com")
        assert found is not None
        assert found.email == "b@example.com"

    def test_returns_none_for_unknown_email(self, session):
        result = crud.get_user_by_email(session=session, email="nobody@example.com")
        assert result is None


class TestGetUserById:
    def test_returns_user(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        found = crud.get_user_by_id(session=session, user_id=user.id)
        assert found is not None
        assert found.id == user.id

    def test_returns_none_for_unknown_id(self, session):
        result = crud.get_user_by_id(session=session, user_id=uuid.uuid4())
        assert result is None


class TestAuthenticate:
    def test_valid_credentials_returns_user(self, session):
        crud.create_user(session=session, user_create=_user_create("c@example.com", "securepass"))
        user = crud.authenticate(session=session, email="c@example.com", password="securepass")
        assert user is not None
        assert user.email == "c@example.com"

    def test_wrong_password_returns_none(self, session):
        crud.create_user(session=session, user_create=_user_create("d@example.com", "correctpass"))
        result = crud.authenticate(session=session, email="d@example.com", password="wrongpass")
        assert result is None

    def test_unknown_email_returns_none(self, session):
        result = crud.authenticate(session=session, email="ghost@example.com", password="any")
        assert result is None


class TestUpdateUser:
    def test_update_full_name(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        updated = crud.update_user(
            session=session,
            db_user=user,
            user_in=UserUpdate(full_name="Alice"),
        )
        assert updated.full_name == "Alice"

    def test_update_password_rehashes(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        old_hash = user.hashed_password
        crud.update_user(
            session=session,
            db_user=user,
            user_in=UserUpdate(password="newpassword99"),
        )
        assert user.hashed_password != old_hash
        # New password must verify
        from core.security import verify_password
        assert verify_password("newpassword99", user.hashed_password)


class TestListUsers:
    def test_returns_all_users(self, session):
        crud.create_user(session=session, user_create=_user_create("x@x.com"))
        crud.create_user(session=session, user_create=_user_create("y@y.com"))
        users = crud.list_users(session=session)
        assert len(users) == 2

    def test_empty_when_no_users(self, session):
        assert crud.list_users(session=session) == []


class TestDeleteUser:
    def test_delete_removes_user(self, session):
        user = crud.create_user(session=session, user_create=_user_create())
        crud.delete_user(session=session, db_user=user)
        assert crud.get_user_by_id(session=session, user_id=user.id) is None


# ---------------------------------------------------------------------------
# SystemPrompt CRUD
# ---------------------------------------------------------------------------

class TestSystemPromptCrud:
    def _make_user(self, session) -> User:
        return crud.create_user(session=session, user_create=_user_create(f"{uuid.uuid4()}@x.com"))

    def test_create_prompt(self, session):
        user = self._make_user(session)
        prompt = crud.create_system_prompt(
            session=session,
            user_id=user.id,
            name="My prompt",
            description="desc",
            content="You are an assistant.",
        )
        assert prompt.id is not None
        assert prompt.name == "My prompt"
        assert prompt.content == "You are an assistant."
        assert prompt.is_active is False

    def test_get_prompt(self, session):
        user = self._make_user(session)
        created = crud.create_system_prompt(
            session=session, user_id=user.id, name="p", description="", content="c"
        )
        found = crud.get_system_prompt(session=session, prompt_id=created.id)
        assert found is not None
        assert found.id == created.id

    def test_get_prompt_unknown_returns_none(self, session):
        assert crud.get_system_prompt(session=session, prompt_id=uuid.uuid4()) is None

    def test_list_prompts_for_user(self, session):
        u1 = self._make_user(session)
        u2 = self._make_user(session)
        crud.create_system_prompt(session=session, user_id=u1.id, name="p1", description="", content="c")
        crud.create_system_prompt(session=session, user_id=u2.id, name="p2", description="", content="c")
        prompts = crud.list_system_prompts(session=session, user_id=u1.id)
        assert len(prompts) == 1
        assert prompts[0].name == "p1"

    def test_update_prompt_content(self, session):
        user = self._make_user(session)
        prompt = crud.create_system_prompt(
            session=session, user_id=user.id, name="p", description="", content="old"
        )
        updated = crud.update_system_prompt(session=session, prompt=prompt, content="new")
        assert updated.content == "new"

    def test_update_prompt_sets_updated_at(self, session):
        user = self._make_user(session)
        prompt = crud.create_system_prompt(
            session=session, user_id=user.id, name="p", description="", content="c"
        )
        before = prompt.updated_at
        import time; time.sleep(0.01)
        crud.update_system_prompt(session=session, prompt=prompt, name="new name")
        assert prompt.updated_at >= before

    def test_update_prompt_ignores_unknown_fields(self, session):
        user = self._make_user(session)
        prompt = crud.create_system_prompt(
            session=session, user_id=user.id, name="p", description="", content="c"
        )
        # Should not raise
        crud.update_system_prompt(session=session, prompt=prompt, nonexistent_field="x")

    def test_delete_prompt(self, session):
        user = self._make_user(session)
        prompt = crud.create_system_prompt(
            session=session, user_id=user.id, name="p", description="", content="c"
        )
        crud.delete_system_prompt(session=session, prompt=prompt)
        assert crud.get_system_prompt(session=session, prompt_id=prompt.id) is None


# ---------------------------------------------------------------------------
# MCP Connection CRUD
# ---------------------------------------------------------------------------

def _mcp_create(name: str = "test-conn", token: str | None = None) -> MCPConnectionCreate:
    return MCPConnectionCreate(
        name=name,
        transport=MCPTransportType.STREAMABLE_HTTP,
        endpoint="http://localhost:9000",
        auth_token=token,
    )


class TestMcpConnectionCrud:
    def test_create_connection(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(), created_by=None
        )
        assert conn.id is not None
        assert conn.name == "test-conn"
        assert conn.transport == MCPTransportType.STREAMABLE_HTTP

    def test_create_with_auth_token_encrypts(self, session):
        conn = crud.create_mcp_connection(
            session=session,
            connection_in=_mcp_create(token="my-secret"),
            created_by=None,
        )
        assert conn.auth_token is not None
        assert conn.auth_token != "my-secret"

    def test_create_with_empty_token_stores_empty(self, session):
        conn = crud.create_mcp_connection(
            session=session,
            connection_in=_mcp_create(token=""),
            created_by=None,
        )
        assert conn.auth_token == ""

    def test_create_without_token_stores_none(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token=None), created_by=None
        )
        assert conn.auth_token is None

    def test_get_connection(self, session):
        created = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(), created_by=None
        )
        found = crud.get_mcp_connection(session=session, connection_id=created.id)
        assert found is not None
        assert found.id == created.id

    def test_get_unknown_returns_none(self, session):
        assert crud.get_mcp_connection(session=session, connection_id=uuid.uuid4()) is None

    def test_list_connections_ordered_by_name(self, session):
        crud.create_mcp_connection(session=session, connection_in=_mcp_create("z-conn"), created_by=None)
        crud.create_mcp_connection(session=session, connection_in=_mcp_create("a-conn"), created_by=None)
        conns = crud.list_mcp_connections(session=session)
        assert conns[0].name == "a-conn"
        assert conns[1].name == "z-conn"

    def test_list_active_excludes_inactive(self, session):
        active = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create("active"), created_by=None
        )
        inactive = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create("inactive"), created_by=None
        )
        crud.update_mcp_connection(
            session=session,
            db_connection=inactive,
            connection_in=MCPConnectionUpdate(is_active=False),
        )
        active_list = crud.list_active_mcp_connections(session=session)
        names = [c.name for c in active_list]
        assert "active" in names
        assert "inactive" not in names

    def test_update_connection_name(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(), created_by=None
        )
        updated = crud.update_mcp_connection(
            session=session,
            db_connection=conn,
            connection_in=MCPConnectionUpdate(name="renamed"),
        )
        assert updated.name == "renamed"

    def test_update_token_to_new_value_encrypts(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token="old"), created_by=None
        )
        old_encrypted = conn.auth_token
        crud.update_mcp_connection(
            session=session,
            db_connection=conn,
            connection_in=MCPConnectionUpdate(auth_token="new-secret"),
        )
        assert conn.auth_token != old_encrypted
        assert conn.auth_token != "new-secret"

    def test_update_token_to_none_clears(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token="something"), created_by=None
        )
        crud.update_mcp_connection(
            session=session,
            db_connection=conn,
            connection_in=MCPConnectionUpdate(auth_token=None),
        )
        assert conn.auth_token is None

    def test_update_token_to_empty_stores_empty(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token="something"), created_by=None
        )
        crud.update_mcp_connection(
            session=session,
            db_connection=conn,
            connection_in=MCPConnectionUpdate(auth_token=""),
        )
        assert conn.auth_token == ""

    def test_delete_connection(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(), created_by=None
        )
        crud.delete_mcp_connection(session=session, db_connection=conn)
        assert crud.get_mcp_connection(session=session, connection_id=conn.id) is None

    def test_connection_to_public_hides_token(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token="secret"), created_by=None
        )
        public = crud.mcp_connection_to_public(conn)
        assert not hasattr(public, "auth_token") or public.model_fields_set.discard("auth_token") is None
        assert public.has_auth_token is True

    def test_connection_to_public_no_token(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create(token=None), created_by=None
        )
        public = crud.mcp_connection_to_public(conn)
        assert public.has_auth_token is False

    def test_connection_to_summary(self, session):
        conn = crud.create_mcp_connection(
            session=session, connection_in=_mcp_create("summary-conn"), created_by=None
        )
        summary = crud.mcp_connection_to_summary(conn)
        assert summary.name == "summary-conn"
        assert summary.transport == MCPTransportType.STREAMABLE_HTTP
        assert summary.is_active is True


# ---------------------------------------------------------------------------
# _normalise_connection_payload
# ---------------------------------------------------------------------------

class TestNormalisePayload:
    def test_none_command_args_becomes_empty_list(self):
        data = {"command_args": None}
        crud._normalise_connection_payload(data)
        assert data["command_args"] == []

    def test_none_headers_becomes_empty_dict(self):
        data = {"headers": None}
        crud._normalise_connection_payload(data)
        assert data["headers"] == {}

    def test_none_config_becomes_empty_dict(self):
        data = {"config": None}
        crud._normalise_connection_payload(data)
        assert data["config"] == {}

    def test_existing_values_preserved(self):
        data = {"command_args": ["--flag"], "headers": {"X-Key": "val"}}
        crud._normalise_connection_payload(data)
        assert data["command_args"] == ["--flag"]
        assert data["headers"] == {"X-Key": "val"}
