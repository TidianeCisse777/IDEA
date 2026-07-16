# Contrats red-team du harness — étape 1

**Date :** 15 juillet 2026
**Statut :** 3 dettes résolues; 4 contrats restent versionnés avec `xfail(strict=True)`.

Ces contrats décrivent le comportement attendu du futur harness. Ils restent volontairement `xfail` jusqu'à l'étape qui introduit le mécanisme exécutable correspondant. Une exécution diagnostique unique avec `pytest --runxfail` a confirmé que chacun échoue sur la faiblesse visée.

| Contrat | Preuve actuelle | Correction prévue |
|---|---|---|
| Un `project_id` nu n'autorise pas EcoTaxa | **Résolu en étape 3** : décision structurée, affinité persistante et garde pré-tool commun | Étape 3 — contrat devenu vert |
| Un résultat numérique d'un tool spécialisé ne force pas `run_pandas` | **Résolu en étape 4A** : règle canonique à trois branches, contrat devenu vert et smoke EcoTaxa sans pandas | Étape 4A — contrat devenu vert |
| Toute opération lourde possède une confirmation exécutable | **Fondation 2A terminée** : risque et confirmation sont déclarés pour les 62 tools ; l'autorisation liée aux arguments reste non exécutable | Étape 7 — `ApprovalGrant` |
| `run_graph` est fail-closed sans workflow graphique du tour | avec `loaded_skills=[]`, `run_graph("pass")` exécute le code | Étape 8 — automate lié au `turn_id` |
| Le Hub ne peut pas introduire un skill absent localement | un faux skill Hub `rogue` est chargé et enregistré | Étape 8 — allowlist locale avant accès Hub |
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

L'étape 4A est fermée : un nombre déjà fourni par un tool spécialisé est repris directement, une nouvelle valeur dérivée d'une table exige pandas et une valeur absente reste inconnue. Les prochaines tranches de l'étape 4 portent sur les déclencheurs graphiques (4B), puis les procédures OGSL et autres sources (4C).
