# Brouillon de plan de gestion des données (PGD / DMP)

**Projet :** Warehouse NeoLab - Université Laval
**Version :** brouillon 0.1
**Audit technique :** 8 octobre 2026
**Statut :** à valider par l'équipe scientifique et la Bibliothèque

Ce document est une base de travail pour l'Assistant PGD de l'Université
Laval. Il ne remplace pas le formulaire institutionnel ni les arbitrages sur
le partage, la licence, la conservation et les coûts.

## 1. Résumé et périmètre

Le warehouse NeoLab est une base PostgreSQL/PostGIS qui centralise les données
marines EcoTaxa, EcoPart, Amundsen/CTD et FILET. Il conserve les clés natives,
les références de fichiers, les versions de jeux de données, les relations
d'appariement et les tables dérivées utilisées par IDEA.

Le périmètre V1 comprend les profils UVP, bins et particules EcoPart, objets
EcoTaxa, profils et mesures CTD, échantillons et abondances FILET, ainsi que
les liens UVP-EcoTaxa, UVP-CTD, EcoTaxa-CTD, FILET-CTD et FILET-UVP. Les vues
`explore.*` sont une surface de lecture calculée, pas une seconde copie source.

## 2. Inventaire observé

Audit en lecture seule de l'instance locale le 8 octobre 2026 :

| Collection | Grain | Volume observé | Provenance actuelle |
|---|---|---:|---|
| EcoTaxa | sample puis objet | 6 138 samples; 15 050 002 objets | API/projet, version et SHA-256 |
| EcoPart / UVP | profil x bin | 585 profils; 59 801 bins; 10 479 780 objets mappés | ZIP, manifeste, lignes source |
| CTD Amundsen | profil x mesure | 380 profils dans la couverture | URL ERDDAP, version et clé de ligne |
| FILET | sample puis analyse x taxon x stade | 6 102 samples; 1 502 analyses; 4 941 lignes source | trois CSV, version et empreinte |
| Correspondances | paire ou match documenté | 783 UVP-EcoTaxa; 413 UVP-CTD; 418 FILET-UVP | statut, méthode et preuve |

Ces chiffres sont des constats de l'instance locale et doivent être recalculés
à chaque version publiée.

## 3. Métadonnées à gérer

Les métadonnées doivent être séparées en quatre niveaux. Une description
générale ne doit pas être répétée dans chaque ligne scientifique et une valeur
manquante ne doit pas être inventée.

### 3.1 Jeu de données / version

À rattacher à `warehouse.dataset_version` ou à une table 1:1 : titre,
description, créateurs, laboratoire, projet, contact, source, URL/API, dates de
collecte et de téléchargement, couvertures temporelle/spatiale/taxonomique,
format original, méthode, protocole, version logicielle, licence, restrictions,
identifiant persistant, version du schéma, journal des changements et SHA-256.

### 3.2 Fichier / artefact source

Pour chaque CSV, TSV, ZIP ou export API : nom stable, type MIME, taille,
empreinte SHA-256, URL ou identifiant de tâche, date de récupération, outil et
version de production, et lien vers `dataset_version`. Les chemins absolus
locaux `/Users/...` ne doivent pas être publiés : utiliser une URI logique ou
un emplacement de dépôt.

### 3.3 Variable / colonne

Le dictionnaire de données doit fournir nom canonique, nom source, définition,
unité, type, valeurs admissibles, règle de valeur manquante, grain, clé,
méthode de calcul, transformation, provenance et statut (`source`, `copie`,
`dérivée`, `contrôle qualité`). Les unités doivent distinguer litres/mètres
cubes, profondeur, pression et abondances normalisées.

### 3.4 Observation / relation

Les tables de liaison conservent la preuve et le statut. Une relation acceptée,
ambiguë, rejetée ou non résolue doit rester distinguable. `source_evidence`,
`match_method`, `evidence`, `mapping_status` et
`marine_zone_assignment_status` sont donc des métadonnées scientifiques.

## 4. État actuel et lacunes mesurées

### EcoTaxa

- 6 137/6 138 samples ont une date; 3 944/6 138 sont géolocalisés;
- 3 383 ont une station et 3 297 une campagne;
- `free_fields_json` est présent pour 6 138/6 138 samples;
- `instrument` est renseigné pour 0/6 138 samples;
- `annotation_status` est renseigné pour 0/15 050 002 objets;
- `image_uri` est renseigné pour 0/15 050 002 objets.

Le JSON libre est conservé, mais il faut en extraire un dictionnaire contrôlé.
Les objets ne doivent pas être présentés comme validés biologiquement si le
statut d'annotation n'est pas présent.

Le contrôle du JSON montre 70 noms de champs distincts sur 6 118 samples ayant
au moins une clé. Les champs `ship`, `stationid`, `cruise`, `profileid`,
`uvpmodel`, `model` et `ctdrosettefilename` existent dans ce JSON, mais ils ne
sont pas tous normalisés dans les colonnes canoniques. Il faut donc conserver le
JSON brut et documenter les règles d'extraction champ par champ.

### EcoPart

- `ecopart_bin_source.source_row_json` conserve une ligne source pour chacun
  des 59 801 bins;
- `ecopart_auxiliary_row` conserve 585 lignes `metadata` et 3 535 lignes
  `zooplankton`, avec les noms de membres et les numéros de lignes;
- les métadonnées source incluent notamment `Profile`, `Rawfilename`, la date,
  `Depth [m]`, `Sampled volume [L]` et les champs taxonomiques/biovolumes.

