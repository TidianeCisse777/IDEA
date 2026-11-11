# Organisation des données FILET : déploiements, filets, couches de profondeur, taxons

Mesuré le 11 novembre 2026 sur l'export FILET du 26 mai 2026 chargé dans le warehouse (vues
`explore.filet_samples`, `explore.filet_data`). Les libellés sont ceux de la source.

## De la station à la ligne d'abondance

1. **Déploiement** (`deployment_id`) : une mise à l'eau d'un engin (`gear`) à une station, avec heure de
   début et de fin, position, type de trait (`tow_type`) et numéro de cast.
2. **Échantillon** (`sample_id`) : le contenu d'un filet de ce déploiement, pour **une couche de profondeur**
   (`min_sample_depth`–`max_sample_depth`, m) et **une maille** (`net_mesh_size`, µm), avec ses deux volumes
   filtrés : par la profondeur (`depth_calc_net_filtered_vol`) et par le débitmètre (`flowmeter_calc_vol`).
   Un échantillon vient en général d'un seul filet; il peut regrouper plusieurs filets (`number_of_nets`,
   `sample_nets` du type « 8+9 », `net_sampling_ids`) : ces libellés ne sont pas des identifiants CTD.
3. **Analyse** (`analysis_id`) : l'analyse taxonomique d'un échantillon (type, contrat, protocole, date).
   1 502 analyses pour 6 102 échantillons : la plupart des échantillons n'ont pas d'analyse.
4. **Abondance** (`explore.filet_data`) : une ligne par échantillon × analyse × taxon × **stade** (C1–C5, M, F,
   COP_NS, N1–N6, NAUP_NS et les agrégats COPEPODID, NAUPLIUS, ALL_STAGES), en individus comptés, ind./m3 et
   µg C/m3, chacun au volume profondeur et au volume débitmètre. Les agrégats sont la somme exacte de leurs
   parties (vérifié) : ne jamais additionner un agrégat et ses parties.

## Comment la colonne d'eau est échantillonnée

Échantillons et déploiements par engin et type de trait (libellés source; « V-Tow » et « O-Tow » ne sont pas
définis dans le dictionnaire du labo, probablement vertical et oblique : à confirmer) :

| Engin | Trait | Échantillons | Déploiements | Épaisseur moyenne (m) | Mailles (µm) |
|---|---|---|---|---|---|
| Hydrobios | V-Tow | 2 721 | 326 | 77 | 50–200 |
| 2x1m2 | O-Tow | 1 299 | 621 | 84 | 50–750 |
| 4x1m2 - LOKI | V-Tow | 784 | 234 | 378 | 50–500 |
| 4x1m2 | V-Tow | 751 | 234 | 380 | 50–500 |
| 2x1m2 | V-Tow | 290 | 134 | 368 | 50–750 |
| Bioness | O-Tow | 225 | 25 | 28 | 750 |
| 2x1m2 - LOKI | V-Tow | 18 | 8 | 75 | 200 |
| hydrobios | V-Tow | 9 | 1 | 29 | 200 |
| Ringnet 1m / 50cm | O-Tow | 5 | 5 | — | 500 / 64 |

Deux façons d'échantillonner, visibles dans les données :

- **Une seule couche, plusieurs mailles en même temps** (2x1m2, 4x1m2, 4x1m2 - LOKI) : chaque déploiement a
  une seule couche (souvent de la surface au fond ou à une profondeur fixe) et 2 ou 3 filets de mailles
  différentes. Exemple : 652 déploiements 2x1m2 à une couche et deux mailles. Comparer des mailles, pas des
  profondeurs.
- **Plusieurs couches superposées, une maille** (Hydrobios, Bioness) : un filet par couche, 5 à 10 couches
  par déploiement (213 déploiements Hydrobios à 9 couches, 25 Bioness à 9). C'est un **profil vertical**.
  Exemple, déploiement 1105 (station 407, 2015, Hydrobios, 200 µm) : 2–20, 20–40, 40–60, 60–100, 100–200,
  200–300, 300–320, 320–340 et 340–360 m (filets 9 à 1).

## Conséquences pour les analyses

- Profil vertical : utiliser les échantillons d'un même déploiement Hydrobios ou Bioness, couche par couche;
  l'abondance est déjà par m3 de chaque couche. Pour une valeur sur toute la colonne, pondérer par
  l'épaisseur ou le volume de chaque couche (le dire), jamais une moyenne simple des concentrations.
- Une seule couche : ne pas comparer directement deux mailles comme deux profondeurs; la maille fixe la
  taille minimale retenue.
- Comparaison avec l'UVP : `explore.filet_uvp_compare` travaille couche par couche (une ligne par échantillon
  et analyse); pour un profil Hydrobios ou Bioness, on obtient une ligne par couche (document
  filet-uvp-comparaison).
