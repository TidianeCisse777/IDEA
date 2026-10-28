# Contrôle d'accès par contrat, zone et année

Un rôle ne lit que les lignes que ses droits couvrent. Le filtre est appliqué par
PostgreSQL (sécurité par ligne, RLS) sur chaque table : une requête SQL, DbHub ou un
agent ne peut pas le contourner. Source : [`warehouse_access_control.sql`](warehouse_access_control.sql).
Tests : `tests/test_warehouse_roles_fair.py` (`WAREHOUSE_TEST_LIVE=1` pour la base réelle).

## Règles

| Dimension | D'où elle vient | Règle |
|---|---|---|
| Source | `dataset_version.source_instance` (ecotaxa, ecopart, filet, ctd…) | égalité |
| Contrat | `dataset_metadata.access_contract`, **porté par la version du jeu de données** | égalité |
| Zone | `marine_zone_key` de la ligne | égalité **et** statut `assigned` |
| Année | année UTC de la date de la ligne (`sampling_year` pour FILET) | dans `[year_min, year_max]` |

- **Refus par défaut** : aucun droit actif, aucune ligne.
- **`NULL` = sans restriction** sur cette dimension (un droit sans zone couvre toutes les zones).
- **Zone inconnue** (`ambiguous`, `outside`, `unresolved`) et **date absente** : cachées à un
  rôle dont le droit borne la zone ou l'année. Elles ne sont visibles que par un droit qui
  ne borne pas cette dimension.
- Les enfants suivent leur parent : un échantillon masqué masque ses objets, bins,
  particules et liens. Les tables de liens exigent que les deux côtés soient visibles.
- Les rôles du groupe `warehouse_all_access` voient tout (chargeur, navigateur, `warehouse_reader`).
  Les superusers et rôles `BYPASSRLS` ne sont jamais filtrés ; `enroll_access_role` les refuse.
- Le catalogue (`explore.dataset_catalog`, `dataset_versions`, `fair_readiness`) reste lisible
  par tous : les métadonnées restent accessibles même quand les données ne le sont pas (FAIR A2).

## Donner un accès

```sql
-- 1. Un administrateur crée le rôle de connexion (mot de passe hors dépôt), puis l'inscrit.
CREATE ROLE role_a LOGIN PASSWORD '...';
SELECT warehouse.enroll_access_role('role_a');   -- lecture seule, 30 s, explore seulement

-- 2. Poser le contrat sur les versions concernées.
UPDATE warehouse.dataset_metadata SET access_contract = 'C1'
 WHERE dataset_version_id IN (SELECT id FROM warehouse.dataset_version WHERE dataset_key = 'p1');

-- 3. Accorder.
INSERT INTO warehouse.access_grant (grantee, source_instance, contract, zone_key, year_min, year_max, note)
VALUES ('role_a', 'ecotaxa', 'C1', 'lab', 2018, 2022, 'Convention X');

-- Révoquer: l'historique est conservé.
UPDATE warehouse.access_grant SET revoked_at = now() WHERE id = 12;
```

Un droit peut viser un groupe de rôles : `grantee` accepte tout rôle dont la connexion est membre.
Chaque utilisateur voit son périmètre avec `SELECT * FROM explore.my_access;`.

## Composer des droits sur plusieurs sources

Une vue qui joint plusieurs sources ne renvoie une ligne que si **chaque** côté est lisible. Les vues UVP
(`explore.uvp_samples`, `uvp_objects`…) partent d'un profil EcoPart et le joignent par jointure interne à son
échantillon EcoTaxa : un compte limité à `ecotaxa` voit 0 ligne dans ces vues, comme un compte limité à
`ecopart`. Il faut un droit par source concernée, avec le même contrat si les deux versions le partagent :

```sql
INSERT INTO warehouse.access_grant (grantee, source_instance, contract, zone_key, year_min, year_max, note) VALUES
 ('role_a', 'ecotaxa', 'C1', 'lab', 2018, 2022, 'Entente X'),
 ('role_a', 'ecopart', 'C1', 'lab', 2018, 2022, 'Entente X (profils)');
```

Un résultat vide dans ces vues n'est donc pas une preuve d'absence de données : vérifier `explore.my_access`.

## Pièges traités

- **PostgreSQL ignore la RLS pour un superuser et pour le propriétaire d'une table**, et une
  vue s'exécute avec les droits de son propriétaire. En Docker, `neolab` est superuser :
  une RLS naïve ne filtrerait rien. Les données appartiennent donc à `warehouse_data_owner`
  (sans login ni superuser), la RLS est forcée, et les politiques lisent `session_user`
  (le rôle de connexion), jamais `current_user`.
- **Une vue créée plus tard par le chargeur contourne le filtre** tant qu'elle n'appartient pas à
  `warehouse_data_owner`. `explore.access_audit` la signale ; rejouer
  `scripts/deploy_warehouse_postgres.py` lui transfère la propriété. `--check` renvoie le code 3
  s'il reste un écart. À faire après chaque nouvelle vue `explore`.
- Une table ajoutée sans politique est aussi signalée par `access_audit`.

## Limites connues

- **CTD** : `ctd_profile` n'a pas de zone. Le filtre par année et par contrat fonctionne, mais un
  droit qui borne la zone ne donne accès à aucun profil CTD tant qu'une zone n'est pas assignée.
- **Contrat FILET** : `filet_analysis.analysis_contract` n'est pas utilisé pour l'accès. Le contrat
  d'accès est celui de la version du jeu de données.
- **Fuites par jointure externe** : une vue qui joint un parent visible à un enfant masqué montre
  l'enfant à `NULL`; aucune valeur masquée n'apparaît, mais la ligne parent reste visible.
- **Performance** : mesurée seulement sur des volumes de test. Les rôles « tout voir » court-circuitent
  le filtre; l'effet sur 15 millions d'objets pour un rôle restreint n'est pas mesuré.
- Les rôles de groupe sont **globaux au serveur PostgreSQL**; les droits (`access_grant`) sont propres à chaque base.
- L'identité est le rôle de connexion : plusieurs personnes partageant un compte partagent ses droits.
