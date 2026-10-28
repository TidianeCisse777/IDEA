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
| Zone | `marine_zone_key` de la ligne (EcoTaxa, UVP, FILET, CTD) | égalité **et** statut `assigned` |
| Année | année UTC de la date de la ligne (`sampling_year` pour FILET) | dans `[year_min, year_max]` |

- **Refus par défaut** : aucun droit actif, aucune ligne.
- **`NULL` = sans restriction** sur cette dimension (un droit sans zone couvre toutes les zones).
- **Zone inconnue** (`ambiguous`, `unresolved` ou absente) et **date absente** : cachées à un droit qui borne
  la zone ou l'année, sauf si ce droit a `include_unknown_scope = true` (choix explicite de l'administrateur,
  option `--include-unknown`). `outside` est une zone connue (hors registre) et ne correspond jamais à une zone.
- Les enfants suivent leur parent : un échantillon masqué masque ses objets, bins,
  particules et liens. Les tables de liens exigent que les deux côtés soient visibles.
- Les rôles du groupe `warehouse_all_access` voient tout (chargeur, navigateur, `warehouse_reader`).
  Les superusers et rôles `BYPASSRLS` ne sont jamais filtrés ; `enroll_access_role` les refuse.
- Le catalogue (`explore.dataset_catalog`, `dataset_versions`, `fair_readiness`) reste lisible
  par tous : les métadonnées restent accessibles même quand les données ne le sont pas (FAIR A2).

## Savoir ce qu'on peut lire

| Vue | Réponse |
|---|---|
| `explore.my_access` | les droits actifs du compte (source, contrat, zone, années) |
| `explore.my_datasets` | pour chaque version de jeu de données : accès `complet`, `partiel` ou `aucun`, la raison (« données masquées, pas absentes »), et une note si une source associée manque |

`my_datasets` distingue « masqué » de « absent » au niveau de la version, **sans compter les lignes masquées**.
Un agent doit la lire avant de conclure qu'un résultat vide signifie une absence de données.

## Donner un accès

Avec l'outil d'administration (recommandé, voir le [guide de connexion](WAREHOUSE_CONNECT.md)) :

```bash
python scripts/warehouse_user.py create role_a --source ecotaxa,ecopart --contract C1 --zone lab \
    --year-min 2018 --year-max 2022 --note "Entente X"
python scripts/warehouse_user.py grant role_a --source ctd --contract C1 --zone lab --include-unknown
```

Ou directement en SQL :

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

## Composer des droits sur plusieurs sources

Une vue qui joint plusieurs sources ne renvoie une ligne que si **chaque** côté est lisible. Les vues UVP
(`explore.uvp_samples`, `uvp_objects`…) joignent un profil EcoPart à son échantillon EcoTaxa : un compte limité
à une seule des deux sources y voit 0 ligne. Donner les deux : `--source ecotaxa,ecopart` crée un droit par source.
L'outil d'administration avertit quand une seule des deux est accordée, et `explore.my_datasets` le signale
au compte dans sa colonne `note`.

## Zone des profils CTD

Les profils CTD portent leur propre zone (`docs/warehouse_ctd_zone_migration.sql`), attribuée depuis leurs
coordonnées avec le même registre et la même convention que FILET et EcoTaxa :

```bash
python scripts/assign_filet_zones.py --table ctd_profile
```

À lancer après chaque chargement de profils CTD. Tant qu'un profil n'a pas de zone, il reste caché aux droits
bornés par zone (sauf `include_unknown_scope`).

## Performance

Mesurée le 28 octobre 2026 sur une base de test : 6 000 échantillons, 120 000 bins, 4,8 millions d'objets et de
liens objet-bin, 600 000 lignes d'abondance, compte restreint couvrant 941 échantillons.

