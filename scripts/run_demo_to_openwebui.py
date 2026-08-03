#!/usr/bin/env python3
"""Exécute des prompts IDEA et publie la conversation dans Open WebUI."""

from __future__ import annotations

import argparse
import os
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv


MODEL_ID = "copepod-agent"


def _request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 300,
) -> dict:
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    response = requests.request(
        method,
        url,
        json=json,
        headers=request_headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _message(
    role: str,
    content: str,
    *,
    parent_id: str | None,
    model: str | None = None,
) -> dict:
    message = {
        "id": str(uuid.uuid4()),
        "parentId": parent_id,
        "childrenIds": [],
        "role": role,
        "content": content,
        "timestamp": int(time.time()),
    }
    if model:
        message["model"] = model
        message["modelName"] = model
    return message


def publish_conversation(
    prompts: list[str],
    *,
    title: str,
    openwebui_url: str,
    agent_url: str,
    token: str,
    timeout: int,
    chat_id: str | None = None,
) -> tuple[str, list[str]]:
    """Crée un chat visible, exécute les tours et persiste leur historique."""
    openwebui_url = openwebui_url.rstrip("/")
    agent_url = agent_url.rstrip("/")
    user = _request_json(
        "GET",
        f"{openwebui_url}/api/v1/auths/",
        token=token,
        timeout=30,
    )
    user_id = str(user["id"])
    if chat_id:
        existing = _request_json(
            "GET",
            f"{openwebui_url}/api/v1/chats/{chat_id}",
            token=token,
            timeout=30,
        )
        chat = dict(existing["chat"])
    else:
        chat = {
            "title": title,
            "models": [MODEL_ID],
            "params": {},
            "history": {"messages": {}, "currentId": None},
            "messages": [],
            "tags": [],
            "timestamp": int(time.time()),
        }
        created = _request_json(
            "POST",
            f"{openwebui_url}/api/v1/chats/new",
            token=token,
            json={"chat": chat},
            timeout=30,
        )
        chat_id = str(created["id"])
    answers: list[str] = []

    for prompt in prompts:
        parent_id = chat["history"]["currentId"]
        user_message = _message("user", prompt, parent_id=parent_id)
        if parent_id:
            chat["history"]["messages"][parent_id]["childrenIds"].append(
                user_message["id"]
            )
        chat["history"]["messages"][user_message["id"]] = user_message

        completion = _request_json(
            "POST",
            f"{agent_url}/v1/chat/completions",
            json={
                "model": MODEL_ID,
                "stream": False,
                "chat_id": chat_id,
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={
                "X-OpenWebUI-Chat-Id": chat_id,
                "X-OpenWebUI-User-Id": user_id,
            },
            timeout=timeout,
        )
        answer = str(completion["choices"][0]["message"]["content"])
        answers.append(answer)
        assistant_message = _message(
            "assistant",
            answer,
            parent_id=user_message["id"],
            model=MODEL_ID,
        )
        user_message["childrenIds"].append(assistant_message["id"])
        chat["history"]["messages"][assistant_message["id"]] = assistant_message
        chat["history"]["currentId"] = assistant_message["id"]
        chat["messages"] = list(chat["history"]["messages"].values())
        _request_json(
            "POST",
            f"{openwebui_url}/api/v1/chats/{chat_id}",
            token=token,
            json={"chat": chat},
            timeout=30,
        )

    return chat_id, answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", action="append", required=True)
    parser.add_argument("--title", default="Démonstration IDEA")
    parser.add_argument("--chat-id", help="Conversation Open WebUI à reprendre")
    parser.add_argument("--openwebui-url", default="http://localhost:3000")
    parser.add_argument("--agent-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.getenv("OPENWEBUI_API_KEY") or os.getenv("OPENWEBUI_ADMIN_TOKEN")
    if not token:
        parser.error("OPENWEBUI_API_KEY ou OPENWEBUI_ADMIN_TOKEN est requis dans .env")

    chat_id, answers = publish_conversation(
        args.prompt,
        title=args.title,
        openwebui_url=args.openwebui_url,
        agent_url=args.agent_url,
        token=token,
        timeout=args.timeout,
        chat_id=args.chat_id,
    )
    print(f"{args.openwebui_url.rstrip('/')}/c/{chat_id}")
    if answers:
        print(answers[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
