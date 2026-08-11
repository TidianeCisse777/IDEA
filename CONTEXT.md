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
- Interroge cinq sources : **EcoTaxa**, **EcoPart**, **Amundsen CTD**, **OGSL**, **Bio-ORACLE**. La route de source est une préférence contextuelle, jamais un verrou empêchant le modèle de choisir une ressource pertinente.
- Exécute des calculs pandas via `run_pandas`.
- Produit des graphiques matplotlib via `run_graph` après qualification du DataFrame choisi dans son plan.
- Interroge un workspace SQL en lecture seule via `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace`.
- Interroge la base de connaissances copépodes (11 docs RAG, ChromaDB) via `query_copepod_knowledge_base`.
- Génère des livrables PDF via `export_deliverable`.

## Ce que l'agent ne fait pas

- Aucune interprétation biologique ou écologique des résultats. Si l'utilisateur demande une explication scientifique, l'agent répond : « L'interprétation revient au chercheur. »
- Aucune citation scientifique fabriquée. Si la source vérifiée manque : redirige vers Google Scholar ou Web of Science.
- Aucune valeur numérique inventée. Tout chiffre vient d'un `run_pandas`, d'un tool, ou du RAG.
- Aucune modification des données brutes. Toute transformation crée une copie nommée.
- Aucun credential affiché, logué, ou inclus dans un livrable.
- Aucune première requête en ligne sans nom de source explicite. Un nombre ou nom de projet seul ne choisit pas sa source; les suivis peuvent réutiliser l'affinité de source persistée.

---

## Pilotage : un seul agent, pas de modes

L'agent est un **LangGraph ReAct unique**. Tous les outils exécutables restent déclarés dans le `ToolNode`. Avec OpenAI Tool Search, le modèle reçoit directement les capacités locales essentielles et quatre namespaces différés (`ecotaxa`, `ecopart`, `geography`, `environmental_enrichment`); OpenAI charge ensuite uniquement les schémas spécialisés utiles. Il n'y a pas d'état de session « mode » à activer ou désactiver.

Le system prompt compact est lu localement depuis `agents/copepod_system_prompt.py`. Il n'existe plus de tool de chargement de skills : les règles actives vivent dans le prompt, les docstrings et le RAG.

1. **File analysis** — quand l'utilisateur travaille un fichier chargé : `load_file`, `run_pandas`.
2. **Knowledge base** — quand l'utilisateur pose une question sur colonnes, méthodes, taxonomie : `query_copepod_knowledge_base` d'abord, jamais de réponse de mémoire.

Pour un calcul ou un graphique, le plan nomme d'abord les DataFrames candidats et leurs critères de grain, colonnes, clés, portée et valeurs manquantes. Un petit contrôle `run_pandas` qualifie le candidat; après son résultat seulement, l'agent poursuit avec le calcul ou `run_graph`. `run_pandas` et `run_graph` restent visibles directement et ne passent jamais par Tool Search.

**Confirmation utilisateur explicite avant opération coûteuse (CT-AG-06)** — le prompt impose un « oui / go / lance / confirme » avant les exports distants, enrichissements lourds, copies SQL non bornées et livrables. Les opérations locales légères restent immédiates.

---

## RAG

`query_copepod_knowledge_base` recherche les 11 documents de `core/copepod_rag/docs/`.
Il fournit le savoir métier sur les colonnes, méthodes, taxonomie et sources. Si
le RAG est appelé, l'agent attend son résultat avant de poursuivre.

---

## Sources de données

| Source | Statut | Outils principaux |
|---|---|---|
| Fichier local (CSV/TSV/Excel/JSON/Parquet) | implémenté | `load_file`, `run_pandas` |
| EcoTaxa | implémenté | cache SQL, `query_ecotaxa`, `export_ecotaxa_samples` |
| EcoPart | implémenté | correspondance, aperçu, enrichissement distant |
| Amundsen CTD | implémenté | disponibilité, profils, enrichissement CTD |
| Bio-ORACLE | implémenté | enrichissement d'un DataFrame qualifié |
| OGSL | implémenté | enrichissement CTD d'un DataFrame qualifié |
| Workspace SQL | implémenté | `list_sql_tables`, `preview_sql_table`, `copy_sql_query_to_workspace` |