| Requête | Restreint avant | Restreint après | Tout voir avant | Tout voir après |
|---|---|---|---|---|
| Objets par taxon (`uvp_objects`) | > 30 s (expire) | 6,8 s | 19,6 s | 8,5 s |
| Total des objets visibles | > 30 s (expire) | 5,4 s | 18,4 s | 7,0 s |
| Abondance moyenne par taxon | 18,5 s | 0,55 s | 0,9 s | 0,4 s |
| Échantillons visibles | 0,2 s | 0,4 s | 0,06 s | 0,07 s |

Trois corrections :
- **Politiques ensemblistes.** Les tables enfants testent `fk IN (SELECT id FROM parent)` : PostgreSQL calcule une
  fois l'ensemble des parents visibles et le sonde par hachage, au lieu de réévaluer le droit pour chaque objet.
  Seule exception : la visibilité d'un objet (ensemble trop grand pour être haché) est vérifiée par index.
- **Versions lisibles calculées une fois.** `warehouse.readable_versions()` remplace l'évaluation par ligne du
  contrôle source et contrat.
- **Jointure par fusion désactivée pour les rôles de lecture des agents.** Sur `explore.uvp_objects`, le
  planificateur estime mal les lignes et choisit une jointure par fusion qui écarte des centaines de millions de
  lignes : plus de 90 s, même pour un superuser. Le réglage `enable_mergejoin = off` est posé sur
  `warehouse_reader` et sur chaque compte inscrit. Le navigateur et le propriétaire ne sont pas modifiés.

## Pièges traités

- **PostgreSQL ignore la RLS pour un superuser et pour le propriétaire d'une table**, et une
  vue s'exécute avec les droits de son propriétaire. En Docker, `neolab` est superuser :
  une RLS naïve ne filtrerait rien. Les données appartiennent donc à `warehouse_data_owner`
  (sans login ni superuser), la RLS est forcée, et les politiques lisent `session_user`
  (le rôle de connexion), jamais `current_user`.
- **Une vue créée plus tard par le chargeur** contournerait le filtre si elle n'appartenait pas à
  `warehouse_data_owner`. Quand le déploiement tourne en superuser (cas Docker), un déclencheur
  d'événement (`warehouse_adopt_explore_views`) la transfère **dès sa création**. Sans superuser (hébergeur
  géré), le déploiement l'annonce; `explore.access_audit` signale alors la vue et rejouer
  `scripts/deploy_warehouse_postgres.py` lui transfère la propriété (`--check` renvoie le code 3 s'il reste un écart).
- Une table ajoutée sans politique est aussi signalée par `access_audit`.

## Limites connues

- **Gros volumes** : à 15 millions d'objets, un parcours complet de `explore.uvp_objects` par un compte
  « tout voir » devrait approcher la limite de 30 s (extrapolation, non mesurée). Pour des statistiques,
  agréger sur `explore.uvp_taxon_abundance`, qui reste sous la seconde.
- **Jointure externe** : avec un accès partiel, une colonne issue d'une jointure externe peut être `NULL` parce
  que la ligne liée est hors périmètre. Aucune valeur masquée n'apparaît. Le contexte MCP le rappelle aux agents.
- **Contrat FILET** : `filet_analysis.analysis_contract` n'est pas utilisé pour l'accès. Le contrat
  d'accès est celui de la version du jeu de données.
- **Fuites de métadonnées (aucune ligne de données)** : les statistiques de PostgreSQL sont lisibles par tout
  rôle. `pg_stat_user_tables.n_live_tup` donne le nombre **total** de lignes d'une table, hors périmètre compris,
  et `EXPLAIN` laisse voir une estimation de lignes. Les noms des tables et colonnes sont visibles. Aucun contenu
  ni valeur n'est accessible. Ces vues système ne peuvent pas être restreintes pour un seul rôle sans modifier le
  catalogue du serveur; si les effectifs globaux sont sensibles, utiliser une base dédiée aux comptes concernés.
- Les rôles de groupe sont **globaux au serveur PostgreSQL**; les droits (`access_grant`) sont propres à chaque base.
- L'identité est le rôle de connexion : plusieurs personnes partageant un compte partagent ses droits.
