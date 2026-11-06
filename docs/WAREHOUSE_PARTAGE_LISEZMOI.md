# Warehouse NeoLab — installation sur votre ordinateur

Ce dossier contient une copie complète du warehouse NeoLab (EcoTaxa, EcoPart/UVP, CTD Amundsen) et de quoi
la faire tourner sur votre ordinateur, puis lui poser des questions avec un assistant IA : **Claude Code**,
**Codex** ou **GitHub Copilot** (dans VS Code). Aucune connaissance préalable n'est supposée : suivez les
parties dans l'ordre.

Compter environ 1 h la première fois (dont une bonne part de téléchargements), puis 1 minute pour relancer.

| Fichier | Rôle |
|---|---|
| `neolab_warehouse_20261104_194551.dump` | la base de données, 311 Mo (environ 7 Go une fois installée) |
| `neolab_warehouse_20261104_194551.dump.sha256` | l'empreinte qui permet de vérifier que le fichier n'est pas abîmé |
| `IDEA-code.tar.gz` | les programmes et la documentation |
| `LISEZMOI.md` | ce fichier |

Aucun mot de passe n'est inclus : vous choisirez les vôtres.

**Ce qu'il faut :** un ordinateur récent (8 Go de mémoire, 20 Go d'espace disque libre), Internet, les droits
d'administrateur pour installer des logiciels, et un compte pour l'assistant choisi (partie 2).

---

## Partie 1 — Installer les outils (une seule fois)

Suivez **une seule** des trois sections, celle de votre système. Le « terminal » est la fenêtre où l'on tape
les commandes : copiez chaque ligne, collez-la, appuyez sur Entrée.

### Windows 10 ou 11

Tout se fera dans **Ubuntu**, un Linux que Windows fait tourner (WSL). Les parties suivantes s'appliquent
ensuite telles quelles, dans le terminal Ubuntu.

1. **Installer Ubuntu (WSL).** Menu Démarrer, taper `PowerShell`, clic droit, « Exécuter en tant
   qu'administrateur », puis :
   ```powershell
   wsl --install
   ```
   Redémarrer l'ordinateur. Au redémarrage, une fenêtre Ubuntu s'ouvre et demande un nom d'utilisateur et un
   mot de passe (ceux de Linux, à retenir). Cette fenêtre est désormais **votre terminal** : on la rouvre
   depuis le menu Démarrer, « Ubuntu ».
2. **Installer Docker Desktop** depuis https://www.docker.com/products/docker-desktop/ (Windows 10 22H2 ou
   Windows 11 23H2 au minimum). L'ouvrir, puis Settings → Resources → WSL integration : activer **Ubuntu**,
   Apply. Docker Desktop doit être lancé chaque fois qu'on utilise le warehouse.
3. **Installer les autres outils**, dans le terminal Ubuntu :
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip unzip curl ca-certificates
   ```
   Puis suivre la section **Linux** ci-dessous à partir de l'étape 3 (client PostgreSQL et Node.js).
4. **Copier le dossier dans Ubuntu.** Le zip téléchargé est côté Windows (par exemple dans Téléchargements).
   Dans le terminal Ubuntu, en remplaçant `VotreNom` par votre nom d'utilisateur Windows :
   ```bash
   cp /mnt/c/Users/VotreNom/Downloads/neolab_warehouse_20261104_v5.zip ~/
   cd ~ && unzip neolab_warehouse_20261104_v5.zip
   ```
   Le dossier `~/neolab_warehouse_20261104` est celui des parties suivantes.

### macOS

1. **Installer Homebrew** (installateur de logiciels) : ouvrir l'application **Terminal**, puis coller la
   commande donnée sur https://brew.sh et suivre ses indications (elle demande le mot de passe du Mac).
2. **Installer Docker Desktop** depuis https://www.docker.com/products/docker-desktop/ (choisir « Apple
   silicon » ou « Intel » selon le Mac), l'ouvrir et attendre qu'il indique « running ». Il doit être lancé
   chaque fois qu'on utilise le warehouse.
3. **Installer les autres outils** :
   ```bash
   brew install python node libpq
   brew link --force libpq
   ```
4. Décompresser le zip (double-clic dans le Finder), puis dans le Terminal : `cd ` (avec un espace), glisser
   le dossier `neolab_warehouse_20261104` dans la fenêtre, Entrée.

### Linux (Ubuntu 22.04 ou 24.04)

1. **Installer Docker** :
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER
   ```
   Se déconnecter puis se reconnecter (pour utiliser Docker sans `sudo`).
2. **Installer Python** :
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip unzip curl ca-certificates
   ```
3. **Installer le client PostgreSQL (version 16 ou plus)** :
   ```bash
   sudo apt install -y postgresql-common
   sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
   sudo apt install -y postgresql-client-16
   ```
4. **Installer Node.js (version 18 ou plus)** :
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
   sudo apt install -y nodejs
   ```
5. Décompresser : `cd` vers le dossier du zip, puis `unzip neolab_warehouse_20261104_v5.zip` et
   `cd neolab_warehouse_20261104`.

