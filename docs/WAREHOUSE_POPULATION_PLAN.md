# Plan de peuplement du warehouse V1

Ce plan décrit comment passer des exports et clients historiques aux tables
`warehouse`. Il sépare l’extraction, la validation et la publication afin qu’un
chargement incomplet ne soit jamais présenté comme une version complète.

## 1. Ordre de chargement

```text
manifeste de sources
  → EcoTaxa (projets, samples, objets, métadonnées)
  → EcoPart (profils, bins, volumes, particules)
  → CTD Amundsen (profils, mesures, dictionnaire de variables)
  → liens EcoTaxa/EcoPart/CTD
  → FILET (samples, analyses, abondances déjà calculées)
  → vues explore et contrôles finaux
```

EcoTaxa est chargé en premier parce qu’il porte le sample et l’objet qui
servent de point d’entrée aux jointures UVP. EcoPart enrichit les objets par
profil et tranche. Le CTD est ensuite relié aux profils déjà identifiés. FILET
reste indépendant jusqu’à la création des liens de comparaison.

## 2. Manifestes de versions

Chaque chargement crée une ligne dans `warehouse.dataset_version` avant toute
insertion de données :

| Champ | Contenu attendu |
|---|---|
| `source_instance` | `ecotaxa`, `ecopart`, `amundsen_ctd` ou `filet` |
| `dataset_key` | projet, campagne ou identifiant de l’export |
| `version_key` | date/version déclarée par la source |
| `file_manifest_uri` | chemin ou URI du fichier/manifeste |
| `sha256` | empreinte exacte du fichier ou lot |

Le manifeste de campagne doit aussi lister les fichiers, leur taille, leur
encodage, leurs colonnes et le nombre de lignes. Une requête ne mélange pas des
`dataset_version_id` provenant de lots incompatibles.

## 3. Étape EcoTaxa

Le script historique de référence est `core/ecotaxa_browser/cache/sync.py`.
Il apporte déjà les garanties utiles :

- synchronisation par projet et transaction par projet ;
- signatures `objcount`, `pctvalidated`, `pctclassified` pour éviter les
  téléchargements inchangés ;
- limitation globale des requêtes et retries ;
- métadonnées sample, coordonnées, dates, `profile_id`, `station_id`,
  `cruise_id` et `ctd_rosette_filename` ;
- statistiques taxonomiques par sample sans télécharger tous les objets ;
- historique de synchronisation et schéma versionné dans le cache SQLite.

Pour le warehouse, on réutilise les fonctions d’extraction et leurs contrôles,
mais on écrit dans `warehouse.ecotaxa_sample` et `warehouse.ecotaxa_object`.
Le cache SQLite historique reste une source de référence et un mécanisme de
reprise ; il ne remplace pas les tables PostgreSQL du warehouse.

Contrôles avant publication : identifiant sample non vide, unicité
`dataset_version/project/sample`, coordonnées plausibles, dates parseables,
compteurs taxonomiques cohérents et statut de zone renseigné ou explicitement
`unresolved`.

## 4. Étape EcoPart

Charger d’abord `uvp_profile`, puis `uvp_bin`, puis `uvp_particle`. Vérifier :

- unicité `(dataset_version_id, ecopart_project_id, ecopart_sample_id)` ;
- présence de `Profile`, `Depth [m]` et `Sampled volume [L]` ;
- volume strictement positif pour les bins utilisables ;
- absence de doublon `(profile, profondeur)` ;
- conservation des bins sans objet EcoTaxa.

Le rattachement objet/bin applique la règle historique de
`core/ecotaxa_ecopart_join.py` :

```text
floor(object_depth_min / 5) * 5 + 2.5
```

Chaque ligne de `uvp_object_bin` conserve la méthode, l’écart de profondeur et
le statut (`accepted`, `ambiguous`, `unmatched`).

## 5. Étape CTD Amundsen

Charger le catalogue `ctd_variable`, puis les profils et enfin les mesures.
Les codes historiques sont `PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`, `pH`,
`NTRA`, `FLOR`.

Le lien EcoTaxa/CTD suit `core/ctd_filename_match.py` : le nom de fichier
génère les candidats, puis station, temps et position confirment la relation.
Chaque candidat est conservé avec distance, écart temporel, méthode, preuve et
statut. Les valeurs historiques de 2 km et 90 minutes restent des paramètres
de chargement à confirmer sur les fichiers réels.

Contrôles : clés de profil uniques, profondeur/pression numériques, unités
présentes, codes variables inscrits au dictionnaire et aucune mesure publiée
pour un profil rejeté.

## 6. Étape FILET

Charger `filet_sample`, `filet_analysis`, puis `filet_abundance` en conservant
les valeurs d’abondance déjà normalisées par le fichier. Vérifier la jointure
`SAMPLE_ID + ANALYSIS_ID`, conserver les lignes non appariées et ne pas
recalculer les volumes ou abondances.

## 7. Publication et contrôles finaux

Une version n’est publiée que si :

1. le manifeste et les empreintes sont enregistrés ;
2. les contrôles de chaque source sont passés ;
3. les liens acceptés ont une preuve ;
4. les lignes rejetées ou ambiguës sont comptées ;
5. les vues `explore` retournent le grain annoncé ;
6. les tests de contrat et un échantillon manuel produisent le résultat attendu.

Les erreurs restent dans un rapport de chargement associé à la version. Une
version partiellement chargée reste consultable pour diagnostic, mais n’est pas
marquée comme publiée.

## 8. Première campagne de validation

La première exécution doit utiliser un petit lot EcoTaxa/EcoPart déjà connu,
avec quelques profils CTD et un export FILET de référence. Elle doit comparer
les comptes, les volumes, les profondeurs et les liens aux audits historiques
avant d’élargir au reste de la campagne.
