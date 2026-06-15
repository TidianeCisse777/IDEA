# TOOLS.md — Inventaire des outils exposés au LLM

23 tools `@tool` LangChain (compte vérifié `grep -cE "^\s*@tool" tools/*.py`), regroupés par catégorie. Pour chaque tool : signature, ce qu'il fait, conditions d'appel dictées par le system prompt.

Le LLM choisit quel tool appeler en lisant les docstrings + le system prompt (`agents/copepod_system_prompt.py`). Les noms internes ne sont jamais exposés à l'utilisateur dans les réponses.

---

## 1. Data tools (fichiers locaux)

**Module : `tools/data_tools.py` — factory : `make_tools(thread_id, store)`**

### `load_file(path: str) -> str`

Charge un fichier tabulaire (CSV, TSV, Excel, JSON, Parquet) en session pour le `thread_id` courant. Auto-inspecte : colonnes, types, lignes, valeurs manquantes. Détecte les exports UVP EcoTaxa/EcoPart et renvoie un hint déclenchant le chargement automatique du skill correspondant (`uvp_ecotaxa`, `uvp_ecopart`).

**Quand l'appeler** : à chaque fichier fourni par l'utilisateur, **sauf** après une `query_*` réussie (les sources en ligne mettent déjà les données en session).

### `run_pandas(code: str) -> str`

Exécute du code pandas dans le namespace de la session (dataframes chargés accessibles par leur nom). Retourne stdout + repr du résultat. Utilisé pour : agrégations, filtres, jointures hors `join_ecotaxa_ecopart`, tableaux markdown, calculs numériques.

**Quand l'appeler** : pour toute valeur numérique. **Toute** valeur écrite par l'agent doit venir d'un `run_pandas`.

### `run_graph(code: str) -> str`

Exécute du code matplotlib, sauvegarde la figure en PNG, retourne le base64 (réécrit ensuite en URL `/graphs/{filename}` par `serve.py`).

**Quand l'appeler** : juste après `load_skill("graph_writer")` quand le `graph_planner` a décidé `visual`. Le system prompt impose que la **prochaine** tool call après `graph_writer` soit `run_graph`, jamais `run_pandas`.

---

## 2. Sources EcoTaxa

**Module : `tools/copepod_sources.py` — factory : `make_source_tools(thread_id)`**

### `list_ecotaxa_projects() -> str`

Liste les projets EcoTaxa auxquels les credentials du `.env` ont accès. Pas de hardcoding — c'est l'API qui répond.

### `preview_ecotaxa_project(project_id: int) -> str`

Aperçu d'un projet (titre, nombre d'objets, taxons dominants, métadonnées). Aucune donnée téléchargée massivement.

### `query_ecotaxa(project_id: int, taxon: str | None = None, status: str = "V") -> str`

Téléchargement structuré. Statut V (validé humain) par défaut. Écrit le résultat en session, retourne le chemin et un résumé. Une fois cette query réussie : `run_pandas` peut accéder aux données sans `load_file`.

**Conditions** : ne se déclenche que sur demande explicite (« charge », « exporte », « récupère »). Sinon l'agent reste sur `preview` ou `list`.

### `find_ecotaxa_projects(title?, instrument?, page=1, page_size=50) -> str`

Recherche les projets accessibles par titre et/ou instrument, avec pagination. Outil de découverte — aucun objet téléchargé. Aliasé sur le tool MCP `search_projects` côté serveur EcoTaxa MCP.

### `inspect_ecotaxa_project_schema(project_id, verbose=False, include_process=False) -> str`

Liste les colonnes typées d'un projet (sample / acquisition / object) avant export. Free fields résolus en labels, types (`number`, `text`, `datetime`, `unknown`) inférés depuis les codes EcoTaxa. Utile pour vérifier la présence de colonnes (profondeur, station, taxon, morpho) avant `query_ecotaxa`. Aliasé sur `get_project_schema` côté MCP.

### `inspect_ecotaxa_column(project_id, column_name, level=None) -> str`

Distribution d'une seule colonne d'un projet :
- numérique : `min/max/mean/median/p25/p75/n`
- texte : top valeurs + `total_distinct` + `sample_size`
Chemin primaire via `/project_set/column_stats` (validés uniquement), fallback first-window échantillonné si l'endpoint ne supporte pas la colonne. Le champ `source` expose le chemin emprunté. Erreur structurée `AMBIGUOUS_COLUMN` si le nom existe à plusieurs niveaux ; rappeler avec `level=` explicite. Aliasé sur `get_column_distribution` côté MCP.

### `count_ecotaxa_taxa(project_ids, taxa) -> str`

