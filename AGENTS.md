# AGENTS.md — IDEA · NeoLab, Université Laval

Assistant graphique copépodes : LangChain (LangGraph ReAct + tools + RAG) + FastAPI/Open WebUI.
Utilisateurs : professeurs et étudiants. Réponses en français par défaut.

---

## Lire avant d'implémenter

| Doc | Pour quoi faire |
|---|---|
| `CONTEXT.md` | Identité métier de l'agent, périmètre, sources et RAG |
| `ARCHITECTURE.md` | Comment `agent.py`, `serve.py`, les tools, le RAG, OpenWebUI sont câblés |
| `TOOLS.md` | Inventaire des 22 tools (25 avec SQL optionnel), par catégorie |
| `agents/copepod_system_prompt.py` | System prompt complet (choix des tools, périmètre, sécurité) |
| `tools/source_scope.py` | Préférence contextuelle de source et affinité persistante, sans blocage de tool |
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
agent.py — LangChain create_agent (ex-create_react_agent)
    │ system prompt copépodes (source locale : agents/copepod_system_prompt.py)
    │ checkpointer AsyncSqliteSaver (data/checkpoints.sqlite)
    │ pre_model_hook : truncate tool results + trim history (40k tokens)
    │
    ├── tools/data_tools.py         → load_file, run_pandas, run_graph
    ├── tools/rag_tool.py           → query_copepod_knowledge_base
    ├── tools/copepod_sources.py    → cache SQL + exports EcoTaxa
    ├── tools/ecopart_sources.py    → correspondance + enrichissement EcoPart
    ├── tools/amundsen_sources.py   → disponibilité/profils/enrichissement CTD
    ├── tools/bio_oracle_sources.py → enrichissement Bio-ORACLE
    ├── tools/ogsl_sources.py       → enrichissement OGSL CTD
    ├── tools/sql_workspace.py      → list/preview/copy SQL (read-only)
    └── tools/deliverable_tool.py   → export_deliverable (PDF via WeasyPrint)

core/copepod_rag/    ChromaDB (14 docs RAG)
core/ecotaxa_client/ core/ecopart_client/ core/amundsen_ctd_client/ core/bio_oracle_client/
agents/skills/       anciennes références métier, non chargées au runtime
```

Le runtime est **un seul agent ReAct**. Les 22 tools canoniques sont tous disponibles (25 avec SQL). `SourceDecision` indique une préférence contextuelle au modèle mais ne filtre, ne masque et ne bloque aucun tool. Il n'y a pas de « mode » de session.

---

## Démarrage

### Docker (recommandé)

```bash
docker compose up --build
# Open WebUI → http://localhost:3000
# Agent FastAPI → http://localhost:8000
```

Le compose monte `.:/app` et lance Uvicorn sans `--reload` pour ne pas interrompre les réponses SSE. Après un changement, redémarrer explicitement `copepod-agent`; aucun rebuild ni `docker cp` n'est requis.

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
| `LLM_MODEL` | ex. `gpt-5.6-luna` |
| `LANGSMITH_API_KEY` | Tracing LangSmith (le system prompt est lu localement) |
| `LANGCHAIN_TRACING_V2` | `true` pour activer LangSmith |
| `LANGFUSE_*` | Self-hosted Langfuse (port 3001) — voir `assistant-copepodes-specs` mémo |
| `MAX_CONTEXT_TOKENS` | Défaut 100000 — plafond de qualité ; au-delà, trim_messages |
| `MAX_CHECKPOINT_MESSAGES` | Défaut 40 — plafond durable des messages LangGraph; Open WebUI garde le transcript complet. |
| `MAX_LIVE_DERIVED_DATAFRAMES` | Défaut 20 — dérivés courants simultanément visibles au runtime; fichiers, exports et enrichissements exclus. |
| `MAX_MODEL_CALLS_PER_TURN` | Défaut 10 — limite technique de sécurité contre une boucle incontrôlée |
| `TARGET_MODEL_CALLS_PER_TURN` | Défaut 5 — cible comportementale d'économie, sans arrêt forcé |
| `TARGET_RUN_PANDAS_CALLS_PER_TURN` | Défaut 2 — cible comportementale pour regrouper qualification et calcul |
| `KEEP_FULL_TOOL_TURNS` | Défaut 3 — anciens résultats de tools compactés au-delà de ces tours |
| `MAX_TOOL_RESULT_CHARS` | Défaut 8000 — au-delà, troncature des résultats de tools |
| `CHECKPOINTS_DB` | Chemin SQLite des checkpoints LangGraph (`data/checkpoints.sqlite`) |
| `DATABASE_URL` | Workspace SQL lecture seule (SQLAlchemy) — optionnel |
| `SESSION_STORE_DATABASE_URL` | PostgreSQL pour les métadonnées de session (ex. `postgresql://copepod:pass@postgres:5432/copepod_sessions`). Si absent → fallback fichiers locaux. |
| `POSTGRES_PASSWORD` | Mot de passe PostgreSQL (défaut `copepod_dev` en dev). À surcharger en prod. |
| `OPENWEBUI_URL` | Backend Open WebUI pour le feedback polling (`http://open-webui:8080` en compose) |

