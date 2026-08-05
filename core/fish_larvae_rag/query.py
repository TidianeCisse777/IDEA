"""Small local RAG for fish-larvae knowledge, with no runtime network call."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


_CHUNKS_PATH = Path(__file__).parent / "chunks.json"


@lru_cache(maxsize=1)
def _chunks() -> tuple[dict, ...]:
    return tuple(json.loads(_CHUNKS_PATH.read_text(encoding="utf-8")))


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-zà-ÿ0-9_]+", text.casefold()))


def query_fish_larvae_rag(question: str, top_k: int = 3) -> list[dict]:
    """Return relevant fish-larvae documentation chunks for a user question."""
    question_terms = _terms(question)
    ranked = []
    for chunk in _chunks():
        searchable = f"{chunk['title']} {chunk['content']}"
        score = len(question_terms & _terms(searchable))
        ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {**chunk, "score": score}
        for score, chunk in ranked[:max(1, top_k)]
        if score > 0
    ]
