# Stockage persistant du warehouse

Le warehouse NeoLab est identifié par le conteneur `neolab-warehouse-db`, le
volume Docker `neolab_warehouse_pgdata` et la base PostgreSQL
`neolab_warehouse`. Le port hôte par défaut est `55432` afin de ne pas entrer
en collision avec un PostgreSQL local.

## Démarrage

Copier `example.warehouse.env` vers `.env.warehouse` (ignoré par Git) et remplacer les valeurs
`CHANGER_MOI` : le mot de passe propriétaire, ceux du lecteur et du navigateur sont tous requis.

Puis lancer :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d
```

Le volume est persistant. Les scripts SQL (schéma, migrations, contrôle d'accès, rôles) ne
sont exécutés qu'à la première initialisation du volume vide. Le service ponctuel
`warehouse-context` attend que la base soit prête (contrôle `pg_isready` en TCP, qui n'aboutit
qu'après les scripts d'initialisation) puis publie le contexte MCP. Le relancer après une
modification du schéma :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml run --rm warehouse-context
```

Pour mettre à jour un volume existant, rejouer `python scripts/deploy_warehouse_postgres.py` :
il applique seulement les migrations additives, le contrôle d'accès, les rôles et le contexte.
Vue d'ensemble : [WAREHOUSE_README.md](WAREHOUSE_README.md).

## Sauvegarde et restauration

Sauvegarde recommandée :

```bash
pg_dump -Fc --no-owner --no-acl \
  postgresql://localhost/postgres \
  > data/warehouse_backups/neolab_warehouse.dump
```

Restauration dans le conteneur :

```bash
pg_restore --clean --if-exists --no-owner --no-acl \
  -d postgresql://neolab:${WAREHOUSE_POSTGRES_PASSWORD}@localhost:55432/neolab_warehouse \
  data/warehouse_backups/neolab_warehouse.dump
```

Les dumps et le fichier `.env.warehouse` ne doivent jamais être commités.

## Accès lecture pour un agent ou DbHub

La [procédure d'accès et de qualification](WAREHOUSE_ACCESS_QUALIFICATION.md)
décrit le diagnostic reproductible, les variables lecteur et la recette MCP.

Le rôle `warehouse_reader` est séparé du rôle de chargement `neolab`. Il peut
lire les 16 vues du schéma `explore` (`uvp_projects`, `uvp_samples`,
`uvp_objects`, `uvp_ctd`, `filet_samples`, `filet_uvp_matches`, etc.) et ne
peut pas lire les tables brutes `warehouse`, écrire dans la base ou créer des
objets. Sa transaction est en lecture seule et son délai est limité à 30 s.

Les paramètres locaux et le mot de passe sont conservés dans
`data/warehouse_backups/warehouse_reader.env`, ignoré par Git. Pour un DbHub
sur l’ordinateur hôte, utiliser `127.0.0.1:55432`, la base
`neolab_warehouse` et l’utilisateur `warehouse_reader`. Un DbHub exécuté dans
un autre conteneur doit utiliser le réseau Docker ou un tunnel ; le port
PostgreSQL ne doit pas être publié sur Internet.

Le dump de référence créé le 8 octobre 2026 est
`data/warehouse_backups/neolab_warehouse_20261008.dump`. Il est au format
custom PostgreSQL 16 et a été vérifié avec `pg_restore` dans le conteneur
`neolab-warehouse-db`. Le SHA-256 est conservé dans le journal d’exécution,
pas dans Git.

## Déploiement sur un PostgreSQL existant

Pour un serveur PostgreSQL 16+ déjà en place (hors Docker), une seule commande
crée le schéma, applique les migrations (FAIR, contrôle d'accès) et provisionne les rôles :

```bash
WAREHOUSE_POSTGRES_HOST=... WAREHOUSE_POSTGRES_PASSWORD=... \
WAREHOUSE_READER_PASSWORD=... WAREHOUSE_NAVIGATOR_PASSWORD=... \
python scripts/deploy_warehouse_postgres.py --check
```

Le script est rejouable : une base existante ne reçoit que les migrations
additives et les rôles. `--dry-run` liste les étapes, `--check` rapporte les
critères FAIR manquants (code de sortie 2 s'il en manque). La base doit exister et
`psql` être disponible; PostGIS est requis seulement par le navigateur spatial.
Le script publie aussi le contexte MCP (nécessite `psycopg[binary]`). Détails : [rôles](WAREHOUSE_ROLES.md), [exigences FAIR](WAREHOUSE_FAIR_REQUIREMENTS.md), [brancher DbHub](WAREHOUSE_CONNECT.md).

Le fichier `.env.warehouse` contient maintenant aussi `WAREHOUSE_READER_PASSWORD`
et `WAREHOUSE_NAVIGATOR_PASSWORD`. Les rôles ne sont créés qu'à la première
initialisation du volume; sur un volume existant, relancer le script ci-dessus.
