"""Tests TDD — tools/rag_tool.py (slice 3)"""

from unittest.mock import patch

import pytest

from tools.rag_tool import make_rag_tool


# --- Comportement 1 : retourne du contenu réel ---


def test_rag_returns_content():
    rag_tool = make_rag_tool()
    result = rag_tool.invoke({"question": "colonnes abondance copépodes"})
    assert len(result) > 50


# --- Comportement 2 : la source est citée ---


def test_rag_cites_source():
    rag_tool = make_rag_tool()
    result = rag_tool.invoke({"question": "obj_orig_id signification"})
    # Le résultat doit mentionner au moins un titre de doc source
    assert "Source" in result or "—" in result


@pytest.mark.parametrize(
    ("question", "expected_first_title", "required_fact"),
    [
        (
            "Quelle source utiliser pour une CTD mesurée près d'une station ?",
            "Quelle source utiliser pour quelle question ?",
            "Amundsen",
        ),
        (
            "Comment filtrer des stations dans la baie de Baffin ?",
            "Zones géographiques NeoLab",
            "get_zone_info",
        ),
        (
            "Comment calculer m5 et m6 pour les profils UVP ?",
            "Comment calculer m5 et m6 UVP MCA",
            "m6_largecop_dens",
        ),
        (
            "Quel est le grain de samples_cache dans le cache EcoTaxa ?",
            "Tables centrales et grain d’analyse EcoTaxa",
            "une ligne par échantillon",
        ),
        (
            "Quel est l'AphiaID de Calanus glacialis ?",
            "Quelles sont toutes les espèces du genre Calanus",
            "104465",
        ),
        (
            "Comment comparer correctement l'abondance de copépodes UVP EcoTaxa EcoPart avec un filet NeoLabs ?",
            "Comment comparer une abondance UVP avec une abondance de filet NeoLabs",
            "somme des individus / somme des volumes",
        ),
    ],
)
def test_rag_prioritizes_decision_ready_evidence(
    question: str,
    expected_first_title: str,
    required_fact: str,
):
    result = make_rag_tool().invoke({"question": question})

    assert result.startswith(f"**{expected_first_title}")
    assert required_fact in result


# --- Comportement 3 : erreur ChromaDB → message gracieux ---


def test_rag_graceful_on_error():
    rag_tool = make_rag_tool()
    with patch(
        "tools.rag_tool.query_copepod_rag", side_effect=Exception("chroma down")
    ):
        result = rag_tool.invoke({"question": "test erreur"})
    assert "indisponible" in result.lower() or "erreur" in result.lower()
