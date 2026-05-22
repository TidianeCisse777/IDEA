# CLAUDE.md — IDEA · NeoLab, Université Laval

Plateforme FastAPI + OpenInterpreter pour l'exploration de données scientifiques en langage naturel.
L'utilisateur pose une question → IDEA génère et exécute du code Python → répond avec analyses et graphiques.

---

## Repos

```
PROJET_INFO/
  IDEA/                          ← ce repo — runtime web (FastAPI)
  assistant-copepodes-specs/     ← specs TDD + package polar_data_tools
```

Les tools copépodes sont développés et testés dans `assistant-copepodes-specs/`, puis exposés dans IDEA via un `AssistantProfile`.

---

## Architecture post-refactor (mai 2026)

### `app.py` — 189L, wiring uniquement

Point d'entrée FastAPI. N'a pas de logique métier : monte les routers, configure le middleware, démarre les tâches de fond. Si tu dois modifier le comportement d'un endpoint, ne touche pas `app.py`.

### `routers/` — adaptateurs HTTP fins

| Fichier | Endpoints |
|---|---|
| `chat_routes.py` | `/chat`, `/history`, `/clear`, `/transcribe`, `/load-conversation` |
| `auth_routes.py` | `/login`, `/logout`, `/verify`, `/share`, `/change-password` |
| `conversation_routes.py` | CRUD conversations + messages (Postgres) |
| `file_routes.py` | upload, delete, list fichiers |
| `knowledge_base_routes.py` | upload PDF, query RAG (PaperQA) |
| `mcp_routes.py` | CRUD connexions MCP |
| `prompt_routes.py` | CRUD system prompts + set_active |
| `user_routes.py` | CRUD utilisateurs (superuser) |

Les routers n'ont pas de logique — ils appellent `core/`.

### `core/` — logique métier et état

| Module | Responsabilité |
|---|---|
| `auth.py` | JWT : `get_current_user`, `get_auth_token`, `get_db` |
| `config.py` | `settings` — toutes les variables d'env (LLM, DB, sessions) |
| `crud.py` | Helpers ORM : User, SystemPrompt, MCPConnection |
| `crypto.py` | Chiffrement des tokens MCP au repos |
| `db.py` | Engine SQLAlchemy + init superuser |
| `security.py` | bcrypt hash/verify |
| `interpreter_session.py` | **Lifecycle OpenInterpreter** : create, configure, idle-timeout, clear |
| `interpreter_store.py` | Dict global `interpreter_instances` |
| `session_store.py` | **SessionStore ABC** + RedisSessionStore + InMemorySessionStore |
| `prompt_store.py` | Cache DB-backed des system prompts actifs |
| `rag_store.py` | Index PaperQA par utilisateur |
| `mcp/manager.py` | Lifecycle connexions MCP (transports, sessions) |
| `mcp/tools.py` | Invocation d'outils MCP |
| `mcp/__init__.py` | Exporte : `mcp_manager`, `call_mcp_tool`, `list_available_tools` |
| `tool_registry/` | **ToolRegistry** — tools composables par tags |
| `instruction_renderer/` | **InstructionRenderer** — blocs d'instructions LLM composables |

### `agents/` — pattern multi-agent

| Fichier | Rôle |
|---|---|
| `base.py` | `AssistantProfile` ABC : `get_system_message`, `get_tool_code`, `get_custom_instructions`, `configure_interpreter` |
| `registry.py` | `register`, `get_profile`, `get_default_profile`, `registered_types` |
| `generic_profile.py` | Profil géoscience — s'auto-enregistre à l'import |

L'agent est sélectionné via le header HTTP `X-Agent-Type`. Inconnu → fallback `"generic"`.

### `models/`

| Fichier | Contenu |
|---|---|
| `db.py` | Tables SQLModel : User, Conversation, Message, SystemPrompt, MCPConnection + enums |
| `schemas.py` | Pydantic I/O : LoginRequest/Response, PromptCreate/Update/Response, MCPToolCallRequest… |
| `__init__.py` | Réexporte tout — `import models` et `from models import X` continuent de fonctionner |

### `utils/`

| Fichier | Contenu |
|---|---|
| `custom_functions.py` | Shim compat → `core/tool_registry` (ne pas modifier directement) |
| `custom_instructions.py` | Shim compat → `core/instruction_renderer` (ne pas modifier directement) |
| `system_prompt.py` | Prompt de base du profil générique |
| `session_utils.py` | Fonctions pures : `make_session_key`, `parse_session_key`, `session_dir_path`, `resolve_agent_type` |
| `prompt_manager.py` | Shim compat → `core/prompt_store` |
| `pqa_multi_tenant.py` | Shim compat → `core/rag_store` |
| `station_list_appendix.py` | Données de référence tide gauge (lecture seule) |

### `docs/adr/` — décisions d'architecture

- `001-assistant-profile-pattern.md` — Pourquoi ABC + registry plutôt que subclasses
- `002-session-key-3-segments.md` — Pourquoi `user_id:session_id:agent_type`
- `003-tool-injection-via-computer-run.md` — Pourquoi string injectée + limites connues

### `tests/` — 48 tests

| Fichier | Ce qu'il teste |
|---|---|
| `test_agents.py` | Registration, get_profile, get_default_profile |
| `test_phase3_wiring.py` | make_session_key, parse_session_key, session_dir_path |
| `test_phase4_db.py` | Initialisation superuser |
| `test_session_store.py` | InMemorySessionStore (sans Redis) |
| `test_interpreter_session.py` | clear_session, cleanup_idle_sessions (avec mocks) |