Compte V/P/D (validés / prédits / douteux) par projet et par taxon. `taxa` accepte des entiers (taxon IDs) ou des noms scientifiques (résolution via autocomplete EcoTaxa, exact-match prioritaire). Projets inaccessibles (401/403) ignorés silencieusement et listés dans `inaccessible_project_ids`. Aliasé sur `taxa_stats` côté MCP.

### `compare_ecotaxa_projects(project_ids) -> str`

Compare les schémas de N projets avant un export combiné. Match par label normalisé (case + séparateurs). Retourne :
- `common_columns` — colonnes partagées avec leurs niveaux + types par projet
- `type_conflicts` — colonnes de type divergent avec `severity` (`blocker` pour `number↔text`, `warning` pour `text↔datetime`)
- `level_conflicts` — la même colonne placée à des niveaux différents *selon les projets*
- `unique_to_project` — colonnes propres à chaque projet
Aliasé sur `compare_project_schemas` côté MCP.

---

## 3. Sources EcoPart

**Module : `tools/ecopart_sources.py` — factory : `make_ecopart_tools(thread_id)`**

### `list_ecopart_samples(project_id: int = 105) -> str`

Liste les échantillons d'un projet EcoPart (défaut 105 = Amundsen 2018 UVP5).

### `preview_ecopart_sample(sample_id: int) -> str`

Aperçu d'un échantillon (profondeur, profil CTD associé, particules agrégées).

### `query_ecopart(project_id, sample_id=None, ...) -> str`

Téléchargement structuré, écriture en session.

### `join_ecotaxa_ecopart(project_id: int | None = None) -> str`

Joint un dataset EcoTaxa avec un dataset EcoPart précédemment chargés en session. Clé `obj_orig_id` (ex. `ips_007_899`) → `profile_id` (`ips_007`). Le tool refuse si l'un ou l'autre n'est pas chargé.

---

## 4. Source Amundsen CTD (ERDDAP)

**Module : `tools/amundsen_sources.py` — factory : `make_amundsen_tools(thread_id)`**

### `list_amundsen_datasets() -> str`

Liste les datasets Amundsen connus, en priorité `ca-cioos_ccin-12713` (CTD-Rosette officielle).

### `preview_amundsen_profile(station: str | None, cast_number: int | None) -> str`

Aperçu d'un profil CTD.

### `query_amundsen_ctd(station: str | None, cast_number: int | None) -> str`

Téléchargement structuré via ERDDAP (`core/amundsen_ctd_client.py`).

---

## 5. Source Bio-ORACLE

**Module : `tools/bio_oracle_sources.py` — factory : `make_bio_oracle_tools(thread_id)`**

### `list_bio_oracle_datasets() -> str`

Liste les variables et scénarios disponibles (SST, salinité, oxygène ; scénarios SSP126/245/370/585 ; couches surface, benthic, …).

### `preview_bio_oracle_point(latitude, longitude, variable, scenario, depth_layer) -> str`

Valeur ponctuelle d'une variable à un point.

### `query_bio_oracle(latitude, longitude, variable, scenario, depth_layer) -> str`

Extraction en série ou batch, écriture en session.

### `couple_zooplankton_bio_oracle(rows_json: str) -> str`

Couple un set de lignes de zooplancton (avec lat/lon/date/profondeur) aux variables Bio-ORACLE correspondantes. Documente la méthode dans les métadonnées (CT-AG-07).

---

## 6. RAG : base de connaissances

**Module : `tools/rag_tool.py` — factory : `make_rag_tool()`**

### `query_copepod_knowledge_base(question: str) -> str`

Recherche vectorielle (top-k=3 par défaut) dans ChromaDB sur les 9 docs RAG. Retourne les chunks concaténés.

**Conditions** : **obligatoire avant toute affirmation factuelle** sur colonnes, méthodes, taxonomie, sources. Si retour vide, l'agent dit explicitement « je n'ai pas trouvé cette information dans la base ».

**Exception** : si l'utilisateur demande un graphique/visualisation sur des données déjà chargées, `query_copepod_knowledge_base` est sauté — on va directement à `graph_planner`.

---

## 7. Skills : chargement à la demande

**Module : `tools/skill_tool.py` — factory : `make_skill_tool()`**

### `load_skill(skill_name: str) -> str`

Récupère un skill Markdown depuis LangSmith Hub (ou `agents/skills/*.md` en fallback). 11 skills disponibles :

