# Interroger le warehouse en SQL (DBeaver, pgAdmin, psql, R, Python)

Pour une personne qui veut lire les données elle-même, sans agent. Les agents IA lisent exactement les
mêmes vues, avec les mêmes droits ; ce guide en est la version pour humains.

## Se connecter

Le fichier remis par l'administrateur (`mon_nom.env`) contient tout ce qu'il faut :

| Champ du client SQL | Ligne du fichier |
|---|---|
| Hôte | `WAREHOUSE_DB_HOST` |
| Port | `WAREHOUSE_DB_PORT` |
| Base | `WAREHOUSE_DB_NAME` |
| Utilisateur | `WAREHOUSE_DB_USER` |
| Mot de passe | `WAREHOUSE_DB_PASSWORD` |
| SSL | `WAREHOUSE_DB_SSLMODE` |

Ne garder ce fichier que le temps de remplir la connexion (ou le passer à
`scripts/warehouse_connect.py init`), puis le supprimer.

- Deux schémas sont lisibles : **`explore`**, les données (projets, samples, objets, profils, abondances,
  CTD, FILET, zones), et **`catalogue`**, ce qui décrit les données et le compte (droits, catalogue des jeux
  de données, dictionnaire des colonnes, fiches métier, version déployée). Le schéma `warehouse` (tables
  brutes) est fermé aux comptes de lecture.
- Noms des vues et des colonnes en anglais (convention SQL), descriptions en français.
- Chaque vue et chaque colonne a une description (onglet « Propriétés » ou « Commentaire »).
- Le compte est en lecture seule et une requête est arrêtée après **30 secondes** : filtrer et agréger
  dans la requête plutôt que tout télécharger.
- On ne voit que les lignes de son périmètre (contrat, zone, années) : `SELECT * FROM catalogue.my_datasets;`
  dit, pour chaque jeu de données, si l'accès est complet, partiel ou nul.

## Par où commencer

| Vue | Pour |
|---|---|
| `explore.ecotaxa_projects` | la liste de tous les projets EcoTaxa, avec instrument, période, zones et objets par statut d'annotation |
| `catalogue.my_datasets` | ce que mon compte peut lire |
| `catalogue.warehouse_dictionary` | le sens de chaque colonne de chaque vue, et la requête SQL qui la produit |
| `catalogue.warehouse_context` | les fiches détaillées : grain, jointures, pièges, exemples |

Toutes les vues de la section suivante sont dans `explore` ; `dataset_catalog` est dans `catalogue`.

## Quelle vue pour quelle question

