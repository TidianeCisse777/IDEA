# Schémas et jointures retrouvés dans Git

18 septembre 2026 — consultation par `git show`, sans checkout ni exécution.

L'ancienne archive sur disque reste absente, mais l'historique NeoLab est
disponible dans les références locales du dépôt. Référence examinée :
`origin/main`, commit `475af5d` du 13 août 2026, « Stabilize dataframe lifecycle
and confirmations ». Les références `origin/codex/ecopart-persistent-demo-cache`
(`92aa3f5`) et `origin/codex/net-uvp-comparability` (`df65926`) existent aussi.

## SQLite EcoTaxa

`core/ecotaxa_browser/cache/repo.py`, DDL à partir de la ligne 111 :

- `samples_cache` : grain échantillon, `sample_id` PK, `project_id`,
  `original_id`, `station_id`, `profile_id`, `cruise_id`,
  `ctd_rosette_filename`, coordonnées, dates/profondeurs, instrument,
  compteurs d'objets et de statuts, `used_taxa`, champs libres JSON.
- `projects_cache` : métadonnées et compteurs par projet.
- `project_schemas_cache` : schémas source sous forme JSON.
- `project_signatures_cache` et `sync_runs` : suivi du cache.

Le cache ne contient pas les mesures individuelles des objets. Sa documentation
`core/copepod_rag/docs/ecotaxa_cache_sql.md` distingue clairement navigation SQL
au grain sample et export objet pour les calculs taxonomiques/morphométriques.
`core/ecotaxa_browser/cache/dataframe_bridge.py` permettait aussi de joindre
des DataFrames dans SQLite en mémoire, avec le cache attaché en lecture seule.
Ce contrat est une référence pour SQL → DataFrame, pas une instruction de
réintroduire l'ancien runtime ou son stockage de session.

## SQLite et fichiers EcoPart

`core/ecopart_cache.py` décrit `data/ecopart_cache/manifest.sqlite` :

- `tsv_entries` : empreinte, chemin, profils et colonnes JSON, provenance,
  projets EcoPart/EcoTaxa, nombre de lignes et date d'import ;
- `project_resolutions` : correspondances entre projets et leur statut ;
- `sample_previews` : aperçus d'échantillons.

Les données sont dans des fichiers TSV référencés, pas toutes dans SQLite.
Colonnes minimales : `Profile`, `Depth [m]`, `Sampled volume [L]`.

## Jointures et CTD

- `core/ecotaxa_ecopart_join.py` : `object_depth_min`, centres de tranches
  de 5 m, volume `ecopart_Sampled volume [L]`, audit des duplications,
  volumes manquants/non positifs/incohérents, tranches sans objet. Les tranches
  échantillonnées sans objet doivent rester représentées dans les dénominateurs.
- `core/ctd_filename_match.py` : correspondance UVP/Amundsen par
  `ctd_rosette_filename` ↔ `filename`, avec normalisation d'alias. Les noms
  courts pouvant se répéter, ce module exige aussi accord station, temps et
  position avant `join_eligible`. Valeurs par défaut historiques : 2 km et
  90 minutes ; ce ne sont pas des seuils V1 nouvellement validés.
- `core/amundsen_ctd_client.py`, `tools/amundsen_sources.py` et
  `tools/ctd_matcher.py` sont également présents, à inspecter en détail.
- Le skill applicatif `agents/skills/amundsen_ctd_query.md` décrit le chemin
  par nom de fichier et le fallback spatiotemporel, ainsi que la récupération
  d'un profil entier versus un point enrichi. Il ne constitue pas à lui seul
  une preuve d'exécution du client ni une instruction au nouvel agent.

## Conséquence pour le cadrage

Le schéma proposé doit désormais être confronté à ces contrats historiques,
en plus des exports réellement inspectés. Il n'est plus nécessaire de demander
une copie de l'ancien code pour commencer cette revue. Les fichiers SQLite
contenant les données n'ont pas été retrouvés : leur DDL et leur code le sont.
Ne pas confondre absence d'archive sur disque et absence d'historique Git.
Aucun test historique exécuté, aucune donnée distante téléchargée.
