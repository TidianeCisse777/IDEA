# Bonnes pratiques — IDEA

Ce guide rassemble les règles utiles pour exploiter l’agent et faire évoluer son
code sans rendre le contexte plus rigide ou plus bruyant.

## Formuler une demande exploitable

Une bonne demande précise autant que possible :

1. le livrable attendu : table, calcul, graphique, carte ou export;
2. la population et la période visées;
3. le grain attendu : sample, profil, déploiement, station ou agrégat;
4. les seuils ou règles métier modifiables;
5. le fichier ou DataFrame de départ, seulement s’il est connu avec certitude.

Si le bon DataFrame n’est pas connu, il vaut mieux décrire le résultat attendu
que forcer une ressource. L’agent doit comparer la demande aux capacités réelles
des DataFrames disponibles.

## Choisir et qualifier un DataFrame

Avant un calcul, une analyse ou un graphique :

1. traduire la demande en critères de succès;
2. nommer dans le plan le ou les DataFrames candidats exacts;
3. vérifier le grain, les colonnes requises, la portée et les clés;
4. contrôler les doublons et la nullité des champs pertinents;
5. utiliser un appel `run_pandas` ciblé qui retourne un petit dictionnaire de
   qualification, sans persister un nouveau DataFrame;
6. attendre la preuve, puis accepter ou refuser le candidat;
7. si le candidat échoue, choisir un autre DataFrame ou récupérer la dépendance
   manquante avant de reprendre le plan.

Une qualification encore valide pour la même demande peut être réutilisée. Le
« DataFrame actif » n’est jamais une preuve qu’il est approprié.

## Utiliser le RAG au bon moment

Le RAG répond aux questions de définition, protocole, méthode métier et contrat
de données. Il n’est pas obligatoire lorsqu’un fichier ou un tool fournit déjà
directement la réponse factuelle.

Lorsqu’un appel RAG est nécessaire, il est effectué seul. L’agent attend le
résultat avant de calculer, d’interroger une autre source ou de répondre. Cette
barrière évite de bâtir un plan sur une hypothèse que le document devait valider.

## Choisir les sources sans les bloquer

La décision de source sert à ordonner les options et à rappeler les ressources
probables. Elle ne masque pas une capacité et n’interdit pas l’enrichissement.
Une demande peut partir d’un fichier local, interroger EcoTaxa, puis être enrichie
avec EcoPart ou une source environnementale si cela répond au besoin.

Le bon critère est la capacité de la ressource à fournir le grain, les colonnes
et la portée demandés, pas la dernière source utilisée.

## Calculs et graphiques

- Effectuer les transformations et chiffres avec `run_pandas`.
- Utiliser `run_graph` seulement après qualification du DataFrame.
- Ne pas utiliser `print` pour transmettre un résultat : assigner une valeur
  compacte à `result`.
- Ne persister que les résultats qui doivent être réutilisés.
- Conserver les identifiants et la provenance nécessaires pour auditer une
  jointure ou un filtrage.
- Signaler les écarts de grain, les doublons et les valeurs manquantes qui
  changent la portée du résultat.

## Opérations coûteuses

La confirmation doit porter sur l’action concrète : projet, volume, période et
source. Une confirmation ancienne ou vague ne doit pas autoriser une autre
opération. Après confirmation, l’agent exécute l’action sans redemander tant que
ses paramètres significatifs n’ont pas changé.

## Reprendre après une erreur

Une variable, table ou colonne manquante ne termine pas automatiquement
l’analyse. L’agent doit :

1. lire l’erreur structurée;
2. comparer le manque avec l’inventaire de ressources;
3. retrouver la table, le DataFrame ou la colonne avec les tools existants;
4. reprendre l’étape échouée;
5. demander une information à l’utilisateur seulement si aucune récupération
   accessible ne permet de progresser.

## Ajouter ou modifier un tool

- N’ajouter qu’une fonction canonique qui apporte une capacité distincte.
- Donner au `@tool` une docstring décisionnelle : quand l’utiliser, ses entrées,
  son grain et ce qu’il retourne.
- Employer des schémas Pydantic stricts et un résultat structuré cohérent.
- Retourner le tool depuis la factory active et l’inclure dans le catalogue
  généré.
- Ajouter une confirmation s’il télécharge beaucoup de données ou déclenche un
  calcul lourd.
- Ne jamais inclure de credential dans le code, les erreurs ou les exemples.
- Retirer les anciens chemins d’import et factories lorsqu’un remplacement est
  validé, afin d’éviter deux vérités concurrentes.

## Garder le contexte lisible

L’ordre de contexte reste stable : instructions permanentes, historique utile,
contexte applicatif du tour, demande originale, puis observations ReAct.

- Les fichiers importés sont des ancres durables et restent détaillés.
- Les exports, résultats de cache et enrichissements restent visibles tant
  qu’ils peuvent servir de point de départ.
- Les cartes de DataFrames doivent être bornées et centrées sur les colonnes
  pertinentes; la liste complète reste récupérable si nécessaire.
- Un DataFrame dérivé inactif est masqué après six tours, puis supprimé après
  vingt tours sauf s’il soutient encore une lignée visible.
- Les anciens résultats de tools sont compactés sans perdre la décision ou la
  provenance utile.

## Vérifier sans consommer de crédits LLM

Les campagnes de projection valident la construction du contexte et son
évolution multi-tour sans appel au modèle :

```bash
python scripts/dev/run_context_projection_campaign.py --json
python scripts/dev/run_context_projection_campaign.py --facet tools --json
pytest -q tests/test_tool_catalog.py tests/test_openai_tool_search.py tests/test_tool_exposure.py
python scripts/dev/generate_tools_doc.py --check
```

Ces contrôles doivent notamment couvrir la tâche courante, les DataFrames
disponibles, les faits du dernier graphique, la frontière d’exploration, le
vieillissement des ressources et la cohérence des tools exposés.

## Maintenir la documentation

- `README.md` reste le point d’entrée et le guide de démarrage.
- `PRESENTATION.md` explique la valeur et le comportement de l’agent.
- `ARCHITECTURE.md` décrit uniquement les composants réellement actifs.
- `TOOLS.md` est généré ou vérifié depuis le catalogue exécutable.
- `BEST_PRACTICES.md` porte les règles d’usage et d’évolution.

Avant de supprimer un Markdown historique, présenter son chemin, son rôle, ses
liens entrants et la raison proposée, puis attendre une approbation explicite.
