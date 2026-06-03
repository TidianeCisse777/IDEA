# Audit — Contexte donné à l'agent copépode

**Date :** 2026-06-03
**Scope :** profil `copepod` uniquement (le profil `generic` est mentionné par comparaison).
**Objectif :** rendre limpide ce que le LLM reçoit à chaque tour, identifier les zones floues ou dupliquées.

---

## 1. TL;DR

- **Il n'y a PAS de séparation planner/executor.** Un seul appel LLM par tour. Le "plan" est une convention de prompt ("écris un plan puis le code dans la même réponse"), pas une architecture.
- **Le LLM reçoit 3 couches** : un system_message statique, un custom_instructions composé de blocs, un historique. Les tools sont déjà exécutés dans le sandbox (le LLM voit leurs signatures dans le custom_instructions).
- **Pour le profil copépode**, le system_message est muté à chaque tour (notes contextuelles ajoutées). C'est la principale source de complexité.

---

## 2. Le pipeline en 2 phases

### Phase A — Création de l'interpreter (1× par `session_key`)

```
core/interpreter_session.py::get_or_create_interpreter
```

1. Instancier `OpenInterpreter()`
2. Récupérer le profil : `profile = get_profile(agent_type)`
3. Pour `generic` uniquement : lire en DB le `SystemPrompt` actif du user → `active_prompt`
4. `interpreter.system_message = profile.get_system_message(active_prompt)`
   - **`generic`** : `sys_prompt + active_prompt` (lit la DB)
   - **`copepod`** : `COPEPOD_SYSTEM_PROMPT` constant (ignore `active_prompt`)
5. Configurer le LLM : model, temperature, context_window, api_key, etc.
6. **Injecter les tools** : `interpreter.computer.run("python", profile.get_tool_code())` — ~3000 lignes de Python définissent toutes les fonctions disponibles dans le sandbox.
7. Monkeypatch `interpreter.llm.completions` (workaround `gpt-5.4-mini` via OpenRouter)
8. Stocker l'interpreter dans `interpreter_instances[session_key]` (cache global)

Cette phase n'arrive qu'une fois par session. Tous les tours suivants réutilisent le même interpreter caché.

### Phase B — Chaque tour de chat (à chaque POST `/chat`)

```
routers/chat_routes.py::chat_endpoint → event_stream
```

1. Acquérir un `threading.Lock` par `session_key` (P3 fix — serialise les tours sur la même session)
2. Compter les tours utilisateur passés (`user_turns`) depuis `session_store`
3. Démarrer un `ChatRuntimeTracer` Langfuse
4. Gather MCP tools disponibles → descriptions textuelles
5. **`interpreter.custom_instructions = profile.get_custom_instructions(...)`**
   - Re-rendu à chaque tour
   - Pour copépode : 4 blocs concaténés
     - `output_format` — vision, sauvegarde des plots
     - `copepod_tool_signatures` — signatures des fonctions copépode
     - `mcp_tools_block` — liste des tools MCP disponibles
     - `session_metadata` — host, user_id, session_id, online_mode, chemin uploads
6. Restaurer l'historique depuis `session_store.read_messages(session_key)` → `interpreter.messages`
7. Persister le message user entrant dans `session_store`
8. **[generic uniquement]** `plan_and_run_mcp_tools(...)` — LLM-router séparé qui décide d'invoquer ou non des tools MCP en pre-step. **Skippé pour copépode** (cf. [ADR 005](adr/005-mcp-planner-skipped-for-copepod.md))
9. **[copépode uniquement]** Injection d'env vars dans le sandbox via `computer.run` :
   - `IDEA_RUNTIME_SESSION_KEY`
   - `IDEA_RUNTIME_ROUND`
10. **[copépode uniquement]** Calculer 3 notes contextuelles :
    - `copepod_inspect_then_code_note` (hints sur les join keys détectées — depuis le fix de consolidation)
    - `copepod_session_resources_note` (working set, fichiers, etc.)
    - `retry_note` (si erreur précédente)
11. **[copépode uniquement]** Boucle retry (max 2) :
    - Re-muter `interpreter.system_message = base + notes_dynamiques`
    - Strip les system messages de l'historique (`_strip_system_messages`)
    - Streamer `interpreter.chat(stream=True)` → SSE
    - Détecter une erreur ? → calculer `_build_copepod_error_recovery_note` et retry
12. `finally` : restaurer `interpreter.system_message = base_system_message`
13. Persister l'historique final dans `session_store`
14. Fermer la trace Langfuse

---

## 3. Ce que voit le LLM (vue depuis l'API LLM)

Le payload final envoyé à LiteLLM ressemble à :

