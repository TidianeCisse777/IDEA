# Warehouse NeoLab — version 1.0.0

Première version stable du warehouse : schéma, rôles, contrôle d'accès par contrat, zone et année, catalogue
FAIR, connexion des agents par DbHub (Codex, Claude), et déploiement Docker ou sur un PostgreSQL existant.
Le numéro de version est défini à un seul endroit, [`warehouse_release.sql`](warehouse_release.sql), et chaque
déploiement l'enregistre dans la base avec l'empreinte SHA-256 des migrations (`explore.warehouse_release`).

## Contenu

| Domaine | Livré | Guide |
|---|---|---|
| Schéma | EcoTaxa, EcoPart/UVP, FILET, CTD (zone incluse), liens et vues `explore` | [Architecture](WAREHOUSE_ARCHITECTURE.md) |
| Rôles | propriétaire, navigateur, lecteur, comptes personnels, groupes techniques | [Rôles](WAREHOUSE_ROLES.md) |
| Accès | sécurité par ligne forcée sur 23 tables, refus par défaut, `my_access`, `my_datasets` | [Contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md) |
| Agents | DbHub 1.5.0 épinglé, comptes personnels, recette `check`, Codex et Claude | [Connexion](WAREHOUSE_CONNECT.md) |
| FAIR | catalogue, identifiant persistant unique, contrainte de publication, mesure de complétude | [Exigences FAIR](WAREHOUSE_FAIR_REQUIREMENTS.md) |
| Déploiement | Docker en une commande, script rejouable, rapport de préparation, version enregistrée | [Déploiement](WAREHOUSE_DOCKER.md) |

## Déployer

```bash
cp example.warehouse.env .env.warehouse              # remplacer les CHANGER_MOI
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d
#   ou sur un PostgreSQL 16+ existant (base créée, psql et psycopg[binary] disponibles):
set -a; . ./.env.warehouse; set +a
python scripts/deploy_warehouse_postgres.py --check
```

## Vérifier avant d'ouvrir aux comptes

```bash
python scripts/deploy_warehouse_postgres.py --verify     # ne modifie rien
```

La v1 est prête quand la dernière ligne est `PRÊT`. Le rapport contrôle : version enregistrée, rôles présents,
lecteur et navigateur en lecture seule avec délai de 30 s, propriétaire en lecture-écriture, base fermée à
`PUBLIC`, aucun contournement du filtre, sécurité par ligne forcée, contexte MCP publié, vues de découverte
présentes. Deux lignes `NOTE` n'empêchent pas l'ouverture : l'adoption automatique des nouvelles vues (absente sans
superuser) et la cohérence des contrats FILET.

Codes de sortie : `0` prêt, `2` prêt mais métadonnées FAIR incomplètes (attendu en v1), `3` non prêt.

Ensuite, de bout en bout :

```bash
python scripts/warehouse_user.py create essai --source ecotaxa,ecopart --contract C1 --expires-days 7
python scripts/warehouse_connect.py init --from-file data/warehouse_backups/users/essai.env
python scripts/warehouse_connect.py check                 # PASS attendu
python scripts/warehouse_user.py offboard essai           # puis retirer le compte d'essai
```

Avant d'exposer l'interface IDEA (Open WebUI) : `ENABLE_SIGNUP` vaut `true` par défaut dans `docker-compose.yml`.
Créer d'abord le compte administrateur, puis passer `ENABLE_SIGNUP=false`.

## Mettre à jour et revenir en arrière

1. Sauvegarder : `pg_dump -Fc` (voir [Déploiement](WAREHOUSE_DOCKER.md#sauvegarde-et-restauration)).
2. Récupérer la nouvelle version du dépôt, puis `python scripts/deploy_warehouse_postgres.py --check`.
   Les migrations sont additives et rejouables; une base existante n'est jamais réécrite.
3. Comparer `explore.warehouse_release` avant et après (version, empreintes).
4. Retour arrière : restaurer la sauvegarde. Les migrations n'ont pas de script inverse.

Pour publier une nouvelle version : modifier `\set release` dans `warehouse_release.sql` (`1.0.x` correction,
`1.x.0` ajout compatible, `2.0.0` changement incompatible) et consigner le changement dans `ROADMAP.md`.

## Décisions de la v1

| Sujet | Décision | Raison |
|---|---|---|
| Contrat d'accès | porté par la **version** du jeu de données, pour toutes les sources | seule dimension présente partout; `analysis_contract` FILET reste une donnée scientifique. Une version FILET aux contrats mélangés est signalée par le rapport : la charger en une version par contrat |
| Zones et dates inconnues | cachées aux droits bornés, sauf `--include-unknown` | ne jamais ouvrir par défaut ce qui ne peut pas être situé |
| Plusieurs sources | un droit par source; `--source ecotaxa,ecopart` pour les vues UVP | les vues UVP joignent les deux |
| Mot de passe local | fichier privé `600` par défaut; trousseau du système avec `init --keyring` | aucune dépendance imposée, option plus sûre disponible |
| Performance | jointure par fusion désactivée pour les rôles de lecture des agents | mesures dans le [contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md#performance) |

## Risques acceptés

- **Effectifs globaux visibles** : `pg_stat_user_tables`, `pg_class.reltuples` et `EXPLAIN` donnent le nombre
  total de lignes d'une table, hors périmètre compris. `pg_class` doit rester lisible pour que PostgreSQL et
  DbHub fonctionnent, donc ce n'est pas corrigeable dans la base. Aucune valeur ni ligne n'est exposée. Si les
  effectifs sont sensibles pour un partenaire, lui ouvrir une base dédiée contenant seulement ses données.
- **Secret dans l'environnement du processus DbHub** : le DSN y figure le temps de la session, lisible par
  l'utilisateur local du poste seulement.
- **Comptes partagés** : l'identité est le rôle de connexion; ne pas partager un compte entre personnes.

## Validé et non validé

**Validé ici** sur PostgreSQL 16 :
- 92 tests, dont 23 qui interrogent une base réelle (propriétaire superuser et non-superuser, initialisation
  Docker simulée);
- initialisation Docker rejouée sans Docker, dans l'ordre exact du compose, jusqu'à `PRÊT`;
- performance sur 4,8 millions d'objets;
- recette avec un agent Claude Code via le vrai DbHub;
- TLS en local (`require`, `verify-full` avec certificat d'autorité);
- diagnostics de connexion provoqués et vérifiés.

**Non validé** :
- `docker compose up` réel (image PostGIS, service `warehouse-context`), PostGIS et le navigateur spatial;
- Codex et Claude Desktop, Windows pour les scripts de compte et de connexion;
- un serveur distant avec un certificat d'une vraie autorité;
- 15 millions d'objets (extrapolé);
- les données réelles NeoLab.

Ces points sont à cocher lors du premier déploiement sur le serveur cible.
