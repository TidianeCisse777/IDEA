# NeoLab MCP — warehouse de données plancton et océan

Serveur MCP qui donne à un assistant IA (Claude, Codex, OpenCode, VS Code / Copilot) un accès en lecture au
**warehouse NeoLab** (Université Laval) : PostgreSQL 16 + PostGIS, avec les données de l'Arctique canadien.

| Source | Contenu |
|---|---|
| EcoTaxa | 23 projets (UVP, Zooscan, LOKI), 15 M d'objets : taxon et lignée, statut validé/prédit, taille, image |
| EcoPart (UVP) | 686 profils : tranches de profondeur, volumes échantillonnés, particules, abondances par taxon |
| CTD Amundsen | 456 profils : température, salinité, densité, oxygène, nitrate, fluorescence (pas de pH) |
| FILET | 6 102 échantillons de filet, abondances et biomasses de copépodes par stade |
| Référentiels | zones maritimes, stades de copépodes, taxonomie EcoTaxa, documents (protocoles, méthodes) |

L'assistant reçoit des **fiches** (grain, clés, unités, pièges de chaque vue), une **base de connaissances**
(documents cherchables) et des règles de réponse : il explore avant d'écrire du SQL, ne devine aucun nom de
colonne, dit ses choix et liste ses requêtes.

## Comment ça marche

```
EcoTaxa, EcoPart, CTD, FILET ──chargeurs──▶ PostgreSQL (schéma warehouse, sécurité par ligne)
                                                  │ vues explore.* et catalogue.*, fiches MCP
                                                  ▼
           assistant IA ◀── MCP (stdio) ── relais warehouse_connect.py ── DbHub ── compte de lecture
```

- **Relais** `scripts/warehouse_connect.py run` : lance DbHub, ajoute les instructions du serveur, donne des
  noms d'outils clairs, ajoute une aide aux erreurs SQL. Outils : `read_data_guide`, `run_sql_query`,
  `find_tables_and_columns`, `search_documents`, `read_document`.
- **Image tout-en-un** `docker/allinone` : PostgreSQL + PostGIS + DbHub + relais dans un conteneur
  `neolab-warehouse`; l'assistant lance le serveur par `docker exec -i neolab-warehouse neolab-mcp`.

## Installer (utilisateur)

Il ne faut que **Docker Desktop**. Avec la copie partagée (deux zips), lancer l'installeur de son système;
il construit l'image, installe la base et branche les assistants trouvés. Détails :
[docs/WAREHOUSE_PARTAGE_LISEZMOI.md](docs/WAREHOUSE_PARTAGE_LISEZMOI.md).

| Système | Installer | Rebrancher les assistants | Mettre à jour |
|---|---|---|---|
| Windows | `scripts/install_shared_copy_windows.bat` | `scripts/connect_assistants_windows.bat` | `scripts/update_warehouse_windows.bat -Auto` |
| macOS | `scripts/install_shared_copy_mac.command` | relancer l'installeur | relancer l'installeur |
| Linux | `scripts/install_shared_copy.sh` | relancer l'installeur | relancer l'installeur |

Puis, dans le dossier de travail créé par l'installeur : `cd ~/neolab-travail` et `claude`, `codex` ou
`opencode`. La mise à jour Windows récupère le dernier code de cette branche, applique les migrations et
recharge le FILET s'il a changé, sans toucher aux données ni aux comptes.

## Organisation du dépôt

```
scripts/      relais MCP, déploiement, comptes, fiches, base de connaissances, chargeurs, installeurs
  warehouse_connect.py          relais MCP, vérification, branchement des assistants
  deploy_warehouse_postgres.py  migrations + fiches + documents, rapport « PRÊT »
  warehouse_context.py          contenu des fiches MCP (une par vue) et règles de graphiques
  publish_warehouse_context.py  publie les fiches dans catalogue.warehouse_context
  add_warehouse_document.py     base de connaissances (documents .md, .txt, .pdf)
  warehouse_user.py             comptes personnels et périmètres (contrat, zone, années)
  populate_*.py, load_*.py      chargeurs EcoTaxa, EcoPart, CTD, FILET, zones
  install_*, connect_*, update_*  installation, branchement des assistants, mise à jour
sql/          migrations PostgreSQL, appliquées dans l'ordre de deploy_warehouse_postgres.py
dbhub/        configuration DbHub (outils SQL, fiches, documents)
docker/       image tout-en-un (allinone) et petite image de publication des fiches (context)
docs/         documentation du warehouse, documents de la base de connaissances (docs/filet, …)
shared_data/  export FILET du labo (CSV, classeur) et registre des zones maritimes
tests/        tests du schéma, des droits, du relais, des chargeurs et batterie de questions d'agent
```

## Développer

```bash
pip install -r scripts/requirements-warehouse.txt
python -m pytest -q tests/                      # tests rapides (ceux qui demandent PostgreSQL sont sautés sans lui)
python scripts/deploy_warehouse_postgres.py --check   # sur une base : migrations, fiches, rapport « PRÊT »
```

Dans le conteneur tout-en-un, `neolab-update <version>` applique un code copié dans `/opt/neolab/IDEA`.
Règles de contribution : [AGENTS.md](AGENTS.md). Historique et preuves : [ROADMAP.md](ROADMAP.md).

## Confidentialité

La base contient des projets EcoTaxa privés et les noms et courriels des responsables de projets. Ne pas
transmettre une copie sans accord. Aucun mot de passe dans le dépôt : ils sont générés dans le conteneur.
Avec un modèle d'IA, les résultats des requêtes partent chez son fournisseur : préférer un fournisseur sans
conservation des données.
