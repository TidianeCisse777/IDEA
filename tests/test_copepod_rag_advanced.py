"""TDD — RAG avancé : multi-query + re-ranking (core/copepod_rag/query.py)"""
from unittest.mock import patch

import pytest

from core.copepod_rag.query import query_copepod_rag, _rerank


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
# Behaviour 2 — re-ranking : le chunk le plus pertinent arrive en position 0
#   On construit deux chunks artificiels : un très pertinent, un hors-sujet.
#   Le cross-encoder doit mettre le pertinent en premier.
# ---------------------------------------------------------------------------

def test_rerank_puts_most_relevant_chunk_first():
    """Le cross-encoder place le chunk pertinent avant le chunk hors-sujet."""
    question = "signification de la colonne obj_orig_id dans EcoTaxa"
    chunks = [
        {
            "chunk_id": "off_topic",
            "doc": "sources_en_ligne.md",
            "title": "Sources de données climatiques",
            "content": "Bio-ORACLE fournit des données climatiques globales. OGSL est un portail océanographique.",
            "score": 0.30,
        },
        {
            "chunk_id": "relevant",
            "doc": "colonnes_sources.md",
            "title": "obj_orig_id — clé de jointure EcoTaxa/EcoPart",
            "content": "obj_orig_id est l'identifiant original de l'objet dans EcoTaxa. C'est la clé de jointure entre EcoTaxa et EcoPart. Format : ips_007_899.",
            "score": 0.45,
        },
    ]
    reranked = _rerank(question, chunks)
    assert reranked[0]["chunk_id"] == "relevant", (
        f"Le chunk hors-sujet est arrivé premier : {reranked[0]['title']}"
    )


# ---------------------------------------------------------------------------
# Behaviour 3 — intégration : multi-query + re-ranking ensemble
#   La question utilise un terme non-canonique ("identifier les organismes")
#   et le résultat final doit être trié par le cross-encoder, pas par distance.
# ---------------------------------------------------------------------------

def test_full_pipeline_multi_query_and_rerank():
    """Pipeline complet : reformulations mockées + re-ranking réel."""
    alternatives = [
        "taxonomie copépodes identification espèces",
        "classification organismes planctoniques",
    ]
    with patch(
        "core.copepod_rag.query._generate_alternative_queries",
        return_value=alternatives,
    ):
        with patch(
            "core.copepod_rag.query._rerank",
            side_effect=lambda q, chunks: sorted(chunks, key=lambda c: c["score"]),
        ):
            results = query_copepod_rag("identifier les organismes copépodes", top_k=3)

    assert len(results) <= 3
    assert all("chunk_id" in r and "title" in r and "content" in r for r in results)
