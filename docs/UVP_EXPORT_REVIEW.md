# Exports UVP retrouvés dans Téléchargements

18 septembre 2026 — inspection en lecture seule, phase 1 de cadrage.

## Recherche de l'ancien projet

L'archive `../IDEA-archive-20260911` n'est pas présente. Le dossier
`/Users/tidianecisse/PROJET_INFO/IDEA` contient des répertoires data, logs,
models et static, mais aucun fichier trouvé récursivement. Les recherches
dans Dev, PROJET_INFO, Desktop, Documents et Downloads n'ont pas retrouvé
l'ancien schéma SQLite. Cela ne prouve pas son absence sur un autre support.

## Références retrouvées

Dossier : `/Users/tidianecisse/Downloads/UVP_metrics_for_MCA`.

- `data/ecotaxa_hawkechannel_30jan.tsv` : 137 128 lignes, 130 colonnes,
  30 valeurs distinctes de `sample_id`.
- `data/ecopart_hawkechannel_30jan.tsv` : 1 946 lignes, 73 colonnes,
  30 valeurs distinctes de `Profile` ; lecture CP1252.
- `Code - UVP_metrics_from_raw_data.R` : sélection des métadonnées et
  jointures aux lignes 56–103.
- Guide d'export et rapport PDF présents, non lus pour cette vérification.
- Autre dictionnaire trouvé dans Downloads :
  `ZooScan_UVP5_Flowcam_fields_in_Ecotaxa_exported_TSV_files.xlsx`, non inspecté.

Empreintes SHA-256 :

- EcoTaxa : `a72b757d9e819bd2bf76e5e24c502e5c79f6496f8e27a9c832b29fc17bfc7853`.
- EcoPart : `beea324b630f81395cd98837d48834f5bed5d97f22e51cf0f14dc3891b9d93fd`.

## Relations confirmées sur ces fichiers

1. Les ensembles EcoTaxa `sample_id` et EcoPart `Profile` sont identiques.
   Il s'agit des identifiants textuels d'export, pas d'une égalité prouvée entre
   IDs numériques internes des applications.
2. Le script R définit le centre de tranche comme
   `floor(object_depth_min / 5) * 5 + 2.5`, puis joint par profil et tranche.
3. La clé EcoPart `(Profile, Depth [m])` est unique dans cet export.
4. Reproduction de cette jointure par pandas avec `validate='many_to_one'` :
   137 128 lignes en sortie, 137 128 appariées, aucune multiplication.
   Ceci vérifie la correspondance avec les lignes EcoPart, pas une validation
   des calculs de concentration, des valeurs de volume ou du protocole complet.
5. Le volume s'appelle `Sampled volume [L]` ; les concentrations particulaires
   utilisent notamment `[# l-1]`. Ne pas renommer ces valeurs en m3 sans
   conversion explicite. Les biovolumes sont également des produits distincts.
6. Le champ `sample_ctdrosettefilename` existe, avec des valeurs telles que
   `HC-02`, mais il est manquant sur 73 145 lignes d'objets. Aucun fichier CTD
   correspondant n'a été vérifié. Ce champ ne prouve pas une correspondance
   directe au catalogue Amundsen ni une disponibilité complète du contexte CTD.

## Conséquence pour le warehouse

Préserver les identifiants de profil exportés et leur portée projet/source.
Charger les tranches EcoPart et exposer le lien objet → tranche dans une vue
documentée, une fois la règle des tranches qualifiée pour chaque export.
Ne pas généraliser des tranches de 5 m à tous les projets.

Cette inspection apporte un exemple réel de jointure EcoTaxa/EcoPart. Elle
ne remplace pas le schéma SQLite historique demandé, toujours non retrouvé,
ni la vérification des clés CTD Amundsen. Aucun DDL ni runtime modifié.
