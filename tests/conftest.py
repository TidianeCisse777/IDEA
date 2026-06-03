"""
Conftest — neutralise la pollution de `sys.modules` causée par
`test_chat_routes.py`.

`test_chat_routes.py` installe au top-level des stubs (`MagicMock`) en
`sys.modules.setdefault(...)` pour `passlib.context`, `cryptography.fernet`,
`core.auth`, `core.crud`, `core.mcp`, `models`, etc. Comme `setdefault`
n'écrase pas si la clé existe déjà, il suffit d'importer les vrais modules
ici (avant la collecte de pytest) pour que ces stubs soient ignorés.

Sans ce conftest, l'ordre alphabétique fait collecter `test_chat_routes.py`
avant `test_crud.py` / `test_phase4_db.py` / `test_prompt_store.py`, qui
récupèrent alors des MagicMock à la place du vrai code et échouent en chaîne.

Il sauvegarde également `requests.get` (remplacé au module-level par
`test_chat_routes`) et le restaure avant chaque test.
"""
from __future__ import annotations

import requests as _requests

_real_requests_get = _requests.get

# Pré-import des modules réels — neutralise les `sys.modules.setdefault(...)`
# de test_chat_routes.
import passlib.context  # noqa: F401,E402
import cryptography.fernet  # noqa: F401,E402
import litellm  # noqa: F401,E402

import models  # noqa: F401,E402
import core.auth  # noqa: F401,E402
import core.crud  # noqa: F401,E402
import core.crypto  # noqa: F401,E402
import core.security  # noqa: F401,E402
import core.mcp  # noqa: F401,E402


def pytest_runtest_setup(item):  # noqa: ARG001 — pytest hook signature
    """Restaure `requests.get` avant chaque test (test_chat_routes le mute au top-level)."""
    _requests.get = _real_requests_get
