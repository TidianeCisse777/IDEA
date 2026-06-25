"""Tests for core/erddap_cache.py."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def cache_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.delenv("ERDDAP_CACHE_DISABLED", raising=False)
    import core.erddap_cache as mod
    importlib.reload(mod)
    yield mod
    importlib.reload(mod)


def test_cache_returns_none_when_missing(cache_module):
    assert cache_module.cache_get("ns", ("a", 1)) is None


def test_cache_round_trip_with_dict(cache_module):
    payload = {"value": 12.3, "dataset_id": "thetao", "time": "2020"}
    cache_module.cache_set("bio_oracle_point", ("lat", "lon", "var"), payload)
    assert cache_module.cache_get("bio_oracle_point", ("lat", "lon", "var")) == payload


def test_cache_round_trip_with_dataframe(cache_module):
    df = pd.DataFrame({"time": ["2020"], "lat": [10.0], "value": [42.0]})
    cache_module.cache_set("amundsen_bbox", {"bbox": [1, 2]}, df)
    cached = cache_module.cache_get("amundsen_bbox", {"bbox": [1, 2]})
    pd.testing.assert_frame_equal(cached, df)


def test_cache_namespaces_are_isolated(cache_module):
    cache_module.cache_set("a", "k", "value-a")
    cache_module.cache_set("b", "k", "value-b")
    assert cache_module.cache_get("a", "k") == "value-a"
    assert cache_module.cache_get("b", "k") == "value-b"


def test_cache_disabled_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("ERDDAP_CACHE_DISABLED", "1")
    import core.erddap_cache as mod
    importlib.reload(mod)
    try:
        mod.cache_set("ns", "k", "v")
        assert mod.cache_get("ns", "k") is None
    finally:
        importlib.reload(mod)


def test_cache_clear_namespace(cache_module):
    cache_module.cache_set("ns1", "k", "v1")
    cache_module.cache_set("ns2", "k", "v2")
    cache_module.cache_clear("ns1")
    assert cache_module.cache_get("ns1", "k") is None
    assert cache_module.cache_get("ns2", "k") == "v2"
