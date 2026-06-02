"""
Tests for conversation_routes.py — all 12 endpoints.

Uses an in-memory SQLite DB (no Postgres, no Redis required).
Auth dependencies are overridden with a fake user.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from core.auth import get_db, get_auth_token
from routers.conversation_routes import router, get_current_user_dependency
from models import User, Conversation, Message, MessageRole, MessageType


# ---------------------------------------------------------------------------
# In-memory SQLite setup
# ---------------------------------------------------------------------------

def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(engine, email: str = "test@example.com") -> User:
    user = User(
        email=email,
        hashed_password="irrelevant",
        full_name="Test User",
    )
    with Session(engine) as s:
        s.add(user)
        s.commit()
        s.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def setup():
    """Return (TestClient, User, engine) with auth bypassed."""
    engine = _make_engine()
    user = _make_user(engine)

    app = FastAPI()
    app.include_router(router)

    fake_user = MagicMock(spec=User)
    fake_user.id = user.id

    def override_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_auth_token] = lambda: "test-token"
    app.dependency_overrides[get_current_user_dependency] = lambda: fake_user

    client = TestClient(app)
    return client, fake_user, engine


@pytest.fixture()
def two_users():
    """Return two clients with separate users (for ownership tests)."""
    engine = _make_engine()
    user_a = _make_user(engine, "a@example.com")
    user_b = _make_user(engine, "b@example.com")

    def make_client(user):
        app = FastAPI()
        app.include_router(router)
        fake = MagicMock(spec=User)
        fake.id = user.id

        def override_db():
            with Session(engine) as s:
                yield s

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_auth_token] = lambda: "tok"
        app.dependency_overrides[get_current_user_dependency] = lambda: fake
        return TestClient(app)

    return make_client(user_a), make_client(user_b), engine


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _create_conv(client: TestClient, title: str | None = None) -> dict:
    resp = client.post("/", json={"title": title})
    assert resp.status_code == 200
    return resp.json()


def _add_msg(
    client: TestClient,
    conv_id: str,
    content: str = "hello",
    *,
    attachments: list[dict] | None = None,
    message_type: str = "message",
    message_format: str | None = None,
) -> dict:
    payload = {
        "role": "user",
        "content": content,
        "conversation_id": conv_id,
        "message_type": message_type,
        "message_format": message_format,
    }
    if attachments is not None:
        payload["attachments"] = attachments
    resp = client.post(f"/{conv_id}/messages", json=payload)
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# POST / — create conversation
# ---------------------------------------------------------------------------

class TestCreateConversation:
    def test_create_with_title(self, setup):
        client, user, _ = setup
        data = _create_conv(client, "My chat")
        assert data["title"] == "My chat"
        assert data["user_id"] == str(user.id)
        assert data["is_shared"] is False
        assert data["is_favorite"] is False

    def test_create_without_title_gets_default(self, setup):
        client, _, _ = setup
        data = _create_conv(client, None)
        assert data["title"] == "New conversation"

    def test_create_with_blank_title_gets_default(self, setup):
        client, _, _ = setup
        data = _create_conv(client, "   ")
        assert data["title"] == "New conversation"

    def test_create_returns_uuid(self, setup):
        client, _, _ = setup
        data = _create_conv(client)
        assert uuid.UUID(data["id"])  # no exception → valid UUID


# ---------------------------------------------------------------------------
# GET / — list conversations
# ---------------------------------------------------------------------------

class TestListConversations:
    def test_empty_list(self, setup):
        client, _, _ = setup
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["count"] == 0

    def test_lists_own_conversations(self, setup):
        client, _, _ = setup
        _create_conv(client, "A")
        _create_conv(client, "B")
        resp = client.get("/")
        assert resp.json()["count"] == 2

    def test_pagination_skip_limit(self, setup):
        client, _, _ = setup
        for i in range(5):
            _create_conv(client, f"conv-{i}")
        resp = client.get("/?skip=2&limit=2")
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["count"] == 5

    def test_user_isolation(self, two_users):
        client_a, client_b, _ = two_users
        _create_conv(client_a, "A conv")
        resp = client_b.get("/")
        assert resp.json()["count"] == 0

    def test_ordered_by_updated_at_desc(self, setup):
        client, _, _ = setup
        first = _create_conv(client, "first")
        second = _create_conv(client, "second")
        # Add a message to first to update its updated_at
        _add_msg(client, first["id"])
        resp = client.get("/")
        titles = [c["title"] for c in resp.json()["data"]]
        assert titles[0] == "first"


# ---------------------------------------------------------------------------
# GET /{id} — read conversation with messages
# ---------------------------------------------------------------------------

class TestReadConversation:
    def test_returns_conversation_with_messages(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "with msgs")
        _add_msg(client, conv["id"], "hello")
        resp = client.get(f"/{conv['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == conv["id"]
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"] == "hello"

    def test_round_trips_message_attachments(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "with attachments")
        attachments = [
            {
                "name": "import.csv",
                "path": "import.csv",
                "session_id": "session-1",
                "mimeType": "text/csv",
            }
        ]

        saved = _add_msg(client, conv["id"], "Files uploaded in this message", attachments=attachments)
        assert saved["attachments"] == attachments

        resp = client.get(f"/{conv['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["messages"][0]["attachments"] == attachments

    def test_404_unknown_id(self, setup):
        client, _, _ = setup
        resp = client.get(f"/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a, "private")
        resp = client_b.get(f"/{conv['id']}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------

class TestDeleteConversation:
    def test_delete_removes_conversation(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        resp = client.delete(f"/{conv['id']}")
        assert resp.status_code == 200
        assert client.get(f"/{conv['id']}").status_code == 404

    def test_delete_cascades_messages(self, setup, ):
        client, _, engine = setup
        conv = _create_conv(client)
        _add_msg(client, conv["id"])
        client.delete(f"/{conv['id']}")
        from sqlmodel import select as _select
        with Session(engine) as s:
            remaining = s.exec(
                _select(Message).where(Message.conversation_id == uuid.UUID(conv["id"]))
            ).all()
        assert remaining == []

    def test_delete_404_unknown(self, setup):
        client, _, _ = setup
        resp = client.delete(f"/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        resp = client_b.delete(f"/{conv['id']}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /{id}/messages — add message
# ---------------------------------------------------------------------------

class TestAddMessage:
    def test_add_user_message(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "New conversation")
        msg = _add_msg(client, conv["id"], "first message")
        assert msg["role"] == "user"
        assert msg["content"] == "first message"
        assert uuid.UUID(msg["id"])

    def test_first_user_message_sets_title(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, None)
        _add_msg(client, conv["id"], "Tell me about copepods")
        updated = client.get(f"/{conv['id']}").json()
        assert updated["title"] == "Tell me about copepods"

    def test_title_truncated_at_50_chars(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, None)
        long_msg = "A" * 60
        _add_msg(client, conv["id"], long_msg)
        updated = client.get(f"/{conv['id']}").json()
        assert updated["title"] == "A" * 50 + "..."

    def test_title_not_overwritten_if_already_set(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "Custom title")
        _add_msg(client, conv["id"], "this should not change the title")
        updated = client.get(f"/{conv['id']}").json()
        assert updated["title"] == "Custom title"

    def test_add_message_404_unknown_conv(self, setup):
        client, _, _ = setup
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/{fake_id}/messages",
            json={"role": "user", "content": "hi", "conversation_id": fake_id},
        )
        assert resp.status_code == 404

    def test_add_message_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        fake_id = conv["id"]
        resp = client_b.post(
            f"/{fake_id}/messages",
            json={"role": "user", "content": "hi", "conversation_id": fake_id},
        )
        assert resp.status_code == 403

    def test_updated_at_changes_after_message(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        before = conv["updated_at"]
        import time; time.sleep(0.01)
        _add_msg(client, conv["id"], "ping")
        after = client.get(f"/{conv['id']}").json()["updated_at"]
        assert after >= before


# ---------------------------------------------------------------------------
# GET /{id}/messages — list messages
# ---------------------------------------------------------------------------

class TestListMessages:
    def test_returns_messages_in_order(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        _add_msg(client, conv["id"], "one")
        _add_msg(client, conv["id"], "two")
        resp = client.get(f"/{conv['id']}/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["data"][0]["content"] == "one"
        assert body["data"][1]["content"] == "two"

    def test_pagination(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        for i in range(5):
            _add_msg(client, conv["id"], f"msg-{i}")
        resp = client.get(f"/{conv['id']}/messages?skip=1&limit=2")
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["count"] == 5

    def test_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        resp = client_b.get(f"/{conv['id']}/messages")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /{id} — update conversation
# ---------------------------------------------------------------------------

class TestUpdateConversation:
    def test_update_title(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "old title")
        resp = client.put(f"/{conv['id']}", json={"title": "new title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "new title"

    def test_update_favorite(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        resp = client.put(f"/{conv['id']}", json={"is_favorite": True})
        assert resp.json()["is_favorite"] is True

    def test_update_404(self, setup):
        client, _, _ = setup
        resp = client.put(f"/{uuid.uuid4()}", json={"title": "x"})
        assert resp.status_code == 404

    def test_update_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        resp = client_b.put(f"/{conv['id']}", json={"title": "hacked"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /{id}/favorite — toggle favorite
# ---------------------------------------------------------------------------

class TestToggleFavorite:
    def test_toggle_on(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        resp = client.post(f"/{conv['id']}/favorite")
        assert resp.status_code == 200
        assert resp.json()["is_favorite"] is True

    def test_toggle_off(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        client.post(f"/{conv['id']}/favorite")
        resp = client.post(f"/{conv['id']}/favorite")
        assert resp.json()["is_favorite"] is False

    def test_toggle_404(self, setup):
        client, _, _ = setup
        resp = client.post(f"/{uuid.uuid4()}/favorite")
        assert resp.status_code == 404

    def test_toggle_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        resp = client_b.post(f"/{conv['id']}/favorite")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /favorites — favorites list
# ---------------------------------------------------------------------------

class TestFavoritesList:
    def test_only_favorites_returned(self, setup):
        client, _, _ = setup
        conv_a = _create_conv(client, "fav")
        _create_conv(client, "not fav")
        client.post(f"/{conv_a['id']}/favorite")
        resp = client.get("/favorites")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["data"][0]["id"] == conv_a["id"]

    def test_favorites_user_isolation(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        client_a.post(f"/{conv['id']}/favorite")
        resp = client_b.get("/favorites")
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# POST /{id}/share + DELETE /{id}/share
# ---------------------------------------------------------------------------

class TestShareLink:
    def test_create_share_link(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        resp = client.post(f"/{conv['id']}/share", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert "share_token" in body
        assert body["share_url"].endswith(body["share_token"])

    def test_create_share_idempotent(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        token_1 = client.post(f"/{conv['id']}/share", json={}).json()["share_token"]
        token_2 = client.post(f"/{conv['id']}/share", json={}).json()["share_token"]
        assert token_1 == token_2

    def test_remove_share_link(self, setup):
        client, _, engine = setup
        conv = _create_conv(client)
        client.post(f"/{conv['id']}/share", json={})
        resp = client.delete(f"/{conv['id']}/share")
        assert resp.status_code == 200
        with Session(engine) as s:
            from models import Conversation as Conv
            db_conv = s.get(Conv, uuid.UUID(conv["id"]))
            assert db_conv.is_shared is False
            assert db_conv.share_token is None

    def test_share_403_other_user(self, two_users):
        client_a, client_b, _ = two_users
        conv = _create_conv(client_a)
        resp = client_b.post(f"/{conv['id']}/share", json={})
        assert resp.status_code == 403

    def test_share_404_unknown(self, setup):
        client, _, _ = setup
        resp = client.post(f"/{uuid.uuid4()}/share", json={})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /shared/{token} — public shared access
# ---------------------------------------------------------------------------

class TestSharedConversation:
    def test_get_shared_conversation(self, setup):
        client, _, _ = setup
        conv = _create_conv(client, "shared chat")
        _add_msg(client, conv["id"], "public message")
        share = client.post(f"/{conv['id']}/share", json={}).json()
        token = share["share_token"]
        resp = client.get(f"/shared/{token}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "shared chat"
        assert len(body["messages"]) == 1

    def test_shared_404_bad_token(self, setup):
        client, _, _ = setup
        resp = client.get("/shared/totally-fake-token")
        assert resp.status_code == 404

    def test_shared_not_accessible_after_unshare(self, setup):
        client, _, _ = setup
        conv = _create_conv(client)
        token = client.post(f"/{conv['id']}/share", json={}).json()["share_token"]
        client.delete(f"/{conv['id']}/share")
        resp = client.get(f"/shared/{token}")
        assert resp.status_code == 404
