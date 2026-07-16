# Dynamic Tool Filtering Design — étape 6

**Date :** 16 juillet 2026  
**Statut :** révision géographique validée, prête pour planification
**Portée :** réduire à au plus 15 les tools présentés au modèle à chaque appel, sans second modèle, sans embeddings et sans supprimer de tool du catalogue runtime.

## Problème

`build_tool_catalog()` construit 59 tools obligatoires, 62 lorsque le workspace SQL est configuré. `make_agent()` enregistre ce catalogue complet dans `create_agent()`. À chaque appel modèle, `_ContextMiddleware` masque déjà les familles de sources externes non autorisées, mais tous les tools locaux et tous les tools d'une source autorisée restent en compétition.

La conséquence la plus importante est EcoTaxa : une mention explicite peut rendre visibles 28 tools en même temps. Le coût des schémas augmente, les tools proches se concurrencent et la trajectoire dépend davantage du modèle.

## Décision

Étendre le filtrage existant avec un `PolicyEngine` déterministe qui sélectionne les tools depuis quatre catégories d'information :

1. la politique immuable du catalogue (`ToolPolicy`);
2. le `TurnContext` reconstruit au début de l'appel modèle;
3. le texte du dernier message utilisateur du tour;
4. les `ToolResult` réussis depuis ce message utilisateur.

Le moteur produit une allowlist ordonnée et expliquée. `_ContextMiddleware` applique cette allowlist avec `request.override(tools=...)`. Le même moteur est réutilisé dans `wrap_tool_call` et `awrap_tool_call` pour bloquer fail-closed un appel absent de l'allowlist courante.

Le mécanisme est réévalué à chaque itération ReAct. Un résultat réussi peut donc débloquer l'étape suivante sans exposer toute la chaîne dès le début.

### Révision géographique du 16 juillet 2026

Le routage géographique constitue une exception explicite au filtrage lexical. Le moteur ne tente plus de reconnaître les mots « zone », « baie », « Hudson », ni aucun nom ou type de région. Les deux tools géographiques génériques restent visibles à chaque appel modèle. Le modèle principal comprend sémantiquement l'intention et choisit de les appeler ou non; aucun classifieur supplémentaire n'est introduit.

Lorsqu'EcoTaxa est autorisé, son groupe `ecotaxa_geo_time` reste également visible. Les enrichissements EcoPart, Amundsen, Bio-ORACLE et OGSL partent d'un fichier actif et bénéficient donc directement du filtre géographique générique. SQL peut résoudre une zone immédiatement; le filtrage tabulaire devient exécutable après copie des données dans le workspace.

## Alignement avec les pratiques des autres frameworks

La solution reprend les mécanismes publics des frameworks actuels sans dépendre d'un provider :

- LangChain documente le filtrage contextuel dans `wrap_model_call` avec `request.override(tools=...)`;
- Google ADK expose un `ToolPredicate(tool, ReadonlyContext)` et des toolsets dynamiques;
- OpenAI Agents SDK recommande les namespaces et le chargement différé pour les grandes surfaces de tools;
- Anthropic recommande de garder 3 à 5 tools fréquents non différés puis de charger les autres à la demande;
- AWS AgentCore expose une allowlist `allowedTools` par invocation.

Les solutions de recherche de tools hébergées par OpenAI ou Anthropic ne sont pas retenues, car IDEA doit rester compatible avec plusieurs modèles OpenAI-compatible. `LLMToolSelectorMiddleware` n'est pas retenu, car il ajoute un second appel modèle. La sélection sémantique par embeddings n'est pas retenue, car elle ajoute un index, un service d'embeddings et une nouvelle source de variance pour seulement 62 tools.

## Modèle de politique

`ToolPolicy` reste l'unique source de vérité du catalogue. Il reçoit un champ supplémentaire :

```python
ToolExposureGroup = Literal[
    "core",
    "file_analysis",
    "visualization",
    "geography",
    "taxonomy",
    "deliverable",
    "enrichment_ecopart",
    "enrichment_amundsen",
    "enrichment_bio_oracle",
    "enrichment_ogsl",
    "sql_workspace",
    "ecotaxa_discovery",
    "ecotaxa_samples",
    "ecotaxa_geo_time",
    "ecotaxa_taxonomy",
    "ecotaxa_schema",
    "ecotaxa_audit",
    "ecotaxa_export",
    "hidden_legacy",
]

@dataclass(frozen=True)
class ToolPolicy:
    # champs existants inchangés
    exposure_group: ToolExposureGroup
```

Chaque tool runtime doit posséder exactement un groupe. Une absence ou un groupe inconnu fait échouer la validation du catalogue au démarrage. La classification vit dans `tools/tool_catalog.py`; aucun second registre de noms n'est créé ailleurs.

