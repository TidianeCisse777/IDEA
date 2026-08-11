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
| UC-A2 | Détecter automatiquement le profil d’un fichier EcoTaxa / EcoPart et exposer sa description, son grain et ses colonnes dans le contexte. |
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
| UC-G5 | Jointure environnementale non standard (station/cast/time/depth) via les enrichissements canoniques ou `run_pandas`. |

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
| UC-J1 | Compiler le matériel de session (sections markdown, figures, sources, méthodes, limites) en PDF via `export_deliverable` (WeasyPrint, fallback HTML). |

---

## 4. Catalogue canonique des tools

L’agent expose **22 tools obligatoires**, ou **25 lorsque le workspace SQL
optionnel est configuré**. Le catalogue exact est construit et validé dans
`tools/tool_catalog.py`; son inventaire généré est la référence dans
`TOOLS.md`.

Tous les tools canoniques restent disponibles. OpenAI Tool Search peut différer
le chargement de certains schémas, mais `SourceDecision` ne sert jamais de
filtre, d’autorisation ou de blocage.

| Famille | Nombre |
|---|---:|
| Fichier, analyse et graphe | 3 |
| EcoTaxa | 5 |
| EcoPart | 3 |
| Amundsen CTD | 3 |
| Bio-ORACLE | 1 |
| OGSL | 1 |
| Géographie | 3 |
| RAG et taxonomie | 2 |
| Livrable | 1 |
| SQL optionnel | 3 |
| **Total obligatoire** | **22** |
| **Total avec SQL** | **25** |

Le runtime ne possède plus de tool `load_skill`. Les règles actives vivent
dans le system prompt local, les docstrings des tools, le contexte de session et
le RAG.

---

## 5. Contexte et planification

Le même agent ReAct planifie, choisit ses DataFrames et exécute les tools. Avant
un calcul ou un graphique, il qualifie le DataFrame candidat selon la demande,
le grain, les colonnes requises, la portée, les clés et la nullité. Le harness
injecte notamment `CURRENT TASK`, `AVAILABLE DATAFRAMES`, les faits du dernier
graphique et `EXPLORATION FRONTIER`.

Les fichiers Markdown conservés dans `agents/skills/` sont des références
legacy non chargées au runtime. Ils ne constituent ni une capacité ni une étape
du flux agentique.

---

## 6. Base de connaissances RAG (`core/copepod_rag/docs/`, 14 documents)

Le RAG apporte les méthodes, unités, définitions de colonnes, protocoles,
sources et règles métier documentées. Lorsqu’il est appelé, l’agent attend son
résultat avant de poursuivre la boucle ReAct. Il ne remplace jamais l’analyse
des DataFrames réels.

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
