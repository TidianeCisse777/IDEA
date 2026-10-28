# Exigences FAIR du warehouse

Chaque exigence a un identifiant, une preuve vérifiable et un statut honnête.
Mesure en base : `SELECT * FROM explore.fair_readiness;` (par version) et
`SELECT * FROM explore.fair_column_coverage;` (par table). Ces vues mesurent la
**complétude des métadonnées**, pas la validité scientifique des données.

Légende : ✅ en place et testé · 🟡 structure en place, contenu à produire · ⛔ décision requise.

## Findable

| ID | Exigence | Mise en œuvre | Statut |
|---|---|---|---|
| F1 | Identifiant persistant unique | `dataset_metadata.persistent_identifier`, index unique partiel; obligatoire pour `published` | 🟡 aucun identifiant émis; dépôt à choisir (DMP §8.2) |
| F2 | Métadonnées riches | `dataset_metadata` (titre, description, créateurs, couverture, méthode, licence) | 🟡 fiches `draft` à descriptions provisoires (39 sur l'instance locale au 8 octobre 2026, [PGD](WAREHOUSE_DMP_DRAFT.md)) |
| F3 | Métadonnées citent l'identifiant | `explore.dataset_catalog` expose `dataset_version_id` et `persistent_identifier` | ✅ |
| F4 | Indexées et interrogeables | `explore.dataset_catalog`, `keywords_json` | 🟡 mots-clés vides; indexation externe liée au dépôt ⛔ |

## Accessible

| ID | Exigence | Mise en œuvre | Statut |
|---|---|---|---|
| A1 | Récupérable par protocole standard, ouvert | protocole PostgreSQL + SQL; MCP via DbHub | ✅ |
| A1.2 | Authentification et autorisation | trois rôles, lecture seule, `warehouse_reader` limité à `explore` ([rôles](WAREHOUSE_ROLES.md)) | ✅ testé en réel |
| A1 (donnée) | Conditions d'accès déclarées et appliquées | `access_level` + `access_conditions`; application par contrat, zone et année ([contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md)) | ✅ mécanisme testé; 🟡 tout est `internal`, contrats à renseigner ⛔ |
| A2 | Métadonnées conservées même sans les données | catalogue lisible quel que soit `access_level`; `ON DELETE RESTRICT`; statut `retired` | ✅ ; sauvegarde et restauration ⛔ (DMP §8.4) |

## Interopérable

| ID | Exigence | Mise en œuvre | Statut |
|---|---|---|---|
| I1 | Langage formel et partagé | DDL PostgreSQL, JSON UTF-8, `metadata_standard`, `column_metadata.standard_uri` | 🟡 standard cible non choisi |
| I2 | Vocabulaires FAIR | `column_metadata.vocabulary` et `standard_uri` (unités, variables, taxons) | ⛔ aucun terme renseigné; `fair_column_coverage` mesure l'écart |
| I3 | Références qualifiées vers d'autres données | `related_identifiers_json`; tables de liens avec `match_method` et `evidence` | ✅ liens internes; 🟡 références externes |

## Réutilisable

| ID | Exigence | Mise en œuvre | Statut |
|---|---|---|---|
| R1.1 | Licence claire | `license`, `license_uri`; contrainte `dataset_metadata_publish_gate` | ⛔ licence à décider (DMP §8.3) |
| R1.2 | Provenance | `dataset_file` (SHA-256, URI logique), `validation_run`, `software_version`, `methodology` | ✅ structure; contenu 🟡 |
| R1.3 | Standards de la communauté | `metadata_standard`; correspondance Darwin Core / DataCite à écrire | ⛔ |

La contrainte `dataset_metadata_publish_gate` interdit de passer une version à
`validated` ou `published` sans licence, créateurs, contact et méthode (et sans
identifiant pour `published`) : le catalogue ne peut pas annoncer comme réutilisable
ce qui ne l'est pas.

## Ce qui reste à décider avant de pouvoir dire « FAIR »

Ces points ne se codent pas : dépôt et identifiant persistant, licence et niveau
d'accès par jeu, standard de métadonnées, vocabulaires d'unités et de taxons,
politique de sauvegarde et de restauration. Ils reprennent la section 8 du
[brouillon de PGD](WAREHOUSE_DMP_DRAFT.md). Tant que `fair_readiness.fair_ready`
est faux, aucune version ne doit être présentée comme FAIR.
