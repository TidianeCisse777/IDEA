# Plan — Refactor IDEA pour multi-agents

## Contexte

IDEA est un fork d'un assistant géoscientifique FastAPI + OpenInterpreter. On veut y ajouter
un assistant copépodes (NeoLab, Université Laval) sans créer une deuxième codebase.
Problème : `app.py` (1817 lignes) est un God File, et l'injection des tools LLM est hardcodée
pour un seul type d'assistant. Ajouter un deuxième type nécessite aujourd'hui de modifier app.py
à 5+ endroits. Ce refactor crée un seam propre : **un nouveau fichier = un nouveau type d'agent**.

LLM provider déjà découplé (branche `refactor/llm-provider-config`) :
`core/config.py` expose `LLM_MODEL`, `LLM_API_KEY`, `LLM_REASONING_EFFORT`, etc.

---

## Fichiers critiques

| Fichier | Rôle |
|---|---|
| `app.py` | God File — contient tout, à découper |
| `utils/custom_functions.py` | Chaîne Python 633L injectée dans OpenInterpreter |
| `utils/custom_instructions.py` | F-string 239L injectée comme instructions LLM |
| `utils/system_prompt.py` | Prompt de base (150L) |
| `models.py` | Modèles SQLModel — `Conversation` n'a pas de `agent_type` |
| `alembic/versions/4a6f9e0bb0f4_*.py` | Head actuel des migrations |

---

## Pattern d'injection actuel (le seam à créer)

```python
# get_or_create_interpreter() — app.py ~1063
interpreter.system_message = sys_prompt + active_prompt          # hardcodé
interpreter.computer.run("python", custom_tool)                  # hardcodé
# par requête /chat :
interpreter.custom_instructions = get_custom_instructions(...)   # hardcodé
```

---

## Interface AssistantProfile

```python
class AssistantProfile(ABC):
    agent_type: str                          # ex: "generic" | "copepod"

    def get_system_message(self, active_user_prompt: str) -> str: ...
    def get_tool_code(self) -> str: ...      # injecté via computer.run()
    def get_custom_instructions(self, host, user_id, session_id,
                                static_dir, upload_dir, mcp_tools) -> str: ...
    def configure_interpreter(self, interpreter) -> None: ...  # hook optionnel
```

---

## Phases

### Phase 0 — Interface + Registry (fondation)
**Fichiers créés :** `agents/__init__.py`, `agents/base.py`, `agents/registry.py`

`agents/registry.py` expose :
- `register(profile)` — appelé automatiquement à l'import du profile
- `get_profile(agent_type) → AssistantProfile`
- `get_default_profile() → AssistantProfile` (retourne "generic")
- `registered_types() → list[str]`

**Vérification :** `from agents.registry import get_profile` importe proprement.

---

### Phase 1 — GenericProfile (migration sans changement de comportement)
**Fichier créé :** `agents/generic_profile.py`

Wrap les 3 fichiers existants derrière l'interface :
```python
class GenericProfile(AssistantProfile):
    agent_type = "generic"
    def get_system_message(self, p): return sys_prompt + p
    def get_tool_code(self): return custom_tool
    def get_custom_instructions(self, **kw): return _get_ci(**kw)

register(GenericProfile())
```

**Vérification :** `p = GenericProfile(); assert "get_datetime" in p.get_tool_code()`

---

### Phase 2 — CopepodProfile
**Fichier créé :** `agents/copepod_profile.py`

```python
class CopepodProfile(AssistantProfile):
    agent_type = "copepod"
    def get_system_message(self, p): return _COPEPOD_SYS_PROMPT + p
    def get_tool_code(self): return _COPEPOD_TOOL_CODE   # tools EcoTaxa/EcoPart/Amundsen
    def get_custom_instructions(self, **kw): return _COPEPOD_CI_TEMPLATE.format(**kw)

register(CopepodProfile())
```

Le contenu de `_COPEPOD_TOOL_CODE` importe depuis `polar_data_tools` (installé comme
dépendance locale : `polar-data-tools @ file://../assistant-copepodes-specs`).

