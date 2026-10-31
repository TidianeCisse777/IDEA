# Planification de la refonte d’IDEA

**Période proposée :** du 14 septembre au 30 novembre 2026

**Dernière mise à jour :** 31 octobre 2026

### 31 octobre 2026 — Vrais contours de zone pour les agents, et la zone enfin directe sur l'abondance UVP

- Fermé deux écarts trouvés en testant abondance multi-taxon/multi-zone avec un agent réel la veille.
- **Zone manquante sur `explore.uvp_taxon_abundance`** : la vue joint déjà `uvp_profile` (qui porte
  `marine_zone_key`) mais ne le sélectionnait pas — un agent sans `explore.uvp_samples` peuplé (profil sans
  sample EcoTaxa lié) devait deviner la zone autrement. Corrigé (`docs/warehouse_uvp_abundance_zone_migration.sql`) :
  `marine_zone_key/name/assignment_status` et `ecotaxa_project_id` ajoutés en fin de colonnes.
- **Contours de zone absents du SQL** : `marine_zone_key` n'était qu'une étiquette texte partout dans le
  warehouse; la géométrie réelle (`shared_data/geo/zones_registry.geojson`, 65 zones, IHO Marine Regions)
  n'existait que comme fichier local lu par le navigateur et les scripts Python — injoignable depuis DbHub/MCP.
  Ajouts : table PostGIS `warehouse.marine_zone`, vue `explore.marine_zone_boundaries` (GeoJSON), chargeur
  `scripts/load_marine_zones.py` (idempotent, 65 zones). Simplification nécessaire : certaines zones (archipel
  arctique, ex. « Nunavik ») encodent des milliers de petites îles en trous internes — simplifier la ligne
  (Douglas-Peucker) seule ne réduisait presque rien (1,2 Mo même à tolérance 0,5°); retirer d'abord les îles
  sous un seuil de surface a ramené le total des 65 zones de 4,65 Mo à 464 Ko (max 96 Ko/zone, contre 1,2 Mo
  avant).
- PostGIS n'était activé qu'en fin de déploiement, après les migrations (`ensure_postgis`, pour le filtre
  spatial du navigateur, jamais requis par le schéma jusqu'ici) : la nouvelle table en a besoin plus tôt,
  déplacé avant les migrations. Sur un propriétaire non-superuser sans droit préalable sur l'extension
  (hébergement géré, cas déjà testé), la migration se dégrade proprement (vue non créée, reste du déploiement
  intact) — corrigé `publish_warehouse_context.py` pour accepter cette vue comme optionnelle plutôt que
  d'échouer tout le contexte MCP si elle manque.
- Vérifié en direct (Docker, jeu de test, compte scopé C1) avec un agent réel : il a trouvé la zone directement
  sur `explore.uvp_taxon_abundance` (sans deviner, cette fois), calculé l'abondance de Calanus par zone (450 /
  200 / 90 ind/m³, exact), puis tracé une carte avec les **vrais contours polygonaux** des 3 zones concernées
  (pas des points) via `explore.marine_zone_boundaries`, colorée par abondance.
- 101 tests verts en direct (20 vues, 366 colonnes documentées), y compris le cas hébergement géré non-superuser
  sans PostGIS préalable.

### 31 octobre 2026 — Filtre par zone, carte avec taille/couleur de projet : vérifiés, un trou fermé

- Vérifié avec un agent réel (Docker, 3 zones maritimes réelles, 3 projets EcoTaxa de test, compte scopé C1) :
  le filtrage par zone maritime (`marine_zone_key`) fonctionne correctement — l'agent a vérifié les zones
  disponibles, exclu la bonne, et signalé que `marine_zone_name` était vide plutôt que de l'utiliser à tort.
- Demande d'une carte (taille du point = taille réelle moyenne des objets en µm, couleur = nom du projet
  EcoTaxa) : l'agent a produit une page HTML autonome avec SVG, légende accessible et infobulles, chiffres
  exacts (3168/1584/836 µm). Mais il a trouvé un vrai trou : `warehouse.ecotaxa_project.title` (le nom du
  projet, ex. « Campagne Amundsen 2023 ») n'était exposé par aucune vue `explore.*` — seul l'identifiant
  numérique l'était. L'agent l'a signalé plutôt que d'inventer un nom.
- Corrigé (migration `docs/warehouse_ecotaxa_project_title_migration.sql`) : `ecotaxa_project_title` ajouté en
  fin de colonnes de `explore.uvp_samples` et `explore.uvp_projects` (`CREATE OR REPLACE VIEW` refuse de
  renommer une colonne existante en insérant au milieu — corrigé après un premier essai en échec à
  l'initialisation Docker). Référence seule (NULL si le projet n'a pas été chargé), ne remplace pas
  `ecotaxa_project_id` comme clé.
- Rejoué avec succès : la même carte montre maintenant les vrais noms de projet dans la légende, vérifié
  directement dans le HTML produit. 101 tests verts en direct (19 vues, 357 colonnes documentées).

### 30 octobre 2026 — Comparaison FILET/UVP filtrée par taille, taxonomie incluse

- Fermé l'écart trouvé plus tôt dans la journée : `warehouse.taxon_mapping` (correspondance FILET↔UVP retenue)
  n'était accessible à aucun compte scopé (ceux-ci n'ont `USAGE` que sur le schéma `explore`, jamais sur
  `warehouse` directement), donc un agent ne pouvait pas relier un taxon FILET à `explore.uvp_object_sizes`
  sans deviner par nom de taxon en texte libre.
- Ajouts (migration `docs/warehouse_taxon_mapping_view.sql`) : vue `explore.taxon_mapping` (statut `accepted`
  uniquement — `ambiguous`/`rejected` restent cachés, documenté comme tel, pas confondus avec une absence de
  correspondance), et colonne `taxon_key` sur `explore.uvp_object_sizes` (même formule que
  `uvp_taxon_abundance.taxon_key`), permettant la jointure `uvp_object_sizes.taxon_key = taxon_mapping.uvp_taxon_id`.
  Table de référence non datée/zonée, exemptée de sécurité par ligne comme les autres catalogues
  (`dataset_version`, `dataset_metadata`, etc.).
- Vérifié en direct (Docker, jeu de test, compte scopé C1) : un agent Claude réel a comparé l'abondance FILET
  (*Calanus finmarchicus*, toutes tailles, 30 ind/m³) à l'abondance UVP du même taxon filtrée sur un axe majeur
  ≥1000 µm (20 ind/m³, 2 objets sur 3), en utilisant lui-même le chemin `filet_uvp_matches` → `taxon_mapping` →
  `uvp_object_sizes`, sans aide et sans deviner de lien. Chiffres confirmés indépendamment par `psql`.
  L'agent a aussi correctement signalé les limites scientifiques réelles (le taxon UVP est au niveau du genre
  `Calanus`, le mapping le déclare équivalent à l'espèce `C. finmarchicus` — à confirmer; profondeur du trait
  FILET absente; effectif minuscule dans ce jeu de test).
- 101 tests verts en direct contre Docker (19 vues, 355 colonnes documentées).

### 30 octobre 2026 — Taille réelle des objets EcoTaxa (taxon + taille sur une même ligne), vérifiée contre l'API réelle

- Identifiants EcoTaxa réels fournis par l'utilisateur pour cette vérification (jamais commités). Confirmé en
  direct sur l'API (`https://ecotaxa.obs-vlfr.fr/api`), avec les 23 projets réels du compte : les objets
  EcoTaxa portent déjà les mesures Zooprocess (`area`, `esd`, `major`, `minor`, en pixels), mais comme
  « colonnes libres » nommées par projet (`obj_free_cols` fait correspondre un libellé stable à un slot propre
  au projet, ex. `n01`). Pas tous les projets ne définissent pas `esd` (les projets UVP6 récents ne l'ont pas).
  Un libellé demandé qu'un projet ne connaît pas est retiré en silence de la ligne (pas renvoyé NULL), ce qui
  décale les colonnes suivantes : confirmé en testant ce cas précis sur un vrai projet avant d'écrire le
  chargeur, pour ne jamais lire une taille dans la mauvaise colonne.
- La calibration pixel→mm n'est pas un champ d'objet : elle vit sur l'acquisition EcoTaxa
  (`GET /acquisition/{id}.free_columns.pixel`, confirmée à 0,088 mm/pixel sur un vrai projet UVP5), pas
  interrogeable en lot avec les objets.
- Ajouts : colonnes `area_px/esd_px/major_px/minor_px` sur `warehouse.ecotaxa_object`, table
  `warehouse.ecotaxa_acquisition` (calibration par acquisition, sécurité par ligne héritée comme
  `ecotaxa_object`), vue `explore.uvp_object_sizes` (migration `docs/warehouse_ecotaxa_object_size_migration.sql`) :
  un objet identifié par ligne avec sa taille réelle en µm quand elle est calculable — referme l'écart trouvé la
  veille (taxon et taille ne se croisaient dans aucune vue). `scripts/populate_ecotaxa_objects.py` interroge
  désormais `obj_free_cols` par projet avant de demander les champs de taille, et charge la calibration par
  acquisition (un appel par acquisition distincte, mis en cache côté base).
- Vérifié en direct (Docker, jeu de test, compte scopé contrat C1) : tailles calculées correctes (2393,6 µm et
  987,99 µm pour un objet connu), compte hors contrat invisible. Un agent Claude réel a ensuite filtré
  l'abondance d'un taxon par gamme de taille réelle (µm) sans aide, avec le même soin pour agréger le volume du
  bin une seule fois.
- `tests/test_loaders_v1.py` étendu : trois projets de test avec des `obj_free_cols` différents (aucun, partiel,
  complet), vérifie que seules les tailles attendues sont chargées et que la conversion en µm est correcte pour
  un compte scopé. 101 tests verts en direct contre Docker.
- Non fait : chargement réel complet (23 projets, ~15M objets, plusieurs heures) — seule l'infrastructure est
  prête et testée; aucune donnée réelle n'a été chargée dans un warehouse de production.

### 30 octobre 2026 — Jointure FILET–UVP et filtrage par taille UVP vérifiés avec un agent réel (phases 2 et 4)

- Vérifié avec un agent Claude réel (Docker, compte scopé, chiffres indépendamment recalculés par `psql`) : la
  comparaison d'abondance FILET–UVP permet déjà de jouer sur la proximité temporelle (`time_gap_hours` dans
  `explore.filet_uvp_matches`/`explore.filet_uvp_abundance`, filtrable directement en SQL) et sur la proximité
  spatiale — non pré-calculée en vue, mais calculable par l'agent lui-même en PostGIS (`ST_Distance`) à partir de
  `latitude`/`longitude`, déjà exposées sur `explore.filet_samples` et `explore.uvp_samples`. L'agent a produit les
  deux filtres sans aide et avec des chiffres exacts.
