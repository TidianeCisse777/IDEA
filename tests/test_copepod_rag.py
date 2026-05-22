"""
Tests for the copepod RAG pipeline: chunking, indexing, retrieval.

Smoke tests cover the full pipeline end-to-end. They require the index to
have been built (build_index.py must run first). Skip gracefully if ChromaDB
or sentence-transformers are not available in the environment.
"""
import json
import pytest
from pathlib import Path

RAG_DIR = Path(__file__).parent.parent / "core" / "copepod_rag"
CHUNKS_FILE = RAG_DIR / "chunks.json"
CHROMA_DIR = RAG_DIR / "chroma_db"


# ── chunk_docs ────────────────────────────────────────────────────────────────

class TestChunkDocs:
    def test_chunks_file_exists(self):
        assert CHUNKS_FILE.exists(), "Run chunk_docs.py first"

    def test_chunk_count_reasonable(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        assert len(chunks) >= 40, f"Expected ≥40 chunks, got {len(chunks)}"

    def test_all_docs_represented(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        docs = {c["doc"] for c in chunks}
        expected = {
            "colonnes_instruments.md",
            "colonnes_labo.md",
            "colonnes_sources.md",
            "copepodes_domaine.md",
            "methodes_calcul.md",
            "sources_en_ligne.md",
            "taxonomie_worms.md",
        }
        assert expected == docs, f"Missing docs: {expected - docs}"

    def test_each_chunk_has_required_keys(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        for c in chunks:
            assert "doc" in c
            assert "chunk_id" in c
            assert "title" in c
            assert "content" in c
            assert "char_count" in c

    def test_no_empty_chunks(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        for c in chunks:
            assert len(c["content"].strip()) > 0, f"Empty chunk: {c['chunk_id']}"

    def test_chunk_ids_unique(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids)), "Duplicate chunk IDs"

    def test_char_count_matches_content(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        for c in chunks:
            assert c["char_count"] == len(c["content"])

    def test_acq_pixel_chunk_exists(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        texts = " ".join(c["content"] for c in chunks)
        assert "acq_pixel" in texts, "acq_pixel not found in any chunk"

    def test_calanus_chunk_exists(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        texts = " ".join(c["content"] for c in chunks)
        assert "Calanus" in texts, "Calanus not found in any chunk"

    def test_biovolume_chunk_exists(self):
        chunks = json.loads(CHUNKS_FILE.read_text())
        texts = " ".join(c["content"] for c in chunks)
        assert "biovolume" in texts.lower(), "biovolume not found in any chunk"


# ── query (requires built index) ──────────────────────────────────────────────

def _rag_available():
    try:
        import chromadb  # noqa: F401
        return CHROMA_DIR.exists()
    except ImportError:
        return False


@pytest.mark.skipif(not _rag_available(), reason="ChromaDB index not built")
class TestRagQuery:
    @pytest.fixture(scope="class")
    def rag(self):
        from core.copepod_rag.query import query_copepod_rag
        return query_copepod_rag

    def test_returns_list(self, rag):
        results = rag("acq_pixel")
        assert isinstance(results, list)

    def test_returns_top_3_by_default(self, rag):
        results = rag("acq_pixel")
        assert len(results) == 3

    def test_result_has_required_keys(self, rag):
        results = rag("acq_pixel")
        for r in results:
            assert "chunk_id" in r
            assert "doc" in r
            assert "title" in r
            assert "content" in r
            assert "score" in r

    def test_acq_pixel_top_result_is_relevant(self, rag):
        results = rag("acq_pixel signification unité")
        top = results[0]
        assert "acq_pixel" in top["content"] or "pixel" in top["content"].lower()

    def test_calanus_query_finds_domain_doc(self, rag):
        results = rag("différence entre Calanus glacialis et hyperboreus")
        docs_found = {r["doc"] for r in results}
        assert "copepodes_domaine.md" in docs_found

    def test_biovolume_esd_query_finds_method(self, rag):
        results = rag("comment calculer le biovolume à partir de ESD")
        docs_found = {r["doc"] for r in results}
        assert "methodes_calcul.md" in docs_found

    def test_scores_are_floats(self, rag):
        results = rag("station Amundsen CTD")
        for r in results:
            assert isinstance(r["score"], float)

    def test_top_k_respected(self, rag):
        results = rag("ecotaxa colonnes", top_k=5)
        assert len(results) == 5

    def test_session_id_does_not_crash(self, rag):
        results = rag("sources disponibles", session_id="test-session-123")
        assert len(results) > 0


# ── tool registry integration ─────────────────────────────────────────────────

class TestToolRegistration:
    def test_copepod_rag_tool_registered(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_rag  # noqa: F401 — triggers registration
        code = registry.render({"copepod_rag"})
        assert "query_copepod_knowledge_base" in code

    def test_rendered_code_is_executable(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_rag  # noqa: F401
        code = registry.render({"copepod_rag"})
        ns = {}
        exec(code, ns)
        assert "query_copepod_knowledge_base" in ns

    def test_function_has_docstring(self):
        from core.tool_registry import registry
        from core.tool_registry.tools import copepod_rag  # noqa: F401
        code = registry.render({"copepod_rag"})
        ns = {}
        exec(code, ns)
        fn = ns["query_copepod_knowledge_base"]
        assert fn.__doc__ is not None and len(fn.__doc__) > 20
