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
import unicodedata
from pathlib import Path
from typing import Optional

from core.copepod_observability import should_enable_langfuse


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

_QUERY_ALIASES = {
    "obj orig id": ["obj_orig_id", "obj.orig_id"],
    "obj.orig_id": ["obj_orig_id"],
    "txo display name": ["txo_display_name", "txo.display_name"],
    "txo.display_name": ["txo_display_name"],
    "obj classif qual": ["obj_classif_qual", "obj.classif_qual"],
    "obj.classif_qual": ["obj_classif_qual"],
    "fre equivalent diameter area": ["fre_equivalent_diameter_area", "fre.equivalent_diameter_area"],
    "fre.equivalent_diameter_area": ["fre_equivalent_diameter_area"],
    "acq pixel um size": ["acq_pixel_um_size", "acq.pixel_um_size", "pixel_um_size"],
    "pixel um size": ["acq_pixel_um_size", "acq.pixel_um_size", "pixel_um_size"],
    "acq.pixel_um_size": ["acq_pixel_um_size"],
    "ctd embarquée": ["CTD embarquée", "acq_temperature_ctd", "acq_salinity_ctd"],
    "ctd embarquee": ["CTD embarquée", "acq_temperature_ctd", "acq_salinity_ctd"],
    "température salinité oxygène fluorescence": [
        "acq_temperature_ctd",
        "acq_salinity_ctd",
        "acq_oxygen_concent",
        "acq_fluo1",
    ],
}


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
        expanded_question = _expand_query(question)
        candidate_count = max(top_k, min(25, top_k * 5))

        results = _collection.query(
            query_texts=[expanded_question],
            n_results=candidate_count,
            include=["documents", "metadatas", "distances"],
        )

        chunks = []
        for i in range(len(results["ids"][0])):
            content = results["documents"][0][i]
            distance = round(results["distances"][0][i], 4)
            chunks.append({
                "chunk_id": results["ids"][0][i],
                "doc": results["metadatas"][0][i]["doc"],
                "title": results["metadatas"][0][i]["title"],
                "content": content,
                "score": distance,
                "_rank_score": distance - _lexical_boost(expanded_question, content),
            })
        chunks.sort(key=lambda c: (c["_rank_score"], c["score"]))
        chunks = [{k: v for k, v in c.items() if k != "_rank_score"} for c in chunks[:top_k]]
        if session_id and should_enable_langfuse():
            _trace_langfuse(question, chunks, session_id)
        return chunks
    finally:
        if os.getenv("PYTEST_CURRENT_TEST"):
            _close()


def _expand_query(question: str) -> str:
    lower = question.lower().replace("_", " ").replace(".", " ")
    additions = []
    for pattern, aliases in _QUERY_ALIASES.items():
        if pattern in lower or pattern in question.lower():
            additions.extend(aliases)
    if "loki" in lower and "ctd" in lower:
        additions.extend([
            "CTD embarquée",
            "CTD externe indépendante",
            "acq_temperature_ctd",
            "acq_salinity_ctd",
            "acq_raw_depth",
            "capteurs/acquisitions associées",
            "ne pas les confondre",
        ])
    if not additions:
        return question
    return f"{question} {' '.join(dict.fromkeys(additions))}"


def _lexical_boost(expanded_question: str, content: str) -> float:
    content_lower = content.lower()
    terms = {
        term.lower()
        for term in expanded_question.replace(",", " ").split()
        if len(term) >= 3 and ("_" in term or "." in term or term.lower() in {"loki", "ctd"})
    }
    boost = 0.0
    for term in terms:
        if term in content_lower:
            boost += 0.08
    boost += _business_context_boost(expanded_question, content)
    return min(boost, 0.75)


def _business_context_boost(expanded_question: str, content: str) -> float:
    question = _normalize_text(expanded_question)
    content_norm = _normalize_text(content)
    boost = 0.0

    if "loki" in question and "ctd" in question:
        if "ctd embarquee" in content_norm and "ctd externe" in content_norm:
            boost += 0.25
        if "ne pas les confondre" in content_norm or "capteurs/acquisitions associees" in content_norm:
            boost += 0.15

    if "pixel_um_size" in expanded_question or "pixel um size" in question:
        if "acq_pixel_um_size" in content and "/ 1000" in content:
            boost += 0.2
        if "longueur_mm" in content:
            boost += 0.1

    if "acq_pixel" in expanded_question and "acq_pixel_um_size" in expanded_question:
        if "acq_pixel" in content and "acq_pixel_um_size" in content:
            boost += 0.15

    if ("null" in question or "constante" in question) and "tsv" in question:
        if "contenu reel du tsv" in content_norm or "toujours recalculer" in content_norm:
            boost += 0.2

    return boost


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


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