- Lacune trouvée par le même test : les tailles de particules UVP (`warehouse.uvp_particle`, produit EcoPart LPM,
  chargé par `populate_ecopart.py`) n'étaient exposées par aucune vue `explore.*` — donc invisibles à tout agent.
  L'agent a correctement signalé l'absence plutôt que d'inventer un chiffre.
- Ajout : `explore.uvp_particle_sizes` (migration additive `docs/warehouse_uvp_particle_sizes_view.sql`), héritant
  automatiquement du filtre d'accès déjà posé sur `warehouse.uvp_particle` (vérifié : un compte scopé au contrat C1
  ne voit que son profil, pas celui d'un autre contrat). Documentée dans `scripts/warehouse_context.py` et
  `docs/WAREHOUSE_MCP_DICTIONARY.md`.
- Défaut trouvé et corrigé pendant le même test : la formule de densité par gamme de taille documentée
  (`SUM(particle_count)/SUM(sampled_volume_l)`) est fausse dès qu'on agrège plusieurs `size_class_key` d'un même
  bin, car `sampled_volume_l` est répété sur chaque classe et se trouve compté plusieurs fois au dénominateur.
  Un agent de test l'a détecté en recalculant lui-même et en comparant à la fiche; la fiche et l'exemple SQL ont été
  corrigés pour agréger le volume une seule fois par `uvp_bin_id` avant de diviser. Rejoué avec succès : l'agent
  retrouve maintenant le chiffre correct (1900 puis 6980 particules/m³ sur le jeu de test), confirmé indépendamment
  par `psql`.
- 101 tests verts en direct contre Docker (`WAREHOUSE_TEST_LIVE=1`), incluant les nouveaux cas.

### 29 octobre 2026 — Chargeurs et infrastructure vérifiés avant le premier chargement réel (phases 2 et 4)

- Chargement réel reporté : identifiants EcoTaxa et exports FILET absents de l'environnement, conteneur temporaire.
- Chaîne complète des chargeurs (échantillons et objets EcoTaxa, EcoPart, CTD Amundsen, zones CTD, FILET,
  appariements FILET–UVP) exécutée sans modification sur une v1, avec EcoTaxa et l'ERDDAP simulés et les fichiers
  de test, puis contrôle de la qualité et des droits (`tests/test_loaders_v1.py`).
- Défauts bloquants trouvés et corrigés : `COPY` direct vers des tables protégées (refusé pour un propriétaire
  non-superuser), `COPY FROM STDIN` dans un `psql -c` à plusieurs instructions (refusé par psql 16 : chargeurs
  d'objets et de CTD cassés quel que soit le rôle), base `postgres` utilisée par défaut par les chargeurs EcoTaxa,
  hôte et port ignorés par EcoPart, `shapely` et `pandas` non déclarés, versions chargées sans fiche de catalogue
  (donc sans contrat possible), déploiement en échec quand PostGIS est installé mais que le propriétaire n'est pas
  superuser.
- Ajouts : `scripts/load_warehouse.py` (vérification préalable, ordre, arrêt au premier échec, rejeu, audit),
  `scripts/requirements-warehouse.txt`, `warehouse_user.py contract`, [guide de chargement](docs/WAREHOUSE_LOADING.md).
- **`docker compose up` réel validé** (Docker disponible, contrairement à ce qui avait été supposé) : image PostGIS
  16.4/3.4.3, initialisation sans erreur, contexte publié, `--verify` → `PRÊT`, navigateur et filtre spatial, DbHub
  avec un compte personnel. 123 tests verts contre cette base. Ports de la base et du navigateur désormais limités à
  `127.0.0.1` (ils étaient ouverts sur toutes les interfaces). Constaté : rejouer le déploiement avec d'autres mots de
  passe coupe le navigateur; procédure précisée.
- Non vérifié : vraies API, volume réel, contenu des exports FILET.

### 29 octobre 2026 — Warehouse 1.0.0 : version stable prête à déployer (phases 2 et 4)

- [Note de version](docs/WAREHOUSE_RELEASE_V1.md) : contenu, procédure, vérification, décisions et risques acceptés.
- Version enregistrée dans la base à chaque déploiement (`warehouse.release_history`, `explore.warehouse_release`) avec
  le SHA-256 de chaque migration, par le script comme par l'initialisation Docker. Numéro défini une seule fois
  (`docs/warehouse_release.sql`).
- `deploy_warehouse_postgres.py --verify` : rapport de préparation sans modification (version, rôles, réglages,
  propriétaire en lecture-écriture, base fermée à PUBLIC, filtre sans contournement, sécurité forcée, contexte MCP,
  vues de découverte; notes sur l'adoption des vues et les contrats FILET). Verdict `PRÊT` / `NON PRÊT`.
- Défaut trouvé et corrigé : au premier déploiement, la vue de version, adoptée par le propriétaire des données, ne
  pouvait pas lire sa table encore détenue par le déployeur; et une requête en échec du rapport était muette.
- Initialisation Docker rejouée sans Docker, dans l'ordre et avec les noms du compose : `PRÊT`.
- Décisions : contrat d'accès par version (versions FILET aux contrats mélangés signalées), effectifs `pg_stat`
  acceptés (base dédiée si sensible), mot de passe local en fichier privé ou trousseau du système (`--keyring`).
- Correction d'honnêteté : les entrées précédentes comptaient comme « sur base réelle » tous les tests lancés avec la
  base active. Décompte exact : 92 tests, dont 23 interrogent une base réelle.
- Non validé : `docker compose up` réel, PostGIS, Codex, Claude Desktop, Windows, serveur distant, données réelles.

### 28 octobre 2026 — Sécurité : vues adoptées à la création, propriétaire non-superuser (phases 2 et 4)

- Déclencheur d'événement `warehouse_adopt_explore_views` : toute nouvelle vue `explore` est transférée au
  propriétaire des données dès sa création (déploiement en superuser). Sans superuser, avis explicite, audit et rejeu.
- **Défaut corrigé, présent dans les commits `b4e1675` et `ac6204b`** : sous PostgreSQL 16, le créateur d'un rôle en
  devient membre administrateur; la boucle de mise à jour des comptes restreints a donc pu mettre en lecture seule un
  propriétaire non-superuser au rejeu suivant. Seuls les hébergements sans superuser étaient concernés. La boucle ne
  vise plus que les comptes restreints, la session de déploiement force la lecture-écriture et le rejeu répare le
  propriétaire. Test de non-régression avec un propriétaire non-superuser.
- Plusieurs bases sur un serveur : délégation des groupes et des rôles de service documentée (`WITH ADMIN OPTION`).
- Preuves : 86 tests exécutés avec une base réelle active, verts deux fois, sans rôle ni base résiduels.

### 28 octobre 2026 — Connexion : diagnostics, expiration, TLS, installation hors ligne (phase 4)

- `warehouse_connect.py check` donne la cause d'un échec à partir des messages de DbHub (jamais affichés tels
  quels) : mot de passe refusé, TLS exigé, certificat non vérifiable, serveur injoignable, hôte inconnu, délai
  réseau. Chaque cas a été provoqué et vérifié sur PostgreSQL 16 avec DbHub 1.5.0.
- Expiration : date écrite dans le fichier d'identifiants, alerte 14 jours avant et après expiration;
  `rotate` conserve ou renouvelle la validité et refuse de réactiver un compte expiré sans `--expires-days`.
- TLS testé en local (certificat autosigné, `hostssl`) : `require` chiffre, `verify-full` exige le certificat
  d'autorité, désormais accepté (`WAREHOUSE_DB_SSLROOTCERT`, `init --sslrootcert`).
- `install-dbhub` installe la version épinglée dans `data/tooling/dbhub` pour les postes sans npm. Un défaut de
  chemin d'installation trouvé au test (un niveau de trop, masqué par une installation existante) a été corrigé
  et vérifié à vide.
- Preuves : 84 tests exécutés avec une base réelle active, verts deux fois. Non vérifié : serveur distant réel, Codex,
  Claude Desktop, Windows.

### 28 octobre 2026 — Accès des agents aux données : performance, CTD, zones inconnues, multi-sources (phases 2 et 4)

- **Performance** (base de test : 4,8 M d'objets, 600 000 abondances) : un compte restreint expirait à 30 s sur
  `explore.uvp_objects` et mettait 18,5 s sur les abondances. Causes trouvées dans les plans : politiques enfants
  réévaluant le droit pour chaque objet, contrôle de version par ligne, et jointure par fusion mal estimée par le
  planificateur sur `uvp_objects` (> 90 s même en superuser). Corrections : politiques ensemblistes,
  `warehouse.readable_versions()`, `enable_mergejoin = off` pour les rôles de lecture des agents. Après : 6,8 s,
  5,4 s et 0,55 s (restreint); 8,5 s, 7,0 s et 0,4 s (tout voir). Une variante `LATERAL` de la vue a été essayée et
  écartée (pas plus rapide).
- **Masqué ou absent** : vue `explore.my_datasets` (accès complet, partiel ou aucun par version, raison, source
  associée manquante), sans comptage. Recette agent : le compte limité à EcoTaxa explique désormais ses 0 profils par
  l'absence de droit EcoPart et sait quoi demander. Un texte inexact (dates déclarées exclues sans borne d'années)
  repéré pendant cette recette a été corrigé.
- **Multi-sources** : `warehouse_user.py --source ecotaxa,ecopart`, avertissement quand une seule source UVP est
  accordée, ligne `jeux lisibles` dans `warehouse_connect.py check`.
- **CTD** : zone propre aux profils (`docs/warehouse_ctd_zone_migration.sql`), attribuée par
  `assign_filet_zones.py --table ctd_profile` avec le registre existant (vérifié : Baie de Baffin `assigned`,
  point du Pacifique `outside`, profil sans coordonnées `unresolved`).
- **Zones et dates inconnues** : option explicite par droit `include_unknown_scope` (`--include-unknown`), refus
  par défaut conservé.
- **Contexte MCP sous Docker** : service ponctuel `warehouse-context` après un contrôle de santé de la base. Non
  exécuté (Docker absent ici). Contexte MCP enrichi (my_datasets, jointures externes, multi-sources).
- Preuves : 52 tests exécutés avec PostgreSQL 16 réel actif (80 au total), installation portable rejouée.
- Limites : 15 M d'objets extrapolé (parcours complet de `uvp_objects` proche de 30 s pour un compte tout voir),
  réglage du planificateur à réévaluer si les vues changent.

### 28 octobre 2026 — Rôles, accès par périmètre, FAIR, connexion DbHub et documentation (phases 2 et 4)

- Rôles clarifiés ([WAREHOUSE_ROLES.md](docs/WAREHOUSE_ROLES.md)) : `docs/warehouse_roles.sql` est la
  source unique. Écarts corrigés : Docker ne créait aucun rôle de lecture, le navigateur utilisait le rôle
  propriétaire, les vues créées après provisionnement étaient illisibles, la migration EcoPart manquait au compose.
- Préparation FAIR ([exigences](docs/WAREHOUSE_FAIR_REQUIREMENTS.md)) : migration additive, identifiant
  persistant unique, contrainte de publication, vues `explore.dataset_catalog`, `fair_readiness` et
  `fair_column_coverage`. **Le warehouse n'est pas FAIR** : fiches en brouillon (39 sur l'instance locale au 8 octobre), aucun
  identifiant ni licence; dépôt, licence, niveaux d'accès, vocabulaires et sauvegarde restent à décider (PGD §8).