## Modèle de décision

Le moteur pur retourne une décision auditable :

```python
@dataclass(frozen=True)
class ToolExposureDecision:
    tool_names: tuple[str, ...]
    active_groups: tuple[ToolExposureGroup, ...]
    reasons: tuple[str, ...]
    dropped_tool_names: tuple[str, ...]
    source_decision: SourceDecision
    max_tools: int = 15

@dataclass(frozen=True)
class TurnSignals:
    latest_user_text: str
    enrichment_requested: bool
    requested_enrichment_sources: tuple[str, ...]
    ecotaxa_intents: tuple[str, ...]
    taxonomy_requested: bool
    deliverable_requested: bool
    successful_tools_this_turn: tuple[str, ...]
    successful_skills_this_turn: tuple[str, ...]
```

`TurnSignals` est calculé localement. Les signaux lexicaux ne donnent jamais une autorisation de source : ils choisissent seulement un sous-toolset à l'intérieur de la `SourceDecision` déjà autorisée. Un identifiant, un nom de projet ou le mot « échantillon » ne sélectionne jamais EcoTaxa. Aucun signal lexical géographique n'existe : `_GEOGRAPHY_PATTERN` est supprimé.

## Politique d'exposition

### Noyau permanent

Trois tools restent visibles à chaque appel :

- `load_file`;
- `load_skill`;
- `query_copepod_knowledge_base`.

Le noyau fournit les trois portes d'entrée : données utilisateur, procédure spécialisée et connaissance métier.

Les deux capacités géographiques `get_zone_info` et `filter_dataframe_by_zone` sont ajoutées systématiquement à ce noyau d'exposition. `get_zone_info` fonctionne sans dataset; `filter_dataframe_by_zone` reste visible mais retourne `blocked` si aucune table n'est active. Cette visibilité permanente délègue l'interprétation de l'intention au modèle principal sans ajouter d'appel modèle.

### Données locales

- `run_pandas` devient visible lorsqu'un dataset actif existe.
- `filter_dataframe_by_zone` et `get_zone_info` restent visibles à chaque appel, indépendamment des mots employés par l'utilisateur.
- `lookup_marine_taxonomy` devient visible pour une demande taxonomique.
- `export_deliverable` devient visible seulement après le chargement réussi de `deliverable_writer` dans le tour courant.
- `run_graph` devient visible seulement après les chargements réussis de `graph_planner`, puis `graph_writer`, dans le tour courant. La garde 4B.1 reste la défense d'exécution.

### Enrichissements externes

EcoPart, Amundsen CTD, Bio-ORACLE et OGSL ne sont plus des familles de navigation dans la surface LLM normale. Une famille devient visible uniquement si les trois conditions suivantes sont satisfaites :

1. au moins un dataset est chargé;
2. le dernier message demande explicitement un enrichissement;
3. la source est nommée explicitement ou reste autorisée par une affinité née d'une demande d'enrichissement explicite.

Un seul tool canonique est alors exposé :

| Source | Tool canonique |
|---|---|
| EcoPart | `enrich_ecotaxa_with_ecopart_remote` |
| Amundsen CTD | `enrich_with_amundsen_ctd` |
| Bio-ORACLE | `enrich_with_bio_oracle` |
| OGSL | `enrich_with_ogsl` |

Tous les autres tools de ces familles reçoivent `exposure_group="hidden_legacy"`. Ils restent enregistrés, testés et exécutables depuis du code interne, mais ne sont jamais proposés au modèle par le `PolicyEngine` de l'étape 6. Leur suppression éventuelle est un chantier séparé.

La liste fermée des tools `hidden_legacy` est :

- EcoPart : `list_ecopart_samples`, `preview_ecopart_sample`, `find_ecopart_project_for_ecotaxa`, `query_ecopart`, `join_ecotaxa_ecopart`, `audit_ecotaxa_ecopart_join`;
- Amundsen CTD : `list_amundsen_datasets`, `preview_amundsen_profile`, `find_amundsen_data_for_table`, `enrich_loaded_table_with_amundsen_ctd`, `query_amundsen_ctd`;
- Bio-ORACLE : `list_bio_oracle_datasets`, `preview_bio_oracle_point`, `query_bio_oracle_zones`, `find_bio_oracle_data_for_table`, `couple_zooplankton_bio_oracle`, `query_bio_oracle`;
- OGSL : `query_ogsl`.

Si la source est nommée sans verbe d'enrichissement, aucun tool de cette source n'est exposé. L'agent doit demander si l'utilisateur souhaite enrichir le ou les fichiers chargés. Si aucun dataset n'est chargé, le tool d'enrichissement reste caché et l'agent demande un fichier.

