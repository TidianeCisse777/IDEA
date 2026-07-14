"""Driver de tour E2E — pilote l'agent copépodes un tour à la fois.

Usage:
    python scripts/dev/e2e_turn.py <thread_id> <user_id> "question"

L'état de conversation est persisté par le checkpointer LangGraph (même
`thread_id` => reprise). Utiliser un `user_id` unique par run de scénario pour
éviter la pollution de la mémoire long-terme entre exécutions.
"""

import sys

from agent import make_agent, repair_invalid_tool_history


def main() -> None:
    if len(sys.argv) < 4:
        print("usage: e2e_turn.py <thread_id> <user_id> <question>", file=sys.stderr)
        raise SystemExit(2)
    thread_id, user_id, question = sys.argv[1], sys.argv[2], sys.argv[3]
    agent = make_agent(thread_id, user_id=user_id)
    config = {"configurable": {"thread_id": thread_id}}
    repair_invalid_tool_history(agent, config)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
    )
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