- Accès par source, contrat, zone et année ([WAREHOUSE_ACCESS_CONTROL.md](docs/WAREHOUSE_ACCESS_CONTROL.md)) :
  sécurité par ligne forcée sur 23 tables, refus par défaut, propriétaire non-superuser dédié. Limites :
  CTD sans zone, performance non mesurée sur 15 M d'objets, toute vue `explore` créée ensuite doit être
  rattachée au propriétaire des données (`explore.access_audit`, `--check` code 3).
- Déploiement `scripts/deploy_warehouse_postgres.py` rejouable; comptes via `scripts/warehouse_user.py`;
  branchement via `scripts/warehouse_connect.py` ([guide](docs/WAREHOUSE_CONNECT.md)). Le déploiement
  publie maintenant le contexte MCP, absent hors installation Windows.
- Preuves : 41 tests exécutés avec PostgreSQL 16 réel actif (propriétaire superuser et non-superuser), recette avec le
  vrai DbHub 1.5.0 (mauvais mot de passe refusé, rotation, révocation) et `claude mcp list` connecté.
  Échec relevé : les tests `test_populate_*` ne s'exécutent pas sans `pytest` (préexistant).
- Documentation : point d'entrée [WAREHOUSE_README.md](docs/WAREHOUSE_README.md), `example.warehouse.env`,
  guide Docker corrigé (trois mots de passe, publication du contexte MCP), dictionnaire MCP régénéré, renvois
  entre guides. Liens relatifs vérifiés.
- Recette avec agents (Claude Code non interactif, vrai DbHub, deux comptes) : périmètre, catalogue et filtrage
  corrects, écriture refusée, limites signalées. Règle découverte et documentée : une vue multi-sources exige
  un droit par source (EcoTaxa et EcoPart pour les vues UVP). Suppression de la branche
  `claude/warehouse-fair-roles` refusée par la passerelle git (403), à faire dans GitHub.
- Recette sur valeurs avec un agent (données fictives) : abondances par taxon recalculées par l'agent, égales à la
  vérité terrain (4 valeurs, 12 lignes visibles sur 60). Contrôle d'évasion fait directement en SQL avec le compte
  restreint : 18 tentatives (tables brutes, `SET ROLE`, `row_security = off`, écriture des droits, fichier serveur,
  `COPY PROGRAM`…) refusées par la base; ajouté aux tests. Fuites de métadonnées sans donnée relevées et
  documentées : effectifs globaux (`pg_stat`), estimations `EXPLAIN`, noms de tables. Un agent a refusé de mener
  lui-même la mission d'évasion; le contrôle a été fait par le développeur.
- Non vérifié : `docker compose up`, PostGIS et le navigateur spatial, Codex, Claude Desktop, Windows
  pour les nouveaux scripts, TLS distant. Phases non clôturées.

### 21 octobre 2026 — Cartographie et bibliothèques océanographiques dans le MCP

- Fiche graphs étendue : Cartopy, Folium, GeoPandas/Shapely/pyproj, cmocean,
  oceans, gsw/TEOS-10 et xarray selon besoin. Règles d’ordre des coordonnées,
  CRS/projections, géodésie, attributions et fonctionnement réseau des fonds.
- Conventions physiques et unités exigées avant calcul; pas de substitution
  implicite salinité pratique/absolue, température ou pression/profondeur.
  « oceangs » n’étant pas un nom confirmé, oceans est documenté comme option
  d’analyse océanographique vérifiée, sans prétendre identifier le package voulu.
- TDD : test cartographique en échec avant ajout, puis 8 tests de contexte
  réussis; métadonnées et documentation générée republiées. Les bibliothèques
  restent à installer selon le calcul demandé; aucun calcul scientifique réalisé.
- Recette MCP réelle réussie : les noms Cartopy, Folium, oceans, TEOS-10 et
  cmocean sont bien présents dans la fiche renvoyée par DbHub.

### 21 octobre 2026 — Règles de graphiques dans le contexte MCP

- Fiche `warehouse_context(topic=graphs)` publiée et annoncée dans l’overview
  et la description de l’outil : bibliothèques Python, style, unités, axes,
  palette/statuts, exports PNG/SVG/CSV et provenance SQL reproductible.
- Règles explicites contre les graphiques sur données inventées ou résultat
  tronqué, les normalisations implicites et la confusion entre lien accepted
  et validation scientifique. Vérification des dépendances requise avant tracé.
- TDD : contrat en échec avant ajout de la fiche, puis 6 tests de contexte
  réussis. Publication SQL des métadonnées et contrôle des rôles réussis;
  documentation générée actualisée. Aucune bibliothèque graphique installée
  ni figure scientifique produite par ce changement de contexte.
- Recette MCP réelle réussie : la fiche graphs renvoie Matplotlib, le statut
  Exploratoire et les exports CSV; les contrôles métier/SQL existants passent.

### 21 octobre 2026 — Recherche de sauvegarde dans l’historique de la branche

- Audit de `codex/validate-warehouse-v1` au commit `0483871` : 869 commits
  accessibles et 2 054 contenus de fichiers examinés, y compris fichiers supprimés.
- Aucun chemin de fichier SQLite/dump/backup trouvé. Inspection des signatures
  binaires : aucune base SQLite, dump PostgreSQL custom/SQL, archive ZIP/gzip
  ou pointeur Git LFS détecté; inventaire LFS également vide.
- Seuls les DDL/migrations et les mentions documentaires de sauvegardes
  restent disponibles. Limite : audit de l’historique accessible depuis cette
  branche; n’inclut pas d’autres branches, releases, artifacts ou objets orphelins.

### 21 octobre 2026 — Contexte métier distribué via le MCP (phases 1 et 2)

- Dictionnaire versionné des 16 vues scientifiques : usage, grain, clés de
  jointure, provenance par SQL réel, limites et exemples. Publication de
  commentaires sur 304 colonnes; unités inconnues explicitement à confirmer.
