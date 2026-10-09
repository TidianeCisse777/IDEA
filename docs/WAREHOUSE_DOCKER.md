# Stockage persistant du warehouse

Le warehouse NeoLab est identifié par le conteneur `neolab-warehouse-db`, le
volume Docker `neolab_warehouse_pgdata` et la base PostgreSQL
`neolab_warehouse`. Le port hôte par défaut est `55432` afin de ne pas entrer
en collision avec un PostgreSQL local.

## Démarrage

Créer un fichier `.env.warehouse` local (ignoré par Git) :

```env
WAREHOUSE_POSTGRES_PASSWORD=choisir-un-mot-de-passe-local
```

Puis lancer :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d
```

Le volume est persistant. Le script SQL est utilisé uniquement à la première
initialisation du volume vide.

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
