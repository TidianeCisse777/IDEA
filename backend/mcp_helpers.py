import asyncio
import json
import logging
import re
from typing import Any

from interpreter.core.core import OpenInterpreter
from litellm import completion
from sqlmodel import Session

from backend import crud, models
from core.config import settings
from core.mcp_manager import mcp_manager

logger = logging.getLogger(__name__)

MCP_TOOL_PLANNER_PROMPT = (
    "You are a routing assistant for the IDEA application. "
    "Analyze the latest user message and decide whether calling one of the available MCP tools would help. "
    "Only call a tool if it is likely to provide data needed to answer the user. "
    "Otherwise, do not call any tool."
)


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
            await mcp_manager.reset_connection(connection.id)
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

        proxy_kwargs = (
            {"api_base": settings.LITELLM_PROXY_URL, "api_key": settings.LITELLM_MASTER_KEY}
            if settings.LITELLM_PROXY_URL
            else {}
        )
        try:
            planner_response = await asyncio.to_thread(
                completion,
                model=interpreter.llm.model,
                messages=planning_messages,
                tools=tool_defs,
                tool_choice="auto",
                **proxy_kwargs,
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
