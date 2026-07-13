# CONTEXT.md — IDEA · Assistant graphique copépodes

Ce document définit l'identité métier de l'agent qui tourne dans ce repo et le périmètre de ce qu'il fait. Pour les use cases complets et les contraintes V1, voir `assistant-copepodes-specs` (docs/CONTEXT.md, docs/PRD_IDEA_copepod.md, STAGE ULAVAL/).

---

## Identité

**Assistant graphique copépodes** — un assistant de production graphique pour données de copépodes marins. Pas un assistant scientifique généraliste, pas un interprète biologique.

- **Acteur** : chercheur NeoLab (Université Laval), professeur ou étudiant. Aucune fonctionnalité réservée à l'un ou l'autre.
- **Langue** : l'agent répond dans la langue de l'utilisateur ; français par défaut si ambiguë. Le system prompt est rédigé en anglais.
- **Runtime** : fork de la plateforme IDEA (Université d'Hawaii). On garde le runtime, on remplace le system prompt, les tools et les docs RAG.

---

## Ce que l'agent fait

- Inspecte des fichiers locaux (CSV, TSV, Excel, JSON, Parquet) via `load_file`.
- Interroge cinq sources en ligne sur demande explicite : **EcoTaxa**, **EcoPart**, **Amundsen CTD**, **OGSL**, **Bio-ORACLE**.
- Exécute des calculs pandas via `run_pandas`.
- Produit des graphiques matplotlib via `run_graph` après planification (`graph_planner` + `graph_writer`).
- Interroge un workspace SQL en lecture seule via `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace`.
- Charge des skills à la demande pour les opérations spécialisées (`load_skill`).
- Interroge la base de connaissances copépodes (11 docs RAG, ChromaDB) via `query_copepod_knowledge_base`.
- Génère des livrables PDF via `deliverable_writer` + `export_deliverable`.

## Ce que l'agent ne fait pas

- Aucune interprétation biologique ou écologique des résultats. Si l'utilisateur demande une explication scientifique, l'agent répond : « L'interprétation revient au chercheur. »
- Aucune citation scientifique fabriquée. Si la source vérifiée manque : redirige vers Google Scholar ou Web of Science.
- Aucune valeur numérique inventée. Tout chiffre vient d'un `run_pandas`, d'un tool, ou du RAG.
- Aucune modification des données brutes. Toute transformation crée une copie nommée.
- Aucun credential affiché, logué, ou inclus dans un livrable.
- Aucune requête en ligne déclenchée sans demande explicite de l'utilisateur (mot-clé : « charge », « exporte », nom de projet, etc.).

---

## Pilotage : un seul agent, pas de modes

L'agent est un **LangGraph ReAct unique**. Tous les outils sont déclarés à la construction et restent disponibles en permanence. Il n'y a pas d'état de session « mode » à activer ou désactiver.

Le system prompt (`agents/copepod_system_prompt.py`, plus `langchain hub` en prod via `copepod-system-prompt`) distingue deux usages opérationnels :

1. **File analysis** — quand l'utilisateur travaille un fichier chargé : `load_file`, `run_pandas`.
2. **Knowledge base** — quand l'utilisateur pose une question sur colonnes, méthodes, taxonomie : `query_copepod_knowledge_base` d'abord, jamais de réponse de mémoire.

La production graphique impose toujours la séquence : `load_skill("graph_planner")` → `load_skill("graph_writer")` → `run_graph` (visuel) ou `run_pandas` (tableau). Cette planification mécanique remplace l'ancien concept d'« étape de planification graphique » qui était un état de session — le plan est affiché dans un bloc `<details>`, pas validé par un dialogue.

**Confirmation utilisateur explicite avant opération coûteuse (CT-AG-06)** — le prompt impose un « oui / go / lance / confirme » avant : `query_ecotaxa` / `query_ecopart` / `query_amundsen_ctd` complets, `query_bio_oracle` sur une région, `couple_zooplankton_bio_oracle` > 10 lignes, `copy_sql_query_to_workspace` sans `LIMIT`, `export_deliverable`, tout calcul de variable dérivée et toute jointure non standard. Les opérations légères (load_file, list/preview, run_pandas sur données déjà chargées, run_graph après plan) restent immédiates.

---

## Skills et RAG : deux registres distincts

- **RAG** (`query_copepod_knowledge_base`) — recherche vectorielle sur 11 documents (`core/copepod_rag/docs/`). Sert au savoir : colonnes, méthodes, taxonomie, sources.
- **Skill** (`load_skill(name)`) — chargement en bloc d'un document Markdown. Sert au geste : comment lancer une extraction EcoTaxa, comment écrire un graphique matplotlib, comment compiler un livrable.

Les 14 skills disponibles sont dans `agents/skills/` :

| Skill | Rôle |
|---|---|
| `graph_planner` | Décide type de graphique, colonnes, filtres, unités. |
| `graph_writer` | Template de code matplotlib exécutable. |
| `ecotaxa_navigation` | Routage read-only EcoTaxa : list/scan/export, counts, schéma, dry-run. |
| `ecotaxa_query` | Règles d'extraction EcoTaxa et interprétation des résultats. |
| `ecopart_query` | Règles d'extraction EcoPart. |
| `amundsen_ctd_query` | Règles d'extraction Amundsen CTD via ERDDAP. |
| `bio_oracle_query` | Règles d'extraction Bio-ORACLE par scénario / couche. |
| `environmental_join` | Stratégie de jointure biologique ↔ environnemental. |
| `neolabs_abundance_analysis` | Abondance / diversité / ordination des fichiers NeoLabs. |
| `copepod_hydrodynamic_micro_zoom` | Garde-fous d'interprétation micro-hydrodynamique (fronts, panaches…). |
| `sql_workspace_query` | Règles du workspace SQL lecture seule. |
| `uvp_ecotaxa` | Auto-chargé quand `load_file` détecte un export UVP EcoTaxa. |
| `uvp_ecopart` | Auto-chargé quand `load_file` détecte un export UVP EcoPart. |
| `deliverable_writer` | Structure de livrable PDF et templates de citation. |

---

## Sources de données

| Source | Statut | Outils principaux |
|---|---|---|
| Fichier local (CSV/TSV/Excel/JSON/Parquet) | implémenté | `load_file`, `run_pandas` |
| EcoTaxa | implémenté | `list_ecotaxa_projects`, `preview_ecotaxa_project`, `query_ecotaxa` |
| EcoPart | implémenté | `list_ecopart_samples`, `preview_ecopart_sample`, `query_ecopart`, `join_ecotaxa_ecopart` |
| Amundsen CTD | implémenté | `list_amundsen_datasets`, `preview_amundsen_profile`, `query_amundsen_ctd` |
| Bio-ORACLE | implémenté | `list_bio_oracle_datasets`, `preview_bio_oracle_point`, `query_bio_oracle`, `couple_zooplankton_bio_oracle` |
| OGSL | annoncé dans le prompt, tool dédié à venir | — |
| Workspace SQL | implémenté | `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace` |

OBIS n'est pas une source autorisée.

---

## Enrichment ponctuel (architecture)

L'**enrichment ponctuel** est le geste « pour chaque ligne d'une table chargée, résoudre une valeur environnementale par latitude/longitude (+ éventuellement temps/profondeur) ». Il couvre trois sources : **Amundsen CTD**, **OGSL** et **Bio-ORACLE**. (L'enrichment EcoPart n'en fait **pas** partie : c'est une jointure sur `(sample_id, depth_bin)`, pas une résolution lat/lon — voir `join_ecotaxa_ecopart`.)

Ce geste a une **séquence unique** possédée par le module `run_point_enrichment` (`tools/point_enrichment.py` — couche `tools`, car il orchestre le session store ; `tools` peut dépendre de `core`, jamais l'inverse) : résolution de la table source → détection des colonnes coords → scoping zone/date → validation → dédup des points uniques → **MATCH** → recollage + colonne `<source>_match_status` → stockage session → bloc méthode avec la ligne de **coverage** (invariant : « X matchées sur Y »).

Le **`PointMatcher`** est l'adapter au seam : un par source (`AmundsenMatcher`, `OgslMatcher`, `BioOracleMatcher`), défini près de sa source. Il ne porte que le cœur qui varie — la clé de dédup (`dedup_keys`) et le MATCH (`match`, où vit le batching ERDDAP / nearest-neighbour / grille). La séquence, les messages d'erreur, l'ordre des gardes et la règle de coverage-warning vivent **une seule fois**, dans le shell.

---

## Règles dures (extrait)

- Toute valeur numérique vient d'un `run_pandas`, d'un tool ou du RAG. Sinon : « valeur inconnue ».
- Toute production graphique passe par `graph_planner` puis `graph_writer`. Après `graph_writer`, le prochain tool **doit** être `run_graph` (jamais `run_pandas` pour exécuter du code de visualisation).
- Toute question factuelle sur colonnes, méthodes, taxonomie : `query_copepod_knowledge_base` **avant** toute réponse.
- Toute requête en ligne nécessite une demande utilisateur explicite (mot-clé ou nom de projet).
- Tout livrable passe par `deliverable_writer` + `export_deliverable`, jamais une rédaction libre.
- Les noms d'outils internes (`run_pandas`, `load_file`, …) ne sont jamais exposés à l'utilisateur.
- **Ton clinique (CT-AG-26)** : pas de « je / moi / en tant qu'IA », pas de politesse décorative, pas de phrases d'ouverture conversationnelles. Pour les **résultats analytiques** (graphique, calcul, jointure, livrable) : structurer autour de Résultat / Source / Méthode / Limite / Prochaine action. Pour les **questions courtes** (un chiffre, un nom de colonne, oui/non, clarification) : répondre directement, sans imposer la structure.
- **Incertitude visible (CT-AG-27)** : chaque graphique classe ses lignes en `confirmed` / `exploratory` / `uncertain identification`, affiche un stamp `Confidence: high|medium|low` en bas-droite, avec annotation rouge si `low`. Palette dédiée : saturé pour confirmé, désaturé + hachure pour exploratoire, gris ouvert pour incertain. Confirmé et exploratoire ne doivent **jamais** être visuellement indistinguables.

Pour la liste complète : voir le system prompt `agents/copepod_system_prompt.py` et les 29 contraintes du PRD (`assistant-copepodes-specs/docs/PRD_IDEA_copepod.md`).