### EcoTaxa

EcoTaxa reste une source riche. Ses 28 tools sont répartis en sept groupes :

| Groupe | Tools |
|---|---|
| Découverte | `list_ecotaxa_projects`, `find_ecotaxa_projects`, `list_ecotaxa_campaigns`, `preview_ecotaxa_project`, `get_ecotaxa_cache_status` |
| Samples | `list_ecotaxa_project_samples`, `get_ecotaxa_sample`, `summarize_ecotaxa_sample`, `summarize_ecotaxa_samples`, `summarize_ecotaxa_sample_deployment` |
| Zone/période | `find_ecotaxa_samples_in_region`, `group_ecotaxa_samples_by_year`, `find_ecotaxa_projects_in_region`, `group_ecotaxa_project_samples_by_region`, `rank_ecotaxa_samples_by_region` |
| Taxonomie | `search_ecotaxa_taxa`, `count_ecotaxa_taxa`, `find_ecotaxa_observations` |
| Schéma | `inspect_ecotaxa_project_schema`, `inspect_ecotaxa_column`, `compare_ecotaxa_projects` |
| Audit | `audit_ecotaxa_availability`, `audit_ecotaxa_spatial_coverage`, `summarize_ecotaxa_project`, `summarize_ecotaxa_projects` |
| Export | `query_ecotaxa`, `query_ecotaxa_sample`, `export_ecotaxa_samples` |

EcoTaxa doit être autorisé par `SourceDecision` avant tout choix de groupe. Ensuite :

- le groupe Zone/période est toujours exposé dès qu'EcoTaxa est autorisé;
- une intention explicite sélectionne au plus un autre groupe EcoTaxa;
- sans autre intention reconnue, le groupe Découverte accompagne Zone/période;
- le groupe Export apparaît seulement pour « exporte », « télécharge », « charge les données », ou lors d'un suivi d'export après une sélection EcoTaxa réussie;
- au plus deux groupes EcoTaxa peuvent être actifs au même appel, dont Zone/période toujours présent;
- les dépendances nécessaires sont ajoutées explicitement, jamais par élargissement à toute la famille.

Le maximum EcoTaxa reste exactement 15 : noyau permanent (3) + géographie générique (2) + Zone/période (5) + un autre groupe (5 au maximum).

Une demande multifonction qui nécessiterait plus de deux groupes doit être traitée par étapes ReAct : le résultat du premier groupe débloque le groupe suivant au prochain appel modèle.

### Workspace SQL optionnel

Les tools SQL n'existent dans le catalogue runtime que lorsque `DATABASE_URL` est résolvable. Ils restent cachés tant que SQL n'est pas la source explicitement autorisée.

- `list_sql_tables` et `preview_sql_table` deviennent visibles pour une demande d'exploration SQL;
- `copy_sql_query_to_workspace` devient visible seulement lorsque l'utilisateur demande explicitement de copier ou d'analyser localement le résultat d'une requête read-only;
- un suivi conserve l'affinité SQL existante, comme les autres sources;
- l'absence de configuration ne doit jamais produire un nom de tool fantôme dans la décision.

## Ordre de filtrage

La préparation d'une requête suit cet ordre :

```text
catalogue runtime complet
→ disponibilité de configuration (SQL, sources)
→ SourceDecision existante
→ TurnContext
→ TurnSignals non géographiques du tour courant
→ groupes d'exposition actifs
→ fermeture des dépendances obligatoires
→ validation du plafond de 15
→ request.override(tools=allowlist)
```

Le filtre de source reste propriétaire des autorisations externes. Le `PolicyEngine` ne peut jamais réintroduire un tool retiré par `SourceDecision`.

## Plafond et comportement fail-closed

Le plafond est une validation de politique, pas une troncature arbitraire. Une combinaison valide doit produire au plus 15 tools, noyau compris.

Si une configuration produit plus de 15 tools :

1. l'audit enregistre `policy_overflow=true` et la liste complète;
2. le modèle reçoit seulement le noyau permanent et, si EcoTaxa est autorisé, le groupe Découverte;
3. aucun tool supprimé par ce fallback n'est exécutable;
4. les tests de matrice doivent empêcher cette configuration d'atteindre la branche principale.

L'ordre des tools est stable : noyau, outils locaux, groupe de source, dépendances de workflow. La même entrée doit produire la même liste et les mêmes raisons.

## Garde d'exécution

La visibilité et l'autorisation sont appliquées par la même décision. `wrap_tool_call` et `awrap_tool_call` reconstruisent ou récupèrent la décision du tour et bloquent un tool absent de `tool_names` avec :

