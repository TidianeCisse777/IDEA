# Campagne de pression DataFrames

Cette campagne hors ligne rejoue 50 tours avec 34 tables initiales, puis une
nouvelle version d'analyse à chaque tour. Elle exerce le vrai pipeline de
projection du harness, la compaction du checkpoint, le WorkingSet et le cycle
de vie des DataFrames.

Commande de reproduction :

```bash
python scripts/dev/plot_dataframe_pressure_evolution.py \
  --output-dir docs/e2e/dataframe-pressure
```

## Résultats observés

| Mesure | Maximum | Valeur finale |
|---|---:|---:|
| DataFrames/versions stockés | 84 | 84 |
| Dérivés courants visibles au runtime | 20 | 1 |
| Dérivés courants archivés | 30 | 30 |
| Versions superseded archivées | 50 | 50 |
| Cartes DataFrames détaillées dans le prompt | 6 | 4 |
| Messages du checkpoint après compaction | 40 | 39 |
| Messages projetés au provider | 42 | 40 |
| Contexte DataFrames | 4 945 caractères | 3 626 caractères |
| Contexte dynamique estimé | 1 664 tokens | 1 564 tokens |
| Requête modèle totale estimée | 13 778 tokens | 13 733 tokens |

Les payloads persistés augmentent parce que l'historique de versions est
archivé au lieu d'être supprimé. Cette croissance n'est pas exposée telle quelle
au modèle : le runtime plafonne les dérivés courants à 20, la projection détaille
au plus huit ressources et le checkpoint durable reste borné à 40 messages.

## Artefacts

- `dataframe_pressure_timeline.json` : métriques des 50 tours;
- `dataframe_pressure_evolution.png` : stockage, archivage et visibilité;
- `context_pressure_evolution.png` : messages et tokens projetés.
