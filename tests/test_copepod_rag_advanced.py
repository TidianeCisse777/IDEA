"""TDD — RAG avancé : multi-query (core/copepod_rag/query.py)"""
from unittest.mock import patch

import pytest

from core.copepod_rag.query import query_copepod_rag


# ---------------------------------------------------------------------------
# Behaviour 1 — vocabulaire non-canonique trouve le bon chunk
#   "densité copépodes" n'est pas dans les docs mais "abondance" oui.
#   Le multi-query LLM génère des reformulations qui matchent.
# ---------------------------------------------------------------------------

def test_non_canonical_vocabulary_finds_relevant_chunk():
    """Vocabulaire non-canonique (densité) trouve un chunk sur l'abondance."""
    alternative_queries = [
        "abondance copépodes par mètre cube",
        "concentration organismes planctoniques",
        "densité copépodes Arctique",
    ]
    with patch(
        "core.copepod_rag.query._generate_alternative_queries",
        return_value=alternative_queries,
    ):
        results = query_copepod_rag("densité copépodes Arctique", top_k=3)

    titles = [r["title"].lower() for r in results]
    content = " ".join(r["content"].lower() for r in results)
    assert any(
        "abondance" in t or "calanus" in t or "copépode" in t or "distribution" in t
        for t in titles
    ) or "abondance" in content or "calanus" in content, (
        f"Aucun chunk pertinent trouvé. Titres: {titles}"
    )


# ---------------------------------------------------------------------------
# Behaviour 2 — intégration : multi-query
#   La question utilise un terme non-canonique ("identifier les organismes").
# ---------------------------------------------------------------------------

def test_full_pipeline_multi_query():
    """Pipeline : reformulations mockées + tri par distance Chroma."""
    alternatives = [
        "taxonomie copépodes identification espèces",
        "classification organismes planctoniques",
    ]
    with patch(
        "core.copepod_rag.query._generate_alternative_queries",
        return_value=alternatives,
    ):
        results = query_copepod_rag("identifier les organismes copépodes", top_k=3)

    assert len(results) <= 3
    assert all("chunk_id" in r and "title" in r and "content" in r for r in results)


def test_rag_contains_neolabs_standard_abundance_and_ordination_methods():
    """Le RAG documente les analyses réalistes NeoLabs abondance + CTD."""
    from pathlib import Path

    chunks = Path("core/copepod_rag/chunks.json").read_text(encoding="utf-8").lower()

    assert "analyses standard neolabs abondance + ctd" in chunks
    assert "ind./m3" in chunks or "ind m" in chunks
    assert "ctd_match_status" in chunks
    assert "shannon" in chunks
    assert "simpson" in chunks
    assert "pielou" in chunks
    assert "anomalie" in chunks
    assert "ordination" in chunks
    assert "pcoa" in chunks
    assert "nmds" in chunks
    assert "rda" in chunks
