# Plan de tests graphes biodiversite copepodes

Ce plan fige les graphes de reference a utiliser pour verifier que l'agent
reproduit proprement les analyses courantes sur les copepodes et la
biodiversite. Il sert de source locale pour aligner `graph_planner`,
`graph_writer` et les evals agent.

## Fichiers de reference

| Fichier | Role |
|---|---|
| `data/demo/neolabs_taxonomy_2014_2020.tsv` | Jeu principal : taxons, abondance, station, date, profondeur, latitude/longitude et variables CTD Amundsen. |
| `data/demo/zooplankton_demo_stations.tsv` | Jeu fallback compact : station, profondeur, taxon, stade et abondance. |
| `UVP_metrics_for_MCA/final_datasets/uvp_metrics_Hawke_Channel_2024.csv` | Jeu UVP/EcoPart pour courbes particules, morpho-diversite et densite de copepodes. |

## Graphes P0

| Graphe | Donnees minimales | Attendu |
|---|---|---|
| Profil vertical | profondeur + abondance | Profondeur sur Y, axe inverse avec `ax.invert_yaxis()`, abondance sur X. |
| Composition taxonomique | sample/station/date + taxon + abondance | Barres empilees par station, mois ou profondeur. |
| Carte d'observations | latitude + longitude + metrique | Carte cartopy avec couleur ou taille encodee. |
| Indices de diversite | matrice sample x taxon | Richesse, Shannon, Simpson, Pielou calcules sur la meme matrice. |

## Graphes P1

| Graphe | Donnees minimales | Attendu |
|---|---|---|
| Rarefaction | matrice sample x taxon en comptes/abondances | Courbes richesse attendue selon effort, avec bande d'incertitude si disponible. |
| Accumulation d'especes | matrice site/sample x taxon | Courbe cumulative moyenne par permutations ou ordre stable, avec intervalle si calcule. |
| NMDS | matrice sample x taxon | Ordination Bray-Curtis, points colorables par station/date/environnement. |
| PCoA | matrice sample x taxon | Ordination sur dissimilarite Bray-Curtis, axes etiquetes. |
| Heatmap de composition | taxon + station/mois/profondeur + abondance | Heatmap log1p ou relative abundance, taxa dominants seulement. |

## Graphes P2

| Graphe | Donnees minimales | Attendu |
|---|---|---|
| Rank-abundance | taxon + abondance | Rang sur X, abondance relative ou totale sur Y, echelle log optionnelle. |
| Courbe taille/biovolume/biomasse | classe taille ou biovolume + densite/biomasse | Courbe ou barres ordonnees par classe. |
| Lacunes d'echantillonnage | station + coverage/count | Carte ou barres distinguant coverage absent, sparse, suffisant. |

## Evals agent a maintenir

Les cas `GR-12` a `GR-15` dans `evals/eval_graphs.py` couvrent les graphes
biodiversite manquants :

| ID | Graphe | Fichier |
|---|---|---|
| `GR-12` | rarefaction | `data/demo/neolabs_taxonomy_2014_2020.tsv` |
| `GR-13` | NMDS / PCoA Bray-Curtis | `data/demo/neolabs_taxonomy_2014_2020.tsv` |
| `GR-14` | heatmap de composition taxonomique | `data/demo/neolabs_taxonomy_2014_2020.tsv` |
| `GR-15` | rank-abundance | `data/demo/neolabs_taxonomy_2014_2020.tsv` |

## Criteres de validation

- Le planner doit choisir un type de graphe explicite, pas un `scatter`
  generique, pour rarefaction, accumulation, NMDS, PCoA, heatmap et
  rank-abundance.
- Le writer doit produire du code matplotlib complet, non interactif, avec le
  style sombre obligatoire.
- Les graphes de profondeur doivent inverser l'axe Y.
- Les graphes de composition doivent construire une matrice `sample x taxon`
  ou `groupe x taxon` avant de tracer.
- Les ordinations doivent utiliser Bray-Curtis pour NMDS/PCoA et rester
  presentees comme exploratoires sans test de permutation.
- Les sorties ne doivent pas ajouter d'interpretation scientifique ou
  biologique non demandee.
