# CLAUDE.md — IDEA · NeoLab, Université Laval

Assistant graphique copépodes : LangChain (LangGraph ReAct + tools + RAG) + FastAPI/Open WebUI.
Utilisateurs : professeurs et étudiants. Réponses en français par défaut.

---

## Lire avant d'implémenter

| Doc | Pour quoi faire |
|---|---|
| `CONTEXT.md` | Identité métier de l'agent, périmètre, ce qu'il fait / ne fait pas, sources, skills, RAG |
| `ARCHITECTURE.md` | Comment `agent.py`, `serve.py`, les tools, le RAG, OpenWebUI sont câblés |
| `TOOLS.md` | Inventaire des 62 tools (65 avec SQL optionnel) exposés au LLM, par catégorie |
| `SPEC.md` | Spécification figée : use cases classés (UC-A…UC-J), capacités, contraintes dures |
| `PARTAGE.md` | Partage & déploiement : état actuel et cible |
| `SEQUENCES.md` | Diagrammes de séquence par use case |
| `agents/copepod_system_prompt.py` | System prompt complet (règles de routage des tools, périmètre, sécurité) |
| `assistant-copepodes-specs/` | Repo des specs métier (PRD V1.2, 14 UC, 29 contraintes, glossaire) |

---

## Architecture en une vue

```
Open WebUI (port 3000)
    │ OpenAI-compatible (POST /v1/chat/completions)
    ▼
serve.py — FastAPI (port 8000)
    │ SSE streaming, feedback polling, image hosting, downloads
    ▼
agent.py — LangChain create_agent (ex-create_react_agent, déprécié en LangGraph 1.0)
    │ system prompt copépodes (source locale : agents/copepod_system_prompt.py)
    │ checkpointer AsyncSqliteSaver (data/checkpoints.sqlite)
    │ _ContextMiddleware : trim model request + audit + inject long-term memory
    │                     + inject session state map (TurnContext: loaded files, zone subsets, source scope)
    │                     + guards (source scope, ungrounded ids, graph intent) + restricted code namespace
    │
    ├── tools/data_tools.py         → load_file, run_pandas, run_graph
    ├── tools/rag_tool.py           → query_copepod_knowledge_base
    ├── tools/skill_tool.py         → load_skill
    ├── tools/copepod_sources.py    → list/preview/query EcoTaxa
    ├── tools/ecopart_sources.py    → list/preview/query EcoPart + join
    ├── tools/amundsen_sources.py   → list/preview/query Amundsen CTD
    ├── tools/bio_oracle_sources.py → list/preview/query Bio-ORACLE + coupling
    ├── tools/sql_workspace.py      → list/preview/copy SQL (read-only)
    └── tools/deliverable_tool.py   → export_deliverable (PDF via WeasyPrint)

core/copepod_rag/    ChromaDB (11 docs RAG)
core/ecotaxa_client/ core/ecopart_client/ core/amundsen_ctd_client/ core/bio_oracle_client/
agents/skills/       15 skills Markdown manifestés et chargeables à la demande
```

Le runtime est **un seul agent ReAct**. Tous les tools sont déclarés à la construction, puis au plus 15 sont exposés par appel modèle. Il n'y a pas de « mode » de session.

---

## Démarrage

### Docker (recommandé)

```bash
docker compose up --build
# Open WebUI → http://localhost:3000
# Agent FastAPI → http://localhost:8000
```

Le compose monte `.:/app` et lance `uvicorn --reload` : les changements de code sont rechargés à chaud, pas besoin de rebuild ni `docker cp`.

### Local (CLI rapide)