- Surfaces lecteur additives : `explore.warehouse_context`,
  `explore.warehouse_dictionary`, `explore.dataset_versions`. Aucun secret
  ni URI locale de manifeste exposé par l'inventaire des versions.
- Outil DbHub `warehouse_context` avec fiche générale, fiche par vue ou
  ensemble des fiches. Description invitant le modèle à lire le contexte
  avant analyse; aucune injection automatique de tout le dictionnaire promise.
- TDD : tests du contrat écrits et exécutés en échec avant implémentation,
  puis 4 tests réussis. Recette MCP réelle réussie : contexte général et
  FILET CTD, dictionnaire SQL, commentaire de volume renvoyé par search_objects,
  requête lecteur; les droits bruts restent limités.
- [Dictionnaire Markdown](docs/WAREHOUSE_MCP_DICTIONARY.md) généré depuis
  l'instance et le même contenu métier. Risques de doublons/versions de
  `filet_uvp_abundance` documentés; calcul scientifique non déclaré validé.
- Limites : base toujours vide, nouveau chargement du catalogue MCP dans Codex
  requis. La disponibilité du contexte ne garantit pas que chaque modèle le
  consulte systématiquement. Phases non clôturées.

### 21 octobre 2026 — Warehouse portable, interface et DbHub dans Codex (phases 1 et 2)

- PostgreSQL 16.15/PostGIS 3.6.2, Python 3.11.9, Node 24.22.0 et DbHub 1.5.0
  installés sous `data/tooling/`, sans Docker ni service Windows.
- Cluster et base vide initialisés; interface lancée sur `127.0.0.1:8090`.
  Les huit routes HTTP de recette répondent 200, avec et sans filtre spatial.
- Rôles `warehouse_reader` et `warehouse_navigator` contrôlés en SQL réel :
  lecture seule, absence de droits DDL/écriture et privilèges administratifs,
  lecture brute refusée au lecteur MCP. Calcul géodésique PostGIS vérifié.
- DbHub : handshake MCP, découverte et requête SQL lecteur réussis;
  serveur `neolab-warehouse` enregistré dans la configuration personnelle
  Codex sans secret. Rechargement de Codex requis pour le catalogue d'outils.
- Tests exécutés : 20 schéma, 6 audit, 2 contrat spatial, 12 UI et contrôle
  PowerShell du lanceur, tous réussis. Les blocages Windows initdb ont été
  résolus avec les chemins courts et l'extraction complète du runtime.
- Livrable : résumé opérationnel du 21 octobre (archivé depuis, voir WAREHOUSE_RELEASE_V1.md et WAREHOUSE_ROLES.md), procédure
  [portable](docs/WAREHOUSE_PORTABLE.md), scripts de cycle de vie et recette.
- Limites : archive et sauvegarde absentes, aucune donnée scientifique
  restaurée; recette visuelle et conversation Codex après rechargement non
  exécutées. Phases non clôturées. Aucun changement publié ou poussé;
  suivi GitHub Project non synchronisé dans cette session.

### 21 octobre 2026 — Écart spatial de comparaison FILET–UVP (phase 2)

- Ajout d'un seuil spatial facultatif en km, combiné au seuil temporel sur
  les paires stockées. Distance géodésique PostGIS, affichée dans les fiches;
  même filtre sur carte, compteurs et liste des correspondances.
- Contrats écrits avant implémentation, tests UI et recette live étendus
  (seuil nul, sous-ensembles, cohérence des trois routes).
- Tentative d'exécution Python bloquée avant collecte : interpréteur absent.
  Node et Docker indisponibles dans le PATH; recette UI/PostgreSQL non exécutée.
  `git diff --check` est le seul contrôle exécuté avec succès.
- Limite : aucune nouvelle paire spatiale n'est créée et aucun statut
  scientifique n'est modifié; la phase reste en cours.

### 21 octobre 2026 — Documentation, accès lecteur et qualification (phases 1 et 2)

- Contrat et procédure regroupés dans
  [WAREHOUSE_ACCESS_QUALIFICATION.md](docs/WAREHOUSE_ACCESS_QUALIFICATION.md) :
  grains, références du dictionnaire, connexion lecteur et recette MCP à effectuer.
- Tests de contrat écrits avant `scripts/audit_warehouse.py` : absence de
  fallback propriétaire, délais et lecture seule, découverte sans scan,
  vues manquantes explicites et restitution des mesures par version.
- Diagnostic ajouté : inventaire des colonnes accessibles puis scan taxonomique
  uniquement avec `--qualify`. Identifiant, libellé, annotation et contrat FILET
  sont distingués; aucun rapprochement scientifique n'est créé.
- Tentative de test : `python -m unittest discover -s tests -p test_warehouse_audit.py`
  échoue avant collecte car Python est absent (raccourci Microsoft Store).
  Aucun résultat rouge/vert TDD exécuté n'est donc revendiqué.
- Limites : ni connexion PostgreSQL live ni configuration DbHub/MCP validée
  dans cet environnement; aucun credential local trouvé ou affiché. « Données
  contrats » reste à clarifier. Phases et use cases restent en cours.

### 8 octobre 2026 - Brouillon PGD/DMP et audit des métadonnées (phases 1 et 2)

- Audit live en lecture seule : métadonnées EcoTaxa et FILET, versions,
  manifestes, empreintes et relations de provenance inventoriés.
- Constats : `dataset_version` conserve source, version, URI et SHA-256; EcoTaxa
  compte 6 137/6 138 samples datés, 3 944 géolocalisés et aucun `instrument`
  ou `annotation_status` chargé; FILET conserve les métadonnées d'échantillon
  mais les deux volumes sont partiels (4 483/6 102 et 2 377/6 102).
- Brouillon ajouté dans [docs/WAREHOUSE_DMP_DRAFT.md](docs/WAREHOUSE_DMP_DRAFT.md)
  avec inventaire, cycle de vie, standards, accès, préservation, décisions et
  proposition de catalogue `dataset_metadata`, `dataset_file`,
  `column_metadata` et `validation_run`.
- Aucune migration scientifique ou publication n'a été exécutée : noms,
  licence, dépôt, rôles et conservation doivent être validés avant publication;
  le contrat SQL additif de catalogue est préparé et appliqué localement dans
  `docs/warehouse_metadata_migration.sql`.
- Les métadonnées sources ont été vérifiées : EcoTaxa conserve 70 noms de
  champs JSON sur 6 118 samples ayant au moins une clé; EcoPart conserve
  59 801 lignes source de bins, 585 lignes `metadata` et 3 535 lignes
  `zooplankton`. Aucun champ EcoTaxa absent n'est complété automatiquement par
  EcoPart sans lien prouvé.
- Sauvegarde opérationnelle vérifiée :
  `data/warehouse_backups/neolab_warehouse_20261008.dump` (format custom
  PostgreSQL 16, environ 243 Mo). Le rôle `warehouse_reader` a été créé et
  testé : lecture des vues `explore.*` uniquement, accès aux tables
  `warehouse.*` et opérations DDL refusés. Les identifiants restent dans le
  fichier local ignoré `data/warehouse_backups/warehouse_reader.env`.

### 7 octobre 2026 - Redémarrage du warehouse local (phase 2)

- Docker Desktop démarré, puis stack reconstruite et lancée avec
  `docker-compose.warehouse.yml` et la configuration locale ignorée par Git.
- PostgreSQL `neolab-warehouse-db` accepte les connexions sur le port hôte
  `55432`; le navigateur `neolab-warehouse-navigator` répond sur
  `http://localhost:8090`, avec `/health` et les routes `/api/options` et
  `/api/coverage` en HTTP 200.
- Contrôle de couverture après démarrage : 585 profils UVP, 10 479 780 objets
  mappés, 380 profils CTD et 6 102 échantillons FILET. Le volume persistant
  existant a été réutilisé; aucune recharge de données ni migration exécutée.
- Limite : ce démarrage local ne valide ni le déploiement VPS, ni la
  restauration, ni l'accès IDEA strictement en lecture seule. La phase 2 reste
  en cours.

### 7 octobre 2026 - Diagramme de classes du warehouse (phases 1 et 2)

- Diagramme de classes consolidé à partir du DDL principal et des migrations
  additives EcoPart et zones FILET : 26 tables persistantes, clés, relations,
  grains métier et inventaire des vues `explore.*`.
- Livrables : `docs/warehouse_class_diagram.mmd` modifiable,
  `docs/WAREHOUSE_CLASS_DIAGRAM.md` et
  `output/pdf/warehouse_database_class_diagram.pdf` en A3 paysage.
- Preuve de livraison : génération PDF reproductible avec ReportLab, rendu des
  sept pages en PNG et inspection visuelle sans texte coupé ni chevauchement.
- Limite : le service PostgreSQL warehouse n'était pas actif pendant la
  génération. Le document représente le schéma versionné dans le dépôt, pas
  une introspection live. La phase 1 reste en cours jusqu'à la revue d'équipe.

### 5 octobre 2026 — Vérification pré-démo des données affichées (phases 2 et 3)

