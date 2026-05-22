"""
Chat, history, clear, load-conversation, and transcription routes.

Also owns the interpreter lifecycle helpers (get_or_create_interpreter,
clear_session, clear_all_interpreter_instances, cleanup_idle_sessions,
periodic_cleanup) and the MCP pre-planning helpers
(gather_available_mcp_tools, plan_and_run_mcp_tools, and formatting utils).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from time import time
from typing import Any

import redis
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from interpreter.core.core import OpenInterpreter
from litellm import completion, transcription
from sqlmodel import Session

from core import crud
import models
from agents.registry import get_profile, registered_types
from core.auth import get_auth_token, get_current_user, get_db
from core.config import settings
from core.interpreter_store import interpreter_instances
from core.mcp_manager import mcp_manager
from core.prompt_store import get_prompt_manager
from core.rag_store import ensure_user_pqa_settings
from utils.session_utils import make_session_key, parse_session_key, resolve_agent_type, session_dir_path
from utils.transcription_prompt import transcription_prompt

logger = logging.getLogger(__name__)

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

# Redis — same connection as app.py
redis_client = redis.Redis(host="redis", port=6379, db=0)

# Rate limiter reference — populated by app.py after the limiter is created
_limiter = None

router = APIRouter(tags=["chat"])


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
# Interpreter lifecycle
# ---------------------------------------------------------------------------

def get_or_create_interpreter(
    session_key: str,
    token: str | None = None,
    db: Session | None = None,
    agent_type: str = "generic",
) -> OpenInterpreter:
    """Get existing interpreter or create a new one."""
    try:
        if session_key in interpreter_instances:
            logger.info(f"Retrieved existing interpreter for session {session_key}")
            return interpreter_instances[session_key]

        interpreter = OpenInterpreter()

        active_prompt = ""
        user = None
        if token and db is not None:
            user = get_current_user(token)
            if user:
                active_prompt = get_prompt_manager().get_active_prompt(db, user.id)
        if not active_prompt and (token and db and user):
            active_prompt = get_prompt_manager().get_active_prompt(db, user.id)

        profile = get_profile(agent_type)
        interpreter.system_message = profile.get_system_message(active_prompt)

        interpreter.llm.model = settings.LLM_MODEL
        interpreter.llm.supports_vision = settings.LLM_SUPPORTS_VISION
        interpreter.llm.supports_functions = settings.LLM_SUPPORTS_FUNCTIONS
        interpreter.llm.temperature = settings.LLM_TEMPERATURE
        interpreter.llm.context_window = settings.LLM_CONTEXT_WINDOW
        interpreter.llm.max_completion_tokens = settings.LLM_MAX_COMPLETION_TOKENS
        if settings.LLM_API_KEY:
            interpreter.llm.api_key = settings.LLM_API_KEY
        if settings.LLM_API_BASE:
            interpreter.llm.api_base = settings.LLM_API_BASE
        if settings.LLM_REASONING_EFFORT is not None:
            interpreter.llm.reasoning_effort = settings.LLM_REASONING_EFFORT
        interpreter.max_output = settings.LLM_MAX_OUTPUT
        interpreter.computer.import_computer_api = False
        interpreter.computer.run("python", profile.get_tool_code())
        profile.configure_interpreter(interpreter)
        interpreter.auto_run = True

        interpreter_instances[session_key] = interpreter
        logger.info(f"Created new interpreter for session {session_key}")
        return interpreter
    except Exception as e:
        logger.error(f"Error creating interpreter for session {session_key}: {str(e)}")
        raise


# ---------------------------------------------------------------------------
# Session cleanup helpers (used by app.py startup task too)
# ---------------------------------------------------------------------------

def clear_session(session_key: str):
    """Clear all resources associated with a session"""
    try:
        interpreter = interpreter_instances.get(session_key)
        if interpreter:
            interpreter.reset()
            del interpreter_instances[session_key]

        redis_client.delete(f"{LAST_ACTIVE_PREFIX}{session_key}")
        redis_client.delete(f"messages:{session_key}")

        try:
            session_dir = session_dir_path(session_key, STATIC_DIR)
            if session_dir.exists():
                shutil.rmtree(session_dir)
        except ValueError:
            session_dir = STATIC_DIR / session_key
            if session_dir.exists():
                shutil.rmtree(session_dir)
        logger.info(f"Cleared session {session_key}")
    except Exception as e:
        logger.error(f"Error clearing session {session_key}: {str(e)}")
        raise


def clear_all_interpreter_instances():
    """Clear all interpreter instances to force recreation with new system message"""
    try:
        for session_key, interpreter in list(interpreter_instances.items()):
            try:
                interpreter.reset()
                logger.info(f"Reset interpreter for session {session_key}")
            except Exception as e:
                logger.error(f"Error resetting interpreter for session {session_key}: {str(e)}")
        interpreter_instances.clear()
        logger.info("Cleared all interpreter instances due to system prompt change")
    except Exception as e:
        logger.error(f"Error clearing all interpreter instances: {str(e)}")
        raise


async def cleanup_idle_sessions():
    """Remove interpreter instances and data for idle sessions"""
    try:
        current_time = time()
        logger.info(f"Current time: {current_time}")
        logger.info(f"interpreter_instances: {list(interpreter_instances.keys())}")
        for session_key in list(interpreter_instances.keys()):
            try:
                last_active = redis_client.get(f"{LAST_ACTIVE_PREFIX}{session_key}")
                if last_active:
                    logger.info(f"Last active time for session {session_key}: {last_active}")
                    last_active_time = float(last_active.decode("utf-8"))
                    if current_time - last_active_time > IDLE_TIMEOUT:
                        clear_session(session_key)
            except Exception as e:
                logger.error(f"Error during idle cleanup for {session_key}: {str(e)}")
    except Exception as e:
        logger.error(f"Error cleaning up sessions: {str(e)}")
        raise


async def periodic_cleanup():
    """Background task for periodic cleanup of idle sessions"""
    while True:
        try:
            logger.info("Running periodic cleanup of idle sessions")
            await cleanup_idle_sessions()
            await asyncio.sleep(CLEANUP_INTERVAL)
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {str(e)}")
            await asyncio.sleep(60)


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

        logger.info(f"Received messages for session {session_key}")
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
                logger.info(f"Gathered {len(tool_defs)} MCP tools")
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

        redis_client.set(f"{LAST_ACTIVE_PREFIX}{session_key}", str(time()))

        stored_messages = redis_client.get(f"messages:{session_key}")
        if stored_messages:
            try:
                interpreter.messages = json.loads(stored_messages)
                logger.info(
                    f"Restored {len(interpreter.messages)} messages from Redis for session {session_key}"
                )
            except Exception as e:
                logger.warning(f"Failed to restore messages from Redis: {str(e)}")

        tool_runs = []
        try:
            last_user_message = ""
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                    last_user_message = m["content"]
                    break
            if last_user_message:
                tool_runs = await plan_and_run_mcp_tools(
                    interpreter=interpreter,
                    user_message=last_user_message,
                    db=db,
                )
                logger.info("Executed %d MCP tool calls", len(tool_runs))
        except Exception as exc:
            logger.warning("MCP planning/execution skipped: %s", exc)

        def event_stream():
            try:
                if tool_runs:
                    streamed_keys: set[str] = set()
                    repos_summary = None
                    for run in tool_runs:
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

                for result in interpreter.chat(messages[-1], stream=True):
                    data = json.dumps(result) if isinstance(result, dict) else result
                    yield f"data: {data}\n\n"
            except Exception as e:
                logger.error(f"Error in chat stream: {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            finally:
                redis_client.set(
                    f"messages:{session_key}", json.dumps(interpreter.messages)
                )

        return StreamingResponse(event_stream(), media_type="text/event-stream")

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

    stored_messages = redis_client.get(f"messages:{session_key}")
    if stored_messages:
        return json.loads(stored_messages)
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
    except redis.RedisError as e:
        logger.error(f"Redis error in clear_endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to clear chat history")
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
                interpreter_msg = {
                    "role": msg.get("role"),
                    "type": "message",
                    "content": msg.get("content", ""),
                }
                interpreter_messages.append(interpreter_msg)
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
                    interpreter_messages.append(interpreter_msg)

        redis_client.set(f"messages:{session_key}", json.dumps(interpreter_messages))

        if session_key in interpreter_instances:
            try:
                interpreter_instances[session_key].reset()
                del interpreter_instances[session_key]
                logger.info(f"Cleared existing interpreter for session {session_key}")
            except Exception as e:
                logger.warning(f"Error clearing existing interpreter: {str(e)}")

        logger.info(
            f"Stored {len(interpreter_messages)} messages in Redis for session {session_key}"
        )
        return {"status": "Conversation loaded", "message_count": len(interpreter_messages)}

    except Exception as e:
        logger.error(f"Error loading conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load conversation: {str(e)}")