```bash
pip install -r requirements.txt
python core/copepod_rag/build_index.py   # une fois pour construire l'index
python agent.py                          # REPL CLI
python agent.py fichier.tsv "ta question" # one-shot
python serve.py                          # serveur FastAPI seul
```

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `OPENAI_API_KEY` | Provider LLM |
| `LLM_MODEL` | ex. `openai/gpt-5.4-mini`, `claude-sonnet-4-6` |
| `LANGSMITH_API_KEY` | Tracing + pull Hub des skills (le system prompt est lu localement) |
| `LANGCHAIN_TRACING_V2` | `true` pour activer LangSmith |
| `LANGFUSE_*` | Self-hosted Langfuse (port 3001) — voir `assistant-copepodes-specs` mémo |
| `MAX_CONTEXT_TOKENS` | Défaut 40000 — au-delà, trim_messages |
| `MAX_TOOL_RESULT_CHARS` | Défaut 8000 — au-delà, troncature des résultats de tools |
| `CHECKPOINTS_DB` | Chemin SQLite des checkpoints LangGraph (`data/checkpoints.sqlite`) |
| `DATABASE_URL` | Workspace SQL lecture seule (SQLAlchemy) — optionnel |
| `SESSION_STORE_DATABASE_URL` | PostgreSQL pour les métadonnées de session (ex. `postgresql://copepod:pass@postgres:5432/copepod_sessions`). Si absent → fallback fichiers locaux. |
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL (défaut `copepod_dev` en dev). À surcharger en prod. |
| `OPENWEBUI_URL` | Backend Open WebUI pour le feedback polling (`http://open-webui:8080` en compose) |
| `ECOTAXA_CACHE_DB` | Chemin SQLite du cache EcoTaxa (défaut `data/ecotaxa_cache.sqlite`) — index spatio-temporel lu par les recherches zone/temps/taxon |
| `ECOTAXA_EXTRA_PROJECT_IDS` | Liste de `project_id` EcoTaxa (séparés par virgule/espace) à synchroniser en plus de `list_projects()` — pour les projets lisibles par ID mais absents (ou instables) de la recherche projet du compte |

`.env` contient des credentials EcoTaxa/EcoPart/SQL — jamais commité, jamais affiché.

---

## Structure du repo

```
agent.py                  Agent ReAct + CLI
serve.py                  FastAPI : /v1/chat/completions (SSE), /v1/models, /graphs/, /downloads/
docker-compose.yml        copepod-agent + open-webui + watchtower
scripts/dev/push_prompt.py
scripts/dev/push_skills.py
scripts/dev/prune_data.py
studio.py                 LangGraph Studio entry

agents/
  copepod_system_prompt.py  Kernel permanent compact (anglais, ≤ 3 500 tokens)
  (copepod_prompt.py déprécié → archivé dans docs/legacy/copepod_prompt_DEPRECATED.py)
  skills/                   15 skills Markdown manifestés

tools/                    62 tools @tool LangChain (65 avec SQL optionnel — voir TOOLS.md)

core/
  copepod_rag/            ChromaDB + 11 docs RAG
  ecotaxa_client.py … *_client.py
  instruction_renderer/   Composition des system prompts
  mcp/                    MCP integrations (si actives)

tests/                    pytest (~30 modules, 42 tests verts au dernier merge main)
evals/                    Évaluations LangSmith (copepod graph happy path…)
SPEC.md ARCHITECTURE.md TOOLS.md PARTAGE.md SEQUENCES.md   Docs de référence figées (racine)
docs/                     Notes internes / test maps (gitignored sauf exceptions)
data/                     checkpoints.sqlite, fichiers de session (gitignored)
logs/                     Logs runtime
openwebui/                Hooks et bridges OpenWebUI
scripts/                  Outils CLI ponctuels
```

---

## Règles de dev

