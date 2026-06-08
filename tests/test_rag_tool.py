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


# --- Comportement 3 : erreur ChromaDB → message gracieux ---

def test_rag_graceful_on_error():
    rag_tool = make_rag_tool()
    with patch("tools.rag_tool.query_copepod_rag", side_effect=Exception("chroma down")):
        result = rag_tool.invoke({"question": "test erreur"})
    assert "indisponible" in result.lower() or "erreur" in result.lower()