```jsonc
{
  "model": "openrouter/openai/gpt-5.4-mini",
  "messages": [
    // ─── Couche 1 : system_message (composé) ──────────────────────────
    {
      "role": "system",
      "content": [
        "<COPEPOD_SYSTEM_PROMPT — 308 lignes statiques>",
        "",
        "<custom_instructions — 4 blocs render()'s, ~80 lignes>",
        "",
        "## Inspection context for this turn",
        "- Join keys already surfaced by inspection: station | time | depth.",
        "",
        "<copepod_session_resources_note si applicable>",
        "",
        "<retry_note si retry actif>"
      ]
    },
    // ─── Couche 2 : historique restauré (sans system messages) ──────
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "computer", "type": "console", "content": "..."},
    // ...
    // ─── Couche 3 : le message user du tour courant ──────────────────
    {"role": "user", "content": "<dernière question + Files uploaded:>"}
  ],
  "temperature": 0.3,
  "max_tokens": 4096,
  // PAS de "tools" — copépode n'utilise pas le function-calling
}
```

Les **tools** ne sont pas dans ce payload : ils sont déjà exécutés dans le sandbox Python à la création de l'interpreter, et leurs signatures sont décrites textuellement dans `copepod_tool_signatures` (inclus dans le system_message).

---

## 4. Comparaison `generic` vs `copepod`

| Aspect | `generic` | `copepod` |
|---|---|---|
| Source du system_message | `sys_prompt + active_user_prompt` (DB) | `COPEPOD_SYSTEM_PROMPT` (constant) |
| `active_user_prompt` respecté | ✅ | ❌ (silently dropped — P1, pas encore fixé) |
| Blocs `instruction_blocks` | `output_format, cli_reference, tool_signatures, mcp_tools_block, session_metadata` | `output_format, copepod_tool_signatures, mcp_tools_block, session_metadata` |
| Tag `cli_reference` (Codex) | ✅ | ❌ (non documenté — P13) |
| MCP pre-planner | ✅ `plan_and_run_mcp_tools` | ❌ skippé ([ADR 005](adr/005-mcp-planner-skipped-for-copepod.md)) |
| Retry sur erreur | ❌ | ✅ max 2 retries avec recovery_note |
| Env vars runtime | ❌ | ✅ `IDEA_RUNTIME_SESSION_KEY`, `IDEA_RUNTIME_ROUND` |
| system_message muté par tour | ❌ stable | ✅ recomposé (+ notes) |
| Working set Redis | ❌ | ✅ `seen_files`, `active_files`, `latest_inspection_by_file`, `current_user_goal` |
| Lock concurrence (P3) | ✅ | ✅ |

---

## 5. Le « planner » — état réel

L'utilisateur peut penser qu'il y a un planner/executor séparé. **Ce n'est pas le cas.**

| Concept | État réel |
|---|---|
| Planner LLM séparé | ❌ **N'existe pas** pour copépode. Pour `generic`, seul `plan_and_run_mcp_tools` joue un rôle de routing MCP (pas un vrai planner d'analyse). |
| "Plan" mentionné dans `COPEPOD_SYSTEM_PROMPT` | ✅ **Convention de prompt** : "écris un plan en 5–10 lignes puis le code dans la même réponse" — un seul appel LLM, le plan et le code sortent dans la même génération. |
| Phase Plan Mode → Analyse (ancien workflow) | ❌ **Supprimé.** L'ancienne machine d'état avec artifacts (Data Understanding, Graph Context, `[PLAN_READY]`) a été retirée — cf. `routers/session_routes.py` qui ne contient plus que l'online-mode. |
| Validateur backend du plan | ❌ Aucun. Le LLM est libre de produire un plan + code dans la même réponse, le backend ne vérifie pas. |
| Boucle retry | ✅ Si une erreur d'exécution est détectée (traceback, KeyError), le tour est rejoué avec une `recovery_note` injectée dans le system. Max 2 fois. |

**Conclusion :** une seule génération LLM par tour. Le "plan" est de la **discipline de prompt**, pas une étape architecturale.

---

## 6. Incohérences identifiées (audit complet)

### 🔴 Critiques

| # | Problème | Statut |
|---|---|---|
| P1 | `active_user_prompt` silently dropped par `CopepodProfile.get_system_message` | ❌ Non fixé — out of scope (le user a dit "focus copepod, pas la création de profil") |
| P2 | Lookup DB du active_prompt hardcodé sur `agent_type == "generic"` dans `interpreter_session.py` | ❌ Non fixé — même raison |
| **P3** | **Race condition sur `interpreter.system_message`** (mutation par tour sans lock) | ✅ **Fixé** — `threading.Lock` par `session_key` |
| **P4** | **MCP planner skippé pour copépode sans doc** | ✅ **Fixé** — commentaire + [ADR 005](adr/005-mcp-planner-skipped-for-copepod.md) |

### 🟠 Sérieuses

