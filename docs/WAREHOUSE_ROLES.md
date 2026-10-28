# Rôles du warehouse

Source de vérité SQL : [`warehouse_roles.sql`](warehouse_roles.sql) et
[`warehouse_access_control.sql`](warehouse_access_control.sql). Contrat testé par
`tests/test_warehouse_roles_fair.py` (statique, et sur PostgreSQL réel avec `WAREHOUSE_TEST_LIVE=1`).
Vue d'ensemble : [WAREHOUSE_README.md](WAREHOUSE_README.md).

## Trois couches, à ne pas confondre

| Couche | Rôles | Où c'est défini |
|---|---|---|
| Application (Open WebUI) | `pending`, `user`, `admin` | `DEFAULT_USER_ROLE` (défaut `pending`) et `ENABLE_SIGNUP` dans `docker-compose.yml`; l'inscription est ouverte par défaut (`true`), à passer à `false` avant d'exposer le service |
| Base PostgreSQL du warehouse | voir ci-dessous | `docs/warehouse_roles.sql`, `docs/warehouse_access_control.sql` |
| Services annexes (autres bases) | `idea_langgraph`, `langfuse`, `litellm` | `langgraph/db/`, `langfuse/`, `litellm/` |

**DbHub n'est pas un rôle.** C'est la passerelle MCP : elle se connecte à PostgreSQL avec le compte de la
personne (ou `warehouse_reader` pour l'installation locale) et n'a pas d'autres droits que ce compte.

## Rôles de la base du warehouse

Un **compte** est un rôle PostgreSQL avec connexion. Les rôles de groupe n'ont pas de connexion.

| Rôle | Connexion | Utilisé par | Lit | Écrit | Limites |
|---|---|---|---|---|---|
| `neolab` | oui | chargement, migrations, déploiement | tout | oui | jamais donné à une application ni à un agent |
| `warehouse_navigator` | oui | API du navigateur (port 8090) | `warehouse` + `explore`, toutes les lignes | non | lecture seule, 30 s |
| `warehouse_reader` | oui | installation locale, audit | `explore` seulement, toutes les lignes | non | lecture seule, 30 s, tables brutes refusées |
| comptes personnels | oui | une personne, via DbHub | `explore`, **lignes de son périmètre** | non | lecture seule, 30 s; aucun droit par défaut |
| `warehouse_data_owner` | non | propriétaire des tables et vues | — | — | rend le filtre par ligne effectif |
| `warehouse_all_access` | non | groupe « voit toutes les lignes » | — | — | membres : `neolab`, `warehouse_navigator`, `warehouse_reader`, comptes `--all-access` |
| `warehouse_explore_reader` | non | groupe des comptes personnels | `explore` | — | pas d'accès à `warehouse` |

Les rôles de lecture sont `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, sans `CREATE` sur
aucun schéma, et `PUBLIC` n'a aucun droit sur la base. Les groupes sont globaux au serveur PostgreSQL; les
droits d'un compte (`warehouse.access_grant`) sont propres à chaque base.

Créer un compte et lui accorder un périmètre : [guide de connexion](WAREHOUSE_CONNECT.md) et
[contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md).

## Secrets

Mots de passe fournis par l'environnement (`WAREHOUSE_POSTGRES_PASSWORD`, `WAREHOUSE_READER_PASSWORD`,
`WAREHOUSE_NAVIGATOR_PASSWORD`), jamais dans un fichier versionné ni sur une ligne de commande. Rejouer le
déploiement fait pivoter les mots de passe des deux rôles de service. Les mots de passe des comptes personnels
sont générés par `scripts/warehouse_user.py` et ne sont écrits que dans le fichier remis à la personne.
