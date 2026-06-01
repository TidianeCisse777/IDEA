"""
Chat, history, clear, load-conversation, and transcription routes.

Interpreter lifecycle (get_or_create_interpreter, clear_session,
clear_all_interpreter_instances, cleanup_idle_sessions, periodic_cleanup)
lives in core/interpreter_session.py.

MCP pre-planning helpers (gather_available_mcp_tools, plan_and_run_mcp_tools,
and formatting utils) are defined here because they are tightly coupled to
the streaming chat endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from interpreter.core.core import OpenInterpreter
from litellm import completion, transcription
from sqlmodel import Session

from core import crud
import models
from agents.registry import get_profile, registered_types
from core.auth import get_auth_token, get_current_user, get_db
from core.chat_observability import ChatRuntimeTracer
from core.chat_stream_events import chat_stream_events
from core.config import settings
from core.interpreter_session import (
    get_or_create_interpreter,
    clear_session,
    clear_all_interpreter_instances,
    cleanup_idle_sessions,
    periodic_cleanup,
)
from core.interpreter_store import interpreter_instances
from core.mcp import mcp_manager
from core.prompt_store import get_prompt_manager
from core.rag_store import ensure_user_pqa_settings
from core.session_store import session_store
from utils.session_utils import make_session_key, resolve_agent_type
from utils.transcription_prompt import transcription_prompt

logger = logging.getLogger(__name__)


def _short(session_key: str) -> str:
    """Return a compact session key for log lines: 'session-abc/copepod'."""
    parts = session_key.split(":")
    if len(parts) >= 3:
        return f"{parts[1]}/{parts[2]}"
    return session_key


def _safe_message_get(message: Any, key: str, default: Any = None) -> Any:
    """Return message[key] without letting nonstandard message objects crash the stream."""
    try:
        if isinstance(message, dict):
            return message.get(key, default)
        getter = getattr(message, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except TypeError:
                return getter(key)
        return getattr(message, key, default)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Constants (shared with app.py via import)
# ---------------------------------------------------------------------------
STATIC_DIR = Path("./static")
UPLOAD_DIR = Path("uploads")
IDLE_TIMEOUT = settings.SESSION_IDLE_TIMEOUT
INTERPRETER_PREFIX = "interpreter:"
LAST_ACTIVE_PREFIX = "last_active:"
CLEANUP_INTERVAL = settings.SESSION_CLEANUP_INTERVAL
CHAT_RATE_LIMIT = "10/minute"

# LLM tool planner prompt
MCP_TOOL_PLANNER_PROMPT = (
    "You are a routing assistant for the IDEA application. "
    "Analyze the latest user message and decide whether calling one of the available MCP tools would help. "
    "Only call a tool if it is likely to provide data needed to answer the user. "
    "Otherwise, do not call any tool."
)

# Rate limiter reference — populated by app.py after the limiter is created
_limiter = None

router = APIRouter(tags=["chat"])

_UPLOAD_BLOCK_MARKER = "Files uploaded in this message:"
_UPLOAD_BLOCK_FOOTER = "Use these paths when referencing the uploaded files."
_UPLOAD_LINE_RE = re.compile(
    r"^- (?P<name>.+?)(?: \((?P<mime>[^)]+)\))?(?: \| relative path: (?P<rel_path>.+))?$"
)
_IMAGE_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".svg": "image/svg+xml",
}


# ---------------------------------------------------------------------------
# MCP helper functions
# ---------------------------------------------------------------------------

async def gather_available_mcp_tools(db: Session):
    """Retrieve active MCP connections and their tool schemas."""
    connections = crud.list_active_mcp_connections(session=db)
    tool_defs = []
    tool_lookup: dict[str, tuple[models.MCPConnection, dict[str, Any]]] = {}

    for connection in connections:
        if not connection.is_active:
            continue
        try:
            tools_payload = await mcp_manager.list_tools(connection)
        except Exception as exc:
            logger.warning("Failed to list tools for connection %s: %s", connection.id, exc)
            continue

        tools = (
            tools_payload.get("tools")
            if isinstance(tools_payload, dict)
            else tools_payload
        ) or []

        for tool in tools:
            tool_name = tool.get("name")
            if not tool_name:
                continue
            prefix = f"mcp_{connection.id.hex[:12]}_"
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(tool_name)).lower()
            max_slug_len = max(1, 64 - len(prefix))
            slug = slug[:max_slug_len]
            tool_id = f"{prefix}{slug}"
            raw_schema = (
                tool.get("inputSchema")
                or tool.get("input_schema")
                or {"type": "object", "properties": {}}
            )
            parameters = (
                raw_schema
                if isinstance(raw_schema, dict)
                else {"type": "object", "properties": {}}
            )
            tool_defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_id,
                        "description": f"[{connection.name}] {tool.get('description', '')} (tool: {tool_name})".strip(),
                        "parameters": parameters,
                    },
                }
            )
            tool_lookup[tool_id] = (connection, tool)

    return tool_defs, tool_lookup


def _pretty_json(data: Any, max_length: int = 4000) -> str:
    try:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        text = str(data)
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _format_mcp_result(result: Any) -> str:
    """Render MCP result payloads nicely for chat."""
    try:
        if isinstance(result, dict):
            structured = result.get("structuredContent")
            if structured is not None:
                return _pretty_json(structured)

            content = result.get("content")
            if isinstance(content, list) and content:
                texts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        txt = item.get("text", "")
                        if isinstance(txt, str):
                            stripped = txt.strip()
                            if (stripped.startswith("{") and stripped.endswith("}")) or (
                                stripped.startswith("[") and stripped.endswith("]")
                            ):
                                try:
                                    parsed = json.loads(stripped)
                                    texts.append(_pretty_json(parsed))
                                    continue
                                except Exception:
                                    pass
                            texts.append(txt)
                if texts:
                    return "\n".join(texts)
        return _pretty_json(result)
    except Exception:
        return str(result)


def _summarize_mcp_result(result: Any) -> str:
    """Generate a compact human-readable summary for streaming UI."""
    try:
        parsed = None
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            first = result["content"][0] if result["content"] else None
            if isinstance(first, dict):
                txt = first.get("text")
                if isinstance(txt, str):
                    s = txt.strip()
                    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                        try:
                            parsed = json.loads(s)
                        except Exception:
                            parsed = None
        data = parsed if parsed is not None else result

        if isinstance(data, dict) and data.get("isError"):
            return "error"

        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return f"{len(data['items'])} items"
            login = None
            if "login" in data and isinstance(data["login"], str):
                login = data["login"]
            elif isinstance(data.get("details"), dict) and "login" in data["details"]:
                login = data["details"]["login"]
            if login:
                return f"login {login}"

        return "done"
    except Exception:
        return "done"


def _extract_json_payload(result: Any) -> Any:
    """Try to extract a JSON object from typical MCP result wrappers."""
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        content = result.get("content")
        if isinstance(content, list) and content:
            item = content[0] if isinstance(content[0], dict) else {}
            txt = item.get("text") if isinstance(item, dict) else None
            if isinstance(txt, str):
                s = txt.strip()
                if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                    try:
                        return json.loads(s)
                    except Exception:
                        pass
    return result


def _render_repo_table(repos_payload: Any, max_rows: int = 20) -> str:
    """Render a concise table for GitHub repositories."""
    data = _extract_json_payload(repos_payload)
    items = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, list):
        items = data

    def get(row: dict, key: str, default=""):
        return row.get(key, default) if isinstance(row, dict) else default

    def visibility(row: dict) -> str:
        if "private" in row:
            return "private" if row.get("private") else "public"
        return get(row, "visibility", "")

    lines = ["Your repositories (page 1)", "", "name\tvisibility\tupdated_at (ISO)\thtml_url\tdescription"]
    for r in items[:max_rows]:
        name = get(r, "name")
        vis = visibility(r)
        updated = get(r, "updated_at")
        url = get(r, "html_url")
        desc = (get(r, "description") or "").replace("\n", " ")[:80]
        lines.append(f"{name}\t{vis}\t{updated}\t{url}\t{desc}")
    if not items:
        lines.append("(no repositories found)")
    return "\n".join(lines)


def _data_url_for_image_path(image_path: Path, mime_type: str | None = None) -> str | None:
    try:
        if not image_path.exists() or not image_path.is_file():
            return None
        resolved_mime = mime_type or mimetypes.guess_type(image_path.name)[0]
        if not resolved_mime:
            resolved_mime = _IMAGE_SUFFIX_MIME.get(image_path.suffix.lower())
        if not resolved_mime:
            resolved_mime = "image/png"
        data = image_path.read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{resolved_mime};base64,{encoded}"
    except Exception as exc:
        logger.warning("Failed to read image attachment %s: %s", image_path, exc)
        return None


def _coerce_multimodal_message_content(
    message: dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    static_dir: Path = STATIC_DIR,
) -> dict[str, Any]:
    """Turn file-upload instruction text into multimodal OpenAI content.

    The frontend currently serializes uploaded image attachments as a text
    block containing relative paths. This helper converts every image line
    into an ``image_url`` item while keeping the user's text prompt intact.
    Non-image attachment lines are preserved as text.
    """
    if not isinstance(message, dict):
        return message

    content = message.get("content")
    if not isinstance(content, str) or _UPLOAD_BLOCK_MARKER not in content:
        return message

    lines = content.splitlines()
    prompt_lines: list[str] = []
    attachment_lines: list[str] = []
    in_upload_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == _UPLOAD_BLOCK_MARKER:
            in_upload_block = True
            continue
        if in_upload_block:
            if stripped == _UPLOAD_BLOCK_FOOTER:
                break
            attachment_lines.append(line)
        else:
            prompt_lines.append(line)

    prompt_text = "\n".join(prompt_lines).strip()
    if not attachment_lines:
        return message

    image_items: list[dict[str, Any]] = []
    text_attachment_lines: list[str] = []
    upload_root = static_dir / str(user_id) / str(session_id) / UPLOAD_DIR
    for line in attachment_lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        match = _UPLOAD_LINE_RE.match(stripped)
        if not match:
            text_attachment_lines.append(stripped)
            continue

        rel_path = (match.group("rel_path") or match.group("name") or "").strip()
        mime_type = (match.group("mime") or "").strip() or None
        candidate = upload_root / rel_path
        suffix = candidate.suffix.lower()
        resolved_mime = (mime_type or _IMAGE_SUFFIX_MIME.get(suffix) or mimetypes.guess_type(candidate.name)[0] or "").lower()
        if resolved_mime.startswith("image/"):
            data_url = _data_url_for_image_path(candidate, resolved_mime)
            if data_url:
                image_items.append({
                    "type": "image_url",
                    "image_url": {"url": data_url},
                })
                continue
        text_attachment_lines.append(stripped)

    if not image_items:
        fallback = dict(message)
        fallback.setdefault("type", "message")
        return fallback

    content_items: list[dict[str, Any]] = []
    if prompt_text:
        content_items.append({"type": "text", "text": prompt_text})
    if text_attachment_lines:
        content_items.append({"type": "text", "text": "\n".join(text_attachment_lines).strip()})
    content_items.extend(image_items)

    new_message = dict(message)
    new_message["content"] = content_items
    return new_message


def _coerce_multimodal_messages(
    messages: list[dict[str, Any]] | None,
    *,
    user_id: str,
    session_id: str,
    static_dir: Path = STATIC_DIR,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    return [
        _coerce_multimodal_message_content(
            msg,
            user_id=user_id,
            session_id=session_id,
            static_dir=static_dir,
        )
        for msg in messages
        if isinstance(msg, dict)
    ]


def _split_upload_block_content(content: str) -> tuple[str, list[str]]:
    """Split the auto-generated upload block into prompt text + attachment lines."""
    lines = content.splitlines()
    prompt_lines: list[str] = []
    attachment_lines: list[str] = []
    in_upload_block = False
    for line in lines:
        stripped = line.strip()
        if stripped == _UPLOAD_BLOCK_MARKER:
            in_upload_block = True
            continue
        if in_upload_block:
            if stripped == _UPLOAD_BLOCK_FOOTER:
                break
            attachment_lines.append(line)
        else:
            prompt_lines.append(line)
    return "\n".join(prompt_lines).strip(), attachment_lines


def _extract_user_prompt_text(
    message: dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    static_dir: Path = STATIC_DIR,
) -> str:
    """Extract the plain-text user prompt from a message, if any."""
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        if _UPLOAD_BLOCK_MARKER in content:
            prompt_text, _ = _split_upload_block_content(content)
            return prompt_text
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()

    # Fall back to the existing compatibility helper for any unusual payload.
    hydrated = _coerce_multimodal_message_content(
        message,
        user_id=user_id,
        session_id=session_id,
        static_dir=static_dir,
    )
    content = hydrated.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    if isinstance(content, str):
        return content.strip()
    return ""


def _expand_multimodal_message_for_interpreter(
    message: dict[str, Any],
    *,
    user_id: str,
    session_id: str,
    static_dir: Path = STATIC_DIR,
) -> list[dict[str, Any]]:
    """Expand upload-block or legacy multimodal messages into native LMC messages.

    OpenInterpreter handles ``type="image"`` natively; we keep images as
    separate messages so the runtime never has to carry OpenAI-style content
    lists through its internal history machinery.
    """
    if not isinstance(message, dict):
        return []

    role = message.get("role") or "user"
    content = message.get("content")

    expanded: list[dict[str, Any]] = []

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    expanded.append({
                        "role": role,
                        "type": "message",
                        "content": text.strip(),
                    })
                continue
            if item_type != "image_url":
                continue

            image_url = item.get("image_url") or {}
            url = image_url.get("url") if isinstance(image_url, dict) else None
            if not isinstance(url, str) or not url:
                continue
            if url.startswith("data:"):
                match = re.match(
                    r"^data:image/(?P<ext>[^;]+);base64,(?P<data>[A-Za-z0-9+/=]+)$",
                    url,
                )
                if not match:
                    continue
                expanded.append({
                    "role": role,
                    "type": "image",
                    "format": f"base64.{match.group('ext').lower()}",
                    "content": match.group("data"),
                })
            else:
                expanded.append({
                    "role": role,
                    "type": "image",
                    "format": "path",
                    "content": url,
                })
        if expanded:
            return expanded
        fallback = dict(message)
        fallback.setdefault("type", "message")
        return [fallback]

    if not isinstance(content, str):
        fallback = dict(message)
        fallback.setdefault("type", "message")
        return [fallback]

    if _UPLOAD_BLOCK_MARKER not in content:
        fallback = dict(message)
        fallback.setdefault("type", "message")
        return [fallback]

    prompt_text, attachment_lines = _split_upload_block_content(content)
    upload_root = static_dir / str(user_id) / str(session_id) / UPLOAD_DIR
    image_found = False
    text_attachment_lines: list[str] = []

    if prompt_text:
        expanded.append({
            "role": role,
            "type": "message",
            "content": prompt_text,
        })

    for line in attachment_lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        match = _UPLOAD_LINE_RE.match(stripped)
        if not match:
            text_attachment_lines.append(stripped)
            continue

        rel_path = (match.group("rel_path") or match.group("name") or "").strip()
        mime_type = (match.group("mime") or "").strip() or None
        candidate = upload_root / rel_path
        suffix = candidate.suffix.lower()
        resolved_mime = (
            mime_type
            or _IMAGE_SUFFIX_MIME.get(suffix)
            or mimetypes.guess_type(candidate.name)[0]
            or ""
        ).lower()
        if not resolved_mime.startswith("image/"):
            text_attachment_lines.append(stripped)
            continue
        image_found = True
        expanded.append({
            "role": role,
            "type": "image",
            "format": "path",
            "content": str(candidate),
        })

    if image_found:
        if text_attachment_lines:
            attachment_text = "\n".join(text_attachment_lines).strip()
            if attachment_text:
                expanded.append({
                    "role": role,
                    "type": "message",
                    "content": attachment_text,
                })
        return expanded
    fallback = dict(message)
    fallback.setdefault("type", "message")
    return [fallback]


def _expand_multimodal_messages(
    messages: list[dict[str, Any]] | None,
    *,
    user_id: str,
    session_id: str,
    static_dir: Path = STATIC_DIR,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    expanded: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, dict):
            expanded.extend(
                _expand_multimodal_message_for_interpreter(
                    msg,
                    user_id=user_id,
                    session_id=session_id,
                    static_dir=static_dir,
                )
            )
    return expanded


async def plan_and_run_mcp_tools(
    *,
    interpreter: OpenInterpreter,
    user_message: str,
    db: Session,
) -> list[dict[str, Any]]:
    """Let an LLM decide whether to call MCP tools and execute them (iteratively)."""
    if not user_message.strip():
        return []

    tool_defs, tool_lookup = await gather_available_mcp_tools(db)
    if not tool_defs:
        return []

    executed_tools: list[dict[str, Any]] = []
    seen_calls: set[str] = set()

    for _ in range(3):
        planning_messages = [{"role": "system", "content": MCP_TOOL_PLANNER_PROMPT}]
        if executed_tools:
            summaries = []
            for run in executed_tools:
                try:
                    conn = run["connection"]
                    tool = run["tool"]
                    hint = _summarize_mcp_result(run["result"])
                    summaries.append(f"- {conn.name} • {tool.get('name')}: {hint}")
                except Exception:
                    continue
            if summaries:
                planning_messages.append(
                    {
                        "role": "system",
                        "content": "Previously executed MCP tools:\n" + "\n".join(summaries),
                    }
                )
        planning_messages.append({"role": "user", "content": user_message})

        try:
            planner_response = await asyncio.to_thread(
                completion,
                model=interpreter.llm.model,
                messages=planning_messages,
                tools=tool_defs,
                tool_choice="auto",
            )
        except Exception as exc:
            logger.warning("MCP tool planner failed: %s", exc)
            break

        message = planner_response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        calls_to_execute: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
        for call in tool_calls:
            fn = call.get("function") or {}
            tool_id = fn.get("name")
            if not tool_id or tool_id not in tool_lookup:
                continue
            connection, tool = tool_lookup[tool_id]
            arguments_raw = fn.get("arguments") or "{}"
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError:
                arguments = {}
            key = json.dumps(
                {"cid": str(connection.id), "tool": tool.get("name"), "args": arguments},
                sort_keys=True,
            )
            if key in seen_calls:
                continue
            seen_calls.add(key)
            calls_to_execute.append((connection, tool, arguments))

        if not calls_to_execute:
            break

        for connection, tool, arguments in calls_to_execute:
            try:
                result = await mcp_manager.call_tool(connection, tool["name"], arguments)
            except Exception as exc:
                logger.error("MCP tool %s execution failed: %s", tool.get("name"), exc)
                result = {"error": str(exc)}

            executed_tools.append(
                {
                    "connection": connection,
                    "tool": tool,
                    "arguments": arguments,
                    "result": result,
                }
            )

            raw_json_text = None
            if isinstance(result, dict):
                content_items = result.get("content")
                if isinstance(content_items, list) and content_items:
                    first = content_items[0] if isinstance(content_items[0], dict) else {}
                    txt = first.get("text") if isinstance(first, dict) else None
                    if isinstance(txt, str):
                        raw_json_text = txt
            internal_payload = raw_json_text if raw_json_text is not None else _pretty_json(result)
            interpreter.messages.append(
                {
                    "role": "assistant",
                    "type": "message",
                    "content": (
                        f"CONTEXT (do not expose directly): MCP {connection.name} • {tool['name']} ->\n"
                        f"{internal_payload}\n"
                        "Instruction: Do NOT output raw JSON; provide a concise human-readable answer only."
                    ),
                }
            )

    return executed_tools


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(contents)

        with open(temp_path, "rb") as audio_file:
            transcription_response = transcription(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                prompt=transcription_prompt,
            )

        os.remove(temp_path)
        return {"text": transcription_response.text}

    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise HTTPException(status_code=500, detail="Transcription failed")


@router.post("/chat")
async def chat_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    # Rate limiting is applied at the app level via the limiter middleware;
    # the decorator cannot be used here directly because the router-level
    # limiter reference is set after app creation.  The app.py wrapper
    # applies @limiter.limit(CHAT_RATE_LIMIT) before include_router.
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="x-session-id header is required")

        body = await request.json()
        messages = body.get("messages", [])

        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        agent_type = resolve_agent_type(
            request.headers.get("x-agent-type"), registered_types()
        )
        session_key = make_session_key(user.id, session_id, agent_type)

        _user_preview = ""
        for _m in reversed(messages):
            if isinstance(_m, dict) and _m.get("role") == "user":
                _user_preview = _extract_user_prompt_text(
                    _m,
                    user_id=str(user.id),
                    session_id=session_id,
                    static_dir=STATIC_DIR,
                )
                if len(_user_preview) > 80:
                    _user_preview = _user_preview[:80] + "…"
                _user_preview = _user_preview.replace("\n", " ")
                break
        logger.info(f"► {_short(session_key)} | \"{_user_preview}\"")
        interpreter = get_or_create_interpreter(session_key, token, db, agent_type)

        ensure_user_pqa_settings(user.id)

        tool_defs = []
        tool_lookup = {}
        mcp_tool_descriptions = []
        try:
            tool_defs, tool_lookup = await gather_available_mcp_tools(db)
            if tool_defs:
                for tool_def in tool_defs:
                    func_spec = tool_def.get("function", {})
                    tool_id = func_spec.get("name")
                    if tool_id and tool_id in tool_lookup:
                        connection, tool = tool_lookup[tool_id]
                        desc = func_spec.get("description", "No description")
                        params = func_spec.get("parameters", {}).get("properties", {})
                        param_list = ", ".join(
                            [f"{k} ({v.get('type', 'any')})" for k, v in params.items()]
                        )
                        mcp_tool_descriptions.append(f"- {tool_id}({param_list}): {desc}")
                logger.debug(f"Gathered {len(tool_defs)} MCP tools")
        except Exception as exc:
            logger.warning("Failed to gather MCP tools: %s", exc)

        host = os.getenv("API_HOST", "https://uhslc.soest.hawaii.edu/idea-api")
        profile = get_profile(agent_type)
        interpreter.custom_instructions = profile.get_custom_instructions(
            host=host,
            user_id=str(user.id),
            session_id=session_id,
            static_dir=STATIC_DIR,
            upload_dir=UPLOAD_DIR,
            mcp_tools=mcp_tool_descriptions,
        )

        session_store.touch(session_key)

        stored_messages = session_store.read_messages(session_key)
        if stored_messages is not None:
            try:
                interpreter.messages = _expand_multimodal_messages(
                    stored_messages,
                    user_id=str(user.id),
                    session_id=session_id,
                    static_dir=STATIC_DIR,
                )
                logger.info(
                    f"  restored {len(interpreter.messages)} msgs — {_short(session_key)}"
                )
            except Exception as e:
                logger.warning(f"Failed to restore messages from store: {str(e)}")

        _user_turns = sum(
            1 for m in (session_store.read_messages(session_key) or [])
            if _safe_message_get(m, "role") == "user"
        )
        logger.info(f"  round={_user_turns} | history={len(interpreter.messages)} msgs")

        # Persist the incoming user message immediately so F5 always sees it
        incoming_user = messages[-1] if messages else None
        if incoming_user and isinstance(incoming_user, dict) and incoming_user.get("role") == "user":
            current = session_store.read_messages(session_key) or []
            incoming_user_messages = _expand_multimodal_message_for_interpreter(
                incoming_user,
                user_id=str(user.id),
                session_id=session_id,
                static_dir=STATIC_DIR,
            )
            if not current or current[-len(incoming_user_messages):] != incoming_user_messages:
                session_store.write_messages(session_key, current + incoming_user_messages)

        tool_runs = []
        try:
            last_user_message = ""
            last_user_message_payload: dict[str, Any] | None = None
            last_user_message_messages: list[dict[str, Any]] = []
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                    last_user_message = _extract_user_prompt_text(
                        m,
                        user_id=str(user.id),
                        session_id=session_id,
                        static_dir=STATIC_DIR,
                    )
                    last_user_message_payload = m
                    last_user_message_messages = _expand_multimodal_message_for_interpreter(
                        m,
                        user_id=str(user.id),
                        session_id=session_id,
                        static_dir=STATIC_DIR,
                    )
                    break
            if last_user_message:
                tool_runs = await plan_and_run_mcp_tools(
                    interpreter=interpreter,
                    user_message=last_user_message,
                    db=db,
                )
                if tool_runs:
                    logger.info("  mcp=%d tool calls", len(tool_runs))
        except Exception as exc:
            logger.warning("MCP planning/execution skipped: %s", exc)

        def event_stream():
            fallback_sent = False
            # Count user turns from the persisted session store, not the request
            # body. The body can carry an arbitrary message history (e.g. when
            # the frontend hydrates a loaded conversation), but the round index
            # should reflect this session's true progression: 1 for a brand-new
            # conversation, N for a session that already holds N user turns
            # (e.g. after /load-conversation).
            persisted = session_store.read_messages(session_key) or []
            user_turns = sum(
                1 for m in persisted
                if isinstance(m, dict) and m.get("role") == "user"
            )
            tracer = ChatRuntimeTracer.from_env(
                session_key=session_key,
                user_id=str(user.id),
                agent_type=agent_type,
                model=interpreter.llm.model,
                user_input=messages[-1] if messages else {},
                round_index=max(1, user_turns),
            )
            try:
                if tool_runs:
                    streamed_keys: set[str] = set()
                    repos_summary = None
                    for run in tool_runs:
                        tracer.record_mcp_tool_run(run)
                        connection = run["connection"]
                        tool = run["tool"]
                        arguments = run["arguments"]
                        key = json.dumps(
                            {"cid": str(connection.id), "tool": tool.get("name"), "args": arguments},
                            sort_keys=True,
                        )
                        if key in streamed_keys:
                            continue
                        streamed_keys.add(key)
                        start_chunk = {
                            "start": True,
                            "role": "computer",
                            "type": "message",
                            "format": "tool_status",
                            "content": f"🔧 Using {connection.name} • {tool.get('name')}",
                        }
                        yield f"data: {json.dumps(start_chunk)}\n\n"
                        if tool.get("name") == "search_repositories":
                            try:
                                repos_summary = _render_repo_table(run["result"])
                            except Exception:
                                repos_summary = None
                        end_chunk = {
                            "end": True,
                            "role": "computer",
                            "type": "message",
                            "format": "tool_status",
                            "content": "",
                        }
                        yield f"data: {json.dumps(end_chunk)}\n\n"
                    if repos_summary:
                        chunk = {
                            "start": True,
                            "end": True,
                            "role": "computer",
                            "type": "message",
                            "content": repos_summary,
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"

                if agent_type == "copepod":
                    try:
                        interpreter.computer.run(
                            "python",
                            (
                                "import os\n"
                                f"os.environ['IDEA_RUNTIME_SESSION_KEY'] = {json.dumps(session_key)}\n"
                                f"os.environ['IDEA_RUNTIME_ROUND'] = {json.dumps(str(max(1, user_turns)))}\n"
                            ),
                        )
                    except Exception:
                        pass
                import time as _time
                total_chunks = 0
                _had_code = False
                _had_image = False
                _had_error = False
                _last_usage = None
                _t0 = _time.monotonic()
                chat_input = (
                    list(interpreter.messages) + last_user_message_messages
                    if last_user_message_messages
                    else (last_user_message_payload if last_user_message_payload is not None else messages[-1])
                )
                stream_events = chat_stream_events(
                    interpreter.chat(chat_input, stream=True),
                )
                for result in tracer.observe_stream(
                    stream_events
                ):
                    total_chunks += 1
                    if isinstance(result, dict):
                        if isinstance(result.get("usage"), dict):
                            _last_usage = result["usage"]
                        _t = result.get("type")
                        if _t == "code":
                            _had_code = True
                        elif _t == "image":
                            _had_image = True
                        elif result.get("error"):
                            _had_error = True
                    data = json.dumps(result) if isinstance(result, dict) else result
                    yield f"data: {data}\n\n"
                _elapsed = f"{(_time.monotonic() - _t0):.1f}s"
                if total_chunks == 0 and not fallback_sent:
                    fallback_sent = True
                    fallback = {"start": True, "end": True, "role": "assistant", "type": "message",
                                "content": "⚠️ Le modèle n'a pas retourné de réponse. Vérifiez la compatibilité du LLM configuré."}
                    tracer.record_event(fallback)
                    yield f"data: {json.dumps(fallback)}\n\n"
                    logger.warning(f"◄ {_short(session_key)} | [empty] {_elapsed}")
                else:
                    _kinds = []
                    if _had_code: _kinds.append("code")
                    if _had_image: _kinds.append("image")
                    if _had_error: _kinds.append("error")
                    if not _kinds: _kinds.append("text")
                    logger.info(f"◄ {_short(session_key)} | [{'+'.join(_kinds)}] {_elapsed} ({total_chunks} chunks)")
                summary = {
                    "type": "generation_summary",
                    "role": "assistant",
                    "model": interpreter.llm.model,
                    "elapsed_ms": round((_time.monotonic() - _t0) * 1000, 1),
                }
                if isinstance(_last_usage, dict):
                    summary["usage"] = _last_usage
                yield f"data: {json.dumps(summary)}\n\n"
            except Exception as e:
                logger.exception("Error in chat stream")
                err_str = str(e)
                if "RateLimitError" in err_str or "rate_limit" in err_str.lower() or "quota" in err_str.lower() or "RESOURCE_EXHAUSTED" in err_str:
                    user_msg = "⏳ Quota API atteint. Attendez quelques secondes et réessayez, ou vérifiez les limites de votre plan LLM."
                elif "Bearer " in err_str or "api_key" in err_str.lower() or "AuthenticationError" in err_str:
                    user_msg = "Clé API LLM manquante ou invalide. Configurez la clé dans le fichier .env et redémarrez le serveur."
                else:
                    user_msg = err_str
                tracer.record_route_error(user_msg)
                yield f"data: {json.dumps({'error': user_msg})}\n\n"
            finally:
                tracer.close()
                clean_msgs = [
                    m for m in interpreter.messages
                    if not (
                        _safe_message_get(m, "role") == "assistant"
                        and _safe_message_get(m, "type") == "message"
                        and isinstance(_safe_message_get(m, "content"), str)
                        and str(_safe_message_get(m, "content", "")).lstrip().startswith("to=execute")
                    )
                ]
                session_store.write_messages(session_key, clean_msgs)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat_endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/history")
def history_endpoint(request: Request, token: str = Depends(get_auth_token)):
    session_id = request.headers.get("x-session-id")
    if not session_id:
        return {"error": "x-session-id header is required"}
    user = get_current_user(token)
    if user is None:
        return {"error": "Invalid or expired token"}
    agent_type = request.headers.get("x-agent-type", "generic")
    if agent_type not in registered_types():
        agent_type = "generic"
    session_key = make_session_key(user.id, session_id, agent_type)

    stored_messages = session_store.read_messages(session_key)
    if stored_messages is not None:
        return stored_messages
    return []


@router.post("/clear")
def clear_endpoint(request: Request, token: str = Depends(get_auth_token)):
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="x-session-id header is required")
        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        agent_type = request.headers.get("x-agent-type", "generic")
        if agent_type not in registered_types():
            agent_type = "generic"
        session_key = make_session_key(user.id, session_id, agent_type)
        clear_session(session_key)
        return {"status": "Chat history cleared"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in clear_endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/load-conversation")
async def load_conversation_endpoint(
    request: Request,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
    """Load a conversation's messages into the interpreter context"""
    try:
        session_id = request.headers.get("x-session-id")
        if not session_id:
            raise HTTPException(status_code=400, detail="x-session-id header is required")

        user = get_current_user(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        agent_type = request.headers.get("x-agent-type", "generic")
        if agent_type not in registered_types():
            agent_type = "generic"

        body = await request.json()
        messages = body.get("messages", [])

        session_key = make_session_key(user.id, session_id, agent_type)

        interpreter_messages = []
        for msg in messages:
            if (
                msg.get("message_type") == "console"
                and msg.get("message_format") == "active_line"
            ):
                continue

            if msg.get("role") in ["user", "assistant"]:
                interpreter_messages.extend(
                    _expand_multimodal_message_for_interpreter(
                        {
                            "role": msg.get("role"),
                            "type": msg.get("type", "message"),
                            "content": msg.get("content", ""),
                        },
                        user_id=str(user.id),
                        session_id=session_id,
                        static_dir=STATIC_DIR,
                    )
                )
            elif msg.get("role") == "computer":
                msg_type = msg.get("message_type", "message")
                if msg_type == "console":
                    continue
                else:
                    interpreter_msg = {
                        "role": "user",
                        "type": msg_type if msg_type in ["code", "message", "image"] else "message",
                        "content": msg.get("content", ""),
                    }
                    if msg.get("message_format"):
                        interpreter_msg["format"] = msg.get("message_format")
                    interpreter_messages.extend(
                        _expand_multimodal_message_for_interpreter(
                            interpreter_msg,
                            user_id=str(user.id),
                            session_id=session_id,
                            static_dir=STATIC_DIR,
                        )
                    )

        clean_interpreter_messages = [
            m for m in interpreter_messages
            if not (
                m.get("role") == "assistant"
                and m.get("type") == "message"
                and isinstance(m.get("content"), str)
                and m["content"].lstrip().startswith("to=execute")
            )
        ]
        session_store.write_messages(session_key, clean_interpreter_messages)

        if session_key in interpreter_instances:
            try:
                interpreter_instances[session_key].reset()
                del interpreter_instances[session_key]
                logger.info(f"  cleared kernel — {_short(session_key)}")
            except Exception as e:
                logger.warning(f"Error clearing existing interpreter: {str(e)}")

        logger.info(
            f"  loaded {len(interpreter_messages)} msgs → {_short(session_key)}"
        )
        return {"status": "Conversation loaded", "message_count": len(interpreter_messages)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load conversation: {str(e)}")
