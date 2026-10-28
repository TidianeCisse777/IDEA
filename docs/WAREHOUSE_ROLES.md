# Rôles du warehouse

Source de vérité SQL : [`warehouse_roles.sql`](warehouse_roles.sql). Contrat testé
par `tests/test_warehouse_roles_fair.py` (statique, et sur PostgreSQL réel avec
`WAREHOUSE_TEST_LIVE=1`).

## Trois couches, à ne pas confondre

| Couche | Rôles | Où c'est défini |
|---|---|---|
| Application (Open WebUI) | `pending`, `user`, `admin` | `DEFAULT_USER_ROLE` (défaut `pending`) et `ENABLE_SIGNUP` dans `docker-compose.yml`; l'inscription est ouverte par défaut (`true`), à passer à `false` avant d'exposer le service |
| Base PostgreSQL du warehouse | `neolab`, `warehouse_navigator`, `warehouse_reader` | `docs/warehouse_roles.sql` |
| Services annexes (autres bases) | `idea_langgraph`, `langfuse`, `litellm` | `langgraph/db/`, `langfuse/`, `litellm/` |

**DbHub n'est pas un rôle.** C'est la passerelle MCP qui se connecte à PostgreSQL
avec le rôle `warehouse_reader` (`dbhub/warehouse.toml`). Ses droits sont ceux de ce
rôle, rien de plus.

## Rôles PostgreSQL du warehouse

| Rôle | Utilisé par | Lit | Écrit | Limites |
|---|---|---|---|---|
| `neolab` | chargement, migrations, déploiement | tout | oui (propriétaire) | jamais donné à une application ni à un agent |
| `warehouse_navigator` | API du navigateur (port 8090) | `warehouse` + `explore` | non | transaction lecture seule, 30 s |
| `warehouse_reader` | DbHub, agents, audit | `explore` seulement | non | lecture seule, 30 s, tables brutes refusées |

Rôles techniques sans connexion : `warehouse_data_owner` (propriétaire des tables et vues,
nécessaire pour que le filtre s'applique), `warehouse_all_access` (voit toutes les lignes;
`neolab`, `warehouse_navigator` et `warehouse_reader` en sont membres) et
`warehouse_explore_reader` (lecture de `explore`, réservé aux rôles restreints).

**Rôles restreints.** Un rôle supplémentaire (par exemple une équipe ou un partenaire) ne lit que
certains contrats, zones et années : voir [contrôle d'accès](WAREHOUSE_ACCESS_CONTROL.md).
Sans droit explicite il ne voit aucune ligne.

Les deux rôles de lecture sont `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
NOBYPASSRLS`, sans `CREATE` sur aucun schéma, et `PUBLIC` n'a aucun droit sur la base.

## Ce qui était incohérent et a été corrigé

- **Docker ne créait aucun rôle de lecture.** Le compose n'initialisait que `neolab` ;
  `warehouse_reader` et `warehouse_navigator` n'existaient que via le script Python du
  poste Windows. Un déploiement Docker ou PostgreSQL neuf n'avait donc pas d'accès
  lecture seule, contrairement à ce que disait la documentation.
- **Le navigateur tournait avec le rôle propriétaire** (`neolab`) en Docker. Il utilise
  maintenant `warehouse_navigator`.
- **Les vues créées après le provisionnement étaient illisibles** pour les rôles de
  lecture (`GRANT ... ON ALL TABLES` ne couvre que l'existant). Des `DEFAULT PRIVILEGES`
  couvrent désormais les futurs objets du propriétaire.
- Le compose n'appliquait pas la migration EcoPart ; il l'applique.

## Secrets

Mots de passe fournis par l'environnement (`WAREHOUSE_POSTGRES_PASSWORD`,
`WAREHOUSE_READER_PASSWORD`, `WAREHOUSE_NAVIGATOR_PASSWORD`), jamais dans un fichier
versionné ni sur une ligne de commande. Rejouer le script fait pivoter les mots de passe.
