from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from core.prompt_store import PromptManager
from models import SystemPrompt


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


def test_seeded_default_prompts_do_not_include_sea(session):
    manager = PromptManager()
    user_id = uuid.uuid4()

    prompts = manager.list_prompts(session, user_id)

    names = {prompt["name"] for prompt in prompts}
    assert "Welcome Assistant" in names
    assert "SEA" not in names


def test_list_prompts_removes_legacy_sea_prompt(session):
    manager = PromptManager()
    user_id = uuid.uuid4()
    now = datetime.utcnow()
    welcome = SystemPrompt(
        user_id=user_id,
        name="Welcome Assistant",
        description="Introduction to IDEA",
        content="Welcome content",
        created_at=now,
        updated_at=now,
        is_active=False,
    )
    sea = SystemPrompt(
        user_id=user_id,
        name="SEA",
        description="Station Explorer Assistant",
        content="## SEA Role & Scope\nold SEA content",
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    session.add(welcome)
    session.add(sea)
    session.commit()

    prompts = manager.list_prompts(session, user_id)

    assert all(prompt["name"] != "SEA" for prompt in prompts)
    rows = session.exec(
        select(SystemPrompt).where(SystemPrompt.user_id == user_id)
    ).all()
    assert all(row.name != "SEA" for row in rows)
    assert any(row.name == "Welcome Assistant" and row.is_active for row in rows)


def test_get_active_prompt_removes_active_legacy_sea_prompt(session):
    manager = PromptManager()
    user_id = uuid.uuid4()
    now = datetime.utcnow()
    replacement = SystemPrompt(
        user_id=user_id,
        name="Replacement",
        description="",
        content="replacement content",
        created_at=now,
        updated_at=now,
        is_active=False,
    )
    sea = SystemPrompt(
        user_id=user_id,
        name="SEA",
        description="Station Explorer Assistant",
        content="## SEA Role & Scope\nold SEA content",
        created_at=now,
        updated_at=now,
        is_active=True,
    )
    session.add(replacement)
    session.add(sea)
    session.commit()

    active_prompt = manager.get_active_prompt(session, user_id)

    assert active_prompt == "replacement content"
    rows = session.exec(
        select(SystemPrompt).where(SystemPrompt.user_id == user_id)
    ).all()
    assert all(row.name != "SEA" for row in rows)
