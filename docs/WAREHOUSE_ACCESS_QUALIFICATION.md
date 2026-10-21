# Accès et qualification du warehouse

## Écart spatial FILET–UVP dans le navigateur

Le mode comparaison propose un écart spatial maximal en kilomètres, cumulable
avec le seuil temporel. Un champ vide conserve toutes les distances; zéro
sélectionne les coordonnées identiques. Le même paramètre API `max_distance_km`
s'applique à `/api/filet-uvp`, `/api/map` et `/api/coverage` (ces deux dernières
routes l'appliquent avec `matched_only=true`). Les valeurs négatives ou non
finies sont refusées. La fiche de comparaison affiche `distance_km`.

La distance est géodésique WGS84, calculée par PostGIS `ST_Distance` sur des
points `geography`, puis convertie de mètres en kilomètres. Les coordonnées
absentes restent exclues de la carte. Ce filtre réduit les paires stockées :
il ne génère pas de candidats par proximité et ne requalifie pas les ambiguïtés.
La fenêtre temporelle demeure limitée par les correspondances déjà chargées.
Le seuil spatial doit être ressaisi après rechargement de la page.

## Contrat et état de validation — 21 octobre 2026

Ce chantier concerne les phases 1 et 2 du [plan](../ROADMAP.md).
Le schéma versionné et les preuves historiques ne remplacent pas une mesure
live. Ce checkout ne contient ni configuration locale du warehouse ni serveur
DbHub configuré. La connexion MCP à Codex reste à effectuer sur la machine
disposant du service et des credentials lecteur.

## Documentation de référence

| Sujet | Référence et grain |
|---|---|
| Tables, clés, relations | [Diagramme de classes](WAREHOUSE_CLASS_DIAGRAM.md) |
| Sources et versions | `warehouse.dataset_version` : une version de dataset, manifeste et empreinte |
| Catalogue descriptif | [Migration métadonnées](warehouse_metadata_migration.sql) : datasets, fichiers, colonnes et validations |
| EcoTaxa / EcoPart | [Contrat EcoPart](WAREHOUSE_ECOPART.md) : objets, profils, bins, volumes en litres et abondances dérivées |
| FILET | [DDL](warehouse_schema_proposal.sql) : échantillon, analyse, ligne source × taxon × stade |
| Calculs et usages | [Cas SQL](UVP_USE_CASES_SQL.md) et [frictions](UVP_FRICTIONS_OPEN.md) |
| Connexion et stockage | [Procédure Docker](WAREHOUSE_DOCKER.md) |

Les abondances FILET depth et flowmeter et les biomasses restent distinctes.
Les stades agrégés ne doivent pas être additionnés à leurs sous-stades.
Le catalogue contient un champ `taxonomic_scope`; sa présence dans le DDL
ne prouve ni son remplissage ni la validation des annotations des objets.
Les graphiques et calculs documentés dans les cas SQL sont des usages proposés;
ils ne constituent pas un inventaire de graphiques effectivement produits.

## Connexion reproductible en lecture seule

Prérequis : Python 3.10+, `psycopg[binary]`, PostgreSQL démarré et rôle
`warehouse_reader` provisionné selon la procédure Docker. Fournir via
l'environnement `WAREHOUSE_READER_PASSWORD`, et au besoin
`WAREHOUSE_READER_HOST`, `WAREHOUSE_READER_PORT`, `WAREHOUSE_READER_DB`.
Ne pas utiliser le mot de passe du rôle d'ingestion. Aucun secret n'est passé
sur la ligne de commande ou inclus dans le rapport.

```bash
python scripts/audit_warehouse.py
python scripts/audit_warehouse.py --qualify
```

Le premier appel inventorie les colonnes `explore` accessibles. Le second
déclenche explicitement un scan potentiellement lourd, limité à 30 secondes
par requête. Les rapports JSON peuvent être conservés sous `data/` (ignoré).
Code de sortie : 0 diagnostic effectué, 1 erreur technique, 2 vues nécessaires
absentes ou inaccessibles. `measured` signifie mesuré, pas scientifiquement validé.

Pour DbHub/MCP, configurer le même rôle lecteur avec un secret local et le
serveur MCP retenu. Depuis l'hôte : `127.0.0.1:55432`; depuis un conteneur,
utiliser le réseau Docker approprié. Aucun serveur ou paquet MCP n'est
installé automatiquement par ce script. Vérifier ensuite depuis le client :

```sql
SELECT current_user, current_database();
SHOW transaction_read_only;
SELECT table_name FROM information_schema.views WHERE table_schema = 'explore';
```

La recette doit également confirmer les refus de lecture `warehouse.*` et
d'écriture avec ce rôle. La lecture seule de transaction ne remplace pas les
privilèges PostgreSQL. Aucun accès MCP fonctionnel n'est revendiqué avant recette.

## Qualification taxonomique

L'audit sépare identifiant taxonomique, libellé et statut d'annotation manquants,
y compris les chaînes vides. Les comptes UVP sont dédupliqués par identifiant
d'objet dans chaque version afin de ne pas compter deux fois les liens aux bins.
Ils portent uniquement sur les objets exposés par `explore.uvp_objects`, pas sur
tout EcoTaxa. Les lignes FILET sont comptées au grain taxon × stade; les nombres
ne sont donc pas directement comparables aux comptes d'objets UVP.

`analysis_contract` est un champ source FILET : son absence est mesurée
séparément des liens de métadonnées manquants. Le besoin « différencier données
contrats » reste à préciser avant d'introduire une règle de séparation.
Aucune équivalence taxonomique FILET–UVP n'est déduite d'un nom ou identifiant.
Un résultat vide ne signifie pas couverture complète; une vue inaccessible
est signalée explicitement et ne devient jamais un compteur à zéro.
