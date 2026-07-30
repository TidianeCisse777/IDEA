# Édition rapide du dernier graphique

## But

Une demande d'itération graphique doit modifier le script qui a produit le
dernier graphique, plutôt que régénérer un script et une préparation de données
depuis zéro.

Exemples : recentrer une carte, changer une couleur, retirer une légende,
modifier un titre, une échelle ou des libellés.

## Périmètre V1

Après un `run_graph` réussi, la session conserve :

- le script matplotlib complet exécuté ;
- l'identifiant de l'image rendue ;
- `df_graph_plot`, les lignes effectivement tracées ;
- la spécification/contrat graphique déjà calculé.

Lorsqu'un utilisateur demande une retouche du dernier graphique, l'agent reçoit
ce script et ces faits de rendu. Il produit une version complète du même script,
modifiée uniquement pour la demande, puis appelle `run_graph` sur le même
`df_graph_plot`.

Le script n'est jamais montré automatiquement à l'utilisateur. Il reste une
donnée de session interne, comme la table de rendu.

## Routage

Une demande est une retouche si elle vise explicitement le graphique précédent
et qu'un script de rendu est encore disponible en session. Dans ce cas :

1. exposer uniquement le chemin d'édition/rendu, sans recharger les skills de
   planification ;
2. injecter le dernier script et les faits de rendu dans le contexte modèle ;
3. exécuter le script modifié avec `run_graph` ;
4. remplacer atomiquement le dernier script, l'image et les faits de rendu si
   le rendu réussit.

Une nouvelle analyse est requise seulement si le dernier script est absent, si
l'utilisateur demande d'autres données, ou s'il change le type de graphique de
manière substantielle.

## Contrôles et échecs

Les garde-fous actuels de `run_graph` restent inchangés : sandbox, validation de
contrat, lisibilité et une seule tentative de correction sur diagnostic. Si le
nouveau rendu échoue, le dernier graphique réussi et son script restent
intacts ; une erreur ne remplace jamais l'état utilisable.

## Tests d'acceptation

1. Un rendu réussi persiste son script, `df_graph_plot` et son identifiant.
2. Une demande « enlève la légende » réutilise le script et `df_graph_plot`,
   sans `run_pandas` ni planification.
3. Une demande « centre la carte sur Baffin » modifie le même script de carte.
4. Un échec de la retouche préserve le script et l'image précédents.
5. Sans graphique antérieur, une demande de retouche suit le workflow graphique
   normal.
