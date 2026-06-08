"""Tests TDD — tools/data_tools.py (slice 2)"""
import io
import base64
from pathlib import Path

import pandas as pd
import pytest

from tools.data_tools import make_tools, _sessions


@pytest.fixture
def tsv_path(tmp_path):
    df = pd.DataFrame({
        "profile_id": ["ips_007", "ips_008", "ips_009"],
        "depth": [10.5, 25.0, 50.0],
        "temperature": [2.1, 1.8, 1.2],
    })
    p = tmp_path / "sample.tsv"
    df.to_csv(p, sep="\t", index=False)
    return str(p)


@pytest.fixture(autouse=True)
def clear_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


# --- Comportement 1 : load_file_tool ---

def test_load_file_tool_stores_df(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert "thread-1" in _sessions
    assert _sessions["thread-1"]["df"] is not None
    assert _sessions["thread-1"]["df"].shape == (3, 3)


def test_load_file_tool_returns_summary(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    result = load_file_tool.invoke({"path": tsv_path})
    assert "3" in result  # n_rows
    assert "profile_id" in result


# --- Comportement 2 : run_pandas ---

def test_run_pandas_scalar(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = len(df)"})
    assert "3" in result


def test_run_pandas_dataframe_returns_markdown(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = df.head(2)"})
    assert "profile_id" in result
    assert "lignes" in result


# --- Comportement 3 : erreur pandas ---

def test_run_pandas_error_shows_columns(tsv_path):
    tools = make_tools("thread-1")
    load_file_tool = next(t for t in tools if t.name == "load_file")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    load_file_tool.invoke({"path": tsv_path})
    result = run_pandas.invoke({"code": "result = df['colonne_inexistante'].mean()"})
    assert "Erreur" in result
    assert "profile_id" in result  # aperçu colonnes


# --- Comportement 4 : sans fichier ---

def test_run_pandas_no_file_loaded():
    tools = make_tools("thread-sans-fichier")
    run_pandas = next(t for t in tools if t.name == "run_pandas")
    result = run_pandas.invoke({"code": "result = df.head()"})
    assert "aucun fichier" in result.lower()
