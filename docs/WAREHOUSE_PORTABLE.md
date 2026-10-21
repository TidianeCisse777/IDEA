# Warehouse Windows sans Docker

Ce déploiement local concerne les phases 1 et 2. Il lance PostgreSQL/PostGIS,
le navigateur FastAPI et DbHub comme processus utilisateur, sans service
Windows et sans modifier le PATH système. L'archive historique
`../IDEA-archive-20260911` est absente de ce PC : les données scientifiques
ne sont pas restaurées automatiquement.

## Composants locaux

Les exécutables et dépendances se trouvent sous `data/tooling/`, ignoré par
Git : PostgreSQL 16.15, PostGIS 3.6.2, Python 3.11.9 embarqué, Node 24.22.0
et DbHub installé par npm. La version npm exacte est enregistrée dans le
lockfile local `data/tooling/dbhub/package-lock.json`.

Sources de distribution : [PostgreSQL Windows](https://www.postgresql.org/download/windows/),
[PostGIS Windows](https://postgis.net/documentation/getting_started/install_windows/released_versions/),
[Python](https://www.python.org/downloads/windows/), [Node](https://nodejs.org/),
[DbHub](https://github.com/bytebase/dbhub).

## Démarrage et arrêt

Depuis la racine du projet dans PowerShell :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/warehouse.ps1 stop
```

`ExecutionPolicy Bypass` concerne uniquement ce processus, sans modifier la
politique de la machine. Les politiques imposées par l'organisation restent
prioritaires.

Interface : <http://127.0.0.1:8090>. PostgreSQL : `127.0.0.1:55432`.
Les deux services écoutent uniquement sur la boucle locale. Le cluster,
les journaux et les secrets générés restent dans `data/local_warehouse/`.
Ce dossier doit rester privé; ne pas le partager ou le commiter.

Le démarrage initialise seulement un cluster absent et une base sans schéma
warehouse. Un schéma existant n'est jamais recréé : les mises à jour futures
nécessitent des migrations explicites. Aucune donnée de démonstration n'est
injectée. Une base vide confirme le raccordement technique, pas les scénarios
scientifiques.

## DbHub dans Codex

Le lanceur `scripts/start_dbhub.ps1` lit le credential du rôle lecteur dans
le fichier local si la variable `WAREHOUSE_READER_PASSWORD` est absente.
Le secret n'est enregistré ni dans TOML ni dans les arguments du processus.
La configuration `dbhub/warehouse.toml` expose les outils SQL et découverte,
avec lecture seule, limite de 1 000 lignes et délai de 30 secondes.

L'outil `warehouse_context` fournit le contexte général et les fiches métier.
Les commentaires de vues/colonnes sont également visibles dans la découverte
DbHub; `explore.warehouse_dictionary` expose les types et transformations SQL,
et `explore.dataset_versions` les versions réellement enregistrées.
Le démarrage republie les métadonnées avec `publish_warehouse_context.publish`.
Pour actualiser aussi le document généré après modification du dictionnaire :

```powershell
data/tooling/python/python.exe scripts/publish_warehouse_context.py
```

Cette publication transactionnelle modifie uniquement des vues et commentaires
descriptifs, sans changer les valeurs scientifiques ni autoriser les écritures
aux rôles applicatifs. [Dictionnaire complet](WAREHOUSE_MCP_DICTIONARY.md).

Le rôle `warehouse_reader` lit uniquement les vues `explore`. Le rôle séparé
`warehouse_navigator` lit les tables nécessaires à l'interface; tous deux ont
leurs transactions en lecture seule. Les vues ne remplacent pas une politique
d'accès aux données de production.

Pour enregistrer le lanceur, utiliser `codex mcp add neolab-warehouse --
powershell.exe -NoProfile -ExecutionPolicy Bypass -File <chemin-absolu-du-lanceur>`.
Redémarrer la session Codex pour charger le nouveau serveur et découvrir ses
outils, conformément à la [documentation MCP Codex](https://developers.openai.com/codex/mcp).

## Tests ciblés

```powershell
data/tooling/python/python.exe -m unittest discover -s tests -p test_warehouse_audit.py
data/tooling/python/python.exe -m unittest discover -s tests -p test_navigator_spatial.py
data/tooling/node-v24.22.0-win-x64/node.exe --test tests/navigator_ui.test.cjs
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_dbhub_launcher.ps1
```

La recette HTTP doit couvrir `/health`, `/api/options`, `/api/coverage`,
`/api/map` et `/api/filet-uvp`, avec et sans `max_distance_km=0`.
La recette SQL confirme PostGIS, le compte lecteur, les vues accessibles et
les refus de lecture brute et d'écriture. Le suivi d'exécution dans ROADMAP
précise ce qui a réellement été vérifié.
