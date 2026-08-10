"""
Query the copepod RAG index. Returns top-k chunks with source, title, score.

Usage (module):
    from core.copepod_rag.query import query_copepod_rag
    results = query_copepod_rag("acq_pixel signification")

Usage (CLI):
    python query.py "acq_pixel signification"
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Optional

def _routing_guidance_bonus(question: str, chunk: dict) -> float:
    """Prioritize the RAG decision section for explicit source-route questions.

    Embeddings are good at topical similarity but can rank a single-source
    reference above a document's explicit cross-source decision table.  This
    small, transparent reranker applies only to source-choice and join-route
    questions; it never changes which chunks are retrieved.
    """
    q = question.casefold()
    title = str(chunk.get("title", "")).casefold()
    content = str(chunk.get("content", "")).casefold()
    source_names = ("ecotaxa", "ecopart", "amundsen", "bio-oracle", "ogsl")
    named_sources = sum(name in q for name in source_names)

    net_uvp_match_question = (
        any(term in q for term in ("filet", "neolabs", "net sample"))
        and any(term in q for term in ("uvp", "ecotaxa"))
        and any(
            term in q
            for term in (
                "appari",
                "correspond",
                "match",
                "profil",
                "fenêtre temporelle",
                "delta",
            )
        )
    )
    if net_uvp_match_question:
        if "présélectionner les profils uvp" in title:
            return 0.18
        if "correspondance filet ↔ uvp" in title:
            return 0.08

    dataframe_cache_bridge_question = (
        "ecotaxa" in q
        and (
            "dataframe_refs" in q
            or (
                "dataframe" in q
                and any(term in q for term in ("sql", "join", "joindre", "jointure"))
            )
        )
    )
    if dataframe_cache_bridge_question:
        if (
            chunk.get("doc") == "ecotaxa_cache_sql.md"
            and "route sql cache et tables persistantes" in title
        ):
            return 0.22

    if named_sources >= 2 and any(word in q for word in ("choisir", "quelle source", "source utiliser")):
        if "quelle source utiliser" in title:
            return 0.18

    if any(word in q for word in ("joindre", "jointure", "join")):
        if "ecotaxa" in q and "ecopart" in q:
            if "ecotaxa" in title and "ecopart" in title:
                return 0.12
            if "ecotaxa" in content and "ecopart" in content and "joint" in content:
                return 0.05

    if (
        any(word in q for word in ("calculer", "méthode", "methode"))
        and any(word in q for word in ("abondance", "concentration", "ind m3", "ind./m3"))
        and chunk.get("doc") == "methodes_calcul.md"
    ):
        if "calculer une abondance ou concentration" in title:
            return 0.12
        return 0.05
    return 0.0



@contextlib.contextmanager
def _silence_native_fds():
    """Redirect stdout/stderr at the OS file-descriptor level.

    Necessary because chromadb/onnxruntime writes warnings (e.g.
    "onnxruntime cpuid_info warning: Unknown CPU vendor") and tqdm progress
    bars at the C level — Python's contextlib.redirect_stderr only catches
    Python-level writes, not C writes through fd 1/2. Otherwise this noise
    pollutes the OI console stream and confuses the LLM into hallucinating
    truncation. Only used to wrap one-shot library init/download paths.
    """
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_stdout, 1)
        os.dup2(saved_stderr, 2)
        os.close(devnull)
        os.close(saved_stdout)
        os.close(saved_stderr)

CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "copepod_rag"

_client = None
_collection = None


def _load():
    global _client, _collection
    if _collection is not None:
        return

    # Disable tqdm progress bars (model download, etc.) at the env level,
    # and silence native stdout/stderr around the chromadb/onnx init so the
    # first call doesn't leak warnings + download progress into OI console.
    os.environ.setdefault("TQDM_DISABLE", "1")
    with _silence_native_fds():
        import chromadb
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=DefaultEmbeddingFunction(),
        )


def _close():
    global _client, _collection
    if _client is None:
        return
    try:
        _client.close()
    except Exception:
        pass
    finally:
        _client = None
        _collection = None


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
    try:
        # Retrieve a broad local candidate pool so narrow procedural chunks can
        # be recovered by the transparent reranker even when a long general
        # reference has slightly higher embedding similarity. The corpus is
        # small and local, so 50 candidates add no provider call or token cost.
        candidate_count = min(100, max(top_k, top_k * 5, 50))

        # Retrieval stays local: a RAG lookup must not add a hidden model call.
        queries = [question]

        seen_ids: set[str] = set()
        chunks: list[dict] = []

        for q in queries:
            results = _collection.query(
                query_texts=[q],
                n_results=candidate_count,
                include=["documents", "metadatas", "distances"],
            )
            for i in range(len(results["ids"][0])):
                cid = results["ids"][0][i]
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                content = results["documents"][0][i]
                distance = round(results["distances"][0][i], 4)
                chunks.append({
                    "chunk_id": cid,
                    "doc": results["metadatas"][0][i]["doc"],
                    "title": results["metadatas"][0][i]["title"],
                    "content": content,
                    "score": distance,
                })

        chunks.sort(key=lambda c: (c["score"] - _routing_guidance_bonus(question, c), c["score"]))
        return chunks[:top_k]
    finally:
        if os.getenv("PYTEST_CURRENT_TEST"):
            _close()

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "colonnes EcoTaxa UVP5"
    print(f"Query: {q!r}\n")
    for r in query_copepod_rag(q):
        print(f"[{r['score']:.4f}] {r['doc']} — {r['title']}")
        print(f"  {r['content'][:200]}...\n")
