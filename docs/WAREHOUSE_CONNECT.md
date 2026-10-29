# Se connecter au warehouse avec DbHub (Codex, Claude)

Chaque personne se connecte avec **son propre compte** : son périmètre de lecture
([contrats, zones, années](WAREHOUSE_ACCESS_CONTROL.md)) est appliqué par la base, quel que soit le client.
Les identifiants restent dans un fichier privé hors du dépôt; ils n'apparaissent jamais dans une
configuration MCP, une commande ou une sortie.

## Pour la personne qui teste (5 minutes)

Prérequis : Python 3.10+, Node.js 18+ (DbHub 1.5.0 est téléchargé au premier lancement, ou installé une fois
avec `install-dbhub` pour ne plus dépendre du réseau) et un accès
réseau au serveur PostgreSQL.

```bash
# 1. Enregistrer le fichier remis par l'administrateur (puis le supprimer)
python scripts/warehouse_connect.py init --from-file mon_compte.env
#    (option --keyring: mot de passe dans le trousseau du système, avec `pip install keyring`)

# 2. Vérifier: connexion, compte, périmètre, catalogue, contexte métier
python scripts/warehouse_connect.py check

# 3. Brancher votre client (affiche la commande exacte pour votre poste)
python scripts/warehouse_connect.py config codex           # ou claude-code, claude-desktop
```

Un `PASS` signifie que DbHub est utilisable depuis ce poste. Redémarrer ensuite le client pour qu'il
charge le serveur `neolab-warehouse`.

| Client | Enregistrement |
|---|---|
| Codex | `codex mcp add neolab-warehouse -- <python> <chemin>/scripts/warehouse_connect.py run` ou bloc `[mcp_servers.neolab-warehouse]` de `~/.codex/config.toml` |
| Claude Code | `claude mcp add --scope user neolab-warehouse -- <python> <chemin>/scripts/warehouse_connect.py run`, ou `.mcp.json` de projet (sans secret) |
| Claude Desktop | bloc `mcpServers` de `claude_desktop_config.json` |

### Que demander ensuite

Dans le client, commencer par ces questions : elles utilisent les mêmes points d'entrée que les agents.

| Pour savoir… | Lire |
|---|---|
| ce que **mon compte** peut lire | `SELECT * FROM explore.my_access` |
| quels jeux existent, y compris hors de mon périmètre | `SELECT * FROM explore.dataset_catalog` |
| à quel point les métadonnées sont complètes | `SELECT * FROM explore.fair_readiness` |
| comment utiliser une vue (grain, limites, exemple) | outil `warehouse_context` (`topic=overview`, puis le nom de la vue) |
| les colonnes, types et définitions | `SELECT * FROM explore.warehouse_dictionary` |

Un résultat vide peut signifier **un accès limité**, pas une absence de données : vérifier `my_access` d'abord.

### Dépannage

| Symptôme du `check` | Cause probable |
|---|---|
La recette lit l'erreur de DbHub et donne la cause, sans jamais afficher de secret :

