# Warehouse NeoLab — SQL vers DataFrame

18 septembre 2026 — proposition de cadrage, non déployée.
Cette révision remplace la proposition centrée sur `work.*` et les outils imposés
pour toute exploration. Phase 1 en cours, aucune validation scientifique.

## Parcours cible

Question → agent génère du SQL en lecture seule → résultat chargé dans un
DataFrame du notebook → exploration Python et graphiques. Les relations et
unités sont documentées ; des vues évitent les jointures répétitives. L'agent
peut écrire des JOIN sur les clés déclarées. Les outils déterministes restent
utiles pour les opérations scientifiques délicates : appariement sans clé,
conversion/calcul métier, interpolation ou harmonisation verticale. Leur usage
n'impose pas un système de jobs et résultats dans le warehouse.

Pas de schéma `work` ni de journal d'exploration supplémentaire en V1. Le SQL,
le code et les fichiers restent dans les mécanismes notebook/IDEA existants,
avec référence à la version des données. Aucune reprise automatique de RAM
n'est promise.

## Relations vérifiées dans le code public

Lecture du backend public EcoPart, commit
`4dcd5968bb299b42d2f38406b19b8ca8354503f8` ; cela ne prouve pas la version
utilisée par NeoLab ni la structure de ses exports.

- EcoPart conserve `sample_id`, `sample_name`, `project_id` et des métadonnées
  CTD et EcoTaxa. Il faut conserver identifiants numériques ET identifiants
  originaux, qualifiés par instance/projet.
- Dans `listImportableCTDSamples`, un fichier `<sample_name>.ctd` rejoint
  l'échantillon de même nom dans le projet. L'import conserve ce rattachement.
  Il ne s'agit pas d'une recherche spatiale/temporelle à refaire.
- L'export EcoTaxa utilise le projet EcoTaxa associé, recherche les échantillons
  puis compare exactement `orig_id` au nom demandé pour récupérer `sampleid`.
  Ne pas confondre les identifiants numériques internes des deux plateformes.
- La CTD EcoPart peut être conservée comme série rattachée au profil UVP.
  Ce rattachement ne démontre pas une égalité avec un identifiant de profil du
  catalogue Amundsen ; cette correspondance doit venir des métadonnées réelles.
- Pour FILET, les exports du Bureau confirment la jointure sur
  `SAMPLE_ID + ANALYSIS_ID` : 4 941/5 047 lignes appariées, sans multiplication.
  Le grain d'abondance est sample × analyse × taxon, stades en colonnes.
  Les 106 lignes non appariées restent conservées. Aucun champ CTD/EcoTaxa
  ne prouve encore un lien externe. Voir la [revue des exports](FILET_EXPORT_REVIEW.md).

