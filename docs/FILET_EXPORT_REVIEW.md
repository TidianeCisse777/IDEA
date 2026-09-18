# Vérification des exports FILET du Bureau

18 septembre 2026. Lecture seule des CSV, sans modification des originaux.
Objectif : établir grain et clés pour le warehouse SQL → DataFrame (phase 1).

## Fichiers

Répertoire source : `/Users/tidianecisse/Desktop`.
Préfixe commun : `project_IDEA_taxonomy_samples+analyses-data_&_metadata-20260526`.

| Suffixe | Contenu | SHA-256 |
|---|---|---|
| `(taxonomy samples-data).csv` | 6 105 lignes, 33 colonnes | `9ed57d8cc47fc7261dc4d8f150ab80030b2f15bd82959e910f7fa694446a3c90` |
| `(copepod abund&biomass-data).csv` | 5 047 lignes, 93 colonnes | `6fdb7f5c9afb06c55babd079489dd31abe8e784548706df8044fe419638900a9` |
| `(copepod abund&biomass-metadata).csv` | Dictionnaire des 93 colonnes et périmètre | `4a2e18d5fb48754630aeed57fcf87bac55f94b560c90bd4375088e6ea3ba2f8f` |

`neolab_metadata.csv` est identique octet pour octet au premier fichier : ne
pas l'importer comme un deuxième jeu. Le dictionnaire a été décodé en CP1252 ;
les deux tables de données ont été lues par pandas en UTF-8, identifiants texte.
Les `NA` sont traités comme manquants. Aucun calcul biologique effectué.

## Grain et cardinalités observés

- 1 588 `deployment_id` distincts dans les métadonnées.
- 6 102 `sample_id` distincts ; 3 échantillons ont plusieurs analyses.
- 1 502 lignes avec `analysis_id`, toutes uniques sur
  `(sample_id, analysis_id)` ; les `analysis_id` sont également uniques dans
  cet export. 4 603 lignes sans analyse, à conserver dans l'inventaire.
- 44 échantillons regroupent plusieurs filets : `net_sampling_ids` contient
  une liste, `sample_nets` un libellé tel que `8+9`. Ne pas confondre avec un
  prélèvement élémentaire ni utiliser ces libellés comme ID CTD.
- Abondance : 396 couples `(SAMPLE_ID, ANALYSIS_ID)`, 5 047 triplets
  `(SAMPLE_ID, ANALYSIS_ID, TAXON_ID)` uniques, aucune clé manquante.
- Le grain d'origine est échantillon × analyse × taxon, avec les stades en
  colonnes. Le SQL propose une représentation longue, stade en ligne.

## Jointure réellement exécutée

Lecture pandas, puis `merge(..., how='left', validate='many_to_one')` :

```python
joined = abundance.merge(
    samples,
    left_on=['SAMPLE_ID', 'ANALYSIS_ID'],
    right_on=['sample_id', 'analysis_id'],
    how='left', indicator=True, validate='many_to_one',
)
```

Résultat : 5 047 lignes, dont 4 941 appariées et 106 non appariées (2,10 %).
Pas de multiplication des lignes. Les non-appariés correspondent à neuf couples
de 2024 dont ni l'échantillon ni l'analyse n'existent dans les métadonnées :

| SAMPLE_ID | ANALYSIS_ID |
|---|---|
| 40837 | 1891 |
| 40953 | 1892 |
| 41014 | 1894 |
| 47302 | 1893 |
| 41376 | 1896 |
| 41448 | 1895 |
| 41535 | 1897 |
| 41696 | 1898 |
| 41880 | 1899 |

Sur les 4 941 lignes appariées, aucune différence de chaîne (manquants égaux)
sur station, maille, profondeurs minimale/maximale et les deux volumes filtrés.
La cause de l'écart de couverture n'est pas établie ; ne pas inventer les
métadonnées manquantes. Conserver le contexte déjà porté par l'export abondance
et exposer le statut d'appariement. Une INNER JOIN perdrait les 106 lignes.

## Conséquences pour le SQL

- Conserver les clés natives, avec une portée source/version pour les imports.
- Séparer échantillons, analyses et abondances. Une relation d'appartenance
  permet de déplier les listes de filets sans leur attribuer des volumes ou
  profondeurs individuels non fournis.
- Conserver séparément `DEPTH_CALC_NET_FILTERED_VOL` et `FLOWMETER_CALC_VOL`,
  leurs abondances en ind./m3 et leurs biomasses en µg C/m3. Aucun choix de
  dénominateur implicite, aucune nouvelle division des valeurs déjà calculées.
- Le dictionnaire marque `*_SAMPLE_ABUND` comme calculé : il s'agit d'individus
  attribués à l'échantillon, pas nécessairement de comptages bruts. 2 062 valeurs
  `ALL_STAGES_SAMPLE_ABUND` sont non entières. Type numérique, pas entier.
- Stades détaillés : C1–C5, M, F, COP_NS, N1–N6, NAUP_NS. Les colonnes
  COPEPODID, NAUPLIUS et ALL_STAGES sont des agrégats : ne pas les additionner
  à leurs composants. Fournir une vue dédiée aux totaux.
- L'export ne fournit pas de biomasse pour les colonnes nauplii/all-stages :
  conserver l'absence, pas zéro ni un total inventé.
- `subsampling_quantity` et `subsampling_unit` décrivent le sous-échantillon ;
  leur assimilation à une fraction effectivement analysée n'est pas démontrée.
- Aucun champ explicitement CTD, EcoTaxa ou EcoPart dans ces deux exports.
  `CAST_NUMBER` est défini comme numéro/ordre du trait de l'engin à la station,
  pas comme identifiant CTD universel. Le lien externe reste à documenter.

## Limites

La vérification porte sur ces instantanés. Aucun export UVP/EcoPart/CTD et
aucun ancien code de jointure n'ont été trouvés par la recherche de noms de
fichiers métier sur le Bureau. `Docs/neolab_stations_test.csv` est une table
distincte dont les en-têtes ne suffisent pas à prouver ces correspondances.
Le DDL révisé n'a pas été exécuté ; aucun scénario notebook/IDEA ni aucune
phase du plan n'est déclaré validé par cette vérification locale.