- La chaîne en lecture seule PostgreSQL → API → interface concorde sur la vue globale : 585 profils UVP, dont 386 géolocalisés et 199 sans coordonnées, 10 479 780 objets EcoTaxa associés, 380 profils CTD et 6 102 échantillons FILET. La période combinée des couches visibles est du 9 juillet 2010 au 17 octobre 2025.
- Le scénario « Baie de Baffin, 2024 » a été rejoué dans l’interface et comparé à l’API : 123 profils UVP, 4 279 581 objets, 94 profils CTD et 272 échantillons FILET, du 12 août au 13 octobre 2024. Ce total FILET remplace le chiffre historique de 558 obtenu avant l’application stricte des polygones aux coordonnées.
- Le mode FILET–UVP à 10 h affiche uniquement les paires acceptées cartographiables : 20 profils UVP, 130 échantillons FILET, 12 profils CTD et 554 752 objets EcoTaxa. Les dates affichées combinent correctement les deux couches, du 14 juillet au 18 octobre 2024.
- Preuves automatisées : 68 contrôles live SQL/API réussis, 45 zones GeoJSON hors périmètre canadien ignorées explicitement, et 10 contrats UI réussis. Les 20 zones proposées par l’interface passent un oracle spatial Shapely indépendant ; les années, unions de zones, projets, compteurs, dates et correspondances sont couverts.
- Limite visible et assumée : la vue « Toutes les données » inventorie tout le warehouse, y compris les positions hors Arctique canadien. Les 199 profils UVP sans coordonnées sont comptés globalement mais exclus de tout filtre spatial.
- Correctif UX pré-démo : chaque mise à jour de filtre affiche désormais un indicateur léger sur la carte. Les contours de zones sont recalculés d’après les points des couches visibles ; une zone sans UVP disparaît lorsque FILET est masqué, y compris dans une sélection de plusieurs zones. Le cas Baie d’Hudson confirme 235 FILET et 0 UVP. La recette réelle et 10 contrats UI passent après reconstruction du service local.
- Audit UX documenté dans `docs/WAREHOUSE_NAVIGATOR_UX_AUDIT.md`. Le suivi distingue trois lots : clarté de la démonstration, exploration efficace, puis cartographie arctique et accessibilité. Les cinq priorités immédiates sont les filtres actifs visibles, la légende dynamique, l’accès au résumé à largeur moyenne, les états vides explicites et un modèle unique d’application des filtres. Aucun de ces éléments n’est déclaré terminé avant sa recette dans l’interface.
- Lot A de l’audit exécuté : les filtres année/zone/projet sont préparés puis appliqués en une requête, les pastilles sont supprimables, la légende suit les couches, le résumé compact reste visible à 884 px et les états vides nomment la source concernée. Contrôles : 10 tests UI, 68 contrôles live SQL/API, 45 cas hors périmètre explicitement ignorés et recette navigateur réelle après reconstruction Docker. Les lots B et C restent planifiés.

### 27 septembre 2026 — Recette MVP en cours (contribution à la phase 3)

- Suite opt-in `NAVIGATOR_LIVE=1 pytest -q tests/test_navigator_live.py` : comparaison en lecture seule SQL/API, identité des échantillons par polygone avec un oracle Shapely indépendant, plages temporelles, métadonnées et écarts horaires, paramètres invalides.
- Premier audit exploitable : 27 réussites, 8 échecs spatiaux MEOW, 45 zones hors périmètre ignorées. Exemple : 1 576 FILET géographiquement dans MEOW Baffin Bay–Davis Strait étaient omis malgré la concordance carte/compteur. Cause : les FILET déjà affectés à une zone unique n’étaient pas testés contre les autres polygones.
- Correctif local : appliquer l’intersection géographique à tous les FILET géolocalisés, en conservant les métadonnées d’affectation. Nouvelle exécution en cours. Les couches, dates affichées, mode comparaison et interactions restent à vérifier avant clôture ; aucune validation complète annoncée.
- Décision confirmée : les filtres spatiaux UVP suivent eux aussi uniquement les coordonnées et les polygones du registre. Un profil sans coordonnées reste dans l’inventaire global mais ne peut plus entrer dans une zone via un ancien nom de zone.
- Audit final : 68 contrôles live SQL/API réussis et 45 cas hors périmètre canadien explicitement ignorés ; les 20 zones exposées par le navigateur passent l’oracle géographique indépendant. Les six contrats UI, les 22 tests warehouse et le build Docker du navigateur passent. La recette MVP locale est clôturée ; les validations scientifiques d’équipe et le déploiement VPS restent hors de cette recette.

## Objectif

Centraliser les données NeoLab dans un warehouse SQL mis à jour avec les
nouvelles données et directement interrogeable par IDEA. La V1 doit permettre à
IDEA de sélectionner les données en lecture seule par SQL, puis de réaliser les
analyses et graphiques en Python avec un chemin plus simple et reproductible.

Le périmètre V1 couvre quelques campagnes représentatives et les données
EcoTaxa, EcoPart, CTD, FILET ainsi que leurs métadonnées communes. L’intégration
complète des données historiques du laboratoire reste hors périmètre.

## Résultat attendu au 30 novembre

- warehouse V1 déployé et documenté ;
- accès SQL stable et strictement en lecture seule pour IDEA ;
- campagnes, clés, relations, unités et provenance documentées ;
- scénarios de référence validés de bout en bout ;
- flux et outils devenus inutiles identifiés.

## Règle de suivi

Ce fichier est la source de vérité du calendrier, de l’avancement et des
critères de sortie. Toute intervention doit commencer par identifier la phase et
le résultat attendu auxquels elle contribue. Après chaque travail réellement
exécuté, l’agent met à jour le statut et le journal ci-dessous avec les tests,
scénarios ou limites observés. Une phase passe à **Terminée** uniquement lorsque
son critère de réussite est vérifié. Une modification de code ou un test
unitaire isolé ne suffit pas à valider un scénario conversationnel.

Le suivi opérationnel peut être reproduit dans GitHub Project, mais les statuts
doivent rester synchronisés avec ce fichier versionné.

## Vue d’ensemble

| Phase | Période | Livrable | Critère de réussite | État |
|---|---|---|---|---|
| 1. Cadrage | 14–25 sept. | Schéma V1 et périmètre validés | Revue d’équipe confirmant que les jeux EcoTaxa, EcoPart, CTD et FILET retenus peuvent être reliés | En cours — proposition de schéma rédigée, revue attendue |
| 2. Construction du warehouse V1 | 28 sept.–9 oct. | Warehouse échantillon utilisable en local | Données attendues retrouvées par SQL et jointures de référence cohérentes | En cours - stack locale et API actives; validation des jointures à consolider |
| 3. Validation des données | 12–23 oct. | Jeu de tests et anomalies documentées | Cas de référence conformes aux sources originales | À faire |
| 4. Déploiement | 26 oct.–6 nov. | Warehouse V1 accessible sur le VPS | Connexion stable, restauration testée et aucune écriture possible depuis IDEA | À faire |
| 5. Intégration IDEA | 9–20 nov. | IDEA travaille directement sur le warehouse | Plusieurs scénarios exécutés sans export ni enrichissement externe intermédiaire | À faire |
| 6. Simplification et validation finale | 23–30 nov. | Architecture V1 validée et documentée | Scénarios retenus réussis de bout en bout avec un flux plus simple et reproductible | À faire |

## Phase 1 Cadrage

**Sous-étapes**

- partir du projet IDEA Hawaii et l’adapter use case par use case prioritaire ;
- choisir les campagnes et jeux de données de la V1 ;
- revoir le schéma existant avec Cyril ;
- définir les relations et identifiants communs.

**Validation attendue :** revue avec l’équipe confirmant que les données
EcoTaxa, EcoPart, CTD et FILET sont reliables pour les cas retenus.

## Phase 2 Construction du warehouse V1

**Sous-étapes**

- créer la base SQL ;
- importer EcoTaxa et EcoPart ;
- importer CTD et FILET ;
- documenter les tables, unités, clés et sources.

**Validation attendue :** les données prévues sont retrouvées par SQL et les
jointures de référence produisent les résultats attendus.

## Phase 3 Validation des données

**Sous-étapes**

- comparer les données aux sources originales ;
- vérifier les profils, dates, profondeurs et la taxonomie ;
- tester plusieurs jointures connues ;
- consigner les écarts et leur résolution.

**Validation attendue :** les cas de référence donnent les mêmes informations
que les sources originales, dans les tolérances documentées.

## Phase 4 Déploiement

**Sous-étapes**

- déployer PostgreSQL sur le VPS ;
- configurer les accès, sauvegardes et mesures de sécurité ;
- tester une restauration ;
- donner à IDEA un accès en lecture seule.

**Validation attendue :** la connexion est stable, la restauration est testée
et l’identité utilisée par IDEA ne peut effectuer aucune écriture.

## Phase 5 Intégration IDEA

**Sous-étapes**

- connecter IDEA au warehouse SQL ;
- tester la compréhension du schéma ;
- sauvegarder les sous-ensembles utiles dans le workspace ;
- exécuter les analyses Python et produire les graphiques.

**Validation attendue :** plusieurs scénarios sont exécutés de bout en bout sans
export ni enrichissement externe intermédiaire.

## Phase 6 Simplification et validation finale

**Sous-étapes**

- comparer le nouveau flux au flux actuel ;
- identifier les outils devenus inutiles ;
- tester la non-régression ;
- documenter la V1 et la suite.

**Validation attendue :** les scénarios retenus fonctionnent de bout en bout
avec un flux plus simple, vérifiable et reproductible.

## Journal d’avancement

### 11 septembre 2026 Préparation du socle

