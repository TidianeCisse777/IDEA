"""Test-wide fixtures."""
from __future__ import annotations

import os
import pytest


@pytest.fixture(autouse=True)
def _isolate_erddap_cache(monkeypatch, tmp_path_factory):
    """Each test gets its own ERDDAP cache file — no leakage from real runs."""
    cache_path = tmp_path_factory.mktemp("erddap_cache") / "cache.sqlite"
    monkeypatch.setenv("ERDDAP_CACHE_PATH", str(cache_path))
    monkeypatch.delenv("ERDDAP_CACHE_DISABLED", raising=False)
    import core.erddap_cache as cache_module
    cache_module._initialized.clear()
    yield
    cache_module._initialized.clear()
