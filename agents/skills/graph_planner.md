# Skill : graph_planner

Tu dois planifier un graphique avant de l'exécuter.

## Étapes obligatoires

1. Identifier les colonnes pertinentes dans le fichier chargé
2. Choisir le type de graphe adapté :
   - **bar** : comparer des catégories (ex. abondance par taxon, biomasse par espèce)
   - **line** : évolution dans le temps ou en profondeur
   - **scatter** : relation entre deux variables numériques (ex. température vs profondeur)
   - **histogram** : distribution d'une variable numérique
3. Définir les axes : quelle colonne en X, quelle colonne en Y
4. Identifier les regroupements nécessaires (groupby, pivot, agg)
5. Signaler si des valeurs manquantes peuvent affecter le graphe

## Format du plan

Retourne le plan sous cette forme avant d'écrire le code :

```
Plan graphique :
- Type : <bar | line | scatter | histogram>
- X : <nom de colonne>
- Y : <nom de colonne>
- Agrégation : <sum | mean | count | none>
- Filtre : <condition ou "aucun">
```