```python
ToolResult(
    status="blocked",
    summary="Action indisponible dans l'étape courante du workflow.",
    provenance={"source": "tool_exposure_policy"},
    method="deterministic tool exposure guard",
)
```

Le message n'expose pas les noms internes à l'utilisateur final. Les gardes de source, d'identifiant et de graphique continuent de s'appliquer; le filtre d'exposition ne les remplace pas.

## Observabilité

L'audit de contexte et le replay ajoutent pour chaque appel modèle :

- `tools_before_policy`;
- `tools_after_source_scope`;
- `tools_exposed`;
- `tool_exposure_count`;
- `tool_exposure_groups`;
- `tool_exposure_reasons`;
- `tools_dropped`;
- `policy_overflow`;
- `approx_tokens_tool_schemas_before`;
- `approx_tokens_tool_schemas_after`;
- `approx_tokens_tool_schemas_saved`.

Ces champs sont normalisés dans le replay offline afin de rester identiques run-à-run.

## Compatibilité sync/async

Le moteur de décision est une fonction pure commune. `wrap_model_call` et `awrap_model_call` l'appellent par la même méthode `_prepare_request`. Les gardes `wrap_tool_call` et `awrap_tool_call` utilisent la même allowlist et produisent le même `ToolResult` de blocage.

Aucun accès réseau, aucun appel modèle et aucun embedding n'est effectué pour sélectionner les tools.

## Stratégie de tests

### Contrats unitaires

- chaque tool possède un `exposure_group` valide;
- le noyau contient exactement les trois tools décidés;
- chaque matrice d'état/intention reste à 15 tools ou moins;
- la décision est stable pour des entrées identiques;
- un tool masqué par la source ne peut pas être réintroduit;
- un overflow déclenche le fallback minimal;
- les chemins sync et async sont identiques.
- les deux tools géographiques génériques sont visibles pour toute formulation, avec ou sans nom de zone;
- le texte « baie d'Hudson » et un texte sans aucun terme géographique produisent la même disponibilité géographique;

### Contrats d'enrichissement

Pour chacune des quatre sources :

- source seule → aucun tool de la famille;
- enrichissement explicite sans fichier → aucun tool d'enrichissement;
- fichier + enrichissement explicite → un seul tool canonique;
- tools `list_*`, `preview_*`, `find_*`, `query_*`, variantes legacy et audits restent cachés;
- un appel forcé d'un tool caché retourne `blocked`.

### Contrats EcoTaxa

- EcoTaxa non autorisé → zéro tool EcoTaxa;
- mention EcoTaxa sans intention reconnue → noyau + Zone/période + Découverte;
- une intention de taxonomie, schéma, audit, samples ou export sélectionne le groupe attendu en plus de Zone/période;
- un suivi fondé sur l'affinité EcoTaxa conserve la bonne famille;
- un identifiant nu n'active jamais EcoTaxa;
- une sélection/extraction réussie débloque la prochaine étape sans exposer les 28 tools;
- chaque trajectoire reste sous le plafond.

### Régressions

- `SC-LAB`, `SC-ENRICH` et `SC-ECOTAXA` restent à 100 % aux niveaux 1 et 2 offline;
- les tests de source, `TurnContext`, graph workflow, skills et `ToolResult` restent verts;
- le benchmark live est explicite, N ≥ 5 par scénario, jamais lancé par la CI;
- le rapport live mesure succès, tool manquant, tool interdit, tokens de schémas, appels, latence et variance.

## Critères d'acceptation

1. Chaque appel modèle expose au plus 15 tools; alerte d'observabilité à partir de 12.
2. Le catalogue runtime reste à 59/62 tools et conserve ses schémas stricts.
3. Aucun second modèle, embedding ou mécanisme provider-specific n'est requis.
4. EcoPart, Amundsen CTD, Bio-ORACLE et OGSL n'exposent qu'un enrichissement canonique après une demande explicite sur un fichier chargé.
5. EcoTaxa n'expose jamais ses 28 tools simultanément.
6. Un tool non visible est bloqué avant exécution.
7. Les tokens de schémas avant/après sont mesurés pour chaque appel.
8. Les trois scénarios offline ne régressent pas; le benchmark live N ≥ 5 confirme qu'aucun tool nécessaire n'est masqué.
9. Aucun regex, liste de noms de zones, registre lexical ou appel de classification ne décide de la visibilité géographique.

## Hors portée

- suppression physique des tools legacy;
- recherche de tools hébergée par OpenAI ou Anthropic;
- `LLMToolSelectorMiddleware` ou classifieur supplémentaire;
- sélection par embeddings;
- confirmations exécutables de l'étape 7;
- réduction du system prompt de l'étape 10;
- modification des calculs scientifiques, des formats `ToolResult` ou des clients de sources.
