# SPEC.md — Spécification figée · IDEA / Assistant graphique copépodes

> Document de référence figé. Décrit **ce que l'agent est**, **ce qu'il fait**,
> **ce qu'il ne fait pas**, ses **use cases** classés et l'inventaire complet de
> ses **capacités**. Pour le câblage technique voir [`ARCHITECTURE.md`](ARCHITECTURE.md),
> pour le partage/déploiement voir [`PARTAGE.md`](PARTAGE.md), pour les flux
> détaillés voir [`SEQUENCES.md`](SEQUENCES.md).
>
> Sources de vérité vivantes : `agents/copepod_system_prompt.py` (règles de
> routage), `tools/*.py` (implémentation), `CONTEXT.md` (identité métier).

---

## 1. Identité et périmètre

**Assistant graphique copépodes** — assistant de production graphique et
d'analyse pour données de copépodes marins de NeoLab (Université Laval).

| Attribut | Valeur |
|---|---|
| Acteurs | Chercheur, professeur ou étudiant NeoLab. Aucune fonctionnalité réservée à un rôle. |
| Langue | Répond dans la langue de l'utilisateur, **français par défaut**. System prompt en anglais. |
| Runtime | Fork de la plateforme IDEA (Université d'Hawaï). On garde le runtime, on remplace system prompt + tools + docs RAG. |
| Nature | **Un seul agent LangGraph ReAct**. Pas de « mode » de session. Tous les tools déclarés à la construction. |

### Ce que l'agent EST
- Un producteur de graphiques scientifiques statiques (matplotlib/PNG).
- Un moteur d'analyse tabulaire contrôlée (pandas) sur données chargées.
- Un explorateur read-only de sources océanographiques en ligne.
- Un compilateur de livrables PDF traçables.

### Ce que l'agent N'EST PAS
- Pas un interprète biologique ou écologique. « L'interprétation revient au chercheur. »
- Pas un assistant scientifique généraliste.
- Pas un générateur de citations : source vérifiée absente → redirige vers Google Scholar / Web of Science.
- Pas un moteur qui invente des chiffres : toute valeur vient d'un tool, de `run_pandas` ou du RAG.

---

## 2. Contraintes dures (invariants)

Ces règles sont non négociables. Elles sont appliquées par le system prompt et
doivent être préservées à toute modification.

| # | Contrainte | Référence |
|---|---|---|
| I1 | Toute valeur numérique vient d'un tool, de `run_pandas` ou du RAG. Sinon « valeur inconnue ». | — |
| I2 | Toute production graphique suit `graph_planner` → `graph_writer` → `run_graph`. Le tool juste après `graph_writer` **doit** être `run_graph`. | — |
| I3 | Toute question factuelle (colonnes, méthodes, taxonomie) passe par `query_copepod_knowledge_base` avant toute réponse. | — |
| I4 | Toute requête en ligne exige une demande utilisateur explicite (mot-clé ou nom de projet). | — |
| I5 | Toute donnée EcoTaxa/EcoPart citée inclut l'URL canonique source (`ecotaxa.obs-vlfr.fr/prj/{id}`, `ecopart.obs-vlfr.fr/prj/{id}`). | — |
| I6 | Confirmation explicite avant opération coûteuse (export, download, variable dérivée, jointure non standard). | CT-AG-06 |
| I7 | Aucun credential révélé, logué, ou inclus dans un livrable. | — |
| I8 | Aucun nom de tool interne exposé à l'utilisateur. | — |
| I9 | Ton clinique : pas de « je / moi / en tant qu'IA », pas de politesse décorative, pas de proposition de next steps. | CT-AG-26 |
| I10 | Incertitude visible sur les graphiques : classes `confirmed` / `exploratory` / `uncertain`, stamp `Confidence: high\|medium\|low`, palette dédiée. | CT-AG-27 |
| I11 | Aucune modification des données brutes. Toute transformation crée une copie nommée. | — |
| I12 | OBIS n'est **pas** une source autorisée. | — |

---

## 3. Use cases classés

Regroupement des usages réels de l'agent, du plus stable au plus expérimental.

### UC-A · Analyse de fichier local *(stable)*
| Code | Use case |
|---|---|
| UC-A1 | Charger un fichier tabulaire (CSV, TSV, Excel, JSON, Parquet) et inspecter colonnes, types, manquants, plages, rôles sémantiques (station, depth, lat/lon, taxon, morphométrie). |
| UC-A2 | Détecter automatiquement un export UVP EcoTaxa / EcoPart et charger le skill associé. |
| UC-A3 | Exécuter une analyse pandas contrôlée : filtre, groupby, agrégation, variable dérivée, contrôle qualité, doublons, manquants, jointure simple. |
| UC-A4 | Calculer abondance / biomasse / densité (m5, m6) quand les champs requis existent. |

### UC-B · Production graphique *(stable)*
| Code | Use case |
|---|---|
| UC-B1 | Produire un graphique statique PNG : profil vertical, carte de stations, carte de lacunes spatiales, distribution taxonomique, série temporelle, résumé stratifié en profondeur, profil CTD, superposition environnementale. |
| UC-B2 | Appliquer la planification obligatoire `graph_planner` → `graph_writer` → `run_graph` avec palette d'incertitude (CT-AG-27). |
| UC-B3 | Rendre une sortie sous forme de **tableau** (via `run_pandas`) quand le planner décide « table » plutôt que « visual ». |

### UC-C · Base de connaissances / taxonomie *(stable)*
| Code | Use case |
|---|---|
| UC-C1 | Répondre à une question de savoir (définition, méthode, colonne, protocole, géographie) via le RAG NeoLab (`query_copepod_knowledge_base`). |
| UC-C2 | Résoudre un taxon marin (nom scientifique/vernaculaire, AphiaID, statut WoRMS, synonymie, classification) via `lookup_marine_taxonomy`. |
| UC-C3 | Fournir des garde-fous d'interprétation micro-hydrodynamique (fronts, panaches, upwelling, eddies) centrés copépodes. |

### UC-D · Exploration EcoTaxa (read-only, via cache MCP) *(en développement)*
| Code | Use case |
|---|---|
| UC-D1 | Lister / chercher les projets accessibles (`list_ecotaxa_projects`, `find_ecotaxa_projects`). |
| UC-D2 | Explorer par zone + période : samples et projets d'une région (`find_ecotaxa_samples_in_region`, `find_ecotaxa_projects_in_region`, `group_ecotaxa_project_samples_by_region`). |
| UC-D3 | Explorer les taxons : recherche, counts V/P/D/U, observations (`search_ecotaxa_taxa`, `count_ecotaxa_taxa`, `find_ecotaxa_observations`). |
| UC-D4 | Inspecter schéma / colonnes / distributions et comparer des projets avant merge (`inspect_ecotaxa_project_schema`, `inspect_ecotaxa_column`, `compare_ecotaxa_projects`). |
| UC-D5 | Résumer projets et samples sans télécharger (`summarize_ecotaxa_project(s)`, `summarize_ecotaxa_sample(s)`, `summarize_ecotaxa_sample_deployment`). |
| UC-D6 | Explorer campagnes / legs / missions (`list_ecotaxa_campaigns`). |
| UC-D7 | Diagnostiquer l'état du cache (`get_ecotaxa_cache_status`). |

### UC-E · Export / téléchargement EcoTaxa *(en développement)*
| Code | Use case |
|---|---|
| UC-E1 | Exporter un projet complet (`query_ecotaxa`) — opération confirmée. |
| UC-E2 | Exporter un sample unique ou une sélection de samples (`query_ecotaxa_sample`, `query_ecotaxa(sample_ids=[...])`). |
| UC-E3 | Filtrer l'export côté serveur par taxon, statut, profondeur objet. |

### UC-F · EcoPart et enrichissement biologique↔environnemental *(en développement)*
| Code | Use case |
|---|---|
| UC-F1 | Lister / prévisualiser / exporter des samples EcoPart (`list_ecopart_samples`, `preview_ecopart_sample`, `query_ecopart`). |
| UC-F2 | Vérifier la disponibilité d'un EcoPart pour un EcoTaxa chargé sans export (`find_ecopart_project_for_ecotaxa`). |
| UC-F3 | Joindre EcoTaxa ↔ EcoPart par `(sample_id, depth_bin)` (5 m) — join local (`join_ecotaxa_ecopart`) ou distant (`enrich_ecotaxa_with_ecopart_remote`). |

### UC-G · Enrichissement environnemental (CTD / climatologie) *(en développement)*
| Code | Use case |
|---|---|
| UC-G1 | Enrichir une table chargée avec Amundsen CTD par lat/lon/temps (`enrich_with_amundsen_ctd`). |
| UC-G2 | Enrichir avec OGSL ISMER CTD (Golfe du Saint-Laurent) (`enrich_with_ogsl`). |
| UC-G3 | Enrichir avec Bio-ORACLE (variables actuelles + scénarios SSP futurs) par ligne, par station ou par zone (`enrich_with_bio_oracle`, `query_bio_oracle_zones`). |
| UC-G4 | Enrichissements scopés zone/date et chaînés sur la même table (via `source_variable`). |
| UC-G5 | Jointure environnementale non standard (custom station/cast/time/depth) via skill `environmental_join` + `run_pandas`. |

### UC-H · Workspace SQL read-only *(implémenté)*
| Code | Use case |
|---|---|
| UC-H1 | Lister tables/vues, clés primaires/étrangères (`list_sql_tables`). |
| UC-H2 | Prévisualiser une table avec filtres (`preview_sql_table`). |
| UC-H3 | Copier un `SELECT` (avec `LIMIT` obligatoire) dans le workspace en TSV (`copy_sql_query_to_workspace`). |

### UC-I · Géographie nommée *(implémenté)*
| Code | Use case |
|---|---|
| UC-I1 | Résoudre une zone nommée IHO ou écorégion MEOW en bbox/polygone (`get_zone_info`). |
| UC-I2 | Filtrer une DataFrame chargée par polygone de zone (`filter_dataframe_by_zone`). |

### UC-J · Livrables *(en développement)*
| Code | Use case |
|---|---|
| UC-J1 | Compiler le matériel de session (sections markdown, figures, sources, méthodes, limites) en PDF via `deliverable_writer` + `export_deliverable` (WeasyPrint, fallback HTML). |

---

## 4. Inventaire complet des capacités (tools exposés au LLM)

L'agent expose **59 tools** (62 avec les tools SQL optionnels) répartis en 12
familles. Ils sont tous déclarés à la construction dans `agent.py`
(`create_agent`, ex-`create_react_agent`). Les tools SQL ne sont ajoutés que si
`DATABASE_URL` est résolvable.

> Note : CLAUDE.md et d'anciens docs mentionnent « 23 tools » — chiffre obsolète.
> Le compte réel ci-dessous fait foi.

### 4.1 Données & analyse (`tools/data_tools.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `load_file` | Charger CSV/TSV/Excel/JSON/Parquet, inspecter, détecter UVP | non |
| `run_pandas` | Exécuter du pandas contrôlé sur données de session | non |
| `run_graph` | Exécuter du code matplotlib et héberger le PNG | non |

### 4.2 EcoTaxa read-only & export (`tools/copepod_sources.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_ecotaxa_projects` | Lister projets accessibles | non |
| `find_ecotaxa_projects` | Chercher projets par titre/instrument | non |
| `list_ecotaxa_campaigns` | Grouper projets par campagne/leg | non |
| `preview_ecotaxa_project` | Aperçu objets d'un projet | non |
| `inspect_ecotaxa_project_schema` | Colonnes par niveau (sample/acq/object) | non |
| `inspect_ecotaxa_column` | Distribution/stats d'une colonne | non |
| `compare_ecotaxa_projects` | Compatibilité de schémas avant merge | non |
| `count_ecotaxa_taxa` | Counts V/P/D/U par projet et taxon | non |
| `search_ecotaxa_taxa` | Résoudre `taxon_id` candidats | non |
| `find_ecotaxa_samples_in_region` | Samples par zone/période/instrument | non |
| `find_ecotaxa_projects_in_region` | Projets par zone/période | non |
| `group_ecotaxa_project_samples_by_region` | Samples d'un projet groupés par zone | non |
| `find_ecotaxa_observations` | Samples dont le projet atteste un taxon | non |
| `get_ecotaxa_sample` | Métadonnées / free fields d'un sample | non |
| `summarize_ecotaxa_project` / `summarize_ecotaxa_projects` | Résumé(s) projet | non |
| `summarize_ecotaxa_sample` / `summarize_ecotaxa_samples` | Résumé(s) sample | non |
| `summarize_ecotaxa_sample_deployment` | Position, dates, profondeurs, acquisition | non |
| `get_ecotaxa_cache_status` | État du cache MCP | non |
| `query_ecotaxa` | **Export projet complet** | **oui** |
| `query_ecotaxa_sample` | **Export d'un sample** | **oui** |
| `export_ecotaxa_samples` | **Export d'une sélection nommée de samples** | **oui** |

### 4.3 EcoPart (`tools/ecopart_sources.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_ecopart_samples` | Lister samples EcoPart | non |
| `preview_ecopart_sample` | Aperçu d'un sample | non |
| `find_ecopart_project_for_ecotaxa` | Disponibilité EcoPart (read-only) | non |
| `query_ecopart` | **Export projet EcoPart** | **oui** |
| `join_ecotaxa_ecopart` | Join local `(sample_id, depth_bin)` | non |
| `enrich_ecotaxa_with_ecopart_remote` | **Fetch EcoPart distant + join** | **oui** |

### 4.4 Amundsen CTD (`tools/amundsen_sources.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_amundsen_datasets` | Datasets CTD disponibles | non |
| `preview_amundsen_profile` | Aperçu profil station/cast | non |
| `enrich_with_amundsen_ctd` | Enrichir table par lat/lon/temps | non* |
| `enrich_loaded_table_with_amundsen_ctd` | Variante legacy table explicite | non* |
| `query_amundsen_ctd` | **Download dataset complet** | **oui** |

### 4.5 Bio-ORACLE (`tools/bio_oracle_sources.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_bio_oracle_datasets` | Variables/scénarios disponibles | non |
| `preview_bio_oracle_point` | Valeur en un point | non |
| `query_bio_oracle_zones` | Valeurs par zone nommée | non |
| `couple_zooplankton_bio_oracle` | Coupler lignes zooplancton ↔ variables | oui si >10 lignes |
| `enrich_with_bio_oracle` | Enrichir table (var × scénario par point) | oui si >10 lignes × multi-var |
| `query_bio_oracle` | **Extraction région/scénario** | **oui** |

### 4.6 OGSL (`tools/ogsl_sources.py`)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `enrich_with_ogsl` | Enrichir table avec OGSL ISMER CTD | non* |
| `query_ogsl` | Extraction OGSL | oui |

### 4.7 Workspace SQL (`tools/sql_workspace.py`, conditionnel)
| Tool | Rôle | Coûteux ? |
|---|---|---|
| `list_sql_tables` | Lister tables/vues + PK/FK | non |
| `preview_sql_table` | Aperçu filtré | non |
| `copy_sql_query_to_workspace` | Copier un `SELECT` (LIMIT requis) en TSV | oui si sans LIMIT |

### 4.8 Géographie (`tools/geo_tools.py`)
| Tool | Rôle |
|---|---|
| `get_zone_info` | Résoudre zone IHO/MEOW → bbox + polygone |
| `filter_dataframe_by_zone` | Filtrer df par polygone (point-in-polygon) |

### 4.9 Savoir & taxonomie
| Tool | Module | Rôle |
|---|---|---|
| `query_copepod_knowledge_base` | `tools/rag_tool.py` | RAG NeoLab (ChromaDB, 11 docs) |
| `lookup_marine_taxonomy` | `tools/taxonomy_tool.py` | Résolution taxon (RAG local → WoRMS → Wikipedia) |

### 4.10 Skills & livrables
| Tool | Module | Rôle |
|---|---|---|
| `load_skill` | `tools/skill_tool.py` | Charger un skill Markdown à la demande |
| `export_deliverable` | `tools/deliverable_tool.py` | **Générer un PDF** (WeasyPrint) — coûteux |

\* Les tools d'enrichissement `enrich_with_*` sont considérés légers par ligne
mais franchissent la porte de confirmation au-delà des seuils CT-AG-06
(ex. Bio-ORACLE > 10 lignes multi-variables).

---

## 5. Skills chargeables (`agents/skills/`, 14 fichiers)

Un **skill** est un document Markdown chargé en bloc via `load_skill(name)`. Il
porte le **geste** (comment faire), tandis que le RAG porte le **savoir**.

| Skill | Rôle |
|---|---|
| `graph_planner` | Décide type de graphique, colonnes, filtres, unités |
| `graph_writer` | Template de code matplotlib exécutable |
| `ecotaxa_navigation` | Routage list/scan/export, counts, schéma, dry-run |
| `ecotaxa_query` | Interprétation d'un export EcoTaxa |
| `ecopart_query` | Interprétation d'un export EcoPart |
| `amundsen_ctd_query` | Extraction Amundsen CTD via ERDDAP |
| `bio_oracle_query` | Extraction Bio-ORACLE par scénario/couche |
| `environmental_join` | Stratégie de jointure bio ↔ environnemental |
| `sql_workspace_query` | Règles du workspace SQL read-only |
| `neolabs_abundance_analysis` | Abondance/diversité/ordination NeoLabs |
| `copepod_hydrodynamic_micro_zoom` | Garde-fous micro-hydrodynamique |
| `uvp_ecotaxa` | Auto-chargé sur export UVP EcoTaxa (m5/m6) |
| `uvp_ecopart` | Auto-chargé sur export UVP EcoPart |
| `deliverable_writer` | Structure de livrable PDF + templates de citation |

---

## 6. Base de connaissances RAG (`core/copepod_rag/docs/`, 11 docs)

`colonnes_instruments.md`, `colonnes_labo.md`, `colonnes_sources.md`,
`copepodes_domaine.md`, `ecoregions_meow.md`, `geographie_nord_quebec.md`,
`jointures_environnementales.md`, `methodes_calcul.md`, `sources_en_ligne.md`,
`taxonomie_worms.md`, `zones_geographiques.md`.

Index ChromaDB généré localement (non commité) :
`python core/copepod_rag/build_index.py`.

---

## 7. Sources de données

| Source | Statut | Accès |
|---|---|---|
| Fichier local (CSV/TSV/Excel/JSON/Parquet) | implémenté | `load_file`, `run_pandas` |
| EcoTaxa | implémenté (exploration en dev) | cache MCP read-only + export API |
| EcoPart | implémenté (en dev) | API + join |
| Amundsen CTD (ERDDAP `ca-cioos_ccin-12713`) | implémenté (en dev) | ERDDAP |
| Bio-ORACLE | implémenté (en dev) | ERDDAP |
| OGSL ISMER CTD | implémenté (en dev) | ERDDAP |
| OGSL (source générique) | annoncé, tool dédié à venir | — |
| Workspace SQL (SQLite/PostgreSQL/MySQL/MariaDB) | implémenté | read-only via `DATABASE_URL` |
| OBIS | **non autorisé** | — |

---

## 8. Limites connues (à date)

- Graphiques PNG uniquement — pas de workflow Plotly/HTML interactif.
- Pas de génération de code R.
- Pas de quotas multi-utilisateurs production-grade.
- Dépendance à l'API OpenAI (pas de LLM local hébergé).
- Bio-ORACLE et certains workflows end-to-end nécessitent plus de tests UI.
- Index RAG ChromaDB généré localement, non commité.
- Les DataFrames de session peuvent devoir être rechargées après certains redémarrages.

---

## 9. Traçabilité

- Règles de routage complètes : `agents/copepod_system_prompt.py`.
- 14 UC et 29 contraintes du PRD V1.2 : `assistant-copepodes-specs/` (repo de specs métier, hors de ce dépôt) et `docs/UC_TRACEABILITY.md` si présent.
- Contraintes citées (CT-AG-06, CT-AG-26, CT-AG-27) : identifiants du PRD métier.