| Skill | Quand le charger |
|---|---|
| `graph_planner` | Avant toute production graphique. Inclut le compte confirmed / exploratory / uncertain et le niveau de confiance high/medium/low (CT-AG-27). |
| `graph_writer` | Juste après `graph_planner`. Impose la palette d'incertitude, le stamp de confiance et l'annotation rouge si `low` (CT-AG-27). |
| `ecotaxa_query` | Après une `query_ecotaxa` réussie, pour la lecture des résultats. |
| `ecopart_query` | Idem pour EcoPart. |
| `amundsen_ctd_query` | Idem pour Amundsen. |
| `bio_oracle_query` | Idem pour Bio-ORACLE. |
| `environmental_join` | Avant de joindre biologique ↔ environnemental (CTD, Bio-ORACLE, OGSL). Le system prompt impose **toujours** un `run_pandas` ensuite. |
| `sql_workspace_query` | Quand l'utilisateur travaille un serveur SQL. |
| `uvp_ecotaxa` | Auto-chargé via hint `load_file` quand un export UVP EcoTaxa est détecté. |
| `uvp_ecopart` | Idem pour EcoPart. |
| `deliverable_writer` | Avant de compiler un livrable PDF. |

---

## 8. Workspace SQL (lecture seule)

**Module : `tools/sql_workspace.py` — factory : `make_sql_tools(thread_id)`**

Backends supportés :

- SQLite local : `sqlite:////absolute/path/source.sqlite`
- PostgreSQL : `postgresql+psycopg://user:password@host:5432/dbname`
- MySQL : `mysql+pymysql://user:password@host:3306/dbname`
- MariaDB via protocole MySQL : `mysql+pymysql://user:password@host:3306/dbname`

Le workspace force la lecture seule par backend : ouverture SQLite `mode=ro`, option de transaction read-only PostgreSQL, session read-only MySQL/MariaDB. Les dialectes SQLAlchemy non listés sont refusés avec une erreur explicite.

### `list_sql_tables() -> str`

Cartographie les tables et vues accessibles par `DATABASE_URL` : schéma, nom, type, nombre de colonnes, nombre de lignes quand disponible, clé primaire et clés étrangères.

### `preview_sql_table(table_name: str, limit: int = 10, where: str | None = None, order_by: str | None = None) -> str`

Quelques lignes d'une table ou vue sans matérialiser. `where` accepte une clause de filtre sans `WHERE`; `order_by` accepte une clause de tri sans `ORDER BY`.

### `copy_sql_query_to_workspace(query: str, output_stem: str | None = None) -> str`

Exécute une requête avec `LIMIT` explicite, écrit le résultat en TSV dans `data/sql_workspace/{thread_id}/`, puis charge la copie comme fichier tabulaire ordinaire (`run_pandas` y accède). Refuse les copies sans `LIMIT` et les résultats dépassant `SQL_WORKSPACE_MAX_COPY_ROWS` (défaut : 100000).

Si `DATABASE_URL` n'est pas configurée : l'agent demande à l'utilisateur de coller l'URL SQLAlchemy (détecté par `_is_sql_workspace_config_message` côté `serve.py`).

---

## 9. Livrables

**Module : `tools/deliverable_tool.py`**

### `export_deliverable(content: str, filename: str = "rapport") -> str`

Compile un livrable PDF à partir d'une markdown structurée. WeasyPrint gère le rendu (Pango/Cairo natifs exposés par le Dockerfile). Le fichier est écrit dans `data/downloads/{filename}.pdf` et servi via `/downloads/{filename}`.

**Conditions** : l'agent **doit** avoir chargé `deliverable_writer` au préalable et compilé la markdown depuis l'historique de la session, avant d'appeler ce tool dans la même conversation.

---

## Modules internes (pas exposés au LLM)

Ces fichiers de `tools/` ne sont pas des `@tool` mais des supports utilisés par les vrais tools :

| Fichier | Rôle |
|---|---|
| `tools/ecotaxa_client.py` | Client HTTP EcoTaxa, gestion du token. |
| `tools/file_loader.py` | Détection de format, parsing tabulaire commun. |
| `tools/openwebui_uploads.py` | Récupère un fichier uploadé par Open WebUI à partir d'une URL. |
| `tools/public_url.py` | Résout une URL externe en chemin local téléchargé. |
| `tools/dataset_registry.py` | Catalogue des datasets connus pour `load_file` hints. |
| `tools/session_store.py` | Persistance d'état tabulaire par `thread_id`. |
| `tools/run_store.py` | Historique des runs (debug, replay). |
| `tools/feedback.py` | Bridge entre OpenWebUI 👍/👎 et LangSmith/Langfuse. |

---

## À venir

- **OGSL** — annoncé dans le system prompt mais aucun tool dédié. À ajouter quand l'API/source sera arrêtée. Tant que le tool n'existe pas, l'agent reste sur les sources couvertes ou bascule sur fichier local.
