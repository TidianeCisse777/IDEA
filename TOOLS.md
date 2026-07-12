# TOOLS.md — Inventaire des tools exposés au LLM · IDEA

> Catalogue technique des tools déclarés à la construction de l'agent
> (`agent.py` → `create_react_agent`). Pour les use cases voir [`SPEC.md`](SPEC.md),
> pour le câblage voir [`ARCHITECTURE.md`](ARCHITECTURE.md).
>
> **~53 tools** au total (les 3 tools SQL ne sont ajoutés que si `DATABASE_URL`
> est résolvable). Les règles de routage — quand appeler quel tool — vivent dans
> `agents/copepod_system_prompt.py`, jamais dans le code Python.

Légende « Coûteux ? » : **oui** = franchit la porte de confirmation CT-AG-06
(export/download/compute lourd) ; *cond.* = coûteux au-delà d'un seuil.

---

## 1. Données & analyse — `tools/data_tools.py` (3)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `load_file` | Charge CSV/TSV/Excel/JSON/Parquet, inspecte colonnes/types/manquants/plages, détecte les exports UVP EcoTaxa/EcoPart (hint `load_skill`) | non |
| `run_pandas` | Exécute du pandas contrôlé sur les DataFrames de session ; source de toute valeur numérique | non |
| `run_graph` | Exécute du code matplotlib et héberge le PNG (`/graphs/{file}`) | non |

---

## 2. EcoTaxa — `tools/copepod_sources.py` (24)

### Catalogue & recherche
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_ecotaxa_projects` | Liste les projets accessibles | non |
| `find_ecotaxa_projects` | Cherche des projets par `title` / `instrument` | non |
| `list_ecotaxa_campaigns` | Groupe les projets par campagne / leg (`query` facultatif) | non |
| `preview_ecotaxa_project` | Aperçu d'objets d'un projet | non |

### Schéma & colonnes
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `inspect_ecotaxa_project_schema` | Colonnes par niveau (sample / acquisition / object ; `include_process`) | non |
| `inspect_ecotaxa_column` | Distribution / stats / valeurs distinctes d'une colonne (`level` si ambigu) | non |
| `compare_ecotaxa_projects` | Compatibilité de schémas avant merge (`common_columns`, `type_conflicts`, `severity`) | non |

### Taxons
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `search_ecotaxa_taxa` | Résout les `taxon_id` candidats | non |
| `count_ecotaxa_taxa` | Counts V/P/D/U par `project_ids` × `taxa` | non |
| `find_ecotaxa_observations` | Samples dont le projet atteste un taxon (`bbox`, `date_range`, `status`) | non |

### Zone & période
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `find_ecotaxa_samples_in_region` | Samples par `bbox`/`zone_name`/`date_range`/`instrument`/`project_ids` ; inclut station/profile si le cache a été resynchronisé ; crée une sélection nommée | non |
| `group_ecotaxa_samples_by_year` | Vue **interannuelle** d'un lieu (station ou zone, plusieurs stations possibles) : tableau année × (n_samples, n_stations, dates, instruments, projets) ; mémorise une sélection multi-années pour un export étalé sur les années | non |
| `find_ecotaxa_projects_in_region` | Projets agrégés par zone/période (row/projet) | non |
| `group_ecotaxa_project_samples_by_region` | Samples d'un projet groupés par zone | non |
| `rank_ecotaxa_samples_by_region` | Classement global des samples cache par zone/mer/région (`sample_count`, `date_min`, `date_max`) | non |

### Samples & résumés (sans export)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `get_ecotaxa_sample` | Métadonnées + free fields d'un `sample_id` | non |
| `summarize_ecotaxa_project` / `summarize_ecotaxa_projects` | Résumé(s) projet (dates, bbox, V/P/D/U, top taxa) | non |
| `summarize_ecotaxa_sample` / `summarize_ecotaxa_samples` | Résumé(s) sample (`selection_name="latest"` possible) | non |
| `summarize_ecotaxa_sample_deployment` | Position, dates, profondeurs, acquisition, free fields | non |
| `get_ecotaxa_cache_status` | État du cache MCP (samples/projets indexés, dernier sync) | non |

### Export (opérations confirmées)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `query_ecotaxa` | Export d'un projet (`project_id`, `sample_ids`, filtres taxon/statut/`obj_depth_*`) | **oui** |
| `query_ecotaxa_sample` | Export d'un sample unique (résout le projet auto) | **oui** |
| `export_ecotaxa_samples` | Export d'une sélection nommée de samples (`selection_name`, `confirmed`) | **oui** |

---

## 3. EcoPart — `tools/ecopart_sources.py` (6)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_ecopart_samples` | Liste les samples EcoPart d'un projet | non |
| `preview_ecopart_sample` | Aperçu / détails d'un sample | non |
| `find_ecopart_project_for_ecotaxa` | Vérifie la disponibilité d'un EcoPart lié (read-only, pas d'export) | non |
| `query_ecopart` | Export d'un projet EcoPart | **oui** |
| `join_ecotaxa_ecopart` | Join local `(sample_id, depth_bin 5m)`, préfixe `ecopart_*`, stocke `df_ecotaxa_ecopart` | non |
| `enrich_ecotaxa_with_ecopart_remote` | Fetch EcoPart distant (auto-résolution projet) puis join | **oui** |