OBIS n'est pas une source autorisée.

---

## Enrichment ponctuel (architecture)

L'**enrichment ponctuel** est le geste « pour chaque ligne d'une table chargée, résoudre une valeur environnementale par latitude/longitude (+ éventuellement temps/profondeur) ». Il couvre trois sources : **Amundsen CTD**, **OGSL** et **Bio-ORACLE**. L'enrichissement EcoPart est une jointure sur des identifiants et profondeurs, pas une résolution lat/lon.

Ce geste a une **séquence unique** possédée par le module `run_point_enrichment` (`tools/point_enrichment.py` — couche `tools`, car il orchestre le session store ; `tools` peut dépendre de `core`, jamais l'inverse) : résolution de la table source → détection des colonnes coords → scoping zone/date → validation → dédup des points uniques → **MATCH** → recollage + colonne `<source>_match_status` → stockage session → bloc méthode avec la ligne de **coverage** (invariant : « X matchées sur Y »).

Le **`PointMatcher`** est l'adapter au seam : un par source (`AmundsenMatcher`, `OgslMatcher`, `BioOracleMatcher`), défini près de sa source. Il ne porte que le cœur qui varie — la clé de dédup (`dedup_keys`) et le MATCH (`match`, où vit le batching ERDDAP / nearest-neighbour / grille). La séquence, les messages d'erreur, l'ordre des gardes et la règle de coverage-warning vivent **une seule fois**, dans le shell.

Pour Bio-ORACLE, la voie canonique enrichit un **DataFrame** chargé ligne par
ligne et conserve son grain : une ligne source reste une ligne de sortie. Avant
toute requête distante, l'agent propose la présélection copépodes et le catalogue
complet, puis attend la sélection explicite des variables, scénarios, couche
verticale et statistique. Aucune présélection implicite n'est appliquée.

---

## Règles dures (extrait)

- Toute valeur numérique vient d'un `run_pandas`, d'un tool ou du RAG. Sinon : « valeur inconnue ».
- Toute production graphique utilise directement `run_graph` après qualification du DataFrame candidat.
- Toute question factuelle sur colonnes, méthodes, taxonomie : `query_copepod_knowledge_base` **avant** toute réponse.
- Toute première requête en ligne nécessite le nom explicite de la source; les tours suivants héritent de cette affinité jusqu'à une bascule ou un fichier chargé.
- Tout livrable passe par `deliverable_writer` + `export_deliverable`, jamais une rédaction libre.
- Les noms d'outils internes (`run_pandas`, `load_file`, …) ne sont jamais exposés à l'utilisateur.
- **Ton clinique (CT-AG-26)** : pas de « je / moi / en tant qu'IA », pas de politesse décorative, pas de phrases d'ouverture conversationnelles. Pour les **résultats analytiques** (graphique, calcul, jointure, livrable) : structurer autour de Résultat / Source / Méthode / Limite / Prochaine action. Pour les **questions courtes** (un chiffre, un nom de colonne, oui/non, clarification) : répondre directement, sans imposer la structure.
- **Incertitude visible (CT-AG-27)** : chaque graphique classe ses lignes en `confirmed` / `exploratory` / `uncertain identification`, affiche un stamp `Confidence: high|medium|low` en bas-droite, avec annotation rouge si `low`. Palette dédiée : saturé pour confirmé, désaturé + hachure pour exploratoire, gris ouvert pour incertain. Confirmé et exploratoire ne doivent **jamais** être visuellement indistinguables.

Pour la liste complète : voir le system prompt `agents/copepod_system_prompt.py` et les 29 contraintes du PRD (`assistant-copepodes-specs/docs/PRD_IDEA_copepod.md`).