| Message du `check` | Que faire |
|---|---|
| `Identifiants absents` | refaire l'étape 1 |
| `validité du mot de passe: … expiré` ou `prévoir son renouvellement` | demander un `rotate` à l'administrateur |
| `identifiants refusés` | mot de passe faux, renouvelé ou expiré : demander un nouveau fichier |
| `le serveur exige une connexion chiffrée` | `WAREHOUSE_DB_SSLMODE=require` |
| `certificat du serveur non vérifiable` | indiquer le certificat d'autorité (`WAREHOUSE_DB_SSLROOTCERT`) ou utiliser `require` |
| `serveur injoignable` | service arrêté, port fermé ou tunnel SSH absent |
| `nom d'hôte inconnu` / `délai réseau dépassé` | vérifier l'adresse; pare-feu, VPN ou tunnel |
| `périmètre: aucun droit accordé` | compte créé sans droit: demander un accès à l'administrateur |
| vues UVP vides alors que le périmètre n'est pas vide | il manque le droit sur l'autre source (EcoTaxa **et** EcoPart); la ligne `jeux lisibles` de `check` le signale. Voir [composer des droits](WAREHOUSE_ACCESS_CONTROL.md#composer-des-droits-sur-plusieurs-sources) |
| `contexte métier` en échec | le contexte n'a pas été publié: l'administrateur relance le service `warehouse-context` (Docker) ou le déploiement |
| `Node.js 18+ est requis` | installer Node.js 18+ |
| poste sans accès à npm | sur un poste connecté, `python scripts/warehouse_connect.py install-dbhub`, puis copier `data/tooling/dbhub` |

### Tester avec un agent

Avec Claude Code installé, un agent peut utiliser le serveur sans rien configurer d'autre que le fichier
d'identifiants. Le fragment `config json` donne la configuration; l'agent suit seul le parcours de découverte
(`warehouse_context`, `explore.my_access`, `explore.dataset_catalog`).

```bash
python scripts/warehouse_connect.py config json > mcp.json      # puis ajouter "env" si le fichier d'identifiants est ailleurs
claude -p "Quel est mon périmètre d'accès et combien de profils UVP je vois ?" \
  --mcp-config mcp.json --strict-mcp-config --allowedTools "mcp__neolab-warehouse"
```

Recette réalisée le 28 octobre 2026 sur une base de test (10 profils UVP, contrats C1 et C2, 2 comptes) :
le compte restreint (C1, zone `lab`, 2018–2022) a obtenu 2 profils nommés correctement, a vu les 4 jeux du
catalogue dont 2 hors périmètre, et son essai d'écriture a été refusé. Le compte sans droit a obtenu 0 profil,
a compris qu'il n'avait aucun droit (`my_access` vide) et a indiqué quoi demander à l'administrateur. Une seconde recette sur des
valeurs : le compte restreint a retrouvé les 4 abondances moyennes attendues (270,00 / 647,50 / 328,33 / 793,33 ind/m³),
3 bins, 200 m, et 12 lignes visibles sur 60 en base. Les deux ont
signalé qu'ils ne pouvaient pas distinguer des données masquées de données absentes, ce qui est voulu : le
catalogue n'expose pas de compteurs hors périmètre.

## Pour l'administrateur

Connexion : `WAREHOUSE_POSTGRES_HOST|PORT|DB|USER|PASSWORD` (comme le [déploiement](WAREHOUSE_DOCKER.md)).

```bash
# Compte restreint: contrat C1, EcoTaxa et EcoPart (vues UVP), zone lab, 2018-2022, mot de passe valide 90 jours
python scripts/warehouse_user.py create ines --source ecotaxa,ecopart --contract C1 --zone lab \
    --year-min 2018 --year-max 2022 --note "Entente X" --expires-days 90 --public-host warehouse.exemple.org

python scripts/warehouse_user.py grant ines --source filet --contract C1   # ajouter un droit
python scripts/warehouse_user.py grant ines --source ctd --contract C1 --zone lab --include-unknown  # inclure zones/dates inconnues
python scripts/warehouse_user.py rotate ines                                # nouveau mot de passe
python scripts/warehouse_user.py offboard ines                              # révoque et ferme la connexion
python scripts/warehouse_user.py list                                       # comptes, portée, droits actifs
python scripts/warehouse_user.py create equipe_neolab --all-access          # personnel: toutes les données
```

- **Refus par défaut** : sans option de droit, le compte n'accède à aucune donnée.
- `--source ecotaxa,ecopart` crée un droit par source; l'outil avertit si une seule des deux sources UVP est accordée.
- Un droit borné par zone ou années cache les lignes de zone ou de date inconnue; `--include-unknown` les inclut.
- Le mot de passe est généré (jamais saisi ni affiché) et écrit dans `data/warehouse_backups/users/<nom>.env`
  (ignoré par Git, droits `600`). **Remettre ce fichier par un canal sûr, puis le supprimer.**
- `offboard` conserve l'historique des droits (`revoked_at`); `rotate` invalide l'ancien mot de passe et garde la
  validité actuelle, ou en fixe une nouvelle avec `--expires-days`. Un compte déjà expiré exige `--expires-days`.
- La date d'expiration est écrite dans le fichier d'identifiants : la recette prévient 14 jours avant.
- Le contexte MCP (`warehouse_context`, dictionnaire) est publié par le service Docker `warehouse-context` ou par
  le déploiement. Sans lui, la recette signale l'échec.

### Réseau

Ne pas publier le port PostgreSQL sur Internet. Pour un accès distant, deux options :

- **Tunnel SSH** (`ssh -L 55432:localhost:55432 serveur`), puis `--public-host 127.0.0.1`.
- **TLS côté serveur** : `ssl = on` avec un certificat, et `hostssl` (plutôt que `host`) dans `pg_hba.conf` pour
  refuser les connexions non chiffrées. Côté utilisateur :

| `WAREHOUSE_DB_SSLMODE` | Chiffre | Vérifie le serveur | À utiliser |
|---|---|---|---|
| `require` (défaut hors local) | oui | non | réseau de confiance, certificat autosigné |
| `verify-full` + `WAREHOUSE_DB_SSLROOTCERT` | oui | oui (autorité et nom d'hôte) | recommandé dès que le réseau n'est pas maîtrisé |

Le certificat d'autorité est un fichier public : l'administrateur le distribue, la personne l'indique avec
`init --sslrootcert <chemin>` ou dans son fichier d'identifiants.

## État de validation

- **Vérifié de bout en bout** sur PostgreSQL 16 avec le vrai DbHub 1.5.0 : création du compte, authentification
  par mot de passe (le mauvais est refusé), recette `check`, rotation, révocation, et `claude mcp list` qui
  affiche le serveur connecté.
- **TLS vérifié en local** (certificat autosigné, connexions non chiffrées refusées par le serveur) : `require`
  fonctionne, `disable` est refusé avec le bon diagnostic, `verify-full` échoue sans certificat d'autorité et réussit
  avec. Les diagnostics de mot de passe faux ou expiré, port fermé et hôte inconnu ont été provoqués et vérifiés.
- **Non testé** : Codex (installation absente ici; le format suit sa documentation MCP), Claude Desktop,
  Windows pour ces deux scripts, et un serveur distant réel (certificat d'une vraie autorité).
- **Trousseau du système** : `init --keyring` vérifié avec le module `keyring` (dorsal de test) : aucun mot de passe
  dans le fichier et recette `check` réussie. Non testé sur les trousseaux graphiques de macOS et de Windows.
- Le lanceur Windows historique (`scripts/start_dbhub.ps1`, rôle `warehouse_reader`) reste inchangé.