- dépôt initialisé depuis IDEA Hawaii `next-dev` au commit
  `5b1322dbe68fefd31fc1de29a076b1746a36c5d7` ;
- ancienne version NeoLab préservée dans l’archive locale
  `../IDEA-archive-20260911` ;
- stack locale macOS ARM64 démarrée avec Open WebUI, LangGraph, LiteLLM,
  Langfuse, PostgreSQL, Redis et sandbox Docker ;
- modèle local configuré sur `gpt-5.5` et Pipe IDEA rendu disponible dans Open
  WebUI ;
- 268 tests de la suite principale et 11 tests du sandbox réussis ;
- exécution Python réelle et persistance d’un DataFrame dans un noyau actif
  vérifiées.
- RAG natif Open WebUI désactivé globalement pour les nouveaux téléversements
  locaux : le client demande `process=false` et le serveur impose ce choix même
  lorsqu’un ancien client demande `process=true` ; test HTTP réussi avec
  réponse `data: {}`, journal serveur `process=False`, sans suivi de traitement
  ni génération d’embeddings ;
- 24 tests ciblés réussis pour la politique sans RAG et le déploiement des
  assistants Open WebUI ;
- observabilité branchée sur le projet Langfuse US Cloud : diagnostic du rejet
  401 causé par l’hôte local et un caractère non ASCII dans la clé secrète,
  correction de la paire, hôte Compose rendu configurable, puis trace d’un
  appel `gpt-5.5` validée par l’API Cloud ;
- suivi utilisateur/session du mode Normal validé de bout en bout via
  Open WebUI/LangGraph/LiteLLM : la trace Cloud contient l’email comme
  `userId` et la conversation comme `sessionId` ; le mode Advanced reste hors
  de ce périmètre tant que son chemin `/v1/responses` ne conserve pas ces
  attributs avec la version LiteLLM épinglée ;
- traitement d’embeddings lancé par l’ancien chemin sur un CSV arrêté avant le
  déploiement du correctif.

### 14 septembre 2026 Rechargement de la clé OpenAI

- `OPENAI_API_KEY` est présente dans `.env` et valide par `curl` ;
- après libération de caches locaux et redémarrage de Docker Desktop, les
  services LangGraph/LiteLLM ont été recréés ;
- les empreintes de la variable dans les deux conteneurs correspondent à `.env`
  et `GET /health` de LangGraph répond correctement.

**Limite :** le test de santé ne remplace pas encore un échange conversationnel
complet avec appel d’outil depuis Open WebUI.

### 21 septembre 2026 Enrichissement spatial FILET

- `warehouse.filet_sample` porte désormais les mêmes métadonnées de zone maritime versionnées que les profils : clé, nom, source, version et statut d’affectation ; migration idempotente dans `docs/warehouse_filet_zone_migration.sql`.
- Les **6 102** échantillons FILET géolocalisés ont été classés avec `shared_data/geo/zones_registry.geojson` (`registry-v1`) : **5 239 assigned**, **863 ambiguous**. Les cas ambigus restent explicites, sans choix arbitraire entre zones qui se chevauchent.
- Le chargeur FILET réapplique cette affectation lors de chaque recharge, et `explore.filet_samples` expose les colonnes.
- Le navigateur filtre maintenant FILET directement sur `filet_sample.marine_zone_name` ; contrôle : la Baie de Baffin retourne **1 467** échantillons FILET à la fois dans la synthèse et sur la carte.

### 18 septembre 2026 Proposition de schéma warehouse

- Proposition documentée dans [docs/WAREHOUSE_PROPOSAL.md](docs/WAREHOUSE_PROPOSAL.md) :
  grains FILET/UVP/CTD, sources EcoTaxa/EcoPart/Amundsen, versions, appariements,
  vues SQL en lecture seule et journal d'exploration séparé.
- Documentation locale et pages officielles des fournisseurs consultées.
- Limites : archive absente au chemin prévu ; aucun export métier inspecté,
  aucune jointure exécutée, aucun test runtime ni validation scientifique.
- Phase 1 en cours, non validée. Prochaine étape : revue des exports et des
  règles d'appariement avec Cyril et l'équipe sur une campagne représentative.
- GitHub Project : aucun identifiant de projet trouvé dans les références
  locales consultées ; synchronisation non effectuée. Aucun push ni publication.

### 18 septembre 2026 Jointures et calculs confiés aux outils

- Cadrage corrigé sur demande : jointures scientifiques et calculs métier
  confiés à des outils déterministes ; exploration par l'agent de relations
  préparées. Appariement FILET/UVP ↔ CTD spatial et temporel, extraction
  verticale séparée.
- [Brouillon SQL pour revue](docs/warehouse_schema_proposal.sql) ajouté :
  données versionnées, unités FILET/UVP/CTD, observations, politiques,
  exécutions, correspondances, résultats et historique d'exploration.
- Limites : DDL non exécuté, outils non implémentés, droits et publication
  immuable à construire ; pas de validation scientifique ni de fin de phase.
  GitHub Project reste non synchronisé, faute d'identifiant identifié.

### 18 septembre 2026 Recentrage sur SQL vers DataFrame

- La correction utilisateur remplace le cadrage précédent : IDEA génère du
  SQL en lecture seule et charge les résultats dans son notebook. `work.*`
  retiré du brouillon ; relations connues et vues simples prioritaires.
- Code public EcoPart consulté au commit
  `4dcd5968bb299b42d2f38406b19b8ca8354503f8` : CTD importée par nom
  d'échantillon dans le projet, export EcoTaxa via projet lié et `orig_id`.
  Ces preuves ne confirment pas la version ni les exports NeoLab.
- Proposition et SQL révisés. Clés FILET et liens avec le catalogue CTD
  Amundsen encore à vérifier sur les données ; aucun appariement, DDL ou
  scénario notebook exécuté. Phase 1 toujours en cours. GitHub Project
  non synchronisé, identifiant toujours non disponible.

### 18 septembre 2026 Vérification des exports FILET réels

- CSV retrouvés sur le Bureau et inspectés en lecture seule : métadonnées
  6 105 lignes, abondances/biomasses 5 047 lignes, dictionnaire de 93 colonnes.
  Empreintes et preuves dans [docs/FILET_EXPORT_REVIEW.md](docs/FILET_EXPORT_REVIEW.md).
- Jointure pandas `many_to_one` sur SAMPLE_ID + ANALYSIS_ID : 4 941 appariés,
  106 non appariés (9 analyses de 2024 absentes des métadonnées), sans
  multiplication des lignes. Aucun écart sur six champs de contexte comparés.
- Schéma FILET corrigé : multiples analyses/filets, valeurs déjà calculées,
  deux volumes, biomasses et stades/agrégats distincts, LEFT JOIN explicite.
- Limites : aucun identifiant CTD/EcoTaxa explicite dans ces exports ; DDL
  non exécuté, scénario IDEA non testé. Phase 1 en cours ; GitHub Project
  non synchronisé, identifiant non disponible. Aucun fichier source modifié.

### 18 septembre 2026 Recherche de l'ancien schéma et exports UVP

- Ancien schéma SQLite non retrouvé ; le dossier `~/PROJET_INFO/IDEA` ne
  contient aucun fichier. Archive attendue toujours absente.
- Exports et script R retrouvés dans Downloads/UVP_metrics_for_MCA : 30 profils
  communs EcoTaxa/EcoPart, clé profil + profondeur EcoPart unique. Jointure
  reproduite en lecture seule : 137 128/137 128 objets appariés sans duplication.
- Preuves dans [docs/UVP_EXPORT_REVIEW.md](docs/UVP_EXPORT_REVIEW.md).
  Champ CTD présent mais partiellement vide ; lien Amundsen non vérifié.
  Aucun changement runtime/DDL, phase 1 non clôturée. GitHub Project reste
  non synchronisé faute de référence identifiée.

### 18 septembre 2026 Ancien schéma retrouvé dans Git

- Ancien code NeoLab retrouvé dans `origin/main` (`475af5d`) et les branches
  EcoPart/comparabilité. Inspection par `git show`, aucun checkout.
- DDL SQLite EcoTaxa et manifeste EcoPart, pont SQL/DataFrame, contrat de
  jointure EcoTaxa/EcoPart et matcher CTD par nom de fichier examinés.
  Références dans docs/LEGACY_WAREHOUSE_REFERENCES.md (archivé depuis, contenu repris dans le schéma et WAREHOUSE_ARCHITECTURE.md).
- La recherche antérieure concernait les fichiers sur disque : le code
  historique est disponible dans Git, les bases de données remplies ne sont
  pas retrouvées. Aucun test historique exécuté, phase 1 toujours en cours.
  GitHub Project non synchronisé faute de référence identifiée.

### 18 septembre 2026 Validation documentaire de la proposition V1

- Contrat V1 récapitulé : métadonnées EcoTaxa conservées, UVP dérivé
  EcoTaxa/EcoPart par bin, FILET importé avec ses abondances normalisées,
  CTD reliée au profil et surface SQL pour DataFrame.
- Diagramme ajouté dans [docs/WAREHOUSE_ARCHITECTURE.md](docs/WAREHOUSE_ARCHITECTURE.md).
- Neuf tests de contrat ajoutés dans `tests/test_warehouse_schema.py` : couches,
  grains, formule UVP, agrégation pondérée, conservation des valeurs FILET,
  liens CTD et conservation des non-appariés. Résultat : 9/9 réussis.
