# Connecter un agent IA au warehouse (Claude, Codex, Gemini, OpenCode, Cursor, VS Code)

## Comment ça marche

```
 Votre agent IA ──(MCP)──> warehouse_connect.py run ──> DbHub ──(SQL, lecture seule)──> PostgreSQL
 (Claude, Codex, …)         lit vos identifiants dans                                     applique VOS droits
                            un fichier privé, hors dépôt                                  (contrat, zone, années)
```

- **Un seul compte par personne**, remis par l'administrateur. La base applique vos droits, quel que soit
  l'agent : deux agents branchés sur le même compte voient exactement les mêmes données.
- **Le même branchement pour tous les agents** : chacun lance la commande `warehouse_connect.py run`. Seul
  l'endroit où on l'enregistre change d'un agent à l'autre.
- **Aucun mot de passe dans la configuration de l'agent** : il reste dans un fichier privé de votre poste
  (`~/.config/neolab-warehouse/credentials.env`, ou `%APPDATA%\neolab-warehouse\` sous Windows).
- **Lecture seule** : un agent ne peut rien modifier ni effacer dans le warehouse.

## Étapes 1 et 2 — une seule fois par poste, quel que soit l'agent

Prérequis : Python 3.10+, Node.js 20+, et un accès réseau au serveur (tunnel SSH ou réseau du labo, voir
[Réseau](#réseau)).

```bash
# 1. Enregistrer le fichier remis par l'administrateur, puis supprimer ce fichier
python scripts/warehouse_connect.py init --from-file mon_compte.env
#    option --keyring : garder le mot de passe dans le trousseau du système (pip install keyring)

# 2. Vérifier : connexion, compte, droits, catalogue, contexte métier
python scripts/warehouse_connect.py check            # doit finir par PASS

# Recommandé : installer DbHub une fois (démarrage en ~1 s, sans dépendre d'Internet ensuite)
python scripts/warehouse_connect.py install-dbhub
```

Ne passez à l'étape 3 qu'après un `PASS`. Sinon, voir [Dépannage](#dépannage).

## Étape 3 — brancher votre agent

`python scripts/warehouse_connect.py config <agent>` affiche la commande ou le bloc **exacts pour votre poste**,
avec les bons chemins vers Python et vers le script. Copiez ce qu'il affiche plutôt que les exemples ci-dessous,
où `<python>` et `<IDEA>` sont à remplacer. Après l'enregistrement, **redémarrez l'agent** : il ne charge ses
serveurs MCP qu'au démarrage.

| Agent | `config …` | Testé |
|---|---|---|
| Claude Code | `claude-code` | oui, conversations complètes |
| Codex (OpenAI) | `codex` | oui, serveur démarré et connecté par Codex |
| Gemini CLI (Google) | `gemini` | oui, serveur « Connected » |
| OpenCode (open source, multi-modèles) | `opencode` | oui, serveur « connected » |
| Claude Desktop | `claude-desktop` | non |
| Cursor | `cursor` | non |
| VS Code / GitHub Copilot | `vscode` | non |
| Tout autre client MCP | `json` | — |

### Claude Code

```bash
claude mcp add --scope user neolab-warehouse -- <python> <IDEA>/scripts/warehouse_connect.py run
claude mcp list                       # vérification : neolab-warehouse … ✓ Connected
```

`--scope user` : disponible dans tous vos projets. Pour un projet partagé, `config claude-code` donne aussi un
fichier `.mcp.json` à placer à la racine du projet (il ne contient aucun secret).

### Codex

```bash
codex mcp add neolab-warehouse -- <python> <IDEA>/scripts/warehouse_connect.py run
codex mcp list                        # vérification : neolab-warehouse … enabled
```

Ou directement dans `~/.codex/config.toml` :

```toml
[mcp_servers.neolab-warehouse]
command = "<python>"
args = ["<IDEA>/scripts/warehouse_connect.py", "run"]
startup_timeout_sec = 30
```

**Piège** : Codex abandonne un serveur qui n'a pas répondu en 10 s. Le premier lancement sans `install-dbhub`
télécharge DbHub et peut dépasser ce délai : gardez `startup_timeout_sec = 30`, ou faites `install-dbhub`.
`codex mcp list` montre que le serveur est enregistré, pas qu'il démarre : la vérification réelle est la
première question posée dans une session (voir [Première question](#première-question-à-poser)).

### Gemini CLI

```bash
gemini mcp add -s user neolab-warehouse <python> <IDEA>/scripts/warehouse_connect.py run
gemini mcp list                       # vérification : ✓ neolab-warehouse … Connected
```

**Piège** : Gemini **désactive tous les serveurs MCP** quand il est lancé depuis un dossier qu'il ne
considère pas de confiance (`gemini mcp list` affiche alors « Disabled »). Lancez `gemini` depuis votre dossier
de travail et répondez oui à « Do you trust the files in this folder? », ou utilisez la commande `/permissions`
dans une session.

### OpenCode

Agent open source qui fonctionne avec de nombreux fournisseurs de modèles (Anthropic, OpenAI, modèles ouverts,
modèles locaux). Coller dans `~/.config/opencode/opencode.json` (tous projets) ou `opencode.json` à la racine d'un
projet, en fusionnant la clé `"mcp"` si le fichier existe déjà :

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "neolab-warehouse": {
      "type": "local",
      "command": ["<python>", "<IDEA>/scripts/warehouse_connect.py", "run"],
      "enabled": true
    }
  }
}
```

```bash
opencode mcp list                     # vérification : ✓ neolab-warehouse connected
```

`command` est une **liste** (programme puis arguments), pas une chaîne. OpenCode laisse l'agent appeler les outils
sans demander d'approbation; sans conséquence ici, les trois outils étant en lecture seule.

### Claude Desktop, Cursor, VS Code

Ces trois-là s'enregistrent en collant un bloc JSON dans un fichier de configuration :

| Agent | Fichier | Bloc |
|---|---|---|
| Claude Desktop | Réglages > Développeur > Modifier la config (`claude_desktop_config.json`) | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` (tous projets) ou `.cursor/mcp.json` (un projet) | `mcpServers` |
| VS Code / Copilot (mode agent) | `.vscode/mcp.json` du projet | `servers`, avec `"type": "stdio"` |

```json
{
  "mcpServers": {
    "neolab-warehouse": {
      "command": "<python>",
      "args": ["<IDEA>/scripts/warehouse_connect.py", "run"]
    }
  }
}
```

Pour VS Code, `config vscode` donne la variante avec `servers` et `"type": "stdio"`. Ces trois agents n'ont pas
encore été testés : merci de signaler ce qui coince.

### Tout autre client MCP

Serveur MCP en **stdio**, commande `<python>`, arguments `<IDEA>/scripts/warehouse_connect.py run`, aucune
variable d'environnement nécessaire. `config json` affiche la forme `mcpServers`, la plus répandue.

## Première question à poser

Travaillez de préférence dans un **dossier de travail NeoLab** :

```bash
python scripts/warehouse_connect.py workspace ~/neolab-travail     # CLAUDE.md, AGENTS.md, GEMINI.md, Copilot
cd ~/neolab-travail
```

Chaque agent y lit au démarrage un court fichier d'instructions (aucun mot de passe) qui lui dit que les
questions portent sur ce warehouse. Le serveur envoie aussi ces instructions à la connexion, mais mesuré le
6 novembre 2026, sur des questions très courtes (« combien de copépodes ? », « quelle température en Baie de
Baffin ? »), un agent ouvert dans un dossier vide a répondu de mémoire 4 fois sur 4, et dans un dossier de
travail il a interrogé la base 4 fois sur 4.

Quand une requête échoue, le relais `warehouse_connect.py run` ajoute à l'erreur renvoyée par DbHub un champ
`hint` qui dit quoi faire ensuite :
- délai de 30 s dépassé : filtrer par projet ou sample, chercher les taxons dans `explore.ecotaxa_sample_taxa` ;
- colonne ou vue inconnue : lire `catalogue.warehouse_dictionary` ;
- droit refusé : lire `explore` et `catalogue`.

Dans les traces de 103 cas de test, 34 requêtes portaient sur un nom deviné et 10 dépassaient le délai.

Une fois l'agent redémarré, demandez-lui :

> « Lis le contexte du warehouse NeoLab, puis dis-moi ce que mon compte a le droit de voir. »

Un agent bien branché appelle l'outil `warehouse_context`, puis lit `catalogue.my_access`, et vous répond avec
vos droits (sources, contrats, zones, années). S'il dit ne pas avoir d'outil `neolab-warehouse` : l'agent n'a
pas été redémarré, ou l'enregistrement a échoué (voir [Dépannage](#dépannage)).

Le serveur fournit trois outils, identiques pour tous les agents :

| Outil (titre affiché) | Rôle |
|---|---|
| `read_data_guide` (NeoLab Warehouse · Read data guide) | mode d'emploi métier : à lire en premier (`overview`), puis par vue, et `graphs` avant un graphique |
| `run_sql_query` (NeoLab Warehouse · Run SQL query) | requêtes SQL en lecture seule (1000 lignes au plus par réponse) |
| `find_tables_and_columns` (NeoLab Warehouse · Find tables and columns) | lister vues, colonnes et types |

Ces noms sont donnés par le relais `warehouse_connect.py run`; DbHub, derrière lui, garde les siens
(`warehouse_context`, `execute_sql`, `search_objects`, ceux de `dbhub/*.toml`).

## Que demander ensuite

Ce que l'agent consulte, et que vous pouvez aussi lui demander directement :

| Pour savoir… | Lire |
|---|---|
| ce que **mon compte** peut lire | `SELECT * FROM catalogue.my_access` |
| quels jeux existent, y compris hors de mon périmètre | `SELECT * FROM catalogue.dataset_catalog` |
| à quel point les métadonnées sont complètes | `SELECT * FROM catalogue.fair_readiness` |
| comment utiliser une vue (grain, limites, exemple) | outil `warehouse_context` (`topic=overview`, puis le nom de la vue) |
| les colonnes, types et définitions | `SELECT * FROM catalogue.warehouse_dictionary` |

Un résultat vide peut signifier **un accès limité**, pas une absence de données : vérifier `my_access` d'abord.

## Dépannage

### Dans l'agent

| Symptôme | Que faire |
|---|---|
| l'agent ne connaît pas d'outil `neolab-warehouse` | redémarrer l'agent; vérifier l'enregistrement (`claude mcp list`, `codex mcp list`, `gemini mcp list`) |
| Gemini : serveur « Disabled » | dossier non approuvé : voir [Gemini CLI](#gemini-cli) |
| Codex : délai de démarrage dépassé | `startup_timeout_sec = 30` dans `~/.codex/config.toml`, ou `install-dbhub` |
| l'agent répond mais ne voit aucune donnée | lancer `check` : droits absents, ou une des deux sources UVP manquante (ligne ci-dessous) |
| erreur de connexion dans l'agent | relancer `check` : il donne la cause exacte (tableau suivant) |
| comprendre ce que l'agent a fait (requêtes, erreurs, lignes) | `python scripts/warehouse_connect.py trace on`, redémarrer l'agent, puis `trace show` ([détails](WAREHOUSE_AUDIT.md#trace-de-débogage-chaque-personne-sur-son-poste)) |

Vos requêtes sont aussi journalisées côté serveur pour l'audit du labo (compte, heure, agent) : voir
[Audit et débogage](WAREHOUSE_AUDIT.md).

### Messages du `check`

`check` lit l'erreur de DbHub et donne la cause, sans jamais afficher de secret :

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
| `Node.js 20+ est requis` | installer Node.js 20+ |
| poste sans accès à npm | sur un poste connecté, `python scripts/warehouse_connect.py install-dbhub`, puis copier `data/tooling/dbhub` |

## Tester sans rien enregistrer (Claude Code)

Pour un essai ponctuel, sans toucher à la configuration de Claude Code :

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

## Peut-on faire confiance à ce que l'agent répond ?

L'agent n'est pas plus honnête qu'un autre par principe : c'est le warehouse qui rend l'invention plus difficile
que le signalement de l'incertitude. Trois mécanismes concrets, pas une promesse :

- **Le contrôle d'accès (RLS) l'empêche physiquement de voir ce qu'il n'a pas le droit de voir.** Un résultat vide
  peut vouloir dire « aucun droit sur ce jeu », pas « aucune donnée » — `catalogue.my_access` et `catalogue.my_datasets`
  distinguent les deux (voir plus haut). Un agent qui confond les deux fait une erreur vérifiable : `my_datasets`
  dit explicitement « masqué » pour ce cas.
- **NULL n'est jamais recodé en zéro.** Une taille d'objet non calculable (calibration pixel inconnue), un taxon
  sans correspondance retenue (`warehouse.taxon_mapping`, statut `accepted` uniquement), une zone non attribuée :
  chaque vue documente ce que signifie une valeur absente, et le texte d'aide (`warehouse_context`) le rappelle
  avant que l'agent n'écrive une requête.
- **Les correspondances scientifiques ne sont jamais déduites par l'agent.** Le lien entre un taxon FILET et un
  taxon UVP, par exemple, vient uniquement de `warehouse.taxon_mapping` — une table remplie par un biologiste, pas
  calculée par ressemblance de nom. Sans ligne acceptée pour un taxon, l'agent n'a aucun moyen de deviner une
  correspondance : il doit le signaler comme non mappé.

Recette réalisée le 30 octobre 2026 (Docker, jeu de test, compte scopé contrat C1) : un agent Claude réel a comparé
l'abondance FILET d'un taxon (toutes tailles) à l'abondance UVP du même taxon filtrée sur une taille réelle
(µm), en passant par `filet_uvp_matches` → `taxon_mapping` → `uvp_object_sizes` sans qu'on le lui demande
explicitement. Les deux chiffres ont été recalculés indépendamment par `psql` et correspondaient exactement. Sans
accès aux outils, l'agent a répondu qu'il n'avait aucun chiffre à donner plutôt que d'en estimer un. Il a aussi
signalé de lui-même une limite non demandée (le taxon UVP identifié au genre, le mapping le déclarant équivalent
à l'espèce FILET).

**L'agent montre son travail.** Toute réponse chiffrée se termine par une section « Requêtes exécutées » : le
texte exact de chaque requête SQL qui a produit les chiffres, le nombre de lignes renvoyées et les valeurs
utilisées. Le chercheur peut relancer ces requêtes lui-même. Vérifié le 1ᵉʳ novembre 2026 : les 4 requêtes
affichées par un agent Claude réel figuraient toutes, au caractère près, dans l'[audit du serveur](WAREHOUSE_AUDIT.md),
qui reste la preuve indépendante de ce qui a réellement été lu.

Ce que ça ne garantit pas : que les données elles-mêmes sont correctes (erreur de saisie, mapping mal posé par le
biologiste, calibration manquante), ni qu'un agent mal guidé ne tente pas une estimation si on le lui demande
explicitement. Vérifier un chiffre important par une requête directe reste la bonne pratique, pas une formalité.

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
python scripts/warehouse_user.py remove battery_1a2b3c4d --yes              # supprime un compte jetable (tests)
python scripts/warehouse_user.py list                                       # comptes, portée, droits actifs
python scripts/warehouse_user.py create equipe_neolab --all-access          # personnel: toutes les données
```

- **Refus par défaut** : sans option de droit, le compte n'accède à aucune donnée.
- `--source ecotaxa,ecopart` crée un droit par source; l'outil avertit si une seule des deux sources UVP est accordée.
- Un droit borné par zone ou années cache les lignes de zone ou de date inconnue; `--include-unknown` les inclut.
- Le mot de passe est généré (jamais saisi ni affiché) et écrit dans `data/warehouse_backups/users/<nom>.env`
  (ignoré par Git, droits `600`). **Remettre ce fichier par un canal sûr, puis le supprimer.**
- `offboard` conserve l'historique des droits (`revoked_at`); `remove` (comptes de test seulement) supprime le
  rôle et son historique; `rotate` invalide l'ancien mot de passe et garde la
  validité actuelle, ou en fixe une nouvelle avec `--expires-days`. Un compte déjà expiré exige `--expires-days`.
- La date d'expiration est écrite dans le fichier d'identifiants : la recette prévient 14 jours avant.
- Le contexte MCP (`warehouse_context`, dictionnaire) est publié par le service Docker `warehouse-context` ou par
  le déploiement. Sans lui, la recette signale l'échec.

### Réseau

Ne pas publier le port PostgreSQL sur Internet. Pour un accès distant, deux options :

- **Tunnel SSH** (`ssh -L 55432:localhost:55432 serveur`), puis `--public-host 127.0.0.1`. C'est le mode par
  défaut du compose : la base n'écoute que sur `127.0.0.1` (`WAREHOUSE_BIND_ADDRESS`).
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
- **Codex et Gemini CLI vérifiés le 31 octobre 2026** (base Docker, compte restreint, parcours `init` →
  `check` → enregistrement) : Codex 0.166 a lancé le serveur et terminé la poignée de main MCP (« DBHub MCP
  Server 1.5.0 »), et lit `startup_timeout_sec`; Gemini CLI 0.66 l'affiche `Connected`. Les configurations
  qu'écrivent `codex mcp add` et `gemini mcp add` sont identiques à celles générées par `config`. Une
  conversation complète n'a pas été menée avec ces deux clients (aucun compte OpenAI ni Google dans
  l'environnement de test); elle l'a été avec Claude Code. Démarrage mesuré du serveur : 0,9 s avec DbHub
  installé localement.
- **OpenCode 1.19 vérifié le 31 octobre 2026** : le bloc généré par `config opencode`, collé tel quel, donne
  `✓ neolab-warehouse connected`, et l'agent est identifié (`opencode`) dans la trace. Pas de conversation
  complète : le quota des modèles gratuits d'OpenCode était épuisé depuis l'environnement de test.
- **Non testé** : Claude Desktop, Cursor et VS Code (formats générés selon leur documentation MCP), Windows
  pour ces deux scripts, et un serveur distant réel (certificat d'une vraie autorité).
- **Trousseau du système** : `init --keyring` vérifié avec le module `keyring` (dorsal de test) : aucun mot de passe
  dans le fichier et recette `check` réussie. Non testé sur les trousseaux graphiques de macOS et de Windows.
