import json
import logging
from time import time

import os

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from litellm import transcription
import redis
from sqlmodel import Session

from backend.auth import get_auth_token, get_current_user, get_db
from backend.auth_helpers import _get_user_first_name
from backend.interpreter_manager import get_or_create_interpreter
from backend.mcp_helpers import (
    gather_available_mcp_tools,
    plan_and_run_mcp_tools,
    _render_repo_table,
)
from backend.state import (
    limiter,
    redis_client,
    LAST_ACTIVE_PREFIX,
    STATIC_DIR,
    UPLOAD_DIR,
    CHAT_RATE_LIMIT,
    interpreter_instances,
    make_session_key,
)
from core.config import settings
from utils.prompts.custom_instructions import get_custom_instructions
from utils.prompts.transcription_prompt import transcription_prompt
from utils.pqa.pqa_multi_tenant import ensure_user_pqa_settings

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


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
                **({
                    "api_base": settings.LITELLM_PROXY_URL,
                    "api_key": settings.LITELLM_MASTER_KEY,
                } if settings.LITELLM_PROXY_URL else {}),
            )

        os.remove(temp_path)
        return {"text": transcription_response.text}

    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        raise HTTPException(status_code=500, detail="Transcription failed")


@router.post("/chat")
@limiter.limit(CHAT_RATE_LIMIT)
async def chat_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str = Depends(get_auth_token),
    db: Session = Depends(get_db),
):
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
        session_key = make_session_key(user.id, session_id)

        logger.info(f"Received messages for session {session_key}")
        interpreter = get_or_create_interpreter(session_key, token, db)

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
                        param_list = ", ".join([f"{k} ({v.get('type', 'any')})" for k, v in params.items()])
                        mcp_tool_descriptions.append(
                            f"- {tool_id}({param_list}): {desc}"
                        )
                logger.info(f"Gathered {len(tool_defs)} MCP tools")
        except Exception as exc:
            logger.warning("Failed to gather MCP tools: %s", exc)

        host = os.getenv("API_HOST", "https://uhslc.soest.hawaii.edu/idea-api")
        interpreter.custom_instructions = get_custom_instructions(
            host=host,
            user_id=str(user.id),
            session_id=session_id,
            static_dir=STATIC_DIR,
            upload_dir=UPLOAD_DIR,
            user_first_name=_get_user_first_name(user),
            mcp_tools=mcp_tool_descriptions,
        )

        redis_client.set(f"{LAST_ACTIVE_PREFIX}{session_key}", str(time()))

        stored_messages = redis_client.get(f"messages:{session_key}")
        if stored_messages:
            try:
                interpreter.messages = json.loads(stored_messages)
                logger.info(f"Restored {len(interpreter.messages)} messages from Redis for session {session_key}")
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
                error_message = {"error": str(e)}
                yield f"data: {json.dumps(error_message)}\n\n"
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
    session_key = make_session_key(user.id, session_id)

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

        from backend.interpreter_manager import clear_session
        session_key = make_session_key(user.id, session_id)
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

        body = await request.json()
        messages = body.get("messages", [])

        session_key = make_session_key(user.id, session_id)

        interpreter_messages = []
        for msg in messages:
            if (msg.get("message_type") == "console" and
                    msg.get("message_format") == "active_line"):
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

        redis_client.set(
            f"messages:{session_key}", json.dumps(interpreter_messages)
        )

        if session_key in interpreter_instances:
            try:
                interpreter_instances[session_key].reset()
                del interpreter_instances[session_key]
                logger.info(f"Cleared existing interpreter for session {session_key}")
            except Exception as e:
                logger.warning(f"Error clearing existing interpreter: {str(e)}")

        logger.info(f"Stored {len(interpreter_messages)} messages in Redis for session {session_key}")
        return {"status": "Conversation loaded", "message_count": len(interpreter_messages)}

    except Exception as e:
        logger.error(f"Error loading conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to load conversation: {str(e)}")
