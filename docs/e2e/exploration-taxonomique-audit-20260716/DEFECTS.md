# Défauts observés

## TAX-001 — Le dossier est envoyé à `load_file` au lieu des deux CSV

- Tour : 1
- Gravité : majeure
- Prompt : demande de charger les deux fichiers NeoLabs présents dans `data/neolabs`.
- Appels observés : deux appels `load_file` avec `path=neolabs`.
- Résultat : le dossier n’est pas chargeable ; aucun fichier n’est actif.
- Impact : l’audit initial et tout le scénario taxonomique sont bloqués.
- Cause comportementale probable : l’agent n’a pas résolu le dossier en chemins de fichiers individuels.
- Correction de scénario : fournir explicitement `data/neolabs/neolabs_abundance.csv` et `data/neolabs/neolabs_sample.csv` au prochain tour.

## TAX-002 — Les outils graphiques étaient masqués au premier tour visuel

- Tour : 6
- Gravité : majeure
- Symptôme : après l’audit tabulaire d’un taxon, l’agent chargeait `graph_planner`, puis revenait à `run_pandas` sans appeler `graph_writer` ni `run_graph`.
- Cause : l’exposition déterministe attendait que `graph_planner` et `graph_writer` soient déjà chargés avant d’exposer `run_graph`. Le classifieur sémantique d’intention visuelle n’était appelé qu’après la tentative d’outil.
- Correction : l’intention visuelle est résolue avant le premier appel modèle et injectée directement dans le `TurnContext`. Le groupe `visualization` est alors disponible dès le début du tour, sans exposer les outils graphiques aux tours non visuels.
- Vérification E2E du 2026-07-16 : premier appel avec `visualization` et `run_graph` exposé ; séquence observée `load_skill(graph_planner)` → `load_skill(graph_writer)` → `run_graph(success)` ; artefact produit : `/graphs/66f54462245f.png`.
