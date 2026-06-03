# CLAUDE.md — IDEA · NeoLab, Université Laval

Plateforme FastAPI + OpenInterpreter pour l'exploration de données scientifiques en langage naturel.
L'utilisateur pose une question → IDEA génère et exécute du code Python → répond avec analyses et graphiques.

---

## Repos

```
PROJET_INFO/
  IDEA/                          ← ce repo — runtime web (FastAPI)
  assistant-copepodes-specs/     ← repo compagnon optionnel pour les tools/tests copépodes
```

Les tools copépodes sont développés et testés dans `assistant-copepodes-specs/` quand ce repo compagnon est présent, puis exposés dans IDEA via un `AssistantProfile`.

---

## Architecture (à jour 2026-06-03)

### `app.py` — 202L, wiring uniquement

Point d'entrée FastAPI. N'a pas de logique métier : monte les routers, configure le middleware (CORS, rate limiter SlowAPI), enregistre les profils d'agents (import side-effect), démarre les tâches de fond. **Si tu dois modifier le comportement d'un endpoint, ne touche pas `app.py`.**

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
| `session_routes.py` | `/session/mode`, artifacts (DU/GC) — workflow Plan Mode copépode |
| `user_routes.py` | CRUD utilisateurs (superuser) |

Les routers n'ont pas de logique métier — ils appellent `core/`.

### `core/` — logique métier et état

#### Infrastructure & auth

| Module | Responsabilité |
|---|---|
| `auth.py` | JWT : `get_current_user`, `get_auth_token`, `get_db` |
| `config.py` | `settings` — toutes les variables d'env (LLM, DB, sessions, Langfuse) |
| `crud.py` | Helpers ORM : User, SystemPrompt, MCPConnection |
| `crypto.py` | Chiffrement des tokens MCP au repos |
| `db.py` | Engine SQLAlchemy + init superuser |
| `security.py` | bcrypt hash/verify |

#### Sessions & interpreter

| Module | Responsabilité |
|---|---|
| `interpreter_session.py` | **Lifecycle OpenInterpreter** : `get_or_create_interpreter`, `clear_session`, `cleanup_idle_sessions` |
| `interpreter_store.py` | Dict global `interpreter_instances` |
| `session_store.py` | **SessionStore ABC** + `RedisSessionStore` + `InMemorySessionStore` |
| `prompt_store.py` | Cache DB-backed des system prompts actifs |
| `rag_store.py` | Index PaperQA par utilisateur (multi-tenant) |

#### Chat streaming & observabilité

| Module | Responsabilité |
|---|---|
| `chat_stream_events.py` | Formatage des événements SSE pour `/chat` |
| `chat_observability.py` | Hooks Langfuse génériques sur le tour de chat |
| `copepod_observability.py` | Scoring + tags Langfuse spécifiques copépode |
| `langfuse_guard.py` | Détecte/masque les PII avant push Langfuse |
| `response_formatting.py` | Normalise les réponses LLM (DELIVERABLE card, etc.) |

#### Copépode

| Module | Responsabilité |
|---|---|
| `copepod_join_validation.py` | Validation des joins EcoTaxa ↔ EcoPart |
| `copepod_rag/` | Index Chroma + `build_index.py`, `chunk_docs.py`, `query.py` |

#### Composables

| Module | Responsabilité |
|---|---|
| `mcp/manager.py` | Lifecycle connexions MCP (transports, sessions) |
| `mcp/tools.py` | Invocation d'outils MCP |
| `mcp/__init__.py` | Exporte `mcp_manager`, `call_mcp_tool`, `list_available_tools` |
| `tool_registry/registry.py` | **ToolRegistry** — `Tool(name, tags, code)` composables |
| `tool_registry/tools/` | Tools concrets : `core_tools`, `climate_tools`, `station_tools`, `rag_tools`, `web_tools`, `mcp_tools`, `copepod_*` (5 fichiers) |
| `instruction_renderer/renderer.py` | **InstructionRenderer** — blocs composables |
| `instruction_renderer/blocks/` | Blocs : `session_metadata`, `output_format`, `cli_reference`, `tool_signatures`, `copepod_tool_signatures`, `mcp_tools_block` |

### `agents/` — pattern multi-agent

| Fichier | Rôle |
|---|---|
| `base.py` | `AssistantProfile` ABC : `get_system_message`, `get_tool_code`, `get_custom_instructions`, `configure_interpreter` |
| `registry.py` | `register`, `get_profile`, `get_default_profile`, `registered_types` |
| `generic_profile.py` | Profil géoscience — s'auto-enregistre à l'import |
| `copepod_profile.py` | Profil copépode (Plan Mode, RAG dédié) — s'auto-enregistre à l'import |
| `copepod_prompt.py` | System prompt et constantes du profil copépode |

L'agent est sélectionné via le header HTTP `X-Agent-Type`. Inconnu → fallback `"generic"`.

### `models/`

