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
