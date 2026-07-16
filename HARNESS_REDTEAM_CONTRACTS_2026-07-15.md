# Contrats red-team du harness — étape 1

**Date :** 15 juillet 2026
**Statut :** 5 dettes résolues (dont l'allowlist skills fail-closed en étape 8); 2 contrats restent versionnés avec `xfail(strict=True)` (confirmation exécutable étape 7, budget fixe étapes 6/10); 1 dette comportementale 4A.1 nouvellement observée reste à transformer en contrat rouge.

Ces contrats décrivent le comportement attendu du futur harness. Ils restent volontairement `xfail` jusqu'à l'étape qui introduit le mécanisme exécutable correspondant. Une exécution diagnostique unique avec `pytest --runxfail` a confirmé que chacun échoue sur la faiblesse visée.

| Contrat | Preuve actuelle | Correction prévue |
|---|---|---|
| Un `project_id` nu n'autorise pas EcoTaxa | **Résolu en étape 3** : décision structurée, affinité persistante et garde pré-tool commun | Étape 3 — contrat devenu vert |
| Un résultat numérique d'un tool spécialisé ne force pas `run_pandas` | **Résolu en étape 4A** : règle canonique à trois branches, contrat devenu vert et smoke EcoTaxa sans pandas | Étape 4A — contrat devenu vert |
| Une nouvelle agrégation sur les lignes d'un fichier passe par une exécution contrôlée | **Ouvert en 4A.1** : le smoke agent tableau→carte a produit un comptage par station depuis le résultat de `load_file` sans `run_pandas`; la campagne a terminé `exit 1` sur cette assertion | Étape 4A.1 — écrire le contrat rouge, imposer la règle dans le harness, puis retester l'agent |
| Toute opération lourde possède une confirmation exécutable | **Fondation 2A terminée** : risque et confirmation sont déclarés pour les 62 tools ; l'autorisation liée aux arguments reste non exécutable | Étape 7 — `ApprovalGrant` |
| `run_graph` est fail-closed sans workflow graphique du tour | **Résolu en 4B.1** : garde d'intention typée, ToolResults du tour courant et précondition writer dans `run_graph` | Étape 4B.1 — contrat devenu vert |
| Le Hub ne peut pas introduire un skill absent localement | **Résolu en étape 8** : `load_skill` valide l'allowlist locale avant tout accès Hub ; le contrat rouge devient vert et le happy path graphique reste validé sur l'agent réel | Étape 8 — contrat devenu vert |
| Le coût fixe reste sous 40 % du contexte | 33 290 tokens mesurés pour un plafond de 16 000 | Étapes 6 puis 10 — filtrage dynamique et réduction du prompt |
| La documentation correspond au catalogue runtime | **Résolu en 2A.1** : inventaire généré, trois entrées ajoutées, totaux 59/62 et contrôle `--check` | Étape 2A.1 — contrat devenu vert |

## Fichiers de contrats

- `tests/harness_redteam/test_source_and_prompt_contracts.py`
- `tests/harness_redteam/test_policy_enforcement_contracts.py`
- `tests/harness_redteam/test_budget_and_inventory_contracts.py`

## Règle de migration

Chaque correction doit suivre la séquence suivante :

1. implémenter le mécanisme dans l'étape propriétaire ;
2. retirer uniquement le marqueur `xfail` du contrat concerné ;
3. vérifier le contrat puis comparer la baseline offline/live ;
4. conserver le changement seulement sans régression des scénarios de référence.

La branche 4A « nombre spécialisé → reprise directe » et l'étape graphique 4B.1 sont fermées. La branche « nouvelle agrégation de table → pandas » reste ouverte sous 4A.1 après le smoke réel. La tranche 4C (contradiction OGSL de `environmental_join.md`) est fermée le 16 juillet 2026 : un contrat rouge (`test_ogsl_enrichment_has_a_single_deterministic_rule`) interdit de déclarer deux outils « standard », et le smoke réel `scripts/dev/ogsl_routing_smoke.py` valide 2/2 le choix par clé de jointure (station/temps → `query_ogsl`, lat/lon → `enrich_with_ogsl`).
