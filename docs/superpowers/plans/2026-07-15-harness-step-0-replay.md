# Étape 0 — Harness de replay local

**Objectif :** ajouter une mesure reproductible des trajectoires de l'agent sans modifier son runtime, avec une piste offline déterministe en CI et une commande live explicitement déclenchée.

## Architecture retenue

- `evals/scenarios/harness_reference.json` porte les trois conversations figées et leurs critères de niveau 1/2.
- `evals/replay_harness.py` contient le schéma du rapport, le chargeur de scénarios, les graders déterministes, l'isolation d'environnement et deux exécuteurs interchangeables.
- L'exécuteur offline rejoue des observations scriptées versionnées. Il teste le contrat du harness, pas la qualité d'un modèle réel.
- L'exécuteur live importe `agent.py` seulement après activation d'un répertoire de session jetable, force le tracing à `false`, utilise un thread et un utilisateur uniques, puis capture les appels de tools et l'état actif. Il n'est jamais appelé par pytest.
- `evals/baseline_offline_2026-07-15.json` est le rapport déterministe de référence. Une baseline live datée exige `--lane live --runs 5` au minimum.

## Tâche 1 — Contrat et scénarios, en TDD

**Créer :** `tests/test_replay_harness.py`

Tests rouges :

1. les trois IDs obligatoires sont chargés et `SC-LAB` contient sept tours ;
2. le rapport normalisé est identique sur deux replays offline ;
3. les métriques calculent le taux d'utilisation du bon fichier et les tools moyens/tour ;
4. les graders signalent un tool interdit et une source incorrecte ;
5. le contexte d'isolation coupe LangSmith et restaure l'environnement ;
6. la piste live refuse moins de cinq runs ;
7. le JSON du rapport est sérialisable et ne contient aucun secret.

## Tâche 2 — Implémentation minimale

**Créer :** `evals/replay_harness.py`, `evals/scenarios/harness_reference.json`

Implémenter seulement les structures et comportements exigés par les tests. Les champs temporels et identifiants variables restent dans le rapport brut, mais `normalized()` les retire pour les comparaisons exactes.

## Tâche 3 — Exécuteur live sans changement runtime

Ajouter un callback LangChain local pour capturer les tools présentés à chaque appel modèle. Extraire les appels depuis les nouveaux messages LangGraph, les usages depuis `usage_metadata`, les coûts seulement lorsqu'ils sont fournis, et la source/table depuis `tools.session_store.default_store`.

La CLI doit :

- refuser `--lane live --runs < 5` ;
- refuser le live sans clé modèle ;
- écrire dans un chemin explicitement fourni ;
- annoter modèle, lane, nombre de runs et caractère externe des dépendances.

## Tâche 4 — Baseline et vérification

Générer la baseline offline, la régénérer une seconde fois et comparer les versions normalisées. Exécuter les tests ciblés, puis les tests existants directement liés au contexte, au catalogue et au routage. Le benchmark live n'est lancé que si la configuration modèle est disponible ; son absence ne doit jamais être masquée par une baseline offline.
