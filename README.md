# IDEA — Intelligent Data Exploring Assistant

> Plateforme FastAPI + OpenInterpreter pour explorer des données scientifiques en langage naturel.
> L'utilisateur pose une question → IDEA génère et exécute du code Python → répond avec analyses, tableaux et graphiques.

Fork **NeoLab · Université Laval** — étend [UHSLC IDEA](https://github.com/uhsealevelcenter/IDEA) avec un système multi-agent, un assistant copépodes, et l'observabilité Langfuse.

---

## Sommaire

- [En un coup d'œil](#en-un-coup-dœil)
- [Capacités](#capacités)
- [Architecture](#architecture)
- [Fichiers importants](#fichiers-importants)
- [Démarrage rapide](#démarrage-rapide)
- [Configuration](#configuration)
- [Tests](#tests)
- [Multi-agent](#multi-agent)
- [MCP (Model Context Protocol)](#mcp-model-context-protocol)
- [Observabilité — Langfuse](#observabilité--langfuse)
- [Pour aller plus loin](#pour-aller-plus-loin)
- [Contribuer](#contribuer)
- [Citation & Licence](#citation--licence)

---

## En un coup d'œil

| | |
|---|---|
| **Backend** | FastAPI (Python 3.11), SQLModel + Postgres (pgvector), Redis pour les sessions |
| **Exécution code** | [OpenInterpreter](https://github.com/openinterpreter/open-interpreter) sandboxé dans le container |
| **Modèles** | Toute API compatible LiteLLM (OpenAI, Anthropic, OpenRouter, Jetstream2…) |
| **Frontend** | HTML/CSS/JS statique servi par nginx |
| **Auth** | JWT bcrypt, superuser bootstrap depuis `.env` |
| **Observabilité** | Langfuse self-hosted optionnel |
| **RAG** | PaperQA2 multi-tenant pour la knowledge base PDF |
| **Tests** | ~494 tests pytest, aucune dépendance externe (Redis/DB/Interpreter mockés) |

---

## Capacités

- **Ingestion de données** — CSV, TSV, NetCDF, texte, EcoTaxa, EcoPart. Inspection automatique (colonnes, dimensions, manquants).
- **Analyse exploratoire** — séries temporelles, anomalies, cycles saisonniers, tendances, comparaisons inter-stations.
- **Visualisation** — figures publication-ready (matplotlib/cartopy), cartes interactives (folium), packs exportables.
- **Workflows scientifiques** — niveau marin, marégraphie, extrêmes, indices climatiques (ENSO…), workflow **Plan Mode** pour les copépodes (Data Understanding → Graph Context → Analyse).
- **RAG littérature** — index PaperQA2 par utilisateur, upload PDF → réponses augmentées par documents locaux.
- **Multi-agent** — `generic` (géoscience) et `copepod` (taxonomie/écologie zooplancton) sélectionnables par header HTTP.
- **MCP** — connexions outils externes via Model Context Protocol (tokens chiffrés au repos).
- **Sorties reproductibles** — chaque résultat est adossé au code Python qui l'a généré.

---

## Architecture

```
app.py              ← wiring FastAPI uniquement (pas de logique métier)
routers/            ← adaptateurs HTTP fins → appellent core/
core/               ← logique métier + état (interpreter, sessions, MCP, RAG, observabilité)
agents/             ← profils d'assistant (AssistantProfile ABC + registry)
models/             ← SQLModel (DB) + Pydantic (I/O)
utils/              ← helpers + shims de compat
frontend/           ← static HTML/CSS/JS
scripts/evals/      ← suite d'évaluation Langfuse (copépode Plan Mode)
docs/adr/           ← Architecture Decision Records
tests/              ← ~494 tests pytest
```

> **Détail complet :** voir [`CLAUDE.md`](CLAUDE.md) — il décrit où aller pour modifier chaque comportement (router, lifecycle interpreter, schéma DB, nouvel agent, nouvel outil, nouveau bloc d'instructions).

### Flux de requête

```
HTTP /chat (header X-Agent-Type: copepod)
  → get_profile("copepod")                        agents/registry.py
  → profile.get_tool_code()                       core/tool_registry/
  → interpreter.computer.run("python", code_str)  injection dans sandbox
  → LLM génère du code qui appelle les fonctions injectées
  → stream SSE des sorties vers le client
```

Voir [`docs/adr/003-tool-injection-via-computer-run.md`](docs/adr/003-tool-injection-via-computer-run.md).

---

## Fichiers importants

**Tu débarques sur le repo ?** Lis ces fichiers dans cet ordre.

### À lire en premier

| # | Fichier | Pourquoi |
|---|---|---|
| 1 | [`README.md`](README.md) | Ce document — vue d'ensemble, démarrage |
| 2 | [`CLAUDE.md`](CLAUDE.md) | Carte complète du code : où aller pour modifier quoi |
| 3 | [`share.env.example`](share.env.example) | Toutes les variables d'env, avec valeurs par défaut |
| 4 | [`docker-compose.yml`](docker-compose.yml) | Services : web, db, redis, langfuse, langfuse-db |
| 5 | [`app.py`](app.py) | Wiring FastAPI (202L) — comprendre comment tout est branché |

### Points d'entrée par sujet

#### Backend HTTP

| Sujet | Fichier |
|---|---|
| Chat (endpoint principal) | [`routers/chat_routes.py`](routers/chat_routes.py) |
| Auth (JWT, login, share link) | [`routers/auth_routes.py`](routers/auth_routes.py) + [`core/auth.py`](core/auth.py) |
| Conversations (CRUD Postgres) | [`routers/conversation_routes.py`](routers/conversation_routes.py) |
| Upload fichiers | [`routers/file_routes.py`](routers/file_routes.py) |
| Knowledge base PDF (RAG) | [`routers/knowledge_base_routes.py`](routers/knowledge_base_routes.py) + [`core/rag_store.py`](core/rag_store.py) |
| MCP (outils externes) | [`routers/mcp_routes.py`](routers/mcp_routes.py) + [`core/mcp/`](core/mcp/) |
| System prompts | [`routers/prompt_routes.py`](routers/prompt_routes.py) + [`core/prompt_store.py`](core/prompt_store.py) |
| Workflow Plan Mode (copépode) | [`routers/session_routes.py`](routers/session_routes.py) |

#### Cœur métier

| Sujet | Fichier |
|---|---|
| Lifecycle interpreter (create/clear/idle) | [`core/interpreter_session.py`](core/interpreter_session.py) |
| Persistance sessions (Redis / in-memory) | [`core/session_store.py`](core/session_store.py) |
| Streaming SSE du chat | [`core/chat_stream_events.py`](core/chat_stream_events.py) |
| Config (variables d'env) | [`core/config.py`](core/config.py) |
| Schéma DB | [`models/db.py`](models/db.py) |
| Pydantic I/O | [`models/schemas.py`](models/schemas.py) |

#### Multi-agent

| Sujet | Fichier |
|---|---|
| ABC `AssistantProfile` | [`agents/base.py`](agents/base.py) |
| Registry des agents | [`agents/registry.py`](agents/registry.py) |
| Agent géoscience (défaut) | [`agents/generic_profile.py`](agents/generic_profile.py) |
| Agent copépode | [`agents/copepod_profile.py`](agents/copepod_profile.py) + [`agents/copepod_prompt.py`](agents/copepod_prompt.py) |

#### Composables (tools & instructions)

| Sujet | Fichier |
|---|---|
| Registry des tools (par tags) | [`core/tool_registry/registry.py`](core/tool_registry/registry.py) |
| Tools concrets (core, climate, copepod, web…) | [`core/tool_registry/tools/`](core/tool_registry/tools/) |
| Renderer d'instructions (par blocs) | [`core/instruction_renderer/renderer.py`](core/instruction_renderer/renderer.py) |
| Blocs (session, output, signatures, MCP…) | [`core/instruction_renderer/blocks/`](core/instruction_renderer/blocks/) |

#### Observabilité

| Sujet | Fichier |
|---|---|
| Hooks Langfuse génériques | [`core/chat_observability.py`](core/chat_observability.py) |
| Hooks Langfuse copépode | [`core/copepod_observability.py`](core/copepod_observability.py) |
| Anti-PII Langfuse | [`core/langfuse_guard.py`](core/langfuse_guard.py) |
| Live tail des traces | [`scripts/langfuse_live_log.py`](scripts/langfuse_live_log.py) |

#### Frontend

| Sujet | Fichier |
|---|---|
| Shell HTML principal | [`frontend/index.html`](frontend/index.html) |
| Assistant (logique chat côté client) | [`frontend/assistant.js`](frontend/assistant.js) |
| Conversation UI | [`frontend/conversation_ui.js`](frontend/conversation_ui.js) |
| Upload de fichiers | [`frontend/file-upload.js`](frontend/file-upload.js) |
| Reverse-proxy local | [`nginx.conf`](nginx.conf) |

#### Tests & évals

| Sujet | Fichier |
|---|---|
| Tests pytest (~494) | [`tests/`](tests/) |
| Suite éval Plan Mode | [`scripts/evals/README.md`](scripts/evals/README.md) |
| Runner principal | [`scripts/evals/run_copepod_plan_mode_eval.py`](scripts/evals/run_copepod_plan_mode_eval.py) |

---

## Démarrage rapide

**Prérequis :** Docker + Docker Compose.

```bash
# 1. Cloner
git clone <ce-repo> && cd IDEA

# 2. Configurer
cp share.env.example .env             # remplir LLM_API_KEY, FIRST_SUPERUSER_PASSWORD, SECRET_KEY
cp frontend/config.example.js frontend/config.js

# 3. Démarrer (mode partageable — lit uniquement .env, ignore l'env shell)
./share_start.sh
```

Accès : http://localhost (login via les credentials de ton `.env`).

### Autres scripts de lancement

| Script | Usage |
|---|---|
| `./share_start.sh` | Mode partageable, lit uniquement `.env` (recommandé pour onboarding) |
| `./local_start.sh` | Dev local avec `docker-compose.override.yml` (live reload) |
| `./production_start.sh` | Production sans override (build seul, pas de bind-mount) |

---

## Configuration

Variables minimum dans `.env` (voir [`share.env.example`](share.env.example) pour la liste exhaustive) :

| Variable | Exemple | Note |
|---|---|---|
| `LLM_MODEL` | `openrouter/openai/gpt-5.4-mini` | Tout modèle LiteLLM-compatible |
| `LLM_API_KEY` | `sk-...` | Clé du provider LLM |
| `LLM_API_BASE` | `https://openrouter.ai/api/v1` | Base URL provider |
| `SECRET_KEY` | (random 32+) | Pour JWT |
| `FIRST_SUPERUSER` | `admin@idea.com` | Créé au bootstrap si absent |
| `FIRST_SUPERUSER_PASSWORD` | (mot de passe fort) | idem |
| `POSTGRES_*` | — | DB principale (pgvector pour RAG) |
| `LANGFUSE_*` | — | Optionnel — désactive si non rempli |

### Ports par défaut

| Service | Port hôte | Override `.env` |
|---|---|---|
| nginx (frontend) | 80 | `IDEA_NGINX_HOST_PORT` |
| FastAPI (web) | 8002 | `IDEA_WEB_HOST_PORT` |
| Postgres | 5433 | `IDEA_DB_HOST_PORT` |
| Redis | 6380 | `IDEA_REDIS_HOST_PORT` |
| Langfuse | 3001 | `LANGFUSE_HOST_PORT` |

---

## Tests

```bash
python -m pytest tests/ -q
```

~494 tests, exécution locale sans Redis, DB ni LLM (mocks via `InMemorySessionStore`, fixtures FastAPI `TestClient`).

Pour les **évals copépode Plan Mode** (LLM réel + Langfuse), voir [`scripts/evals/README.md`](scripts/evals/README.md).

---

## Multi-agent

L'agent actif est sélectionné par le frontend via le header HTTP `X-Agent-Type`. Inconnu → fallback `"generic"`.

| `agent_type` | Domaine | Tools / Instructions |
|---|---|---|
| `generic` | Géoscience, niveau marin, climat | Tools de base, system prompt UHSLC |
| `copepod` | Taxonomie & écologie copépodes (EcoTaxa/EcoPart) | Workflow Plan Mode, validation joins, RAG dédié |

### Ajouter un agent

1. Créer `agents/mon_agent.py` (sous-classe `AssistantProfile`, déclarer `tool_tags` + `instruction_blocks`).
2. `register(MonAgent())` à l'import.
3. Importer le module dans `app.py` (~ligne 23).

Patron complet : voir [`CLAUDE.md`](CLAUDE.md#ajouter-un-nouveau-type-dagent) et [`docs/adr/001-assistant-profile-pattern.md`](docs/adr/001-assistant-profile-pattern.md).

---

## MCP (Model Context Protocol)

Les connexions MCP permettent au LLM d'utiliser des outils externes (filesystem, recherche web, APIs métier…).

- Lifecycle : `core/mcp/manager.py`
- Invocation : `core/mcp/tools.py`
- Routes CRUD : `routers/mcp_routes.py`
- Tokens chiffrés au repos via `core/crypto.py`

---

## Observabilité — Langfuse

Langfuse self-hosted est fourni dans `docker-compose.yml`. Désactivé tant que `LANGFUSE_PUBLIC_KEY` n'est pas configuré.

- **UI :** http://localhost:3001
- **Guide complet :** [`docs/langfuse-guide.md`](docs/langfuse-guide.md)
- **API REST + curl :** [`docs/langfuse-rest-api-trace-inspection.md`](docs/langfuse-rest-api-trace-inspection.md)
- **Live tail :** [`docs/langfuse-live-log.md`](docs/langfuse-live-log.md)

---

## Pour aller plus loin

### Documentation produit / workflow

| Sujet | Fichier |
|---|---|
| Architecture complète + "où aller pour modifier X" | [`CLAUDE.md`](CLAUDE.md) |
| Suite d'évaluation copépode | [`scripts/evals/README.md`](scripts/evals/README.md) |
| Routine de test copépode | [`docs/copepod-test-operations.md`](docs/copepod-test-operations.md) |
| Couverture Plan Mode + lacunes | [`docs/copepod-plan-mode-eval-coverage.md`](docs/copepod-plan-mode-eval-coverage.md) |
| Scénarios GC-only | [`docs/copepod-gc-only-live-eval.md`](docs/copepod-gc-only-live-eval.md) |
| Compensations dans le harness | [`docs/copepod-eval-compensations.md`](docs/copepod-eval-compensations.md) |
| Politique mode online | [`docs/copepod-online-mode-policy.md`](docs/copepod-online-mode-policy.md) |
| Stratégie Langfuse | [`docs/copepod-langfuse-evals.md`](docs/copepod-langfuse-evals.md) |

### Décisions d'architecture (ADRs)

| # | Sujet |
|---|---|
| [001](docs/adr/001-assistant-profile-pattern.md) | `AssistantProfile` ABC + registry pattern |
| [002](docs/adr/002-session-key-3-segments.md) | Clés de session 3-segments (`user:session:agent`) |
| [003](docs/adr/003-tool-injection-via-computer-run.md) | Injection des tools via `computer.run()` |
| [004](docs/adr/004-plan-ready-tag-for-mode-switch.md) | Tag `[PLAN_READY]` pour le switch Plan → Analyse |

### Archive

`docs/archive/` contient les status reports datés, plans et specs déjà livrés. Pas de mise à jour — uniquement traçabilité historique.

---

## Sécurité & déploiement

- **Exécution de code :** OpenInterpreter exécute du code généré par un LLM dans le container. Traite le container comme un **environnement d'exécution non-confidentiel**.
- **Dev local (`local_start.sh`) :** mono-utilisateur. Bind-mount du repo → l'interpreter peut lire/écrire dans le filesystem hôte mappé.
- **Mode partageable (`share_start.sh`) :** lit uniquement `.env` projet (`env -i`), n'hérite pas du shell.
- **Production (`production_start.sh`) :** isoler le compute de l'UI. Exposer l'API derrière un reverse-proxy contrôlé. Pas de bind-mount du repo.

Docker isole, mais ne suffit pas pour un déploiement multi-tenant sensible.

---

## Contribuer

- Modifier le comportement d'un endpoint → router concerné dans `routers/`.
- Modifier la logique métier → `core/` (jamais `app.py`).
- Ajouter un agent / outil / bloc d'instructions → voir [`CLAUDE.md`](CLAUDE.md).
- Changement d'architecture significatif → ouvrir un ADR dans `docs/adr/`.
- Tests obligatoires : `python -m pytest tests/ -q` doit passer avant tout PR.

---

## Citation & Licence

Travail original (upstream UHSLC) :

> Widlansky, M. J., & Komar, N. (2025). Building an intelligent data exploring assistant for geoscientists. *JGR: Machine Learning and Computation*, 2, e2025JH000649. https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2025JH000649

Prototype upstream : https://doi.org/10.5281/zenodo.15605301

Licence : MIT (voir [`LICENSE`](LICENSE) — à ajouter si absent).