### Vérifier (tous les systèmes)

```bash
docker --version && docker compose version && python3 --version && psql --version && node --version
```

Chaque ligne doit afficher une version : Docker Compose 2 ou plus, Python 3.10 ou plus, psql 16 ou plus,
Node 18 ou plus. Une erreur « command not found » indique l'outil à réinstaller.

---

## Partie 2 — Installer l'assistant IA (au choix)

Il en faut un seul. Sous Windows, l'installer **dans le terminal Ubuntu**.

| Assistant | Installation | Compte nécessaire |
|---|---|---|
| **Claude Code** (Anthropic) | `curl -fsSL https://claude.ai/install.sh \| bash`, puis lancer `claude` une fois pour se connecter | abonnement Claude Pro, Max, Team ou Enterprise, ou compte Console Anthropic (le plan gratuit ne suffit pas) |
| **Codex** (OpenAI) | `curl -fsSL https://chatgpt.com/codex/install.sh \| sh`, puis lancer `codex` une fois et choisir « Sign in with ChatGPT » | un compte ChatGPT avec accès à Codex, ou une clé d'API OpenAI |
| **GitHub Copilot** (dans VS Code) | installer VS Code (https://code.visualstudio.com), puis l'extension **GitHub Copilot** et se connecter avec son compte GitHub. Sous Windows, ajouter aussi l'extension **WSL** | un compte GitHub avec Copilot activé |

Vérifier avec `claude --version` ou `codex --version` (pour Copilot : l'icône de Copilot apparaît dans VS Code).

---

## Partie 3 — Installer le warehouse

Toutes les commandes se tapent dans le terminal, **depuis le dossier `neolab_warehouse_20261104`**.

### 3.1 Vérifier le fichier et décompresser le code

```bash
sha256sum -c neolab_warehouse_20261104_194551.dump.sha256        # macOS : shasum -a 256 -c …
tar xzf IDEA-code.tar.gz
cd IDEA
```

La première commande doit afficher `OK`. On est maintenant dans le dossier `IDEA`.

### 3.2 Préparer Python

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install "psycopg[binary]" python-dotenv
```

`(.venv)` apparaît en début de ligne. **À chaque nouveau terminal**, revenir dans `IDEA` et retaper
`. .venv/bin/activate` avant les commandes `python`.

### 3.3 Choisir vos mots de passe

```bash
cp example.warehouse.env .env.warehouse
nano .env.warehouse
```

Remplacer chaque `CHANGER_MOI` par un mot de passe de votre choix (trois mots de passe différents, lettres et
chiffres, sans espace ni guillemet). Enregistrer avec `Ctrl+O`, Entrée, puis quitter avec `Ctrl+X`.

### 3.4 Lancer la base

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d --build
set -a; . ./.env.warehouse; set +a
```

Le premier lancement télécharge environ 1 Go et prépare la base (quelques minutes). Vérifier :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml ps
```

`neolab-warehouse-db` doit indiquer `healthy`.

### 3.5 Installer les données

```bash
python scripts/backup_warehouse.py --restore ../neolab_warehouse_20261104_194551.dump --yes
python scripts/deploy_warehouse_postgres.py --check
```

Compter 5 à 10 minutes. La dernière ligne doit être `PRÊT: le warehouse peut être ouvert aux comptes.`

---

## Partie 4 — Brancher l'assistant au warehouse (MCP)

L'assistant ne reçoit jamais le mot de passe principal : on lui crée un compte personnel, en lecture seule.

```bash
python scripts/warehouse_user.py create mon_nom --all-access --out-dir ~/neolab-comptes
python scripts/warehouse_connect.py init --from-file ~/neolab-comptes/mon_nom.env
rm ~/neolab-comptes/mon_nom.env
python scripts/warehouse_connect.py install-dbhub
python scripts/warehouse_connect.py check
```

(`mon_nom` : un nom de compte de votre choix, en minuscules et sans accent.) La dernière commande doit
finir par `PASS`. Ensuite, selon l'assistant :

**Claude Code**
```bash
python scripts/warehouse_connect.py config claude-code
```
Copier et lancer la ligne `claude mcp add …` qu'elle affiche, puis `claude mcp list` doit afficher
`neolab-warehouse … ✓ Connected`.

**Codex**
```bash
python scripts/warehouse_connect.py config codex
```
Copier et lancer la ligne `codex mcp add …` qu'elle affiche, puis `codex mcp list` doit lister
`neolab-warehouse`.

**GitHub Copilot (VS Code)**
```bash
python scripts/warehouse_connect.py config vscode
code .
```
Sous Windows, `code .` ouvre VS Code relié à Ubuntu (accepter l'installation du serveur VS Code si
demandé). Dans VS Code, créer le fichier `.vscode/mcp.json` et y coller le bloc affiché par la commande.
VS Code demande d'autoriser le serveur `neolab-warehouse` : accepter (il ne fait que lire la base). Ouvrir
la fenêtre Copilot Chat et choisir le mode **Agent**.

---

## Partie 5 — Poser une question

Ouvrir l'assistant (`claude` ou `codex` dans un dossier de travail vide, ou Copilot Chat en mode Agent) et
demander par exemple :

> Quels projets EcoTaxa sont dans le warehouse, et quelle part de leurs objets est validée ?

L'assistant répond à partir de la base, en lecture seule, et termine par les requêtes SQL qu'il a exécutées.
La première fois, il peut demander l'autorisation d'utiliser les outils `neolab-warehouse` : accepter.

---

## Les fois suivantes

1. Lancer Docker Desktop (Windows, macOS).
2. Dans le terminal : aller dans le dossier `IDEA`, puis
   `docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml up -d`.
3. Ouvrir l'assistant. Rien d'autre à refaire.

Une carte des données est aussi visible dans le navigateur web à l'adresse http://127.0.0.1:8090.

---

## Ce que contient la base

| Source | Volume |
|---|---|
| EcoTaxa | 23 projets (UVP, Zooscan, LOKI), 6 138 samples, 15 050 002 objets : taxon, statut d'annotation (6 645 676 validés, 7 700 806 prédits, 14 319 douteux, 689 201 jamais classés), profondeur, taille |
| EcoPart (UVP) | 12 projets, 686 profils, 71 520 tranches de profondeur, abondances par taxon (tous objets, ou validés seulement) |
| CTD Amundsen | 456 profils, 5 130 421 mesures (température, salinité, densité, oxygène, nitrate, fluorescence, pH) |
| Référentiels | 65 zones maritimes, 18 stades de copépodes |

Deux schémas se lisent : **`explore`** (les données ; point de départ `ecotaxa_projects`) et **`catalogue`**
(mes droits, le catalogue des jeux de données, le dictionnaire des colonnes). Pour interroger la base
soi-même (DBeaver, pgAdmin, R, Python) : `IDEA/docs/WAREHOUSE_SQL_GUIDE.md`.

## À savoir

- **Validé ou prédit** : une abondance « tous objets » inclut les prédictions automatiques. Exemple réel :
  copépodes 0–200 m en Baie de Baffin, am_leg3 2024 : 750,9 ind/m³ tous objets, 2,1 avec les seuls validés.
- **Projets en double** : 149 contient les 199 samples de 20880 + 20890 (mêmes comptes) plus 5 samples
  propres ; ne pas additionner ces projets : 149 seul donne GreenEdge 2016 sans doublon.
- **Non chargé** : FILET. **Tailles LOKI** : en pixels seulement (pas de calibration).
- **Tailles UVP6** : corrigées dans cette version (EcoTaxa donne le pixel UVP6 en µm, lu par erreur en mm
  dans les versions précédentes, d'où des tailles 1 000 fois trop grandes). Ne pas réutiliser un résultat de
  taille UVP6 obtenu avec une copie antérieure au 4 novembre 2026 (zips v1 à v4).
- **Positions** : 197 profils GreenEdge 2016 sans position propre (sources contradictoires) ; le projet
  17808 n'a pas de projet EcoPart lié.
- **Statut** : données exploratoires.
- **Confidentialité** : la copie contient les métadonnées des projets, dont le nom et le courriel de leurs
  responsables, et donne accès à tous les projets. Ne pas la transmettre plus loin sans l'accord de la
  personne qui vous l'a remise.

## En cas de problème

| Symptôme | Que faire |
|---|---|
| `docker: command not found` ou `Cannot connect to the Docker daemon` | lancer Docker Desktop (Windows : vérifier l'intégration WSL d'Ubuntu, partie 1) ; Linux : `sudo systemctl start docker`, et s'être reconnecté après `usermod` |
| `externally-managed-environment` en installant avec pip | l'environnement Python n'est pas activé : `. .venv/bin/activate` (partie 3.2) |
| `No module named psycopg` | même cause : activer `.venv` |
| `port is already allocated` | un autre logiciel utilise le port : changer `WAREHOUSE_POSTGRES_PORT` (55432) ou `WAREHOUSE_NAVIGATOR_PORT` (8090) dans `.env.warehouse`, puis relancer 3.4 |
| `psql: command not found` ou version < 16 | réinstaller le client PostgreSQL (partie 1) ; macOS : `brew link --force libpq`, puis fermer et rouvrir le Terminal |
| erreur de version ou de compression pendant la restauration | client PostgreSQL trop ancien : installer la version 16+, ou restaurer depuis le conteneur : `docker exec -i neolab-warehouse-db sh -c 'cat > /tmp/w.dump && pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/w.dump; rm /tmp/w.dump' < ../neolab_warehouse_20261104_194551.dump`, puis `python scripts/deploy_warehouse_postgres.py --check` |
| `check` ne finit pas par `PASS` | `IDEA/docs/WAREHOUSE_CONNECT.md`, section Dépannage |
| tout recommencer | `docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml down -v` (efface la base locale), puis reprendre à 3.4 |