- Cette entrée documente l'état initial de la proposition ; la couche
  `filet_uvp_abundance` et le DDL exécutable sont détaillés dans l'entrée
  suivante. Phase 1 reste en cours ; aucun use case conversationnel déclaré
  validé.

### 18 septembre 2026 Couche d'exploration EcoTaxa/EcoPart/CTD

- Le brouillon SQL expose le parcours direct
  `uvp_projects → uvp_samples → uvp_objects → uvp_taxon_abundance`, avec
  rattachement objet → bin EcoPart, volume échantillonné et métadonnées
  EcoTaxa conservées.
- Les liens `ecotaxa_ctd_profile`/`ecotaxa_ctd` donnent accès au profil puis
  aux mesures CTD sans refaire la jointure dans l'agent. La comparaison FILET
  reste disponible par `filet_uvp_matches` et `filet_uvp_abundance`, avec une
  table de mapping taxonomique explicite.
- Validation : 11 tests de contrat Python réussis, `git diff --check` réussi,
  et exécution complète du DDL dans une base PostgreSQL temporaire réussie.
- Limites : ingestion réelle, cardinalités CTD et taxonomie doivent encore
  être vérifiées sur un jeu de campagne avant de déclarer le use case validé.

### 18 septembre 2026 Premiers cas d'usage UVP

- Cas documentés dans [docs/UVP_USE_CASES_SQL.md](docs/UVP_USE_CASES_SQL.md) :
  projets, zones maritimes, samples, objets, bins, abondances et CTD.
- Le modèle expose désormais la zone maritime, sa source, sa version et son
  statut d'affectation sur les profils/samples, ainsi que `cast_key` et le
  nombre de casts par projet.
- Les frictions sont explicitées : point-dans-polygone, dictionnaire CTD,
  agrégation multi-bins et mapping taxonomique. Le rattachement objet/bin est
  déterministe via `object_depth_min` et la grille de 5 m historique.

### 18 septembre 2026 Intégration du contrat CTD historique

- Le catalogue `warehouse.ctd_variable` reprend les codes Amundsen validés dans
  l'historique Git (`PRES`, `TE90`, `PSAL`, `SIGT`, `OXYM`, `pH`, `NTRA`, `FLOR`).
- La documentation décrit le rattachement par nom de fichier CTD, puis la
  confirmation station/temps/position, ainsi que la distinction entre point
  CTD enrichi et profil vertical complet.
- 14 tests de contrat réussissent et le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Cas de découverte et diagnostic des lacunes

- `docs/UVP_USE_CASES_SQL.md` couvre désormais l'inventaire des sources, la
  complétude des métadonnées, la couverture CTD, l'audit des jointures
  EcoTaxa/EcoPart, les taxons observés, la couverture spatiale/verticale et la
  table globale destinée aux graphiques.
- Les vues existantes exposent les colonnes nécessaires à ces diagnostics,
  notamment `dataset_version_id`, `ecopart_project_id` et les zones dans
  `explore.uvp_objects`.
- 15 tests de contrat réussissent ; le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Analyses UVP concrètes par zone

- Les use cases couvrent maintenant les agrégats zone, station, profil,
  sample, bin et objet, avec abondance moyenne par profondeur.
- Des requêtes combinent EcoTaxa, EcoPart et CTD au grain sample, et une vue
  séparée conserve les objets EcoTaxa au grain objet pour l'audit des images et
  des rattachements de bins.
- La moyenne d'abondance est calculée après agrégation objets/volume par profil
  afin de ne pas surpondérer les profils ayant davantage de bins.
- 16 tests de contrat réussissent ; le DDL complet s'exécute dans PostgreSQL
  temporaire.

### 18 septembre 2026 Registre des frictions ouvertes

- Les cas qui n'ont pas encore de solution validée sont suivis dans
  [docs/UVP_FRICTIONS_OPEN.md](docs/UVP_FRICTIONS_OPEN.md) : métadonnées
  manquantes, couverture CTD, unités, taxonomie, versions et grains de
  jointure.
- Chaque entrée précise son statut, la gestion prévue, la preuve attendue et
  les critères de clôture. L'agent doit exposer les statuts au lieu de choisir
  une valeur absente ou ambiguë.

### 18 septembre 2026 Plan de peuplement V1

- Le plan est documenté dans
  [docs/WAREHOUSE_POPULATION_PLAN.md](docs/WAREHOUSE_POPULATION_PLAN.md).
- L'ordre retenu est manifeste → EcoTaxa → EcoPart → CTD → liens → FILET →
  vues et contrôles finaux.
- Le script historique `core/ecotaxa_browser/cache/sync.py` est utilisé comme
  référence d'extraction, de signatures, de retries et de contrôles ; son cache
  SQLite ne remplace pas le warehouse PostgreSQL.

### 18 septembre 2026 Décision de stockage PostgreSQL/PostGIS

- La décision est documentée dans
  [docs/WAREHOUSE_STORAGE_DECISION.md](docs/WAREHOUSE_STORAGE_DECISION.md).
- PostgreSQL devient la source de vérité ; PostGIS calcule l'affectation des
  samples aux zones à l'ingestion. Les fichiers bruts et Parquet restent
  référencés par manifeste et empreinte.
- La prochaine étape est le plan opérationnel d'accès aux sources, de
  téléchargement vérifié, de staging et de chargement.

### 18 septembre 2026 Validation technique du warehouse V1 EcoTaxa/CTD

- PostgreSQL/PostGIS local est opérationnel dans Docker (`neolab-warehouse-db`)
  avec sauvegarde compressée versionnée hors Git.
- EcoTaxa contient 23 projets, 6 138 samples et 15 050 002 objets chargés.
- Amundsen contient 456 profils CTD et 5 130 421 mesures ; 904 samples
  EcoTaxa sont reliés, dont les codes courts 2023/2024 résolus par date et
  position. Les références sans correspondance restent conservées et
  qualifiées.
- Les vues `explore.*` de navigation UVP, EcoTaxa–CTD et FILET–UVP/CTD sont
  créées dans le DDL et présentes dans la base. Les vues UVP/EcoPart restent
  vides jusqu'au prochain chargement EcoPart.
- La couverture et les limites sont détaillées dans
  [docs/WAREHOUSE_ECOTAXA_QA.md](docs/WAREHOUSE_ECOTAXA_QA.md). La prochaine
  étape est l'accès, l'extraction et le chargement EcoPart.

### 21 septembre 2026 Chargement et validation EcoPart

- Les outils historiques EcoPart/EcoTaxa retrouvés dans Git ont été examinés : résolution serveur `filt_proj`, métadonnées du profil, jointure exacte au profil et grille de profondeur de 5 m. L'archive locale reste absente.
- Un chargeur idempotent a téléchargé et conservé les archives originales de 11 projets EcoPart accessibles, avec empreinte, tâche serveur et manifeste local ignoré par Git. Les données sont chargées au grain profil/bin ; les lignes ZOO et métadonnées source restent séparées des particules.
- Le warehouse contient 585 profils EcoPart, 59 801 bins et 10 479 780 objets EcoTaxa reliés à un bin. Les 228 objets sans bin restent explicitement non appariés ; la vue d'objets en expose donc 10 480 008. La couche d'abondance conserve les zéros des bins sans objet dans les dénominateurs.
- Validation réelle : 11 archives comparées aux bins PostgreSQL sans écart ; six audits de jointure, profondeur, cardinalité, formule et provenance CTD retournent 0 anomalie. Les tests ciblés, dont la base PostgreSQL temporaire, réussissent.
- Les sources, limites et commandes de reprise sont documentées dans `docs/WAREHOUSE_ECOPART.md` et `docs/WAREHOUSE_ECOTAXA_QA.md`.
- Après un incident d'espace disque et le redémarrage de Docker le 21 septembre, PostgreSQL accepte de nouveau les requêtes. La migration additive `docs/warehouse_ecopart_migration.sql` a recréé les vues `explore.*` absentes de l'instance restaurée ; une jointure de contrôle donne 36 profils EcoPart/36 samples EcoTaxa pour 417↔5149 et 86 profils/samples pour chacune des politiques 86↔149 et 86↔20880. Pour `de110_001`, `ecotaxa:name:like<Copepoda` donne 308 objets sur 6 121,17 L, soit 50,32 ind/m³ ; aucun lien objet–bin orphelin n'est trouvé.
- **Réparation Docker, 21 septembre :** après les erreurs d'E/S du disque virtuel Docker, le stockage a été recréé puis le dump `data/warehouse_backups/neolab_warehouse_ecopart_20260921.dump` restauré sans erreur. Le contrôle SQL post-restauration retrouve 585 profils EcoPart, 59 801 bins et 10 479 780 objets appariés. Les liens 417↔5149 et 86↔149/20880 donnent respectivement 36/36 et 86/86 profils/samples ; le cas `de110_001`–Copepoda donne 308 objets, 6 121,17 L et 50,32 ind/m³. Les contrôles d'intégrité retournent 0 lien objet–bin orphelin et 0 lien non accepté.
- **Simulation SQL de parcours, 21 septembre :** la requête « profils de la Baie de Baffin en 2024 » retourne 123 profils EcoPart, tous géolocalisés. Pour la carte, le taxon explicite `ecotaxa:name:Copepoda<Multicrustacea` retourne une série d'abondance pour chacun des 123 profils, sans double politique d'annotation ; l'abondance cartographiée est `SUM(objets) / SUM(volume_L) × 1000`, au grain profil. Les autres clés contenant « Copepoda » sont des catégories distinctes et ne sont pas fusionnées implicitement.
- **Validation au grain bin, 21 septembre :** ces 123 profils ont 13 800 bins, tous avec intervalle de profondeur et volume échantillonné valides, sans doublon de profondeur dans un profil. Pour `am_leg3_RA02_1`, la série Copépodes restitue notamment 132 objets sur 64 L entre 20 et 25 m (2 062,50 ind/m³) et des zéros explicites lorsque le bin n'a aucun objet du taxon.
- **Test de rendu Python, 21 septembre :** l'image LangGraph reconstruite contient `psycopg` et Matplotlib. Un script exécuté dans cette image a lu les 95 bins de `am_leg3_RA02_1` via PostgreSQL et produit un PNG Matplotlib. Aucun outil warehouse n'est encore enregistré dans `langgraph/` : cette preuve valide le runtime, pas encore le use case conversationnel d'accès libre aux données.