Sources :
[import CTD](https://github.com/ecotaxa/ecopart_back/blob/4dcd5968bb299b42d2f38406b19b8ca8354503f8/src/domain/repositories/sample-repository.ts),
[liaison et export EcoTaxa](https://github.com/ecotaxa/ecopart_back/blob/4dcd5968bb299b42d2f38406b19b8ca8354503f8/src/domain/repositories/ecotaxa_account-repository.ts).

## Schéma simplifié

Le diagramme complet est dans [docs/WAREHOUSE_ARCHITECTURE.md](WAREHOUSE_ARCHITECTURE.md).

Le [brouillon SQL](warehouse_schema_proposal.sql) décrit les relations centrales :

- `dataset_version` : provenance des exports (source, version, URI, empreinte) ;
- `ecotaxa_sample`, `ecotaxa_object` : échantillons et objets annotés ;
- `uvp_profile`, `uvp_bin`, `uvp_particle` : profils, tranches et spectres ;
- `ctd_profile`, `ctd_measurement` : profils et mesures natives ;
- `ctd_variable` : dictionnaire des codes CTD sources et des unités canoniques
  (`PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`, `pH`, `NTRA`, `FLOR`) ;
- `filet_sample`, `filet_analysis`, `filet_abundance` : prélèvement, analyse,
  observations au grain source ;
- `uvp_ecotaxa`, `uvp_ctd`, `filet_ecotaxa`, `filet_ctd` : uniquement les liens
  explicites connus, avec preuve source, jamais des candidats inventés.

Les clés techniques du warehouse raccourcissent les JOIN. Les clés natives
restent visibles pour retrouver les données et contrôler les relations. Les
liens plusieurs-à-plusieurs ne sont pas aplatis silencieusement. Aucun partenaire
unique n'est imposé sans vérifier la cardinalité dans les données.

Les vues proposées `uvp_ctd`, `filet_data`, `uvp_objects` préparent les chemins
courants tout en gardant leur grain explicite. Une vue UVP/CTD native a une
ligne par lien et mesure CTD : ce n'est pas une concentration par taxon.
Joindre objets et scans CTD par seul profil multiplie les lignes ; une vue
au grain objet/tranche enrichie exige une méthode verticale vérifiée.

Les exports EcoPart consultés ne fournissent pas d'abondance taxonomique UVP.
Ils fournissent notamment `Sampled volume [L]` et les densités LPM par classes
de taille. L'abondance UVP par taxon est donc une variable dérivée du
warehouse : pour un profil et une tranche, compter les objets EcoTaxa retenus
pour le taxon, puis calculer

```text
abundance_uvp_ind_m3 = n_objects_taxon / sampled_volume_l * 1000
```

Le dénominateur est le volume EcoPart de la même tranche ; l'unité doit rester
visible et les bins sans volume, objets hors tranche ou annotations exclues
doivent produire un statut explicite, pas un zéro inventé. Si plusieurs objets
EcoTaxa appartiennent au même taxon, on les compte au grain objet après avoir
fixé le statut d'annotation et la version de taxonomie. Une concentration UVP
ne doit pas être confondue avec les colonnes LPM (`# l-1`) qui décrivent des
classes de taille particulaires.

Côté FILET, les colonnes `*_ABUND (ind./m3 depth vol.)` et
`*_ABUND (ind./m3 flowmeter vol.)` sont déjà normalisées dans l'export NeoLab.
Le warehouse les conserve telles quelles, avec leurs deux dénominateurs et
la colonne `*_SAMPLE_ABUND`; il ne les recalcule pas à l'import. Une vue de
comparaison choisit explicitement la méthode FILET et la variable UVP dérivée.

Les variables CTD sont conservées avec définition, unité et canal. Le catalogue
Amundsen historique est normalisé dans `ctd_variable` : `PRES` (pression/
profondeur), `TE90` (température), `PSAL` (salinité), `SIGT` (densité), `OXYM`
(oxygène), `pH`, `NTRA` (nitrate) et `FLOR` (fluorescence). Les noms demandés
par l'utilisateur sont traduits vers ces codes avant la requête SQL. La pression
CTD et la profondeur dérivée restent distinctes dans la documentation de la
mesure. Les concentrations déjà fournies ne sont pas recalculées.

Le lien EcoTaxa/Amundsen suit la méthode historique retrouvée dans Git :
`ctd_rosette_filename` est comparé au `filename` Amundsen, puis la station, le
temps et la position confirment le candidat. Les seuils historiques de 2 km et
90 minutes sont conservés comme paramètres de méthode, pas comme des constantes
scientifiques universelles. Un candidat non confirmé reste auditable et ne
devient pas une jointure acceptée.

La surface `explore` suit maintenant le parcours utilisateur :

```text
uvp_projects
  → uvp_samples
  → uvp_objects (EcoTaxa + bin/volume EcoPart)
  → uvp_taxon_abundance
  → ecotaxa_ctd_profile / ecotaxa_ctd

filet_samples
  → filet_data / filet_totals
  → filet_ctd
  → filet_uvp_matches / filet_uvp_abundance
```

`uvp_object_bin` enregistre le rattachement objet → bin, son écart de
profondeur et son statut. `taxon_mapping` évite de comparer implicitement deux
identifiants taxonomiques qui ne représenteraient pas le même concept. La vue
de comparaison ne produit des paires d'abondance que pour un mapping accepté.

## Limites et prochaine vérification

DDL illustratif non exécuté, sans ingestion ni connexion notebook. Il ne
représente pas encore tous les champs d'export, taxonomies, unités et règles QC.
Les relations entre versions d'exports doivent être figées dans un manifeste
cohérent pour chaque requête reproductible ; l'automatisation des mises à jour
et les droits par jeu sont à définir avant déploiement.

L'archive `../IDEA-archive-20260911` est absente. Les exports FILET retrouvés sur
le Bureau ont été examinés et joints localement avec pandas. Le schéma FILET
préserve désormais les deux méthodes de volume, les biomasses, les stades et
leurs totaux, et les échantillons regroupant plusieurs filets. Les relations
UVP/EcoPart/EcoTaxa/CTD restent à vérifier sur les exports NeoLab eux-mêmes.
