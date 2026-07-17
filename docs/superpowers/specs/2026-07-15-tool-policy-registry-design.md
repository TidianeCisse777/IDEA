# Design — registre déclaratif `ToolPolicy` (étape 2A)

**Date :** 15 juillet 2026  
**Statut :** approuvé en conversation  
**Portée :** registre, validation, documentation et schémas d'entrée des tools. `ToolResult` reste hors portée jusqu'à l'étape 2B.

## Problème

Le runtime construit aujourd'hui 59 tools obligatoires et 3 tools SQL optionnels depuis `tools/tool_catalog.py`. Ce catalogue valide leur présentation UI, mais ne porte pas les politiques nécessaires au control plane : risque, source, confirmation, mutation, coût ou workflow autorisé.

Ces informations sont dispersées entre le system prompt, les docstrings, les implémentations et `TOOLS.md`. La baseline et les contrats red-team montrent les conséquences : cinq opérations lourdes sans confirmation uniforme, un inventaire documentaire obsolète et aucune API centrale permettant au futur `PolicyEngine` de décider.

## Décision

Étendre `tools/tool_catalog.py`; ne pas créer un second registre dans un autre module.

Deux mappings adjacents restent temporairement distincts par responsabilité :

- `TOOL_PRESENTATION` conserve les libellés et éléments UI existants ;
- `TOOL_POLICIES` devient l'unique source de vérité des politiques exécutables.

`validate_catalog()` impose une égalité stricte entre tools runtime, présentations et politiques, en tenant compte des trois tools SQL optionnels. `ToolCatalog` expose les deux vues par `presentation(name)` et `policy(name)`. Une politique absente, orpheline ou invalide bloque la construction de l'agent.

Cette approche est retenue plutôt qu'une fusion immédiate dans `ToolDefinition`, afin de limiter la réécriture des 62 présentations déjà utilisées par FastAPI SSE. Une fusion interne pourra être mécanique plus tard sans changer l'API publique.

## Modèle `ToolPolicy`

Dataclass immuable avec les champs suivants :

| Champ | Type | Sens |
|---|---|---|
| `family` | `str` | Famille fonctionnelle, identique à la présentation |
| `source` | enum/`Literal` | `file`, `ecotaxa`, `ecopart`, `amundsen`, `bio_oracle`, `ogsl`, `sql`, `geography`, `knowledge`, `taxonomy`, `skill`, `deliverable` |
| `risk` | `low`, `medium`, `high` | Niveau de contrôle requis |
| `read_only` | `bool` | Aucun dataset, fichier, artefact ou état de session créé/modifié |
| `mutates_session` | `bool` | Écrit un dataset, une sélection, un skill chargé ou une métadonnée de session |
| `remote_io` | `bool` | Dépend d'un service ou stockage distant |
| `expensive` | `bool` | Peut entraîner une latence, un volume ou un coût significatif |
| `reversible` | `bool` | Les effets locaux peuvent être supprimés sans modifier la source distante |
| `requires_confirmation` | `bool` | Une approbation exécutable sera exigée à l'étape 7 |
| `required_skill` | `str | None` | Skill procédural exigé avant l'appel, s'il existe |
| `allowed_workflows` | `tuple[str, ...]` | Workflows dans lesquels le tool peut apparaître |
| `max_calls_per_turn` | `int` | Budget de boucle futur, strictement positif |
| `result_schema` | `str` | `legacy_text` pendant 2A; remplacé famille par famille en 2B |

### Invariants

- `family` doit correspondre exactement à `ToolPresentation.family`.
- `requires_confirmation=True` implique `risk="high"` ou une exemption explicite documentée.
- `read_only=True` interdit `mutates_session=True`.
- `max_calls_per_turn >= 1`.
- `required_skill`, s'il existe, doit appartenir à l'allowlist locale découverte.
- Une opération marquée `expensive` ne devient pas automatiquement confirmée : la confirmation reste une décision déclarative explicite.
- `result_schema="legacy_text"` est la seule valeur autorisée avant 2B, afin de rendre la dette visible sans prétendre que les retours sont déjà structurés.

## Classification initiale

La classification est déclarée, jamais déduite d'un préfixe au moment de l'exécution.

