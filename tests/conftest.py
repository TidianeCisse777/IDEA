"""Test-wide fixtures."""
from __future__ import annotations

import os
import tempfile

import pytest

# Isolation posée au niveau module — AVANT que les tests n'importent agent/serve.
# `tools.session_store.default_store` est instancié à l'import du module, et
# load_dotenv() ne remplace pas une variable déjà présente : des valeurs vides ici
# garantissent que la suite n'écrit jamais dans le Postgres de prod ni dans
# data/session_store, et n'envoie jamais de traces réelles à LangSmith.
os.environ["SESSION_STORE_DATABASE_URL"] = ""
os.environ.setdefault("SESSION_STORE_DIR", tempfile.mkdtemp(prefix="session_store_test_"))
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_API_KEY"] = ""
# Idem pour le workspace SQL : sans ça, load_dotenv (déclenché à l'import de
# tools.tool_catalog) réinjecte le DATABASE_URL de démo du .env et fait entrer
# les 3 tools SQL optionnels dans un catalogue censé être sans-SQL. Blanc =
# non configuré ; les tests qui veulent le SQL posent DATABASE_URL via setenv.
os.environ["DATABASE_URL"] = ""


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