**Vérification :** `p = CopepodProfile(); assert p.agent_type == "copepod"`

---

### Phase 3 — Wiring dans app.py (5 changements chirurgicaux)
**Fichier modifié :** `app.py`

**3a** — Bootstrap du registry (top of file) :
```python
import agents.generic_profile
import agents.copepod_profile
from agents.registry import get_profile, registered_types
```

**3b** — `make_session_key` ajoute `agent_type` :
```python
def make_session_key(user_id, session_id, agent_type="generic"):
    return f"{user_id}:{session_id}:{agent_type}"
```

**3c** — `clear_session` : fixer le split du path filesystem :
```python
# Avant: user_id, raw_session_id = session_key.split(":", 1)
# Après:
parts = session_key.split(":")   # ["user_id", "session_id", "agent_type"]
user_id, session_id = parts[0], parts[1]
session_dir = STATIC_DIR / user_id / session_id
```

**3d** — `get_or_create_interpreter` utilise le profile :
```python
profile = get_profile(agent_type)
interpreter.system_message = profile.get_system_message(active_prompt)
interpreter.computer.run("python", profile.get_tool_code())
profile.configure_interpreter(interpreter)
```

**3e** — `/chat` lit le header `X-Agent-Type` :
```python
agent_type = request.headers.get("x-agent-type", "generic")
if agent_type not in registered_types():
    agent_type = "generic"
session_key = make_session_key(user.id, session_id, agent_type)
interpreter.custom_instructions = profile.get_custom_instructions(...)
```
Même ajout (2 lignes) dans `/history`, `/clear`, `/load-conversation`.

**Migration Redis :** Les anciennes clés `messages:{user_id}:{session_id}` ne matchent
plus. Les sessions en mémoire sont abandonnées proprement au premier appel post-déploiement.
L'historique Postgres (conversation_routes) est intact.

**Vérification :**
- Sans header → comportement identique à avant
- Avec `X-Agent-Type: copepod` → interpreter séparé, tools copépodes injectés
- Deux sessions même user, même session_id, agents différents → deux entrées distinctes dans `interpreter_instances`

---

### Phase 4 — Migration DB : agent_type sur Conversation
**Fichier créé :** `alembic/versions/xxxx_add_agent_type_to_conversation.py`
```python
def upgrade():
    op.add_column('conversation',
        sa.Column('agent_type', sa.String(64), nullable=False, server_default='generic'))
```
**Fichier modifié :** `models.py` → ajouter `agent_type: str = Field(default="generic")` sur `ConversationBase`

**Vérification :** `alembic upgrade head` propre. Conversations existantes → `generic`.

---

### Phase 5 — Découpage app.py en routers (clean-up structurel)
**Fichiers créés :**
```
routers/__init__.py
routers/auth_routes.py     (~170L) — login, logout, verify, share, change_password
routers/user_routes.py     (~80L)  — CRUD users (superuser)
routers/prompt_routes.py   (~110L) — CRUD prompts, set_active
routers/chat_routes.py     (~700L) — /chat, /history, /clear, /transcribe, MCP helpers
routers/file_routes.py     (~200L) — upload, delete, list, scan
core/interpreter_store.py  (~10L)  — dict interpreter_instances partagé
```

`app.py` après Phase 5 : ~200 lignes de wiring pur.

**Vérification :** Tous les endpoints répondent identiquement. `docker compose up` propre.

---

## Ordre recommandé pour le sprint immédiat

```
Phase 0 → 1 → 2 → 3   (Sprint copépodes — 1 session de travail)
Phase 4 → 5            (Clean-up — PR séparé)
```

## Ajouter un 3e agent à l'avenir

1. Créer `agents/mon_agent.py` avec `agent_type = "mon_agent"`
2. Ajouter `import agents.mon_agent` dans le bloc bootstrap de `app.py`
3. Frontend passe `X-Agent-Type: mon_agent`

**Aucun autre fichier ne change.**
