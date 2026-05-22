from typing import Any
from pydantic import BaseModel
from sqlmodel import SQLModel, Field


# ---------------------------------------------------------------------------
# Authentication schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: str | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# System Prompt management schemas
# ---------------------------------------------------------------------------

class PromptCreateRequest(BaseModel):
    name: str
    description: str = ""
    content: str


class PromptUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None


class PromptResponse(BaseModel):
    id: str
    name: str
    description: str
    content: str
    created_at: str
    updated_at: str
    is_active: bool


class PromptListResponse(BaseModel):
    id: str
    name: str
    description: str
    content: str
    created_at: str
    updated_at: str
    is_active: bool


class SetActivePromptRequest(BaseModel):
    prompt_id: str


# ---------------------------------------------------------------------------
# MCP request schemas
# ---------------------------------------------------------------------------

class MCPToolCallRequest(SQLModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPPromptRequest(SQLModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