### 21 septembre 2026 Chargement FILET

- Les trois exports FILET validés du 26 mai 2026 ont été chargés par
  `scripts/populate_filet.py` avec leurs trois empreintes SHA-256 dans une
  version unique `filet/neolab-filet/2026-05-26`. Les fichiers bruts du Bureau
  restent inchangés.
- Le warehouse contient 6 102 échantillons, 1 502 analyses, 6 229 appartenances
  échantillon-filet et 90 780 lignes au grain ligne source × taxon × stade,
  issues de 5 047 lignes larges. Les valeurs explicites à zéro et l'absence de
  biomasse pour nauplii/totaux sont conservées ; aucun volume ni abondance n'a
  été recalculé.
- La jointure interne des métadonnées conserve 4 941 lignes source appariées
  et 106 non appariées (1 908 lignes de stades), comme dans la vérification
  initiale. Aucun orphelin de clé n'est trouvé. Les tables de liens FILET vers
  EcoTaxa, CTD ou UVP restent vides : les exports ne fournissent pas de preuve
  de ces relations.

### 21 septembre 2026 Navigateur de couverture V1

- Un navigateur local, indépendant de l'agent conversationnel, est disponible
  dans `warehouse_navigator/` et exposé par le service Docker
  `warehouse-navigator` sur `http://localhost:8090`. Il lit PostgreSQL en
  lecture seule et ne présente aucun objet individuel.
- Les filtres zone, année, projet EcoTaxa/EcoPart et recherche textuelle
  retournent les couvertures agrégées réelles : profils, bins, volume, objets
  EcoTaxa associés, séries taxonomiques, CTD, FILET et liens prouvés. FILET
  reste explicitement indépendant des filtres spatiaux/projets tant qu'un lien
  externe n'est pas démontré.
- Contrôle réel : « Baie de Baffin, 2024 » retourne 123 profils, 13 800 bins,
  4 279 581 objets associés, 117 séries taxonomiques, 94 profils CTD et 558
  échantillons FILET de 2024. Une recherche `21916` retourne l'échantillon
  FILET correspondant sans lui attribuer de lien UVP.

### 21 septembre 2026 Candidats FILET–UVP par station et temps

- `scripts/populate_filet_uvp_matches.py` crée des correspondances sans utiliser
  les identifiants de projets ou d'échantillons des deux méthodes. Il normalise
  uniquement le libellé de station puis applique une fenêtre temporelle passée
  explicitement par paramètre.
- Première exécution avec une fenêtre de 10 h : 130 liens uniques sont
  `accepted` et 288 lignes restent `ambiguous` lorsqu'un échantillon FILET a
  plusieurs profils UVP candidats. Les preuves stockent stations source et
  normalisée, dates, écart temporel, fenêtre et nombre de candidats. Aucun lien
  chargé ne dépasse 10 h.

**Limites :** EcoPart n'a retourné aucun lien pour dix projets EcoTaxa ; le projet 10101 n'est pas classé car son endpoint a expiré. Aucun use case conversationnel IDEA ni validation scientifique d'équipe n'est déclaré achevé. La prochaine étape reste l'ingestion FILET, puis les jointures FILET–UVP/CTD sur correspondances vérifiées.

**Limites restantes :** aucun schéma warehouse V1 ni jeu de campagnes n’est
encore validé avec l’équipe. Aucun use case scientifique NeoLab n’est encore
déclaré validé sur ce socle. Cette politique globale empêche aussi l’indexation
de nouveaux fichiers dans Open WebUI Knowledge ; le flux PaperQA devra être
validé séparément avant sa réactivation.

### 25 septembre 2026 Recette du navigateur de couverture

- Recette locale du service `warehouse-navigator` : `/health`, options et couvertures agrégées répondent sans erreur. Les contrôles Python ciblés ont réussi (22 tests).
- Les compteurs de la carte suivent les filtres réellement appliqués : toutes données (585 profils UVP, 6 102 échantillons FILET), puis Baie de Baffin (199, 1 467). En mode FILET–UVP, le seuil de 10 h retourne 6 profils UVP et 30 échantillons FILET dans cette zone ; 4 h les réduit à 2 et 4.
- L’interface a été vérifiée avec les couches, la zone, le projet EcoTaxa et le mode de comparaison. Le seuil horaire est masqué hors de ce mode ; le filtre EcoPart est retiré. Les points FILET indiquent désormais qu’ils regroupent des échantillons au même emplacement et présentent une plage temporelle lorsque nécessaire.
- Aucun avertissement ou erreur JavaScript n’a été relevé durant la recette. La carte a été restaurée à son état initial après test.

### 25 septembre 2026 Métadonnées des fiches cartographiques

- Les infobulles de comparaison FILET–UVP affichent désormais le titre du projet UVP/EcoTaxa associé au profil, provenant de `warehouse.ecotaxa_project`.
- Les fiches FILET et les comparaisons présentent les métadonnées d’équipement disponibles au grain échantillon : support, engin, type de trait, maille déclarée et nombre de filets. Elles sont agrégées explicitement lorsqu’un point représente plusieurs échantillons.
- Contrôle réel : la correspondance FILET `39908` ↔ UVP `am_leg2_killinik2` restitue le projet `uvp6_sn000006hf_2024_am_leg2`; les métadonnées FILET retournent notamment `CCGS Amundsen`, `2x1m2`, `O-Tow`, une maille de 50 et un filet.

### 25 septembre 2026 Hiérarchie des fiches de carte

- Les infobulles UVP, FILET et FILET–UVP utilisent désormais la même hiérarchie : titre, résumé, sections, libellés en gras et valeurs en texte normal. La légende suit également ce système typographique.
- Les profondeurs FILET min–max sont affichées dans les fiches, au grain de l’échantillon ou de l’agrégat cartographique. Exemple de recette visuelle : un groupe FILET affiche `0 à 511`; une comparaison affiche `0 à 100`.
- Une régression du mode comparaison a été trouvée puis corrigée : 132 candidats FILET–UVP ne possédaient pas de coordonnées UVP et provoquaient une erreur Leaflet. La vue cartographique exclut désormais ces seules paires non cartographiables ; les 286 paires localisables sont affichables, dont 130 acceptées et 156 ambiguës.

### 25 septembre 2026 Correctif d’affichage des heures FILET–UVP

- La fiche de comparaison affichait les horodatages FILET sans fuseau comme heure locale puis les étiquetait « UTC », créant une incohérence visible avec l’écart calculé. La paire FILET `41471` / UVP `am_leg5_TCA_T3_19_02` est stockée à 07:06:56 contre 04:00 UTC, soit 3 h 07.
- Le formateur de la carte interprète désormais les horodatages FILET sans suffixe comme UTC, conformément au calcul de `filet_uvp_match`. La fiche affiche donc 07 h 06 UTC, ce qui concorde avec l’écart de 3 h 07.

### 25 septembre 2026 Filtres cumulables du navigateur

- Le navigateur accepte une plage d’années « De / À » et plusieurs zones ou projets EcoTaxa par cases à cocher. Les mêmes paramètres sont appliqués aux compteurs, points UVP/FILET, contours de zones et correspondances FILET–UVP.
- Les sélections sont cumulatives ; chaque liste possède son action d’effacement. Une plage inversée est normalisée côté API.
- Recette réelle : deux zones et deux projets sélectionnés en 2024 retournent 39 profils UVP et 7 échantillons FILET ; après effacement, la couverture revient à 585 profils et 6 102 échantillons. La page locale est servie avec `Cache-Control: no-store` pour éviter l’interface périmée après redémarrage.

### 25 septembre 2026 Inclusion des chevauchements FILET dans les filtres de zone

- Les 863 échantillons FILET dont les coordonnées croisent plusieurs polygones restent qualifiés `ambiguous` dans leur provenance ; cette qualification ne les exclut plus d’un filtre spatial.
- Pour chaque zone sélectionnée, le navigateur teste les coordonnées de ces chevauchements contre le registre GeoJSON canonique local et inclut les points qui se trouvent réellement dans le polygone demandé. Aucune zone unique n’est donc assignée arbitrairement.
- Recette réelle : le filtre « Baie d’Hudson », auparavant à 0 à cause de cette politique de provenance, restitue désormais 235 échantillons FILET. Les 20 filtres de zone ont été contrôlés : pour chacun, le total des échantillons agrégés sur la carte égale le compteur de couverture retourné par l’API. Les 22 tests ciblés ont réussi.
