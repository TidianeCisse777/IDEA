# IDEA NeoLab — instructions aux agents de développement

## Objectif et références

Répondre en français par défaut. Adapter IDEA Hawaii aux besoins NeoLab,
Université Laval. La priorité est la fiabilité des use cases, pas le nombre
d'outils migrés. Lire le README, [ROADMAP.md](ROADMAP.md),
[ARCHITECTURE.md](ARCHITECTURE.md) et `docs/NEOLAB_MIGRATION.md` avant de
travailler. La cartographie décrit le code actuel et indique les modules et
tests à consulter pour chaque intervention.

`ROADMAP.md` est la source de vérité pour les phases, échéances, livrables,
critères de sortie et statuts. Au début d’un travail, identifier la phase et le
résultat attendu concernés. Après chaque travail réellement exécuté, mettre à
jour le statut et le journal du plan avec les preuves, échecs et limites
observés. Ne jamais déclarer une phase terminée tant que son critère de réussite
n’est pas vérifié. Garder le suivi GitHub Project synchronisé avec ce fichier.

Le socle actif est celui de Hawaii. L'ancien projet est une archive locale dans
`../IDEA-archive-20260911`, à consulter sans la modifier. Ne pas recopier son
runtime, son prompt, son système de contexte ou son stockage de DataFrames en
bloc. Son `AGENTS.md` décrit l'ancien projet : il ne définit pas l'architecture
de ce dépôt. Si l'archive est absente, signaler la dépendance manquante.

## Architecture à respecter

- `langgraph/agents/terminal_agent.py` : modèle et assemblage des outils.
- `langgraph/idea_graph/` : graphe, état, contexte et checkpoints.
- `langgraph/tools/persistent_terminal.py` : interface avec l'exécution.
- `sandbox_service/` et `interpreter_kernel/` : environnement et noyau Python.
- `openwebui/` : interface et transport ; `assistants/` : spécialisation.
- `litellm/`, `example.env`, `langgraph/idea_config.py` : raccordement modèle.

Vérifier le runtime effectivement configuré : le fallback Python de
`IDEA_AGENT_RUNTIME` est `manual`, tandis que `example.env` choisit `langgraph`.
Les variables vivantes du noyau, les fichiers et les checkpoints sont trois
formes de persistance distinctes. Ne pas promettre la récupération automatique
d'un DataFrame après perte du noyau sans preuve d'un mécanisme testé.

## Méthode d'intégration

1. Identifier le use case et son résultat attendu avant de modifier le code.
2. Établir les fixtures et tests du contrat métier avant de porter un outil.
3. Récupérer le minimum utile de l'archive : client, calcul ou jointure validée,
   documentation métier et tests adaptés. Vérifier ses dépendances.
4. Intégrer dans les points d'extension Hawaii ; ne pas créer un second agent
   conversationnel ou réintroduire les anciens mécanismes sans décision motivée.
5. Exécuter les tests ciblés puis le scénario réel dans l'interface, avec les
   suivis de conversation. Rejouer les use cases déjà validés qui sont affectés.
6. Consigner les preuves et limites. Un test unitaire réussi ne suffit pas à
   déclarer un use case conversationnel validé.

Conserver les opérations scientifiques critiques dans du code vérifiable :
jointures, unités, concentrations et enrichissements. Documenter pour chaque
outil ses entrées, sorties, provenance, erreurs et effets sur les fichiers.
Les données volumineuses circulent par fichiers et références, pas par texte LLM.

## Contraintes NeoLab à préserver lors du portage

- Ne pas inventer valeurs, identifiants, colonnes ou provenance.
- Préserver les données brutes ; rendre explicites grain, clés et transformations.
- Demander une clarification si un choix change le sens scientifique du résultat.
- Conserver les confirmations des téléchargements ou calculs lourds concernés.
- Distinguer description des résultats et interprétation biologique, réservée
  au chercheur pour les use cases copépodes.
- Porter et tester les conventions de confiance/incertitude des graphiques métier.

Ne jamais afficher ou commiter de secrets. Ne pas recopier le `.env` de l'archive
en bloc : adapter uniquement les paramètres nécessaires via la configuration
locale. Préserver les modifications non commitées de l'utilisateur. Ne pas
publier ni pousser les changements sans demande. Les étapes futures décrites
dans le plan ne constituent pas une instruction de tout implémenter d'un coup.