| # | Problème | Statut |
|---|---|---|
| **P5** | Règles "inspect-then-code" dupliquées entre `COPEPOD_SYSTEM_PROMPT` et `_build_copepod_inspect_then_code_note` | ✅ **Fixé** — dynamic note réduit aux hints concrets seulement |
| P6 | Drift possible entre tools réels (Python sandbox) et signatures décrites (`copepod_tool_signatures.py`) | ❌ Non fixé — pas de validation automatique |
| P7 | Pas de planner/executor architectural — clarifié dans cet audit | ✅ Documenté |

### 🟡 Mineures

| # | Problème | Statut |
|---|---|---|
| P8 | `_BLOCKS` constante module + attribut classe dupliqués | ❌ |
| P9 | `output_format.py` lit `upload_dir` sans l'utiliser | ❌ |
| P10 | `MCP_TOOL_ROUTING_PROMPT` ultra-générique | ❌ |
| P11 | Monkeypatch litellm hardcodé `gpt-5.4-mini` | ❌ |
| P12 | `_strip_system_messages` peut perdre des system intermédiaires | ❌ |
| P13 | `cli_reference` exclu de copépode sans raison documentée | ❌ |
| P14 | Pas de versionnage du prompt — traçabilité Langfuse manquante | ❌ |

---

## 7. Fixes appliqués (pas encore commités)

### Fix P3 — Lock concurrence

**Fichier :** `routers/chat_routes.py`

Ajout de :
```python
_SESSION_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)

def _session_lock(session_key: str) -> threading.Lock:
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS[session_key]
```

Le générateur `event_stream` est désormais wrappé :
```python
def event_stream():
    with _session_lock(session_key):
        yield from _event_stream_locked()
```

**Impact :** deux requêtes parallèles sur la même `session_key` sont sérialisées. La 2e attend que la 1ère finisse (chunk streaming inclus).

### Fix P4 — Documentation du skip MCP planner

**Fichiers :** `routers/chat_routes.py` (commentaire), `docs/adr/005-mcp-planner-skipped-for-copepod.md` (ADR).

**Rationale documenté :**
1. Redondance — copépode a déjà ses tools métier
2. Discipline du turn — un pre-step `🔧 Using ...` casserait "plan + code en 1 réponse"
3. Coût tokens — éviter un LLM-router redondant
4. Latence — gain ~1-2s de time-to-first-token

### Fix P5 — Consolidation inspect-then-code

**Fichier :** `routers/chat_routes.py::_build_copepod_inspect_then_code_note`

Avant : 12 lignes de **règles permanentes** (déjà dans `COPEPOD_SYSTEM_PROMPT`) + 1 ligne de hints (join_keys).
Après : uniquement les **hints concrets**, retourne `None` si aucun hint à surfacer.

```python
hints: list[str] = []
if join_hints:
    hints.append(f"- Join keys already surfaced by inspection: {' | '.join(join_hints[:2])}.")

if not hints:
    return None

return "## Inspection context for this turn\n" + "\n".join(hints)
```

**Tests** mis à jour dans `tests/test_chat_routes.py::TestCopepodInspectThenCodeNote` pour vérifier que les phrases-règles (`"INSPECT required before code"`, etc.) ne sont **plus** dans le note — elles restent uniquement dans `COPEPOD_SYSTEM_PROMPT`.

---

## 8. Recommandations restantes

Par ordre d'impact :

| # | Action | Effort |
|---|---|---|
| R1 | Soit faire copépode respecter `active_user_prompt`, soit refuser explicitement quand il en a un (lever, logger) — P1 | M |
| R2 | Extraire la résolution d'`active_prompt` du `interpreter_session.py` (méthode sur le profil) — P2 | M |
| R3 | Single source of truth pour les tools (introspection runtime ou tests d'alignement) — P6 | L |
| R4 | Cleanup mineurs (P8/P9/P10/P11/P12/P13) | S |
| R5 | Logger un hash `system_message + custom_instructions` à chaque tour dans Langfuse — P14 | S |

---

## 9. Liens

- [`CLAUDE.md`](../CLAUDE.md) — architecture globale
- [`agents/copepod_profile.py`](../agents/copepod_profile.py) — profil copépode
- [`agents/copepod_prompt.py`](../agents/copepod_prompt.py) — `COPEPOD_SYSTEM_PROMPT` (308L)
- [`routers/chat_routes.py`](../routers/chat_routes.py) — pipeline du tour de chat
- [`core/interpreter_session.py`](../core/interpreter_session.py) — création de l'interpreter
- [`core/tool_registry/README.md`](../core/tool_registry/README.md) — tools & tags
- [`docs/adr/005-mcp-planner-skipped-for-copepod.md`](adr/005-mcp-planner-skipped-for-copepod.md) — ADR planner MCP
