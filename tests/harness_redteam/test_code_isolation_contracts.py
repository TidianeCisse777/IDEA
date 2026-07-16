"""Étape 9 (P0 sécurité) : le code exécuté ne doit atteindre ni secrets ni réseau.

Ces contrats exercent le vrai `run_pandas` avec un DataFrame chargé, puis
tentent des évasions qu'un LLM écrirait naturellement (`import os`, sockets,
subprocess, `open`). Ils doivent échouer côté agent sans jamais fuiter le
secret, tout en laissant tourner l'analyse pandas/numpy légitime.
"""

from __future__ import annotations

import pandas as pd

from tools.data_tools import make_tools
from tools.session_store import SessionStore


def _run_pandas(tmp_path, monkeypatch, code: str) -> str:
    store = SessionStore(tmp_path / "sessions")
    monkeypatch.setattr("tools.session_store.default_store", store)
    monkeypatch.setattr("tools.data_tools.default_store", store)
    tools = {t.name: t for t in make_tools("redteam-isolation", store=store)}
    frame = pd.DataFrame({"a": [1, 2, 3]})
    csv_path = tmp_path / "d.csv"
    frame.to_csv(csv_path, index=False)
    tools["load_file"].invoke({"path": str(csv_path)})
    return tools["run_pandas"].invoke({"code": code})


def test_executed_code_cannot_read_environment_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-leak")
    result = _run_pandas(
        tmp_path,
        monkeypatch,
        "import os\nresult = os.environ.get('OPENAI_API_KEY')",
    )
    assert "sk-should-never-leak" not in result
    assert "not permitted" in result.lower() or "error" in result.lower()


def test_executed_code_cannot_open_network_sockets(tmp_path, monkeypatch):
    result = _run_pandas(
        tmp_path,
        monkeypatch,
        "import socket\nresult = socket.gethostname()",
    )
    assert "not permitted" in result.lower() or "error" in result.lower()


def test_executed_code_cannot_spawn_subprocess(tmp_path, monkeypatch):
    result = _run_pandas(
        tmp_path,
        monkeypatch,
        "import subprocess\nresult = subprocess.run(['echo', 'x'])",
    )
    assert "not permitted" in result.lower() or "error" in result.lower()


def test_executed_code_cannot_open_files(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    result = _run_pandas(
        tmp_path, monkeypatch, f"result = open({str(secret)!r}).read()"
    )
    assert "TOPSECRET" not in result
    assert "error" in result.lower() or "not permitted" in result.lower()


def test_legitimate_pandas_and_numpy_still_run(tmp_path, monkeypatch):
    result = _run_pandas(
        tmp_path,
        monkeypatch,
        "import numpy as np\nresult = int(np.sum(df['a']))",
    )
    assert "6" in result
