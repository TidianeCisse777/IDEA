# Décision de support du warehouse

## Décision

Le warehouse NeoLab V1 utilise **PostgreSQL avec l’extension PostGIS**.
PostgreSQL est la source de vérité pour les données structurées, les liens, les
statuts de qualité et les vues `explore`. PostGIS est utilisé pour affecter les
samples aux zones maritimes à partir de leurs coordonnées.

Les fichiers bruts CSV/TSV/JSON et les exports Parquet restent conservés dans
un stockage de fichiers. Ils sont référencés par `warehouse.dataset_version`
avec leur URI, leur version et leur empreinte SHA-256. Ils ne sont pas remplacés
par des blobs SQL.

## Pourquoi PostgreSQL

- contraintes `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE` et `CHECK` pour protéger
  les grains et les relations scientifiques ;
- jointures robustes entre EcoTaxa, EcoPart, CTD et FILET ;
- vues et vues matérialisées pour fournir du SQL simple à l’agent ;
- `JSONB` pour les champs libres EcoTaxa sans perdre la structure principale ;
- index sur projets, samples, stations, dates, taxons et profils CTD ;
- fonctions d’agrégation, fenêtres et CTE pour les abondances par profil et par
  zone ;
- chargement performant par `COPY` ou tables de staging ;
- accès concurrent pour plusieurs notebooks et agents ;
- intégration directe avec pandas, SQLAlchemy et les outils de notebook.

## Pourquoi PostGIS

PostGIS permet d’utiliser les géométries des zones maritimes et de versionner
la règle d’affectation. L’ingestion transforme les coordonnées du sample en
point géographique, exécute une jointure point-dans-polygone et stocke le
résultat :

```text
ARCTIQUE_CANADIEN
HORS_ARCTIQUE_CANADIEN
```

La source des polygones et leur version sont conservées avec le sample. Une
requête utilisateur lit `marine_zone_key` ; elle ne recalcule pas la géométrie.

## Architecture de stockage

```text
fichiers bruts / Parquet
        ↓ téléchargement vérifié + SHA-256
staging PostgreSQL
        ↓ contrôles de format et de cardinalité
warehouse PostgreSQL + PostGIS
        ↓ vues SQL stables
explore → DataFrame du notebook
```

Les tables de staging sont temporaires ou versionnées et ne sont jamais
présentées directement à l’agent. Les tables `warehouse` gardent les clés
natives, la provenance et les statuts. Les vues `explore` exposent les grains
destinés à l’exploration.

## Rôle des autres supports

- **SQLite** : cache historique EcoTaxa ou reprise locale, pas source de vérité
  du warehouse.
- **Parquet** : conservation des exports volumineux et échanges avec pandas ou
  DuckDB.
- **DuckDB** : analyse locale optionnelle d’un extrait, sans remplacer
  PostgreSQL ni les liens validés.

## Pré-requis de déploiement

1. PostgreSQL avec PostGIS activé ;
2. rôles séparés pour ingestion, lecture warehouse et lecture `explore` ;
3. migrations versionnées du DDL ;
4. sauvegarde de la base et du stockage brut ;
5. index spatiaux sur les géométries de zones et index relationnels sur les
   identifiants de navigation ;
6. contrôle de santé après chaque chargement.

Cette décision ne lance pas encore de téléchargement. Le plan suivant doit
détailler les sources autorisées, les URLs ou clients, les répertoires de
staging, les manifestes, les reprises et l’ordre de peuplement.
