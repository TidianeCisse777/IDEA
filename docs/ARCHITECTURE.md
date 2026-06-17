# Architecture IDEA — runtime de l'assistant graphique copépodes

Ce document décrit le câblage réel du runtime tel qu'il tourne aujourd'hui sur `main`. Il complète `CLAUDE.md` (quickstart) et `CONTEXT.md` (identité métier).

---

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Open WebUI  (frontend, conteneur open_webui, port 3000)                 │
│   • Upload de fichiers, gestion des conversations                       │
│   • POST /v1/chat/completions, SSE pour le streaming                    │
│   • Bridge feedback (👍 / 👎) → polling Langfuse                        │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │  OpenAI-compatible API
┌───────────────────────────────────▼─────────────────────────────────────┐
│ serve.py  (FastAPI, conteneur copepod_agent, port 8000)                 │
│   • /v1/models, /v1/chat/completions (sync + SSE)                       │
│   • /graphs/{filename}, /downloads/{filename}                           │
│   • lifespan : AsyncSqliteSaver checkpointer + feedback polling loop    │
│   • _stream_agent_sse : transforme les updates LangGraph en SSE         │
│   • _extract_and_host_images : héberge les images générées sur /graphs/ │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │  agent.ainvoke / agent.astream
┌───────────────────────────────────▼─────────────────────────────────────┐
│ agent.py  (LangGraph ReAct)                                             │
│   • create_react_agent(llm, tools, checkpointer, pre_model_hook)        │
│   • system prompt : LangSmith hub copepod-system-prompt (fallback local)│
│   • pre_model_hook :                                                    │
│       1. truncate ToolMessages > MAX_TOOL_RESULT_CHARS (8000)           │
│       2. trim_messages strategy="last" ≤ MAX_CONTEXT_TOKENS (40000)     │
│   • _find_invalid_tool_history_cut_index : nettoie les orphelins        │
│     tool_call ↔ ToolMessage (LangGraph exige cet équilibre)             │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │  agent appelle les tools
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
  ┌──────────┐                ┌──────────┐                ┌──────────────┐
  │ Data     │                │ Sources  │                │ Skills + RAG │
  │ tools    │                │ en ligne │                │              │
  │          │                │          │                │              │
  │ load_file│                │ EcoTaxa  │                │ load_skill   │
  │ run_pandas               │ EcoPart  │                │ query_kb     │
  │ run_graph                │ Amundsen │                │              │
  │          │                │ Bio-ORACLE                │              │
  │ SQL      │                │          │                │ ChromaDB     │
  │ workspace│                │ (clients │                │ (9 docs)     │
  └──────────┘                │  core/*) │                │              │
                              └──────────┘                └──────────────┘
```

### Service voisin : MCP EcoTaxa (`mcp-ecotaxa`, port 8001)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ mcp-ecotaxa  (FastMCP, conteneur mcp_ecotaxa, port 8001)                 │
│   • GET  /health     — public, expose cache_age_hours, samples_indexed…  │
│   • POST /mcp        — Bearer, Streamable HTTP MCP transport             │
│   • POST /admin/resync — Bearer, fire-and-forget sync (202 + run_id)     │
│   • GET  /admin/sync_runs/{id} — Bearer, statut d'un run                 │
│   • Apscheduler nightly 3 AM (UTC) → run_full_sync                       │
│                                                                          │
│   15 tools MCP read-only, regroupés par UC :                             │
│   UC1 samples_in_region, projects_in_region              (cache SQLite)  │
│   UC2 find_observations                                  (cache + live)  │
│   UC3 taxa_stats                                                         │
│   UC4 get_project_schema, get_column_distribution                        │
│   UC5 compare_project_schemas                                            │
│   UC6 search/get/list × project / sample / acquisition / object          │
│   UC7 taxonomy_node, search_taxa                                         │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP read-only à ecotaxa.obs-vlfr.fr
                                    ▼
                          ┌─────────────────────┐
                          │ ecotaxa.obs-vlfr.fr │
                          └─────────────────────┘
```

`core/ecotaxa_browser/` (Python pur, ni LangChain ni FastMCP) est partagé entre l'agent IDEA (via les `@tool` LangChain de `tools/copepod_sources.py`, import direct) et le serveur MCP (via les `@mcp.tool` de `core/mcp/ecotaxa_server.py`). Voir `core/mcp/README.md` pour les détails côté MCP.

---

## Cycle de vie d'une requête

1. **Réception** — Open WebUI POST `/v1/chat/completions` avec messages + optionnellement `stream: true`.
2. **Filtrage** — `_is_internal_prompt` rejette les prompts injectés par Open WebUI pour le RAG embedding ; `_is_sql_workspace_config_message` détecte la conf SQL collée par l'utilisateur.
3. **Identification de session** — `_thread_id(...)` reconstruit le `thread_id` LangGraph depuis les headers Open WebUI (`X-OpenWebUI-Chat-Id`) ou depuis le payload. Un nouveau thread = nouveau checkpoint LangGraph.
4. **Préparation des messages** — `_prepare_user_content` extrait le texte et les pièces jointes ; les fichiers uploadés sont enregistrés et leur chemin injecté dans le message.
5. **Invocation de l'agent** :
   - **Sync** : `agent.ainvoke(messages, config)` retourne l'état final.
   - **Streaming SSE** : `agent.astream(messages, config, stream_mode="updates")` génère des updates au fur et à mesure. `_stream_agent_sse` les sérialise au format OpenAI `chat.completion.chunk`. Les appels de tools sont annoncés (`🔧 load_file(path='…')`).
6. **Hébergement des images** — Les images base64 produites par `run_graph` sont extraites par `_extract_and_host_images`, sauvegardées dans `data/graphs/`, et remplacées par un lien `/graphs/{filename}` que Open WebUI peut afficher.
7. **Tracing** — `_RunIdCaptureCallback` capture le `run_id` LangSmith pour le bridge feedback. Si `LANGCHAIN_TRACING_V2=true`, la trace remonte sur LangSmith ; le callback Langfuse est wiré séparément.
8. **Réponse** — bloc JSON pour le sync, flux SSE pour le streaming. `[DONE]` clôture le flux.

---

## Pre-model hook : gestion du contexte

L'agent insère un `pre_model_hook` avant chaque appel LLM (voir `agent._make_context_hook`) :

```python
def trim_context(state):
    msgs = _truncate_tool_results(state["messages"])  # ToolMessage > 8k chars → tronqué
    trimmed = trim_messages(
        msgs,
        max_tokens=40000,
        strategy="last",            # garde la queue
        token_counter=approx_tokens,
        include_system=True,        # le system prompt reste toujours
        allow_partial=False,
    )
    return {"messages": trimmed}
```

Deux objectifs : éviter qu'un gros résultat de tool (`query_ecotaxa` peut renvoyer plusieurs Mo) fasse exploser le contexte, et garder l'historique sous le budget de tokens.

---

## Checkpointing

L'agent utilise un `AsyncSqliteSaver` (SQLite local, `data/checkpoints.sqlite`) configuré dans le lifespan de FastAPI :

```python
@asynccontextmanager
async def lifespan(app):
    async with AsyncSqliteSaver.from_conn_string(str(_CHECKPOINTS_DB)) as cp:
        _checkpointer = cp                # override du MemorySaver par défaut
        # ... feedback polling background task
        yield
```

Chaque `thread_id` (= conversation Open WebUI) a sa propre suite de checkpoints. À chaque tour, LangGraph reprend là où il s'est arrêté. Si le serveur redémarre, les conversations existantes continuent à fonctionner — sauf les datasets en session, qui doivent être rechargés (le system prompt impose au LLM de rejouer silencieusement la dernière `query_*` si `run_pandas` échoue avec KeyError).

---

## System prompt : pull depuis LangSmith Hub

`agent._load_system_prompt` tente d'abord `langchain.hub.pull("copepod-system-prompt")`. Si LangSmith est inaccessible ou la clé absente, fallback sur `agents/copepod_system_prompt.COPEPOD_SYSTEM_PROMPT`. Cela permet de mettre à jour le prompt en production sans redéployer le conteneur — `python push_prompt.py` synchronise la version locale vers le hub.

Même chose pour les skills : `push_skills.py` sync `agents/skills/*.md` vers le hub, et `tools/skill_tool.py` les charge à la demande.

---

## Skills : capacités rechargeables

```
agents/skills/*.md   ─ stockés en local
       │
       ▼ push_skills.py
LangSmith hub        ─ source de vérité en prod
       │
       ▼ load_skill(name) ─ tool exposé à l'agent
[skill content]      ─ retourné en string au LLM, qui l'utilise comme guide
```

Le LLM décide quand charger un skill, sur la base des règles dans le system prompt. Exemple : « toute production graphique → `load_skill("graph_planner")` puis `load_skill("graph_writer")` ».

Les skills `uvp_ecotaxa` et `uvp_ecopart` sont chargés automatiquement quand `load_file` détecte un export UVP (hint dans le retour de `load_file`).

---

## RAG : ChromaDB sur 9 documents

```
core/copepod_rag/
  docs/                 9 .md (colonnes_*, copepodes_domaine, methodes_calcul, etc.)
  chunk_docs.py         Découpe en chunks Markdown-aware
  build_index.py        Embedding + push dans ChromaDB local
  query.py              query_copepod_rag(question, top_k) → list[dict]
  chroma_db/            Index persistant (gitignored)
```

`tools/rag_tool.make_rag_tool` enveloppe `query.query_copepod_rag` dans un `@tool` LangChain (`query_copepod_knowledge_base`). Le LLM doit l'appeler **avant** toute affirmation factuelle sur colonnes, méthodes, taxonomie (règle dans le system prompt).

L'embedding est calculé par OpenAI (via Open WebUI quand `BYPASS_EMBEDDING_AND_RETRIEVAL=true` est désactivé), sinon par `sentence-transformers` local.

---

## Open WebUI : intégration spécifique

- **`OPENAI_API_BASE_URL=http://copepod-agent:8000/v1`** — Open WebUI pointe sur le container agent dans le réseau Docker.
- **`RAG_TEMPLATE=[query]`** — sans ça, Open WebUI injecte un template `### Task:…` qui masque le message original et `_is_internal_prompt` le filtre. Le commentaire dans `docker-compose.yml` documente la subtilité.
- **`BYPASS_EMBEDDING_AND_RETRIEVAL=true`** — on désactive le RAG natif d'Open WebUI : c'est l'agent qui gère son RAG copépodes.
- **Feedback polling** — `_feedback_polling_loop` interroge Open WebUI toutes les N secondes via `OPENWEBUI_URL` et remonte les 👍/👎 en signal LangSmith/Langfuse, mappé sur `run_id` du tour correspondant.
- **Hébergement images** — Open WebUI affiche les images via `<img src="...">`. `_extract_and_host_images` réécrit les base64 en URLs `/graphs/{filename}` servies par FastAPI.

Le container Open WebUI s'appelle **`open_webui`** (avec underscore), pas `open-webui` — piège classique pour `docker exec`.

---

## Workspace SQL

`tools/sql_workspace.py` expose trois tools :

- `list_sql_tables()` — liste les tables accessibles par le `DATABASE_URL` configuré.
- `preview_sql_table(table_name, limit=20)` — quelques lignes pour inspection.
- `copy_sql_query_to_workspace(query, name)` — exécute la requête en read-only, écrit le résultat dans `data/sessions/{thread_id}/{name}.parquet`, retourne le chemin pour que `run_pandas` puisse le lire.

`DATABASE_URL` (SQLAlchemy) est lu depuis le `.env` ou peut être collé par l'utilisateur dans la conversation (détecté par `_is_sql_workspace_config_message`). Aucune écriture n'est jamais émise.

Le skill `sql_workspace_query` documente le pattern d'usage pour le LLM.

---

## Livrables PDF

`tools/deliverable_tool.export_deliverable(content, filename)` :

1. Le LLM compile lui-même un markdown structuré (sections, figures, citations) en s'appuyant sur le skill `deliverable_writer` chargé au préalable.
2. Le tool convertit le markdown → HTML via `markdown` (avec extensions tables, fenced_code, attr_list, …).
3. Génère le PDF via **WeasyPrint** (Pango/Cairo, libraries natives exposées par le Dockerfile).
4. Écrit dans `data/downloads/{filename}.pdf` et retourne `/downloads/{filename}` pour Open WebUI.

Le format n'est pas un rapport interprétatif final — c'est un support de révision pour le chercheur (CT-AG-25).

---

## Persistance de session

- `core/run_store.py` — historique des runs (debug, replay).
- `core/session_store.py` — état tabulaire par thread (datasets chargés, copies SQL, métadonnées de plan graphique). Persistance préfixée par `thread_id`.
- `tools/openwebui_uploads.py` — gère les fichiers uploadés par Open WebUI (path, type, métadonnées).
- `tools/public_url.py` — résolution URL → chemin local pour les téléchargements externes.

Quand le serveur redémarre, les datasets en RAM disparaissent mais les checkpoints LangGraph survivent. Le system prompt instruit le LLM de rejouer silencieusement la dernière `query_*` si `run_pandas` lève un KeyError — c'est la réparation automatique.

---

## Observabilité

- **LangSmith** — tracing complet, `_RunIdCaptureCallback` mappe chaque tour à un `run_id`.
- **Langfuse self-hosted** (port 3001) — callback LiteLLM à câbler dans `agent.py`. Pour inspecter une trace : extraire le `session_id` depuis les logs Docker, puis curl Basic Auth (`langfuse-cli` ne marche pas contre le self-hosted, voir mémo dans `assistant-copepodes-specs`).
- **Logs Docker** — `docker logs copepod_agent -f` ; le fichier `logs/` est aussi monté en volume.
- **OpenWebUI feedback** — 👍/👎 remonte en métadata sur le run LangSmith correspondant via le polling.

---

## Ce qui n'existe pas (mais existait avant ou est annoncé)

- ❌ Mode Contexte / Mode Analyse / Mode En Ligne par source — concept des anciennes specs, jamais implémenté. Tout passe par le system prompt.
- ❌ OBIS — retiré du périmètre.
- ✅ OGSL — `query_ogsl` groups large files by station, derives station-specific
  time windows, persists raw `df_ogsl`, and creates a same-cardinality enriched
  table with time/depth match quality.
- ⏳ Génération de graphiques en R — le prompt dit Python ou R, le runtime ne supporte que Python (matplotlib).
- 🗑️ `core/tool_registry/` — vestiges de l'architecture pré-LangChain ; en cours de retrait, les tools modernes sont dans `tools/` à la racine.
- 🗑️ `agents/copepod_prompt.py` — version archivée, le prompt actif est `agents/copepod_system_prompt.py`.
