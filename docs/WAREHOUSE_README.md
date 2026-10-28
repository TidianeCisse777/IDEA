# Warehouse NeoLab — point d'entrée

Base PostgreSQL qui centralise EcoTaxa, EcoPart, FILET et CTD, avec un accès en lecture par compte,
un catalogue de métadonnées et un branchement DbHub pour Codex et Claude. Ce document relie les guides
et donne le parcours complet; le détail est dans chaque guide.

Vocabulaire : une **version de jeu de données** (`dataset_version`) est un chargement identifié d'une source;
un **compte** est un rôle PostgreSQL avec connexion; son **périmètre** est l'ensemble des lignes que ses droits
couvrent (source, contrat, zone, années); le **contexte MCP** est l'ensemble des fiches lues par DbHub.

## Quel guide lire ?

| Je veux… | Guide |
|---|---|
| comprendre ce que contient la base | [Architecture](WAREHOUSE_ARCHITECTURE.md), [diagramme de classes](WAREHOUSE_CLASS_DIAGRAM.md), [dictionnaire MCP](WAREHOUSE_MCP_DICTIONARY.md) |
| **déployer** sur Docker ou sur un PostgreSQL existant | [Déploiement](WAREHOUSE_DOCKER.md) et la section ci-dessous |
| comprendre **qui peut faire quoi** | [Rôles](WAREHOUSE_ROLES.md) |
| limiter un compte à un contrat, une zone, des années | [Contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md) |
| **créer un compte** et le brancher dans Codex ou Claude | [Connexion DbHub](WAREHOUSE_CONNECT.md) |
| savoir où en est la conformité FAIR | [Exigences FAIR](WAREHOUSE_FAIR_REQUIREMENTS.md), [brouillon PGD](WAREHOUSE_DMP_DRAFT.md) |
| lancer le warehouse sans Docker (Windows) | [Version portable](WAREHOUSE_PORTABLE.md) |
| connaître les contrôles de qualité | [Accès et qualification](WAREHOUSE_ACCESS_QUALIFICATION.md) |

## Déployer, de zéro à un compte qui fonctionne

```bash
# 0. Variables (ne jamais commiter .env.warehouse)
cp example.warehouse.env .env.warehouse      # puis remplacer les CHANGER_MOI

# 1. Docker: schéma, migrations, contrôle d'accès, rôles, puis publication du contexte MCP
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d
#    ou, sur un PostgreSQL 16+ existant (base créée au préalable, psql et psycopg[binary] disponibles):
set -a; . ./.env.warehouse; set +a
python scripts/deploy_warehouse_postgres.py --check

# 2. Après chaque chargement de profils CTD: zone marine depuis les coordonnées
python scripts/assign_filet_zones.py --table ctd_profile

# 3. Créer un compte restreint (aucun droit sans option) et obtenir son fichier d'identifiants.
#    Les vues UVP exigent EcoTaxa ET EcoPart.
python scripts/warehouse_user.py create ines --source ecotaxa,ecopart --contract C1 --zone lab \
    --year-min 2018 --year-max 2022 --expires-days 90 --public-host warehouse.exemple.org

# 4. La personne enregistre le fichier reçu et teste (guide de connexion)
python scripts/warehouse_connect.py init --from-file ines.env
python scripts/warehouse_connect.py check
python scripts/warehouse_connect.py config codex      # ou claude-code, claude-desktop
```

Avec Docker, le service ponctuel `warehouse-context` publie le contexte MCP dès que la base est prête; le
relancer après une modification du schéma : `docker compose ... run --rm warehouse-context`.
Le script de déploiement est **rejouable** : une base existante ne reçoit que les migrations additives,
le contrôle d'accès, les rôles et le contexte. À rejouer après toute nouvelle vue `explore`.
Codes de sortie de `--check` : `0` conforme, `2` critères FAIR manquants, `3` écart du contrôle d'accès.