| Fichier | Contenu |
|---|---|
| `db.py` | Tables SQLModel : User, Conversation, Message, SystemPrompt, MCPConnection + enums |
| `schemas.py` | Pydantic I/O : LoginRequest/Response, PromptCreate/Update/Response, MCPToolCallRequest… |
| `__init__.py` | Réexporte tout — `import models` et `from models import X` fonctionnent |

### `utils/`

| Fichier | Contenu |
|---|---|
| `custom_functions.py` | Shim compat → `core/tool_registry` (ne pas modifier directement) |
| `custom_instructions.py` | Shim compat → `core/instruction_renderer` (ne pas modifier directement) |
| `system_prompt.py` | Prompt de base du profil générique |
| `session_utils.py` | Fonctions pures : `make_session_key`, `parse_session_key`, `session_dir_path`, `resolve_agent_type` |
| `prompt_manager.py` | Shim compat → `core/prompt_store` |
| `pqa_multi_tenant.py` | Shim compat → `core/rag_store` |
| `transcription_prompt.py` | Prompt pour l'endpoint `/transcribe` (Whisper) |
| `station_list_appendix.py` | Données de référence tide gauge (lecture seule) |
| `my_pqa_settings.py` | Settings PaperQA |
| `generate_pdf_stream.js` | Export PDF côté frontend (utilisé via static) |

### `scripts/`

| Fichier | Rôle |
|---|---|
| `evals/run_copepod_lean_eval.py` | Runner d'éval léger |
| `evals/run_copepod_plan_mode_eval.py` | Runner principal Plan Mode (mock, du-only, gc-only, live, trace-smoke) |
| `evals/copepod/` | Package interne de la suite (harness, fixtures, llm_driver, scénarios) |
| `langfuse_live_log.py` | Poll Langfuse toutes les 5s, écrit dans `logs/langfuse_live.log` |

### `docs/adr/` — décisions d'architecture

- `001-assistant-profile-pattern.md` — Pourquoi ABC + registry plutôt que subclasses
- `002-session-key-3-segments.md` — Pourquoi `user_id:session_id:agent_type`
- `003-tool-injection-via-computer-run.md` — Pourquoi string injectée + limites connues
- `004-plan-ready-tag-for-mode-switch.md` — Pourquoi le tag `[PLAN_READY]` pour le switch Plan → Analyse

### `docs/archive/` — historique

- `status-reports/` — snapshots datés (ne pas mettre à jour)
- `plans/` — plans déjà livrés
- `specs/` — specs ayant abouti à du code mergé

### `tests/` — 33 fichiers, ~494 tests

Tests sans dépendance externe (Redis, DB, OpenInterpreter mockés). Points d'entrée principaux :

| Fichier | Ce qu'il teste |
|---|---|
| `test_agents.py` | Registration, get_profile, get_default_profile |
| `test_session_store.py` | InMemorySessionStore (sans Redis) |
| `test_interpreter_session.py` | clear_session, cleanup_idle_sessions |
| `test_chat_routes.py` / `test_chat_stream_events.py` | Endpoint `/chat` + SSE |
| `test_chat_observability.py` / `test_copepod_observability.py` | Hooks Langfuse |
| `test_copepod_profile.py` / `test_copepod_prompt_contract.py` | Profil copépode + contrat de prompt |
| `test_copepod_data*.py` / `test_copepod_columns.py` / `test_copepod_join_validation.py` | Tools données copépode |
| `test_copepod_rag*.py` / `test_copepod_remote_sources.py` / `test_copepod_sources_meta.py` | RAG + sources copépode |
| `test_copepod_online_mode_*.py` | Politique mode online |
| `test_session_routes.py` | Artifacts DU/GC + `/session/mode` |
| `test_tool_registry_litellm_params.py` | Sérialisation tool registry |
| `test_langfuse_guard.py` | Anti-PII Langfuse |
| `test_response_formatting.py` | DELIVERABLE card |
| `test_docker_portability.py` / `test_share_start_script.py` | Démarrage Docker + script `share_start.sh` |
| `test_mcp_planning.py` | Workflow MCP |
| `test_phase3_wiring.py` / `test_phase4_db.py` | Wiring historique (à conserver) |
| `test_crud.py` / `test_prompt_store.py` / `test_conversation_routes.py` | DB & CRUD |

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
cp share.env.example .env    # remplir LLM_API_KEY, FIRST_SUPERUSER, etc.
cp frontend/config.example.js frontend/config.js
./share_start.sh             # Docker requis → partageable, lit seulement .env
```

Variables minimum dans `.env` :
- `LLM_MODEL` (ex: `gpt-4o`, `claude-sonnet-4-6`, `openai/Llama-3.3-70B-Instruct`)
- `LLM_API_KEY`
- `FIRST_SUPERUSER` + `FIRST_SUPERUSER_PASSWORD`
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_SALT` si Langfuse est activé

## Tests

```bash
python -m pytest tests/ -q
# ~494 tests sur 33 fichiers, aucune dépendance externe (Redis, DB, OpenInterpreter mockés)
```

Pour les **évals copépode Plan Mode** (LLM réel + Langfuse), voir `scripts/evals/README.md`.
