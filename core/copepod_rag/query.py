"""
Query the copepod RAG index. Returns top-k chunks with source, title, score.

Usage (module):
    from core.copepod_rag.query import query_copepod_rag
    results = query_copepod_rag("acq_pixel signification")

Usage (CLI):
    python query.py "acq_pixel signification"
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "copepod_rag"

_collection = None


def _load():
    global _collection
    if _collection is not None:
        return

    import chromadb
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=DefaultEmbeddingFunction(),
    )


def query_copepod_rag(
    question: str,
    top_k: int = 3,
    session_id: Optional[str] = None,
) -> list[dict]:
    """Return top_k chunks most relevant to question.

    Args:
        question: Natural language question in French or English.
        top_k: Number of results to return (default 3).
        session_id: Optional Langfuse session ID for tracing.

    Returns:
        List of dicts: {chunk_id, doc, title, content, score}
        score is cosine distance (lower = more similar).
    """
    _load()

    results = _collection.query(
        query_texts=[question],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for i in range(len(results["ids"][0])):
        chunks.append({
            "chunk_id": results["ids"][0][i],
            "doc": results["metadatas"][0][i]["doc"],
            "title": results["metadatas"][0][i]["title"],
            "content": results["documents"][0][i],
            "score": round(results["distances"][0][i], 4),
        })

    if session_id:
        _trace_langfuse(question, chunks, session_id)

    return chunks


def _trace_langfuse(question: str, chunks: list[dict], session_id: str):
    try:
        from langfuse import Langfuse
        lf = Langfuse()
        span = lf.span(
            name="copepod_rag_query",
            session_id=session_id,
            input={"question": question},
            output={"top_k": len(chunks), "chunks": [
                {"chunk_id": c["chunk_id"], "title": c["title"], "score": c["score"]}
                for c in chunks
            ]},
        )
        span.end()
    except Exception:
        pass  # Langfuse optional — never crash the query path


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "colonnes EcoTaxa UVP5"
    print(f"Query: {q!r}\n")
    for r in query_copepod_rag(q):
        print(f"[{r['score']:.4f}] {r['doc']} — {r['title']}")
        print(f"  {r['content'][:200]}...\n")
