"""Submit user feedback to LangSmith."""
from __future__ import annotations

import os

from langsmith import Client


def submit_feedback(run_id: str, score: int, comment: str | None = None) -> None:
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        return
    client = Client()
    client.create_feedback(run_id, key="user_feedback", score=score, comment=comment)
