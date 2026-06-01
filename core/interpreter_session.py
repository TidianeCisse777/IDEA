"""
Interpreter lifecycle management — creation, configuration, cleanup.

Extracted from routers/chat_routes.py so that HTTP routing modules remain
thin adapters and all interpreter state lives in the core layer.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from time import time
from typing import Any

from interpreter.core.core import OpenInterpreter

from agents.registry import get_profile
from core.config import settings
from core.interpreter_store import interpreter_instances
from core.prompt_store import get_prompt_manager
from core.session_store import session_store
from utils.session_utils import session_dir_path

logger = logging.getLogger(__name__)

# Resolved once from settings so callers don't need to pass them explicitly.
_IDLE_TIMEOUT = settings.SESSION_IDLE_TIMEOUT
_CLEANUP_INTERVAL = settings.SESSION_CLEANUP_INTERVAL


def _normalize_chat_content(content: Any) -> Any:
    """Convert Responses-style content items into OpenAI chat-completion content.

    OpenInterpreter can hand us messages that use Responses API item types such
    as ``input_text``. LiteLLM / chat-completions expects either plain strings or
    chat content parts like ``{"type": "text"}`` and ``{"type": "image_url"}``.
    """
    if isinstance(content, str) or content is None:
        return content or ""

    if not isinstance(content, list):
        return content

    normalized: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"text", "input_text"}:
            text = item.get("text")
            if not isinstance(text, str):
                text = item.get("input_text")
            if isinstance(text, str) and text.strip():
                normalized.append({"type": "text", "text": text})
            continue
        if item_type in {"image_url", "input_image"}:
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url")
            else:
                url = image_url
            if isinstance(url, str) and url:
                normalized.append({"type": "image_url", "image_url": {"url": url}})
            continue

    if not normalized:
        return ""
    if len(normalized) == 1 and normalized[0].get("type") == "text":
        return normalized[0]["text"]
    return normalized


def _normalize_chat_messages(messages: Any) -> Any:
    """Normalize a chat-completions messages list in place-safe form."""
    if not isinstance(messages, list):
        return messages

    normalized_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        normalized_message = dict(message)
        normalized_message["content"] = _normalize_chat_content(normalized_message.get("content", ""))
        normalized_messages.append(normalized_message)
    return normalized_messages


# ---------------------------------------------------------------------------
# Interpreter lifecycle
# ---------------------------------------------------------------------------

def get_or_create_interpreter(
    session_key: str,
    token: str | None = None,
    db=None,  # sqlmodel Session
    agent_type: str = "generic",
    static_dir: Path = Path("./static"),
    upload_dir: str = "uploads",
) -> OpenInterpreter:
    """Return the cached interpreter for *session_key*, creating one if absent.

    Parameters
    ----------
    session_key:
        Composite key ``user_id:session_id:agent_type``.
    token:
        Raw bearer token used to resolve the current user for prompt lookup.
    db:
        SQLModel ``Session`` instance used by the prompt manager.
    agent_type:
        Name of a registered agent profile (e.g. ``"generic"``).
    static_dir:
        Path to the static-file directory (passed to profile configuration).
    upload_dir:
        Upload directory name (passed to profile configuration).
    """
    try:
        if session_key in interpreter_instances:
            logger.info(f"Retrieved existing interpreter for session {session_key}")
            return interpreter_instances[session_key]

        interpreter = OpenInterpreter()

        profile = get_profile(agent_type)
        active_prompt = ""
        user = None
        if agent_type == "generic" and token and db is not None:
            from core.auth import get_current_user
            user = get_current_user(token)
            if user:
                active_prompt = get_prompt_manager().get_active_prompt(db, user.id)
        if agent_type == "generic" and not active_prompt and (token and db and user):
            active_prompt = get_prompt_manager().get_active_prompt(db, user.id)

        interpreter.system_message = profile.get_system_message(active_prompt)

        interpreter.llm.model = settings.LLM_MODEL
        interpreter.llm.supports_vision = settings.LLM_SUPPORTS_VISION
        interpreter.llm.supports_functions = settings.LLM_SUPPORTS_FUNCTIONS
        interpreter.llm.temperature = settings.LLM_TEMPERATURE
        if settings.LLM_REPETITION_PENALTY is not None:
            interpreter.llm.repetition_penalty = settings.LLM_REPETITION_PENALTY
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

        # gpt-5.4-mini via OpenRouter returns an empty LiteLLMCompletionStreamingIterator
        # on the Responses API path (litellm.responses). Force standard chat completions.
        _orig_completions = interpreter.llm.completions

        def _completions_via_chat(**params):
            import litellm
            if settings.LLM_REPETITION_PENALTY is not None and "repetition_penalty" not in params:
                params["repetition_penalty"] = settings.LLM_REPETITION_PENALTY
            if "input" in params or "instructions" in params:
                system = params.pop("instructions", "") or ""
                items = params.pop("input", []) or []
                params.pop("max_output_tokens", None)
                if params.get("stream"):
                    stream_options = params.get("stream_options")
                    if not isinstance(stream_options, dict):
                        stream_options = {}
                    stream_options.setdefault("include_usage", True)
                    params["stream_options"] = stream_options
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                for item in items:
                    role = item.get("role", "user")
                    if role not in ("user", "assistant", "system"):
                        role = "user"
                    content = _normalize_chat_content(item.get("content", ""))
                    messages.append({"role": role, "content": content})
                params["messages"] = messages
                # gpt-5.4-mini doesn't support tool calling via OpenRouter chat completions
                params.pop("tools", None)
                params.pop("tool_choice", None)
                return litellm.completion(**params)
            if "messages" in params:
                if params.get("stream"):
                    stream_options = params.get("stream_options")
                    if not isinstance(stream_options, dict):
                        stream_options = {}
                    stream_options.setdefault("include_usage", True)
                    params["stream_options"] = stream_options
                params["messages"] = _normalize_chat_messages(params.get("messages"))
            return _orig_completions(**params)

        interpreter.llm.completions = _completions_via_chat

        interpreter_instances[session_key] = interpreter
        logger.info(f"Created new interpreter for session {session_key}")
        return interpreter
    except Exception as e:
        logger.error(f"Error creating interpreter for session {session_key}: {str(e)}")
        raise


def clear_session(session_key: str, static_dir: Path = Path("./static")) -> None:
    """Clear all resources associated with a session.

    Resets and removes the interpreter instance, evicts the session from the
    store, and deletes the session directory on disk.
    """
    try:
        interpreter = interpreter_instances.get(session_key)
        if interpreter:
            interpreter.reset()
            del interpreter_instances[session_key]

        session_store.evict(session_key)

        try:
            session_dir = session_dir_path(session_key, static_dir)
            if session_dir.exists():
                shutil.rmtree(session_dir)
        except ValueError:
            session_dir = static_dir / session_key
            if session_dir.exists():
                shutil.rmtree(session_dir)
        logger.info(f"Cleared session {session_key}")
    except Exception as e:
        logger.error(f"Error clearing session {session_key}: {str(e)}")
        raise


def clear_all_interpreter_instances() -> None:
    """Reset and remove every interpreter instance.

    Called when the active system prompt changes so that all subsequent
    sessions pick up the new prompt.
    """
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


async def cleanup_idle_sessions() -> None:
    """Remove interpreter instances and data for sessions that have been idle too long."""
    try:
        current_time = time()
        logger.info(f"Current time: {current_time}")
        logger.info(f"interpreter_instances: {list(interpreter_instances.keys())}")
        for session_key in list(interpreter_instances.keys()):
            try:
                last_active_time = session_store.get_last_active(session_key)
                if last_active_time is not None:
                    logger.info(f"Last active time for session {session_key}: {last_active_time}")
                    if current_time - last_active_time > _IDLE_TIMEOUT:
                        clear_session(session_key)
            except Exception as e:
                logger.error(f"Error during idle cleanup for {session_key}: {str(e)}")
    except Exception as e:
        logger.error(f"Error cleaning up sessions: {str(e)}")
        raise


async def periodic_cleanup() -> None:
    """Background coroutine: run :func:`cleanup_idle_sessions` on a fixed interval."""
    while True:
        try:
            logger.info("Running periodic cleanup of idle sessions")
            await cleanup_idle_sessions()
            await asyncio.sleep(_CLEANUP_INTERVAL)
        except Exception as e:
            logger.error(f"Error in periodic cleanup: {str(e)}")
            await asyncio.sleep(60)
