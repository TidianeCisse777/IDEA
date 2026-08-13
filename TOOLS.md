# Catalogue des tools — IDEA

> Catalogue technique des tools déclarés à la construction de l'agent
> (`tools/tool_catalog.py` → `agent.py` → `create_agent`). Pour comprendre
> l’agent, voir [PRESENTATION.md](PRESENTATION.md); pour le câblage, voir
> [ARCHITECTURE.md](ARCHITECTURE.md); pour les règles d’usage, voir
> [BEST_PRACTICES.md](BEST_PRACTICES.md).
>
> Le total inventorié est le catalogue exécutable enregistré dans le `ToolNode`;
> il ne correspond plus à la vue initiale du modèle. Avec
> `OPENAI_TOOL_SEARCH_ENABLED=true`, OpenAI reçoit les capacités locales directes,
> quatre namespaces différés et le Tool Search hébergé. Le fallback sans cette
> option expose directement les 25 tools canoniques sans filtrage lexical.
> Les tools ont des entrées Pydantic strictes et renvoient un artefact `ToolResult`
> structuré (`success`, `empty`, `blocked`, `error` ou `cancelled`) en plus du texte visible.

### Exposition dynamique avec OpenAI Tool Search

- Capacités immédiatement visibles : `load_file`, `query_copepod_knowledge_base`, `run_pandas`, `run_graph`, taxonomie, livrable et workspace SQL lorsqu'il est configuré.
- Namespace `ecotaxa` : cache SQL, inspection du cache et exports confirmés.
- Namespace `ecopart` : recherche de correspondance, aperçu et enrichissement canonique.
- Namespace `geography` : description, filtrage multi-zone et découpe de DataFrame.
- Namespace `environmental_enrichment` : Amundsen CTD, Bio-ORACLE et OGSL.
- Chaque namespace contient moins de dix fonctions. Tous ses membres portent `defer_loading: true`; OpenAI charge leurs descriptions et schémas seulement après la recherche sémantique.
- Le catalogue ne contient que des tools canoniques exécutables. Un retry ou une récupération forcée rend temporairement la fonction visée immédiatement visible, sans duplication dans son namespace.
- `run_pandas` et `run_graph` ne sont jamais différés : la qualification, le calcul et le rendu restent disponibles à chaque étape ReAct.
- `run_pandas` matérialise seulement les DataFrames nommés exactement dans le code; les autres tables restent dans le `SessionStore` et les versions superseded restent archivées hors contexte.

## Choisir la bonne famille

| Intention | Point de départ | Résultat attendu |
|---|---|---|
| Charger un fichier utilisateur | `load_file` | DataFrame persistant avec profil de ressource |
| Vérifier ou transformer un DataFrame | `run_pandas` | preuve compacte ou nouveau DataFrame nommé |
| Produire une figure | `run_graph` | PNG persistant et faits du graphique |
| Consulter le savoir métier | `query_copepod_knowledge_base` | passages documentaires sourcés |
| Explorer le cache EcoTaxa | inspection puis `query_ecotaxa_cache` | table SQL persistée et lignée connue |
| Télécharger depuis EcoTaxa | `query_ecotaxa` ou `export_ecotaxa_samples` | export confirmé et DataFrame durable |
| Ajouter une source externe | tool d’enrichissement correspondant | DataFrame enrichi conservant ses parents |
| Situer ou découper des points | famille géographie | description, filtre ou tables par zone |
| Résoudre un taxon | `lookup_marine_taxonomy` | correspondances et provenance taxonomique |
| Créer un rapport | `export_deliverable` | artefact téléchargeable |

Un tool de consultation ou d’aperçu ne remplace pas une preuve sur le DataFrame
réel. La qualification Pandas est toutefois conditionnelle : elle est inutile
si le résultat structuré ou la fiche de ressource établit déjà la colonne, le
grain et la portée. Sinon, une seule qualification ciblée est permise; plusieurs
colonnes plausibles entraînent une question utilisateur avant le calcul.

<!-- TOOL-INVENTORY:START -->
Inventaire généré : **22 tools obligatoires**, **25 avec SQL**.