- Les opérations `list`, `preview`, `find`, `inspect`, `count`, `summarize`, `audit`, géographie et RAG sont généralement `low` ou `medium`.
- Les extractions complètes, enrichissements distants, copies SQL larges et exports de livrables sont `high` lorsqu'ils exigent une confirmation.
- `load_file`, les requêtes qui matérialisent un DataFrame, `run_pandas`, `run_graph`, `load_skill`, les sélections et les exports déclarent `mutates_session=True` ou une création d'artefact.
- Les tools EcoTaxa, EcoPart, Amundsen, Bio-ORACLE et OGSL déclarent `remote_io=True`, sauf opération prouvée entièrement locale/cache si cette distinction est explicitement documentée.
- Les tools SQL sont optionnels mais possèdent toujours une politique dans le registre.

Les exceptions sont écrites tool par tool dans `TOOL_POLICIES`; aucun défaut permissif n'est utilisé pour compléter silencieusement un tool nouveau.

## API du catalogue

`ToolCatalog` ajoute :

```python
policies: Mapping[str, ToolPolicy]

def policy(self, name: str) -> ToolPolicy | None: ...
```

La construction retourne des `MappingProxyType` immuables. Les consommateurs existants de `tools`, `names`, `presentations` et `presentation()` restent compatibles.

Le futur `PolicyEngine` et le futur `ToolGuardMiddleware` consommeront uniquement `catalog.policy(name)`; ils ne parseront ni le prompt ni les docstrings.

## Génération documentaire

Un générateur déterministe produit l'inventaire tabulaire de `TOOLS.md` depuis `ToolCatalog` : nom, famille, source, risque, confirmation, I/O distante et caractère optionnel.

La narration métier existante reste manuelle. La section générée est délimitée par des marqueurs stables pour éviter de réécrire le reste du document. Une commande `--check` compare la sortie attendue au fichier et échoue en cas de divergence.

Le contrat red-team de parité devient vert quand :

- les trois tools manquants sont présents ;
- les totaux sont 59 obligatoires et 62 avec SQL ;
- aucune entrée runtime/politique/documentation ne diverge.

## Sous-tranche 2A.1 — registre et documentation

1. Ajouter `ToolPolicy`, ses types et ses invariants.
2. Déclarer les 62 politiques, y compris SQL optionnel.
3. Étendre `validate_catalog()` et `ToolCatalog`.
4. Ajouter le générateur et synchroniser `TOOLS.md`.
5. Rendre vert le contrat red-team d'inventaire.

Cette sous-tranche ne filtre aucun tool et ne change pas le routage du modèle.

## Sous-tranche 2A.2 — schémas d'entrée stricts

1. Auditer les `args_schema` Pydantic de chaque tool.
2. Refuser les arguments inconnus avec `extra="forbid"`.
3. Supprimer les identifiants et paramètres dangereux implicites.
4. Vérifier au démarrage que chaque schéma respecte le contrat strict.
5. Migrer famille par famille pour conserver la baseline.

La présence d'un champ `confirmed` dans certains tools reste transitoire. L'étape 7 remplacera cette convention fragmentée par des `ApprovalGrant` liés au nom du tool et au hash canonique des arguments.

## Tests et gates

### 2A.1

- parité exacte runtime ↔ présentation ↔ politique ;
- lookup immuable et compatible de `ToolCatalog.policy()` ;
- invariants fail-closed sur politiques invalides ;
- métadonnées explicites des cinq opérations lourdes ;
- génération déterministe et `--check` de `TOOLS.md` ;
- catalogue 59 sans SQL et 62 avec SQL.

### 2A.2

- schémas Pydantic `extra="forbid"` ;
- aucun identifiant dangereux par défaut ;
- validation de démarrage ;
- non-régression par famille sur la baseline offline.

Les vérifications restent ciblées pendant le développement. Le benchmark live n'est pas relancé avant la fin de 2A et seulement si les trajectoires offline restent stables.

## Gestion des erreurs

- Politique manquante : `ValueError("Tool catalog missing policy: ...")`.
- Politique orpheline : `ValueError("Tool catalog orphan policy: ...")`.
- Invariant incohérent : erreur nommant le tool et le champ fautif.
- Documentation divergente en `--check` : sortie non nulle avec résumé des différences, sans réécriture.

Le système échoue au démarrage plutôt que d'appliquer une politique par défaut permissive.

## Hors portée

- Filtrage dynamique des tools : étape 6.
- Exécution des confirmations : étape 7.
- Automate de skills et workflow graphique : étape 8.
- `ToolResult` structuré : étape 2B.
- Réduction du system prompt : étape 10.

## Critères de réussite

- Les 59/62 tools possèdent une politique explicite et validée.
- Le runtime existant continue de construire le même ensemble de tools.
- `TOOLS.md` est synchronisé par le générateur.
- Le contrat red-team d'inventaire devient vert.
- Aucun comportement de routage n'est modifié pendant 2A.