EcoPart fournit donc une source complémentaire utile pour les profils UVP, mais
elle ne doit pas être utilisée pour remplir un sample EcoTaxa sans lien prouvé.
Quand EcoTaxa n'a pas une métadonnée, le catalogue doit indiquer `missing` ou
`not_provided`, avec la source interrogée et la date du contrôle.

### FILET

- 6 102/6 102 samples ont date, coordonnées, station, plateforme, engin, type
  de trait, zone maritime et identifiants de filets;
- le volume calculé par profondeur est présent pour 4 483/6 102 samples;
- le volume flowmeter est présent pour 2 377/6 102 samples;
- les 1 502 analyses ont type, contrat, protocole et date renseignés.

Les deux volumes doivent rester séparés et leur dénominateur doit être
documenté. Les manquants ne doivent pas être imputés sans décision scientifique.

## 5. Cycle de vie et contrôles

1. **Acquisition :** conserver l'export original, son URI, son identifiant de
   tâche ou de projet, sa date et son SHA-256.
2. **Staging :** vérifier encodage, colonnes attendues, grain, unités et
   doublons sans modifier le fichier brut.
3. **Chargement :** créer une nouvelle `dataset_version`; ne pas écraser une
   version utilisée par une analyse publiée.
4. **Validation :** comparer clés, dates, positions, profondeurs, volumes et
   statuts avec la source; conserver le rapport.
5. **Dérivation :** versionner requête/code, commit, formule et dénominateur;
   distinguer données source et dérivées.
6. **Diffusion :** publier un extrait avec dictionnaire, provenance, licence et
   limites selon les règles d'accès approuvées.
7. **Préservation :** conserver bruts, manifestes, schéma, scripts et résultats
   qui soutiennent une publication.

## 6. Standards, accès et préservation

- PostgreSQL/PostGIS pour le warehouse actif;
- CSV UTF-8 ou Parquet pour les exports, avec schéma explicite;
- JSON UTF-8 pour manifestes et provenance machine;
- dictionnaire de données tabulaire versionné avec le DDL;
- profil de métadonnées du dépôt confirmé par la Bibliothèque et le dépôt
  choisi;
- identifiant persistant reliant publication, code et version publiée lorsque
  le dépôt le permet.

Le rôle IDEA reste strictement en lecture. Les secrets, jetons, chemins locaux
et configurations ne doivent jamais figurer dans les métadonnées. Avant toute
diffusion, vérifier restrictions contractuelles, coordonnées sensibles et
règles applicables aux données autochtones ou partagées. Le volume PostgreSQL
local n'est pas à lui seul une stratégie de préservation : fréquence des
sauvegardes, copies, chiffrement, test de restauration, durée et responsable
doivent être décidés.

## 7. Contrat de métadonnées proposé

Ajouter un catalogue séparé plutôt que d'élargir chaque ligne de
`filet_sample` ou `ecotaxa_sample` :

- `warehouse.dataset_metadata` : description, créateurs, contact, licence,
  couverture, méthode, accès et identifiant de publication par version;
- `warehouse.dataset_file` : fichier source, URI logique, format, taille,
  SHA-256, récupération et rôle;
- `warehouse.column_metadata` : définition, unité, source, transformation et
  règles de valeurs manquantes par table/colonne;
- `warehouse.validation_run` : version testée, outil, commit, date, résultat,
  rapport et anomalies;
- extension contrôlée de `dataset_version` si nécessaire : `title`,
  `description`, `retrieved_at`, `schema_version`, `license`, `access_level`.

La migration SQL doit attendre l'accord sur les noms, la licence, les rôles,
le dépôt et la conservation.

Le contrat proposé est maintenant écrit dans
`docs/warehouse_metadata_migration.sql`. Il est additif et ne modifie aucune
valeur scientifique existante. Il doit être appliqué à chaque nouvelle base
avec le DDL initial; l'instance locale existante doit recevoir la migration
explicitement et être contrôlée par les tests. Il est maintenant appliqué à
l'instance locale : 39 fiches `dataset_metadata` et 39 fiches `dataset_file`
ont été créées à partir des versions déjà présentes. Les fiches sont en statut
`draft`; le dictionnaire `column_metadata` reste à curer.

## 8. Décisions à prendre

1. Nom officiel, responsables et contact des données.
2. Dépôt de diffusion et identifiant persistant.
3. Licence et niveau d'accès pour bruts, dérivés et cartes.
4. Conservation, fréquence de sauvegarde et test de restauration.
5. Source scientifique des métadonnées EcoTaxa manquantes (`instrument`,
   annotation, images).
6. Politique pour les 1 619 samples FILET sans volume profondeur et les 3 725
   sans volume flowmeter.
7. Vocabulaire contrôlé des unités, taxons, stades, zones et statuts.

## Références

- [Bibliothèque de l'Université Laval - Gestion des données de recherche](https://bibl.ulaval.ca/services/soutien-a-ledition-savante-et-a-la-recherche/gestion-des-donnees-de-recherche)
- [Université Laval - Gestion et valorisation des données](https://www.services-recherche.ulaval.ca/gestion-et-valorisation-des-resultats-de-recherche/gestion-des-donnees-de-recherche)
- [Assistant PGD de l'Alliance](https://assistant.portagenetwork.ca/)

## Preuves techniques

- `docs/warehouse_schema_proposal.sql` et migrations additives;
- `docs/WAREHOUSE_ECOTAXA_QA.md`, `docs/WAREHOUSE_ECOPART.md` et
  `docs/FILET_EXPORT_REVIEW.md`;
- requêtes en lecture seule de l'instance locale `neolab_warehouse` le
  8 octobre 2026.