| Tool | Famille | Source | Risque | Confirmation | Optionnel | I/O distant | État de session |
|---|---|---|---|---|---|---|---|
| `copy_sql_query_to_workspace` | sql | sql | high | oui | oui | oui | oui |
| `describe_ecotaxa_cache_table` | ecotaxa | ecotaxa | low | non | non | non | non |
| `enrich_ecotaxa_with_ecopart_remote` | ecopart | ecopart | high | oui | non | oui | oui |
| `enrich_with_amundsen_ctd` | amundsen | amundsen | high | oui | non | oui | oui |
| `enrich_with_bio_oracle` | bio_oracle | bio_oracle | high | oui | non | oui | oui |
| `enrich_with_ogsl` | ogsl | ogsl | high | oui | non | oui | oui |
| `export_deliverable` | core | deliverable | high | oui | non | non | oui |
| `export_ecotaxa_samples` | ecotaxa | ecotaxa | high | oui | non | oui | oui |
| `filter_dataframe_by_zone` | geography | geography | medium | non | non | non | oui |
| `find_amundsen_data_for_table` | amundsen | amundsen | low | non | non | oui | non |
| `find_ecopart_project_for_ecotaxa` | ecopart | ecopart | low | non | non | oui | non |
| `get_zone_info` | geography | geography | low | non | non | non | non |
| `list_ecotaxa_cache_tables` | ecotaxa | ecotaxa | low | non | non | non | non |
| `list_sql_tables` | sql | sql | low | non | oui | oui | non |
| `load_file` | data | file | medium | non | non | non | oui |
| `lookup_marine_taxonomy` | core | taxonomy | low | non | non | oui | non |
| `preview_ecopart_sample` | ecopart | ecopart | low | non | non | oui | non |
| `preview_sql_table` | sql | sql | low | non | oui | oui | non |
| `query_amundsen_profiles_for_table` | amundsen | amundsen | high | oui | non | oui | oui |
| `query_copepod_knowledge_base` | core | knowledge | low | non | non | non | non |
| `query_ecotaxa` | ecotaxa | ecotaxa | high | oui | non | oui | oui |
| `query_ecotaxa_cache` | ecotaxa | ecotaxa | low | non | non | non | non |
| `run_graph` | data | file | medium | non | non | non | oui |
| `run_pandas` | data | file | medium | non | non | non | oui |
| `split_dataframe_by_zone` | geography | geography | medium | non | non | non | oui |
<!-- TOOL-INVENTORY:END -->

## Familles actives

| Famille | Tools | Nombre |
|---|---|---:|
| Fichier, analyse, graphe | `load_file`, `run_pandas`, `run_graph` | 3 |
| EcoTaxa | cache SQL, export de projet et export de samples | 5 |
| EcoPart | correspondance, aperçu, enrichissement distant | 3 |
| Amundsen CTD | disponibilité, profils appariés, enrichissement | 3 |
| Bio-ORACLE | enrichissement d'un DataFrame qualifié | 1 |
| OGSL | enrichissement CTD d'un DataFrame qualifié | 1 |
| Géographie | information, filtre multi-zone, découpage | 3 |
| RAG et taxonomie | recherche documentaire, `lookup_marine_taxonomy` | 2 |
| Livrable | export PDF | 1 |
| SQL optionnel | liste, aperçu, copie vers le workspace | 3 |
| **Total obligatoire** | | **22** |
| **Total avec SQL** | | **25** |

## Contrats communs

- Les entrées sont des schémas Pydantic stricts; les champs inconnus sont refusés.
- Chaque résultat porte un artefact `ToolResult` structuré en plus du texte affiché.
- Les opérations lourdes conservent leur confirmation explicite.
- Le dernier préflight lourd remplace l'ancien et lie la confirmation à un tour
  utilisateur ultérieur, à l'opération, au plan exact et à l'empreinte source;
  aucun regex de confirmation n'est appliqué au texte utilisateur.
- `run_pandas`, `run_graph`, le RAG et `lookup_marine_taxonomy` restent directement visibles.
- OpenAI Tool Search diffère seulement les familles EcoTaxa, EcoPart, géographie et enrichissement environnemental.
- Sans Tool Search, les 25 tools canoniques sont tous exposés; aucune règle lexicale ne bloque une capacité valide.

### États de résultat

| État | Signification |
|---|---|
| `success` | opération terminée avec un résultat exploitable |
| `empty` | opération valide, mais aucune ligne ne correspond |
| `blocked` | confirmation ou dépendance requise avant exécution |
| `error` | entrée, source ou exécution invalide; le diagnostic guide la récupération |
| `cancelled` | opération explicitement abandonnée |

Les erreurs de variable, table ou colonne doivent rester structurées. Elles
permettent à l’agent de récupérer une fois une dépendance dont l'identité est
déjà établie. Une ambiguïté entre plusieurs colonnes ou méthodes ne déclenche
pas une boucle de récupération : l'agent affiche les candidats et interroge
l'utilisateur.

### Préflight EcoPart

`enrich_ecotaxa_with_ecopart_remote(ecotaxa_project_id=<id>,
ecopart_project_id=None, confirmed=False)` résout d'abord le projet EcoPart sans
télécharger les données. La réponse affiche la paire résolue, les profils
EcoTaxa examinés et les profils EcoPart reconnus exactement; chaque liste est
bornée à huit noms puis résumée par `+N autres`. Après confirmation dans un
nouveau tour, l'appel `confirmed=True` doit reprendre les deux identifiants
résolus et la même table source.
