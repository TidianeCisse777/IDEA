"""Tests TDD — tools/file_loader.py (slice 1)"""
import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from tools.file_loader import load_file


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "profile_id": ["ips_007", "ips_008"],
        "depth": [10.5, 25.0],
        "temperature": [2.1, 1.8],
    })


@pytest.fixture
def tsv_file(sample_df, tmp_path):
    path = tmp_path / "sample.tsv"
    sample_df.to_csv(path, sep="\t", index=False)
    return path


@pytest.fixture
def csv_file(sample_df, tmp_path):
    path = tmp_path / "sample.csv"
    sample_df.to_csv(path, index=False)
    return path


@pytest.fixture
def excel_file(sample_df, tmp_path):
    path = tmp_path / "sample.xlsx"
    sample_df.to_excel(path, index=False)
    return path


@pytest.fixture
def json_file(sample_df, tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(sample_df.to_json(orient="records"))
    return path


@pytest.fixture
def parquet_file(sample_df, tmp_path):
    path = tmp_path / "sample.parquet"
    sample_df.to_parquet(path, index=False)
    return path


# --- Tests de chargement ---

def test_load_tsv(tsv_file, sample_df):
    df, meta = load_file(str(tsv_file))
    assert df.shape == sample_df.shape
    assert list(df.columns) == list(sample_df.columns)
    assert meta["format"] == "tsv"


def test_load_csv(csv_file, sample_df):
    df, meta = load_file(str(csv_file))
    assert df.shape == sample_df.shape
    assert meta["format"] == "csv"


def test_load_excel(excel_file, sample_df):
    df, meta = load_file(str(excel_file))
    assert df.shape == sample_df.shape
    assert meta["format"] == "xlsx"


def test_load_json(json_file, sample_df):
    df, meta = load_file(str(json_file))
    assert df.shape == sample_df.shape
    assert meta["format"] == "json"


def test_load_parquet(parquet_file, sample_df):
    df, meta = load_file(str(parquet_file))
    assert df.shape == sample_df.shape
    assert meta["format"] == "parquet"


# --- Tests des métadonnées ---

def test_metadata_keys(tsv_file):
    _, meta = load_file(str(tsv_file))
    for key in ("path", "format", "n_rows", "n_cols", "columns"):
        assert key in meta, f"clé manquante : {key}"


def test_metadata_shape(tsv_file, sample_df):
    _, meta = load_file(str(tsv_file))
    assert meta["n_rows"] == len(sample_df)
    assert meta["n_cols"] == len(sample_df.columns)


def test_metadata_columns_structure(tsv_file, sample_df):
    _, meta = load_file(str(tsv_file))
    assert len(meta["columns"]) == len(sample_df.columns)
    for col in meta["columns"]:
        assert "name" in col
        assert "dtype" in col


# --- Cas d'erreur ---

def test_unsupported_format(tmp_path):
    bad = tmp_path / "data.xyz"
    bad.write_text("garbage")
    with pytest.raises(ValueError, match="xyz"):
        load_file(str(bad))


def test_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_file("/tmp/inexistant_fichier_copepode.tsv")