---

## 4. Amundsen CTD — `tools/amundsen_sources.py` (5)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_amundsen_datasets` | Datasets CTD disponibles (`amundsen12713`) | non |
| `preview_amundsen_profile` | Aperçu profil station/cast | non |
| `enrich_with_amundsen_ctd` | Enrichit la table par lat/lon/temps (auto-détecte colonnes, batch ERDDAP, `zone_name`/`date_range`/`source_variable`) → `amundsen_*` | cond. |
| `enrich_loaded_table_with_amundsen_ctd` | Variante legacy quand la table source est explicite | cond. |
| `query_amundsen_ctd` | Download complet du dataset CTD | **oui** |

---

## 5. Bio-ORACLE — `tools/bio_oracle_sources.py` (6)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_bio_oracle_datasets` | Variables & scénarios disponibles | non |
| `preview_bio_oracle_point` | Valeur d'une variable en un point (`target_year`) | non |
| `query_bio_oracle_zones` | Valeurs par zone(s) nommée(s) (var + scénario + `target_year`) | non |
| `couple_zooplankton_bio_oracle` | Couple des lignes zooplancton ↔ variables par lat/lon | cond. (>10 lignes) |
| `enrich_with_bio_oracle` | Enrichit la table : 1 colonne par (variable × scénario) + traçabilité `_dataset_id`/`_time`/`match_status` | cond. (>10 lignes multi-var) |
| `query_bio_oracle` | Extraction sur région / scénario | **oui** |

Noms de variables « friendly » : `temperature`, `salinity`, `oxygen`,
`chlorophyll`, `nitrate`. Scénarios : `baseline`, `SSP1-2.6`, `SSP2-4.5`,
`SSP5-8.5`. Jamais de noms ERDDAP internes (`thetao`, `so`, `o2`…).

---

## 6. OGSL — `tools/ogsl_sources.py` (2)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `enrich_with_ogsl` | Enrichit la table avec OGSL ISMER CTD par lat/lon/temps → `ogsl_*` | cond. |
| `query_ogsl` | Extraction OGSL | oui |

---

## 7. Workspace SQL — `tools/sql_workspace.py` (3, conditionnel)

Ajoutés seulement si `DATABASE_URL` (SQLAlchemy) est résolvable. Read-only.
Backends : SQLite, PostgreSQL, MySQL, MariaDB (protocole MySQL).

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_sql_tables` | Liste tables/vues + PK/FK + cardinalité | non |
| `preview_sql_table` | Aperçu filtré read-only | non |
| `copy_sql_query_to_workspace` | Copie un `SELECT` (LIMIT obligatoire, row cap) en TSV | cond. (sans LIMIT) |

---

## 8. Géographie — `tools/geo_tools.py` (2)

| Tool | Rôle | Coûteux ? |
|---|---|---|
| `get_zone_info` | Résout une zone IHO/MEOW → `{canonical, source, bbox, polygon_wkt, aliases, pandas_filter}` | non |
| `filter_dataframe_by_zone` | Filtre la df active par polygone (point-in-polygon shapely), persiste `df_in_<zone>_<source>` | non |

---

## 9. Savoir & taxonomie (2)

| Tool | Module | Rôle | Coûteux ? |
|---|---|---|---|
| `query_copepod_knowledge_base` | `tools/rag_tool.py` | Recherche vectorielle RAG NeoLab (ChromaDB, 11 docs) | non |
| `lookup_marine_taxonomy` | `tools/taxonomy_tool.py` | Résolution taxon : RAG local → WoRMS → Wikipedia (fallback) | non |

---

## 10. Skills & livrables (2)

| Tool | Module | Rôle | Coûteux ? |
|---|---|---|---|
| `load_skill` | `tools/skill_tool.py` | Charge un skill Markdown (`agents/skills/`) à la demande | non |
| `export_deliverable` | `tools/deliverable_tool.py` | Compile un PDF (WeasyPrint, fallback HTML) → `/downloads/{file}` | **oui** |

---

## 11. Récapitulatif par famille

| Famille | Module | Nb |
|---|---|---|
| Données & analyse | `data_tools.py` | 3 |
| EcoTaxa | `copepod_sources.py` | 22 |
| EcoPart | `ecopart_sources.py` | 6 |
| Amundsen CTD | `amundsen_sources.py` | 5 |
| Bio-ORACLE | `bio_oracle_sources.py` | 6 |
| OGSL | `ogsl_sources.py` | 2 |
| Workspace SQL (conditionnel) | `sql_workspace.py` | 3 |
| Géographie | `geo_tools.py` | 2 |
| Savoir & taxonomie | `rag_tool.py`, `taxonomy_tool.py` | 2 |
| Skills & livrables | `skill_tool.py`, `deliverable_tool.py` | 2 |
| **Total** | | **~53** |