| Question | Vue |
|---|---|
| Quels projets, quels instruments, combien d'objets validés ? | `ecotaxa_projects` |
| Les samples d'un projet (date, position, zone, comptes par statut) | `ecotaxa_samples` |
| Les objets : taxon, statut, profondeur, taille | `ecotaxa_objects` (15 M lignes : toujours filtrer par projet ou sample) |
| Les profils UVP et leurs samples EcoTaxa | `uvp_projects`, `uvp_samples` |
| Une abondance UVP (ind/m³) par taxon et profondeur | `uvp_taxon_abundance` |
| Une abondance par taxon **et** classe de taille | `uvp_object_sizes` + `ecopart_bins` pour les volumes |
| Le spectre de tailles des particules (sans taxon) | `uvp_particle_sizes` |
| Les profils CTD et leurs mesures (température, salinité, oxygène…) | `ctd_profiles`, `ctd_measurements` |
| Tout ce qui est dans une zone maritime, chevauchements compris | `zone_membership`, contours dans `marine_zone_boundaries` |
| Les stades de copépodes (codes FILET, ce que l'UVP permet) | `copepod_stages` |
| FILET et la comparaison FILET–UVP | `filet_samples`, `filet_data`, `filet_uvp_matches`, `filet_uvp_abundance` |
| Licence, auteurs, provenance d'un jeu de données | `dataset_catalog` |

## Les clés de jointure

| Clé | Désigne | Vues |
|---|---|---|
| `ecotaxa_project_id` | un projet EcoTaxa | `ecotaxa_*`, `uvp_*` |
| `ecotaxa_sample_id` | un sample EcoTaxa (clé technique) | `ecotaxa_samples`, `ecotaxa_objects`, `uvp_samples`, `uvp_objects` |
| `ecotaxa_native_sample_id` | le numéro du sample dans EcoTaxa | `ecotaxa_samples`, `uvp_samples` |
| `uvp_profile_id` | un profil UVP | toutes les vues `uvp_*`, `ecopart_bins`, `zone_membership` (`row_id` quand `row_kind = 'uvp_profile'`) |
| `uvp_bin_id` | une tranche de profondeur d'un profil UVP | `uvp_objects`, `uvp_object_sizes`, `uvp_taxon_abundance`, `ecopart_bins`, `uvp_particle_sizes` |
| `ctd_profile_id` | un profil CTD | `ctd_*`, `ecotaxa_ctd*`, `uvp_ctd`, `filet_ctd` |
| `taxon_key` | un taxon UVP (`ecotaxa:id:N`) ; son nom est dans `taxon_name` | `uvp_taxon_abundance`, `uvp_object_sizes` |

`profile_id` et `bin_id` (dans `ecopart_bins` et `uvp_taxon_abundance`) sont les anciens noms de
`uvp_profile_id` et `uvp_bin_id`, gardés pour ne pas casser les requêtes existantes.

## Cinq pièges

1. **Validé ou prédit.** `annotation_status` vaut `validated` (vu par un humain), `predicted`
   (classification automatique), `dubious`, ou NULL (jamais classé). Les abondances existent en deux
   versions (`annotation_policy` commence par `all_loaded_objects` ou `validated_only`) : toujours en
   choisir une. Exemple réel : copépodes 0–200 m en Baie de Baffin, am_leg3 2024, 750,9 ind/m³ avec tous
   les objets, 2,1 avec les seuls validés.
2. **Projets en double.** 149 contient les 199 samples de 20880 + 20890 (mêmes comptes, sous d'autres
   identifiants d'objet) plus 5 samples qui lui sont propres : ne pas additionner ces projets, 149 seul donne
   GreenEdge 2016 sans doublon. 13224 est un autre projet issu de GreenEdge 2016 ; son lien avec 149 n'est pas
   établi.
3. **Zones.** `marine_zone_key` donne une seule zone par point (zone NeoLab prioritaire sur une écorégion
   MEOW, `AMBIGUOUS` si plusieurs zones NeoLab se chevauchent). Pour tout ce qui est dans une zone,
   joindre `zone_membership`.
4. **Abondance = objets / volume.** Seules les vues UVP portent un volume échantillonné. Agréger par
   `SUM(objets) / SUM(volume) × 1000`, pas par moyenne de concentrations, et compter le volume d'une
   tranche une seule fois.
5. **NULL n'est pas zéro.** Une taille sans calibration (LOKI), une coordonnée manquante ou un statut
   absent restent NULL.

## Exemples

Testés sur la base réelle avec un compte de lecture (3 novembre 2026).

```sql
-- Projets, du plus gros au plus petit, avec la part d'objets validés
SELECT ecotaxa_project_id, ecotaxa_project_title, instrument, n_objects,
       round(100.0 * n_validated / n_objects, 1) AS pct_valides
FROM explore.ecotaxa_projects ORDER BY n_objects DESC;

-- Les samples d'un projet
SELECT ecotaxa_native_sample_id, datetime_min, latitude, longitude, marine_zone_key,
       object_count, nb_validated, nb_predicted
FROM explore.ecotaxa_samples WHERE ecotaxa_project_id = 14859 ORDER BY datetime_min;

-- Les catégories d'un projet LOKI et leur statut
SELECT taxon_name, annotation_status, count(*) AS objets
FROM explore.ecotaxa_objects WHERE ecotaxa_project_id = 14622
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;

-- Les profils UVP en Baie de Baffin, chevauchements de zones compris
SELECT DISTINCT s.uvp_profile_id, s.sample_name, s.sampled_at, s.ecotaxa_project_id
FROM explore.uvp_samples s
JOIN explore.zone_membership m ON m.row_kind = 'uvp_profile' AND m.row_id = s.uvp_profile_id
WHERE m.zone_key = 'Baie de Baffin' ORDER BY s.sampled_at;

-- Abondance des copépodes 0-200 m en Baie de Baffin, par projet, objets validés seulement
SELECT split_part(a.annotation_policy, '=', 2) AS ecotaxa_project_id,
       count(DISTINCT a.uvp_profile_id) AS profils,
       round(sum(a.n_objects_taxon) / sum(a.sampled_volume_l) * 1000, 1) AS ind_m3
FROM explore.uvp_taxon_abundance a
JOIN explore.zone_membership m ON m.row_kind = 'uvp_profile' AND m.row_id = a.uvp_profile_id
WHERE m.zone_key = 'Baie de Baffin' AND a.taxon_name = 'Copepoda<Multicrustacea'
  AND a.annotation_policy LIKE 'validated_only:%' AND a.depth_max_m <= 200
GROUP BY 1 ORDER BY 1;

-- Un profil de température CTD
SELECT round(depth_m) AS profondeur_m, avg(value) AS temperature_c
FROM explore.ctd_measurements
WHERE variable_key = 'TE90' AND ctd_profile_id = (SELECT min(ctd_profile_id) FROM explore.ctd_profiles)
GROUP BY 1 ORDER BY 1;

-- Le sens des colonnes d'une vue
SELECT column_name, data_type, column_description
FROM catalogue.warehouse_dictionary WHERE view_name = 'ecotaxa_samples';
```

Depuis R ou Python, la même connexion fonctionne (`RPostgres`, `psycopg`) ; lire le résultat d'une
requête agrégée plutôt qu'une vue entière.