`.env` contient des credentials EcoTaxa/EcoPart/SQL — jamais commité, jamais affiché.

Le contexte n'affiche pas toutes les colonnes des tables larges : les fiches du
WorkingSet montrent un schéma borné et `schema_visibility=X/Y`. Une colonne
absente ou ambiguë autorise une seule qualification ciblée; plusieurs candidates
plausibles exigent une question utilisateur avant calcul.

---

## Structure du repo

```
agent.py                  Agent ReAct + CLI
serve.py                  FastAPI : /v1/chat/completions (SSE), /v1/models, /graphs/, /downloads/
docker-compose.yml        copepod-agent + open-webui + watchtower
scripts/dev/push_prompt.py
studio.py                 LangGraph Studio entry

agents/
  copepod_system_prompt.py  Kernel permanent compact (anglais, ≤ 3 500 tokens)
  skills/                   références métier legacy, non chargées au runtime
  (copepod_prompt.py déprécié → archivé dans docs/legacy/copepod_prompt_DEPRECATED.py)

tools/                    22 tools canoniques (25 avec SQL optionnel — voir TOOLS.md)

core/
  copepod_rag/            ChromaDB + 11 docs RAG
  ecotaxa_client.py … *_client.py
  instruction_renderer/   Composition des system prompts
  mcp/                    MCP integrations (si actives)

tests/                    pytest (27 fichiers, 248 tests)
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
- **Routage des tools** : tous les tools canoniques restent disponibles. `SourceDecision` et le contexte des ressources guident le choix du modèle sans créer d'autorisation, de filtre lexical ou de blocage.
- **Pas d'interprétation** scientifique ou biologique des résultats, ni par l'agent, ni par les docstrings de tools.
- **Pas de valeur inventée** : tout chiffre vient de `run_pandas`, d'un tool, ou du RAG.
- **Pas de credentials** dans le code, les logs, les docstrings, les commits.
- **Pas de nom interne de tool** exposé à l'utilisateur dans les réponses LLM.
- **Confirmation avant op coûteuse (CT-AG-06)** : si tu ajoutes un nouveau tool qui télécharge ou compute lourd, ajoute-le à la liste « Confirmation before heavy operations » du system prompt.
- **Ton clinique (CT-AG-26)** : pas de « je / moi / en tant qu'IA » dans les réponses LLM ; format Résultat / Source / Méthode / Limite / Prochaine action.
- **Incertitude visible (CT-AG-27)** : tout nouveau type de graphique doit appliquer la palette confirmed/exploratory/uncertain et le stamp de confiance.
- **Rebuilt RAG** : `python core/copepod_rag/build_index.py` après modification de `core/copepod_rag/docs/*.md`.
- **Prompt local** : `agent.py` consomme exclusivement `agents/copepod_system_prompt.py`; `scripts/dev/push_prompt.py` est legacy et n'alimente pas le runtime.

---

## Sources

| Source | Outils | Statut |
|---|---|---|
| Fichier local | `load_file`, `run_pandas`, `run_graph` | implémenté |
| EcoTaxa | `list_ecotaxa_projects`, `preview_ecotaxa_project`, `query_ecotaxa` | implémenté |
| EcoPart | `list_ecopart_samples`, `preview_ecopart_sample`, `query_ecopart`, `join_ecotaxa_ecopart` | implémenté |
| Amundsen CTD (ERDDAP) | `list_amundsen_datasets`, `preview_amundsen_profile`, `query_amundsen_ctd` | implémenté |
| Bio-ORACLE | `list_bio_oracle_datasets`, `preview_bio_oracle_point`, `query_bio_oracle`, `couple_zooplankton_bio_oracle` | implémenté |
| OGSL | — | annoncé dans le prompt, tool dédié à venir |
| SQL (read-only) | `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace` | implémenté |

OBIS n'est **pas** une source autorisée. Toute mention résiduelle est du legacy à retirer.

---

## Tests

```bash
pytest tests/                              # tous
pytest tests/test_agent_harness.py -v      # construction et comportement permanent
pytest tests/test_tool_catalog.py -v       # catalogue canonique
pytest tests/test_context_projection_campaign.py -v  # harness multi-tour hors ligne
pytest tests/test_serve_sse.py -v          # SSE et affichage Open WebUI
```

La suite compacte contient 27 fichiers et 248 tests centrés sur les tools, le
harness et l’affichage. Voir `assistant-copepodes-specs/` pour les scénarios comportementaux
détaillés (`TEST_SCENARIOS.md`).

---

## Pour aller plus loin

- Le flow exact d'un message utilisateur jusqu'à l'image renvoyée : `ARCHITECTURE.md`.
- L'inventaire détaillé de chaque tool, ce qu'il prend, ce qu'il rend : `TOOLS.md`.
- Les 14 UC et 29 contraintes du PRD V1.2 et leur point d'ancrage côté IDEA : `docs/UC_TRACEABILITY.md`.
