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


_cross_encoder = None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default

def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder
        _cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    return _cross_encoder


def _rerank(question: str, chunks: list[dict]) -> list[dict]:
    """Re-classe les chunks par pertinence réelle via cross-encoder."""
    if len(chunks) <= 1:
        return chunks
    try:
        model = _get_cross_encoder()
        pairs = [(question, c["content"]) for c in chunks]
        scores = model.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked]
    except Exception:
        return chunks


def _generate_alternative_queries(question: str) -> list[str]:
    """Génère des reformulations via LLM pour couvrir le vocabulaire non-canonique."""
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_template(
            "Tu es un assistant scientifique spécialisé en océanographie et copépodes marins.\n"
            "Génère 3 reformulations différentes de cette question pour améliorer la recherche documentaire.\n"
            "Retourne uniquement les 3 reformulations, une par ligne, sans numérotation.\n\n"
            "Question originale : {question}"
        )
        llm = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "openai/gpt-4.1-mini"),
            temperature=_env_float("LLM_RAG_TEMPERATURE", 0.3),
        )
        chain = prompt | llm | StrOutputParser()
        output = chain.invoke({"question": question})
        alternatives = [q.strip() for q in output.strip().splitlines() if q.strip()]
        return alternatives[:3]
    except Exception:
        return []



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
        candidate_count = max(top_k, min(100, top_k * 5))

        # Multi-query : on interroge avec la question originale + les reformulations LLM
        queries = [question] + _generate_alternative_queries(question)

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

        chunks.sort(key=lambda c: c["score"])
        reranked = _rerank(question, chunks[:top_k * 3])
        return reranked[:top_k]
    finally:
        if os.getenv("PYTEST_CURRENT_TEST"):
            _close()




def _trace_langfuse(question: str, chunks: list[dict], session_id: str):
    try:
        import os
        from core.copepod_observability import _configure_local_langfuse_host
        _configure_local_langfuse_host()
        from langfuse import Langfuse
        lf = Langfuse()
        output = {"top_k": len(chunks), "chunks": [
            {"chunk_id": c["chunk_id"], "title": c["title"], "score": c["score"]}
            for c in chunks
        ]}
        eval_trace_id = os.getenv("COPEPOD_EVAL_LF_TRACE_ID")
        if eval_trace_id:
            span = lf.span(
                trace_id=eval_trace_id,
                name="tool/rag_query",
                input={"question": question},
                output=output,
                metadata={"session_id": session_id},
            )
        else:
            span = lf.span(
                name="copepod_rag_query",
                session_id=session_id,
                input={"question": question},
                output=output,
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
