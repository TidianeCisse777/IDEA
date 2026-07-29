# Chaîne filet–UVP–EcoPart certifiée

## Objectif

Permettre une chaîne de tools composables, utilisable sur un ou plusieurs tours :

1. auditer une table filet entière ou une sous-sélection persistée ;
2. ne retenir que les samples UVP dont `join_eligible=True` après validation du
   nom de fichier CTD avec Amundsen ;
3. exporter ces samples EcoTaxa, éventuellement répartis entre plusieurs projets ;
4. enrichir chaque sous-ensemble EcoTaxa avec son projet EcoPart lié ;
5. joindre localement les données filet et UVP enrichies à partir de l'audit
   certifié, pour préparer les calculs d'abondance.

Il ne s'agit pas d'un tool « one shot ». Chaque étape produit un artefact nommé,
persistant et réutilisable ; seule l'exportation distante exige une confirmation.

## État actuel et lacune

`find_uvp_matches_for_net_table` persiste déjà l'audit complet
`df_net_uvp_matches`. Il exige une correspondance spatiale et temporelle puis
certifie le nom de fichier CTD-rosette contre les métadonnées Amundsen. Seules
les lignes `join_eligible=True` sont utilisables pour une jointure d'abondance.

`export_ecotaxa_samples` sait déjà exporter une sélection de samples répartie
sur plusieurs projets : il les groupe par projet, demande confirmation, puis
produit une table EcoTaxa consolidée qui porte `export_project_id`.

En revanche, l'audit ne crée pas aujourd'hui de sélection EcoTaxa exportable.
De plus, `enrich_ecotaxa_with_ecopart_remote` traite une unique table EcoTaxa
et un unique projet EcoPart. Appliqué à une exportation consolidée, son
résolveur peut choisir un seul projet EcoPart pour plusieurs projets EcoTaxa.

## Contrat des tools

### Audit filet ↔ UVP

`find_uvp_matches_for_net_table` reste le point d'entrée de vérification. Il
accepte `net_variable_name`, donc il doit consommer indistinctement le fichier
filet chargé ou une sous-sélection persistée, par exemple après filtrage
géographique Baie de Baffin et temporel 2024. Les bornes `date_from` et
`date_to` restent appliquées par l'audit et doivent être rapportées.

L'audit conserve son DataFrame de diagnostic complet, incluant les lignes non
certifiées, mais persiste également une sélection EcoTaxa nommée et traçable :

- seule source d'IDs : `uvp_sample_id` des lignes `join_eligible=True` ;
- déduplication par `uvp_project_id`, `uvp_sample_id` ;
- métadonnées : variable filet source, période, nombre de correspondances,
  projets EcoTaxa, statut CTD et libellé descriptif ;
- aucune sélection exportable n'est créée lorsque le résultat certifié est vide
  ou quand la validation CTD Amundsen est indisponible.

La réponse distingue explicitement l'audit exhaustif de la sélection certifiée
et indique le nom de cette dernière, prête pour l'export.

### Export EcoTaxa

L'export réutilise `export_ecotaxa_samples(selection_name=..., confirmed=...)`.
Le premier appel est un dry-run ; après confirmation, tous les samples certifiés
sont exportés et regroupés automatiquement par projet EcoTaxa. Le DataFrame
consolidé garde `export_project_id`, `selection_name`, la couverture
complète/partielle et la provenance de l'audit qui l'a produit.

Les erreurs d'un projet n'annulent pas les projets réussis, mais rendent la
couverture partielle visible et empêchent de présenter la chaîne comme complète.

### Enrichissement EcoPart multi-projets

L'enrichissement distant reçoit la table consolidée exportée. Il la partitionne
sur `export_project_id`; pour chaque partition :

1. résout le projet EcoPart par le lien serveur EcoTaxa↔EcoPart ;
2. effectue l'export EcoPart confirmé ;
3. joint les objets à EcoPart sur la clé existante `(sample_id, depth_bin 5 m)` ;
4. conserve les bins EcoPart échantillonnés sans objet et n'invente aucun volume.

Les partitions enrichies sont concaténées dans un DataFrame nommé unique. Chaque
ligne garde `export_project_id`, `ecopart_project_id` et une provenance par
partition. Une partition sans lien EcoPart, sans profil commun ou en erreur est
rapportée séparément; elle ne peut pas contribuer aux calculs d'abondance. Le
résultat est explicitement partiel dans ce cas.

Le comportement mono-projet actuel demeure compatible pour les fichiers EcoTaxa
locaux et les appels ciblant un unique projet.

### Jointure filet ↔ UVP enrichi

Un nouveau tool local joint la table fichier filet et le DataFrame UVP enrichi
en s'appuyant obligatoirement sur l'audit `df_net_uvp_matches`. Il ne doit jamais
recalculer une proximité, une date ou une similarité de station.

Il filtre d'abord l'audit à `join_eligible=True`, relie le déploiement filet au
sample/profil UVP certifié, puis rattache ce pont à la table UVP enrichie. La
sortie conserve les identifiants du filet, du sample UVP, des deux projets, la
preuve CTD et les clés de profondeur. Elle constitue un artefact préparatoire :
les métriques d'abondance restent calculées par les contrats existants
(`build_canonical_sample_depth`, puis calculs explicitement demandés).

## Erreurs et garde-fous

- `join_eligible=False` est strictement exclu de la sélection, de l'export et
  de la jointure finale ; les lignes restent disponibles uniquement dans l'audit.
- Indisponibilité Amundsen : résultat d'audit sans sélection certifiée ; aucune
  absence de données UVP/CTD n'est inférée.
- Sous-sélection filet vide, absence de latitude/longitude ou de date exploitable :
  diagnostic explicite, aucune table de chaîne trompeuse.
- Le téléchargement EcoPart demeure une opération confirmée. L'export EcoTaxa
  est déjà confirmé séparément ; l'enrichissement peut donc avoir son propre
  dry-run et sa confirmation avant les téléchargements EcoPart.
- Toute métrique doit signaler les partitions non enrichies, les volumes
  manquants et la couverture effective ; aucune valeur scientifique n'est créée
  par les tools.

## Tests

Tests unitaires à ajouter avant le code :

1. audit d'une sous-sélection filet nommée : seuls les `uvp_sample_id` certifiés
   deviennent une sélection exportable, avec les métadonnées de périmètre ;
2. absence de certification CTD : pas de sélection exportable ;
3. export de cette sélection : groupement multi-projets et conservation de la
   provenance de l'audit ;
4. enrichissement d'une exportation à deux projets : résolution, téléchargement
   et jointure par partition puis concaténation avec les deux project IDs ;
5. échec ou absence EcoPart pour une partition : résultat partiel explicite,
   aucune donnée de volume inventée ;
6. jointure finale : elle refuse un audit sans ligne certifiée et n'associe les
   données qu'au moyen des identifiants présents dans l'audit certifié ;
7. régression mono-projet : les workflows EcoTaxa↔EcoPart actuels restent verts.

Les suites ciblées sont `tests/test_copepod_sources.py`,
`tests/test_ecopart_sources.py`, `tests/test_enrichment_workflows_integration.py`
et une nouvelle suite dédiée à la chaîne filet–UVP si le scénario devient trop
grand pour les tests existants.
