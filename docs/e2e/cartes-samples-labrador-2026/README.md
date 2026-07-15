# Scénario E2E — Cartes de samples (fichier TSV NeoLabs)

Rejeu du parcours réel d'un **superviseur** (professeur) qui demande des cartes
de positions d'échantillons à partir de **son seul fichier TSV**
(`neolabs_taxonomy_2014_2020.tsv`, présent sous `data/demo/`). Transcript source
brut : [`docs/Test_Portable/`](../../Test_Portable). Couvre les use cases
**UC-A** (fichier local) + **UC visualisation cartographique**.

## Intention

« Montre-moi où sont mes échantillons » — la demande la plus basique d'un prof
en phase d'exploration : positions sur une carte, puis taille = nombre
d'échantillons par position, puis couleur = nombre de taxons par échantillon,
restreint à des zones nommées (baie de Baffin, baie d'Hudson, mer du Labrador),
**sans jamais sortir du fichier fourni**.

## Déroulé (transcript prof)

| # | Demande | Observé | Défaut |
|---|---|---|---|
| 1 | Positions Baffin, taille = nb samples/position | Carte rendue, mais `sample_count` **renommé en `abundance_ind_L`** pour passer le contrat | D-CL2 |
| 2 | « comment as-tu déterminé les échantillons ? » | Réponse colonnes correcte | — |
| 3 | Même figure, taille = nb de taxons | Rendu en `kind:"generic"` | — |
| 4 | Baie d'Hudson + côtes | **Échec** « type de carte pas supporté » (`kind:"map"`) puis re-rendu | D-CL1 |
| 5 | Labrador, taille = nb samples + couleur = nb taxons | Demande de clarification (comptage vs ind/L) | — |
| 6 | Abondances ind/L | Refus : `object_annotation_hierarchy` manquante | (hors périmètre carte) |
| 7 | Tous taxa, ind/m³ brut | Table correcte | — |
| 8 | Labrador, couleur = nb taxons | **Dérive EcoTaxa** : appel `find_ecotaxa_samples_in_region`, coordonnées EcoTaxa **codées en dur** dans `plot_df` | D-CL1, D-CL2, D-CL3 |
| 9 | « quel est le nom du fichier ? » | **Esquive** : recharge un skill au lieu de répondre | D-CL4 |
| 10 | « limite-toi au TSV, aucune méthode EcoTaxa » | Accepte… | — |
| 11 | Positions Labrador | D'abord « impossible, pas de positions » (**faux**), puis échec `kind:"map"`, puis scatter sans côtes | D-CL1, D-CL3 |
| 12 | « ajoute la côte » | Esquive → le prof abandonne (« Tu m'emmerdes ! ») | D-CL4 |

## Racine commune

Le seul `kind` de carte du validateur (`abundance_environment_map`) **exigeait**
`size = abundance_ind_L` + toutes les légendes. Une carte de **positions /
comptages / richesse** était donc inexprimable, ce qui poussait l'agent à :

1. **inventer** une colonne `abundance_ind_L` à partir d'un comptage (D-CL2), ou
2. émettre `kind:"map"`/`"scatter"` → rejeté → « carte non supportée » (D-CL1).

Combiné à un scope « fichier TSV seulement » mal tenu (D-CL3), l'agent finissait
par **fabriquer des coordonnées EcoTaxa** pour produire quand même une image.

## Correctifs

- **D-CL1 / D-CL2 — CORRIGÉ** : nouveau `kind:"station_map"` (position obligatoire
  sur GeoAxes cartopy ; `size`/`color` optionnels sur **variable libre**). Skills
  `graph_planner`/`graph_writer` routent dessus et interdisent le renommage d'un
  comptage en `abundance_ind_L`. Voir [DEFECTS_AND_PRIORITIES.md](DEFECTS_AND_PRIORITIES.md).
- **D-CL5 — CORRIGÉ** (portabilité) : fonds Natural Earth 110m + 50m vendorés
  (`assets/cartopy`) + garde-fou d'échelle (`core.cartography`), pour rendre les
  cartes cartopy hors-ligne après un clone neuf.
- **D-CL3 — CORRIGÉ** : règles dures de system prompt — précédence du fichier
  chargé (`get_zone_info` + `filter_dataframe_by_zone`), verrou de périmètre
  après une consigne « fichier seulement », interdiction des coordonnées externes
  codées en dur.
- **D-CL4 — CORRIGÉ** : réponse directe aux questions de métadonnées de session
  (nom de fichier, colonnes) sans esquive par `load_skill`.

## Artefacts

- [Transcript source du prof](../../Test_Portable)
- [Défauts observés et priorités](DEFECTS_AND_PRIORITIES.md)

## Enseignements

- Un contrat de visualisation trop rigide **génère de l'hallucination** : quand
  aucun `kind` valide n'existe pour l'intention réelle, le LLM invente les
  données nécessaires pour satisfaire le validateur. Le bon niveau de contrainte
  est « strict sur la sémantique, permissif sur la variable ».
- Le respect du périmètre « seulement le fichier fourni » doit être une **règle
  dure de system prompt**, pas une politesse : trois consignes explicites du prof
  n'ont pas suffi à empêcher la dérive EcoTaxa.