## Rendre la base trouvable

Une personne ou un agent connecté découvre la base dans cet ordre :

1. `explore.my_access` — ce que **ce compte** peut lire (source, contrat, zone, années).
   `explore.my_datasets` — pour chaque version : accès complet, partiel ou aucun, et pourquoi (masqué ≠ absent).
2. `warehouse_context(topic=overview)` puis `topic=<vue>` — contexte métier, grain, limites, exemple SQL.
3. `explore.dataset_catalog` — toutes les versions de jeux de données, y compris hors périmètre (identifiant,
   licence, accès, couverture, méthode). Les métadonnées restent lisibles même quand les données sont restreintes.
4. `explore.warehouse_dictionary` — colonnes, types, définitions et SQL réel des vues.
5. `explore.fair_readiness` et `explore.fair_column_coverage` — ce qui manque pour être FAIR.

## Variables d'environnement

Modèle : [`example.warehouse.env`](../example.warehouse.env).

| Variable | Rôle |
|---|---|
| `WAREHOUSE_POSTGRES_HOST` `_PORT` `_DB` `_USER` `_PASSWORD` | rôle propriétaire: déploiement, comptes, publication du contexte |
| `WAREHOUSE_READER_PASSWORD`, `WAREHOUSE_NAVIGATOR_PASSWORD` | mots de passe des deux rôles de service, pivotés à chaque déploiement |
| `WAREHOUSE_NAVIGATOR_PORT` | port de l'interface de navigation (8090) |
| `WAREHOUSE_PUBLIC_HOST`, `WAREHOUSE_PUBLIC_PORT` | adresse inscrite dans les fichiers d'identifiants |
| `WAREHOUSE_DB_HOST` `_PORT` `_NAME` `_USER` `_PASSWORD` `_SSLMODE` | côté utilisateur, lus dans son fichier d'identifiants |
| `WAREHOUSE_DB_SSLROOTCERT`, `WAREHOUSE_DB_EXPIRES` | certificat d'autorité du serveur (`verify-full`) et date d'expiration du mot de passe |
| `NEOLAB_WAREHOUSE_CREDENTIALS` | chemin du fichier d'identifiants de l'utilisateur (défaut hors dépôt) |
| `WAREHOUSE_TEST_LIVE=1` | active les tests sur PostgreSQL réel (avec `PGHOST` `PGPORT` `PGUSER` `PGPASSWORD`) |

## Sécurité en bref

- Aucun secret dans Git, dans une configuration MCP, un argument de commande ni une sortie.
- Refus par défaut : un compte sans droit explicite ne lit aucune ligne.
- Ne pas publier le port PostgreSQL sur Internet : tunnel SSH ou TLS.
- Les fichiers d'identifiants générés sont à remettre par un canal sûr puis supprimer.

## Tests

```bash
python -m unittest tests.test_warehouse_schema tests.test_warehouse_context     # sans serveur
WAREHOUSE_TEST_LIVE=1 PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=... \
  python -m unittest tests.test_warehouse_roles_fair tests.test_warehouse_connect  # PostgreSQL réel
```

## État de validation

Validé sur PostgreSQL 16 avec le vrai DbHub 1.5.0 (comptes, filtrage, rotation, révocation) et `claude mcp list`.
Performance mesurée sur 4,8 M d'objets (requêtes d'un compte restreint entre 0,4 et 6,8 s,
[détail](WAREHOUSE_ACCESS_CONTROL.md#performance)).
**Non validé** : le démarrage `docker compose` lui-même (dont le service `warehouse-context`), PostGIS et le
navigateur spatial, Codex, Claude Desktop, Windows pour les scripts d'administration et de connexion, un serveur
distant réel (TLS vérifié en local seulement), le volume réel de 15 M d'objets (extrapolé).
Le warehouse n'est **pas FAIR** : identifiant persistant, licence, niveaux d'accès et vocabulaires restent à décider.