---

## Où aller selon ce que tu veux faire

### Ajouter un nouveau type d'agent

1. Crée `agents/mon_agent.py` :

```python
from agents.base import AssistantProfile
from agents.registry import register
from core.tool_registry import registry as tool_registry
from core.instruction_renderer import renderer as instruction_renderer

class MonAgent(AssistantProfile):
    agent_type = "mon_agent"
    tool_tags = {"core", "mon_domaine"}
    instruction_blocks = ["session_metadata", "output_format", "mon_bloc"]

    def get_system_message(self, active_user_prompt):
        return MON_SYSTEM_PROMPT + active_user_prompt

    def get_tool_code(self):
        return tool_registry.render(self.tool_tags)

    def get_custom_instructions(self, host, user_id, session_id, static_dir, upload_dir, mcp_tools=None):
        ctx = {"host": host, "user_id": user_id, "session_id": session_id,
               "static_dir": static_dir, "upload_dir": upload_dir, "mcp_tools": mcp_tools or []}
        return instruction_renderer.render(self.instruction_blocks, ctx)

register(MonAgent())
```

2. Ajoute `import agents.mon_agent` dans le bloc bootstrap de `app.py` (ligne ~23).
3. Le frontend passe `X-Agent-Type: mon_agent`. C'est tout — aucun autre fichier ne change.

### Ajouter un nouvel outil LLM

1. Crée `core/tool_registry/tools/mon_tool.py` :

```python
from core.tool_registry.registry import Tool, registry

_code = '''
def mon_tool(param):
    """Description pour le LLM."""
    ...
'''

registry.register(Tool(name="mon_tool", tags=frozenset({"mon_domaine"}), code=_code))
```

2. Ajoute `from core.tool_registry.tools import mon_tool` dans `core/tool_registry/tools/__init__.py`.
3. Déclare `"mon_domaine"` dans `tool_tags` du profil qui doit avoir cet outil.

### Ajouter un bloc d'instructions LLM

1. Crée `core/instruction_renderer/blocks/mon_bloc.py` :

```python
from core.instruction_renderer.renderer import InstructionBlock, renderer

def _render(ctx: dict) -> str:
    return f"## Mon bloc\n\nContenu avec {ctx.get('user_id', '')}..."

renderer.register(InstructionBlock(name="mon_bloc", tags=frozenset({"mon_domaine"}), render=_render))
```

2. Ajoute l'import dans `core/instruction_renderer/blocks/__init__.py`.
3. Ajoute `"mon_bloc"` dans `instruction_blocks` du profil concerné.

### Modifier la persistance des sessions

→ `core/session_store.py` — interface `SessionStore` + `RedisSessionStore`.
Pour tester sans Redis, utilise `InMemorySessionStore` dans tes tests.

### Modifier le lifecycle de l'interpreter

→ `core/interpreter_session.py` — `get_or_create_interpreter`, `clear_session`, `cleanup_idle_sessions`.

### Modifier le schéma DB

→ `models/db.py` + créer une migration Alembic :
```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
```

### Modifier un format de réponse API

→ `models/schemas.py` uniquement — ne pas toucher `models/db.py`.

### Modifier la gestion des connexions MCP

→ `core/mcp/manager.py` (lifecycle) ou `core/mcp/tools.py` (invocation).

### Modifier la gestion des system prompts

→ `core/prompt_store.py`.

### Modifier le RAG PaperQA

→ `core/rag_store.py`.

---

## Comment les tools arrivent dans l'interpreter

```
HTTP /chat  (header: X-Agent-Type: mon_agent)
  → get_profile("mon_agent")                       # agents/registry.py
  → profile.get_tool_code()                        # tool_registry.render(tool_tags)
  → interpreter.computer.run("python", code_str)   # injection dans le sandbox Python
  → LLM génère du code qui appelle les fonctions définies dans code_str
```

Les fonctions dans `code_str` sont du Python ordinaire exécuté dans le sandbox OpenInterpreter.
Ce ne sont pas des "tools" au sens LLM function-calling — le LLM les invoque en écrivant du code.

---

## Clés de session

Format : `"{user_id}:{session_id}:{agent_type}"` (3 segments).

```python
from utils.session_utils import make_session_key
key = make_session_key("uid", "sid", "generic")  # → "uid:sid:generic"
```

Deux onglets du même utilisateur avec des agents différents = deux interpreters distincts, zéro fuite d'état.
Voir `docs/adr/002-session-key-3-segments.md`.

---

## Démarrage local

```bash
cp example.env .env          # remplir LLM_API_KEY, FIRST_SUPERUSER, etc.
cp frontend/config.example.js frontend/config.js
./local_start.sh             # Docker requis → http://localhost
```

Variables minimum dans `.env` :
- `LLM_MODEL` (ex: `gpt-4o`, `claude-sonnet-4-6`, `openai/Llama-3.3-70B-Instruct`)
- `LLM_API_KEY`
- `FIRST_SUPERUSER` + `FIRST_SUPERUSER_PASSWORD`

## Tests

```bash
python -m pytest tests/ -q
# 48 tests, aucune dépendance externe (Redis, DB, OpenInterpreter mockés)
```