- **Pas de mode**. Si tu te poses la question « est-ce que je suis dans le bon mode », c'est non — il n'y a qu'un agent. Le comportement vient du system prompt.
- **TDD** pour chaque tool : test d'abord, implémentation après. Fixtures dans `tests/`.
- **Docstring claire** sur chaque `@tool` : le LLM la lit pour décider quand l'appeler.
- **Routage des tools** : les autorisations et l'exposition se modifient dans les politiques Python; le prompt compact ne conserve que les invariants destinés au modèle.
- **Pas d'interprétation** scientifique ou biologique des résultats, ni par l'agent, ni par les docstrings de tools.
- **Pas de valeur inventée** : tout chiffre vient de `run_pandas`, d'un tool, ou du RAG.
- **Pas de credentials** dans le code, les logs, les docstrings, les commits.
- **Pas de nom interne de tool** exposé à l'utilisateur dans les réponses LLM.
- **Confirmation avant op coûteuse (CT-AG-06)** : si tu ajoutes un nouveau tool qui télécharge ou compute lourd, ajoute-le à la liste « Confirmation before heavy operations » du system prompt.
- **Ton clinique (CT-AG-26)** : pas de « je / moi / en tant qu'IA » dans les réponses LLM ; format Résultat / Source / Méthode / Limite / Prochaine action. Si tu modifies un skill, garde la même règle.
- **Incertitude visible (CT-AG-27)** : si tu ajoutes un type de graphique dans `graph_writer.md`, applique la palette confirmed/exploratory/uncertain et le stamp de confiance.
- **Rebuilt RAG** : `python core/copepod_rag/build_index.py` après modification de `core/copepod_rag/docs/*.md`.
- **Prompt local** : `agent.py` consomme exclusivement `agents/copepod_system_prompt.py`; `scripts/dev/push_prompt.py` est legacy.
- **Push skills** : `python scripts/dev/push_skills.py` pour synchroniser `agents/skills/*.md` vers LangSmith Hub.
- **Rétention des données** : `python scripts/dev/prune_data.py --apply` — purge `data/session_store/` (> 30 j) et archive `data/checkpoints.sqlite` (> 500 Mo) vers `data/archive/`. Arrêter `copepod_agent` avant d'archiver les checkpoints. Les scripts e2e créent des milliers de sessions : pointer `SESSION_STORE_DIR` vers un dossier jetable pour les runs de test.

---

## Sources

| Source | Outils | Statut |
|---|---|---|
| Fichier local | `load_file`, `run_pandas`, `run_graph` | implémenté |
| EcoTaxa | `list_ecotaxa_projects`, `preview_ecotaxa_project`, `query_ecotaxa` | implémenté |
| EcoPart | `list_ecopart_samples`, `preview_ecopart_sample`, `query_ecopart`, `join_ecotaxa_ecopart`, `enrich_ecotaxa_with_ecopart_remote` | implémenté — voir `docs/features/ENRICHMENT_ECOTAXA_ECOPART.md` |
| Amundsen CTD (ERDDAP) | `list_amundsen_datasets`, `preview_amundsen_profile`, `query_amundsen_ctd` | implémenté |
| Bio-ORACLE | `list_bio_oracle_datasets`, `preview_bio_oracle_point`, `query_bio_oracle`, `couple_zooplankton_bio_oracle` | implémenté |
| OGSL | `query_ogsl` (station/temps/profondeur), `enrich_with_ogsl` (lat/lon spatial) | implémenté — règle unique : outil choisi par la clé de jointure de la table |
| SQL (read-only) | `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace` | implémenté |

OBIS n'est **pas** une source autorisée. Toute mention résiduelle est du legacy à retirer.

---

## Tests

```bash
pytest tests/                              # tous
pytest tests/test_agent_factory.py -v      # construction de l'agent
pytest tests/test_copepod_rag_advanced.py  # RAG
pytest tests/test_serve_streaming.py       # SSE / OpenWebUI
```

42 tests verts au merge du refactor multi-agent sur `main`. Voir `assistant-copepodes-specs/` pour la liste des scénarios comportementaux (`TEST_SCENARIOS.md`).

---

## Pour aller plus loin

- Le flow exact d'un message utilisateur jusqu'à l'image renvoyée : `ARCHITECTURE.md`.
- L'inventaire détaillé de chaque tool, ce qu'il prend, ce qu'il rend : `TOOLS.md`.
- Les 14 UC et 29 contraintes du PRD V1.2 et leur point d'ancrage côté IDEA : `docs/UC_TRACEABILITY.md`.
