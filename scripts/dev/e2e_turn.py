"""Driver de tour E2E — pilote l'agent copépodes un tour à la fois, avec logs.

Usage:
    python scripts/dev/e2e_turn.py <thread_id> <user_id> "question"

L'état de conversation est persisté par le checkpointer LangGraph (même
`thread_id` => reprise). Utiliser un `user_id` unique par run de scénario pour
éviter la pollution de la mémoire long-terme entre exécutions.

Observabilité : chaque étape de l'agent (appel d'outil, résultat d'outil,
message) est journalisée sur stderr avec un timestamp et le temps écoulé, pour
suivre la progression en direct — y compris quand le tour est lent (Bio-ORACLE,
gros export). La réponse finale est imprimée sur stdout.
"""

import sys
import time
from datetime import datetime

from agent import make_agent, repair_invalid_tool_history


_START = time.monotonic()


def _log(msg: str) -> None:
    elapsed = time.monotonic() - _START
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp} +{elapsed:6.1f}s] {msg}", file=sys.stderr, flush=True)


def _short(value: object, limit: int = 300) -> str:
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} car.)"


def _log_message(message: object) -> None:
    """Log a single message emitted by the agent stream."""
    mtype = type(message).__name__
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        for call in tool_calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "?")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            _log(f"→ appel outil: {name}({_short(args, 200)})")
        return
    if mtype == "ToolMessage":
        name = getattr(message, "name", "?")
        _log(f"← résultat {name}: {_short(getattr(message, 'content', ''))}")
        return
    content = getattr(message, "content", "")
    if mtype == "AIMessage" and content:
        _log(f"· message agent: {_short(content)}")


def main() -> None:
    if len(sys.argv) < 4:
        print("usage: e2e_turn.py <thread_id> <user_id> <question>", file=sys.stderr)
        raise SystemExit(2)
    thread_id, user_id, question = sys.argv[1], sys.argv[2], sys.argv[3]
    _log(f"construction de l'agent (thread={thread_id}, user={user_id})")
    agent = make_agent(thread_id, user_id=user_id)
    config = {"configurable": {"thread_id": thread_id}}
    repair_invalid_tool_history(agent, config)

    _log("envoi de la question, streaming des étapes…")
    seen = 0
    last = None
    for chunk in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
        stream_mode="values",
    ):
        messages = chunk.get("messages", [])
        for message in messages[seen:]:
            _log_message(message)
        if len(messages) > seen:
            seen = len(messages)
            last = messages[-1]

    _log("tour terminé.")
    if last is not None:
        print(getattr(last, "content", ""))


if __name__ == "__main__":
    main()
