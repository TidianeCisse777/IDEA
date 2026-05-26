"""
Functional retrieval tests for copepod RAG business questions and edge cases.

These tests verify that domain-specific questions retrieve the chunks needed
to answer safely, including schema aliases and source distinctions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest


RAG_DIR = Path(__file__).parent.parent / "core" / "copepod_rag"
CHROMA_DIR = RAG_DIR / "chroma_db"


def _rag_available() -> bool:
    try:
        import chromadb  # noqa: F401
        return CHROMA_DIR.exists()
    except ImportError:
        return False


@dataclass(frozen=True)
class FunctionalRagScenario:
    question: str
    expected_docs: tuple[str, ...]
    expected_terms: tuple[str, ...]
    forbidden_top_terms: tuple[str, ...] = ()


FUNCTIONAL_SCENARIOS = (
    FunctionalRagScenario(
        question="LOKI pixel_um_size convertir une longueur de pixels en mm",
        expected_docs=("colonnes_instruments.md",),
        expected_terms=("acq_pixel_um_size", "/ 1000", "longueur_mm"),
        forbidden_top_terms=("object_feret * acq_pixel",),
    ),
    FunctionalRagScenario(
        question="CTD embarquée LOKI versus CTD externe indépendante",
        expected_docs=("colonnes_sources.md",),
        expected_terms=("CTD embarquée", "CTD externe", "acq_temperature_ctd", "acq_salinity_ctd"),
        forbidden_top_terms=("PRES", "TE90", "PSAL", "NTRA"),
    ),
    FunctionalRagScenario(
        question="taxon validé txo_display_name ou object_annotation_category, pas classif_auto",
        expected_docs=("colonnes_sources.md",),
        expected_terms=("object_annotation_category", "txo_display_name", "ne remplace pas"),
        forbidden_top_terms=("taxon final = classif_auto",),
    ),
    FunctionalRagScenario(
        question="différence acq_pixel et acq_pixel_um_size pour convertir une taille",
        expected_docs=("colonnes_instruments.md", "colonnes_sources.md"),
        expected_terms=("acq_pixel", "acq_pixel_um_size", "/ 1000"),
        forbidden_top_terms=("sans conversion par `acq_pixel`",),
    ),
    FunctionalRagScenario(
        question="colonnes nulles constantes peut-on conclure sans voir le TSV objet",
        expected_docs=("colonnes_sources.md",),
        expected_terms=("TSV", "contenu réel", "Toujours recalculer"),
        forbidden_top_terms=("peuvent être retirées",),
    ),
    FunctionalRagScenario(
        question="notation API EcoTaxa avec points obj.orig_id txo.display_name TSV avec underscores",
        expected_docs=("colonnes_instruments.md", "colonnes_sources.md"),
        expected_terms=("obj.orig_id", "obj_orig_id", "txo.display_name", "txo_display_name"),
    ),
)


@pytest.mark.skipif(not _rag_available(), reason="ChromaDB index not built")
@pytest.mark.parametrize("scenario", FUNCTIONAL_SCENARIOS, ids=lambda s: s.question[:60])
def test_functional_rag_scenarios_retrieve_business_context(scenario):
    from core.copepod_rag.query import query_copepod_rag

    results = query_copepod_rag(scenario.question, top_k=5)

    docs_found = {result["doc"] for result in results}
    missing_docs = [doc for doc in scenario.expected_docs if doc not in docs_found]
    assert not missing_docs, f"Missing expected docs: {missing_docs}"

    combined = "\n".join(result["content"] for result in results).lower()
    missing_terms = [term for term in scenario.expected_terms if term.lower() not in combined]
    assert not missing_terms, f"Missing expected terms: {missing_terms}"

    top_content = results[0]["content"].lower()
    forbidden_found = [term for term in scenario.forbidden_top_terms if term.lower() in top_content]
    assert not forbidden_found, f"Forbidden terms found in top result: {forbidden_found}"
