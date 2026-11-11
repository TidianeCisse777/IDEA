# Warehouse NeoLab — installation

Une copie complète du warehouse NeoLab (EcoTaxa, EcoPart/UVP, CTD Amundsen), à installer sur votre ordinateur
pour l'interroger avec un assistant IA (Claude Code, Codex ou GitHub Copilot).

## Avant de commencer

- Un ordinateur Windows 10/11, Mac ou Linux (Ubuntu) avec 8 Go de mémoire et 20 Go d'espace libre.
- Les droits d'administrateur sur cet ordinateur.
- Un compte pour l'assistant : abonnement Claude (Pro ou plus), ou accès à Codex.
- Les deux fichiers reçus : `neolab_warehouse_20261108_1sur2.zip` et `neolab_warehouse_20261108_2sur2.zip`.
- 15 à 30 minutes.

## Installer

### Windows

1. Mettre les deux zips dans **Téléchargements**.
2. Clic droit sur `neolab_warehouse_20261108_1sur2.zip` → **Extraire tout** → **Extraire**.
3. Dans le dossier qui s'ouvre, double-cliquer **`installer_windows.bat`**.
   Si Windows affiche un avertissement : **Informations complémentaires** → **Exécuter quand même**.
4. La première fois, le script installe Ubuntu et demande de **redémarrer**. Après le redémarrage : ouvrir
   « Ubuntu » depuis le menu Démarrer, choisir un nom d'utilisateur et un mot de passe (à retenir), puis
   double-cliquer de nouveau `installer_windows.bat`.
5. Le script installe Docker Desktop : accepter ses conditions dans sa fenêtre. Il fait ensuite le reste seul.

### Mac

1. Télécharger les deux zips, puis double-cliquer le premier (`…_1sur2.zip`).
2. Dans le dossier `neolab_warehouse_20261108`, double-cliquer **`installer_mac.command`**.
   Si macOS bloque : clic droit → **Ouvrir** → **Ouvrir** (ou **Réglages Système → Confidentialité et sécurité →
   Ouvrir quand même**).
3. Donner le mot de passe du Mac quand il est demandé et accepter les conditions de Docker Desktop.

### Linux (Ubuntu)

```bash
unzip -o neolab_warehouse_20261108_1sur2.zip && unzip -o neolab_warehouse_20261108_2sur2.zip
bash neolab_warehouse_20261108/installer.sh
```

C'est fini quand le script affiche **`INSTALLATION TERMINÉE.`** S'il n'y a pas encore d'assistant IA, il propose
d'installer Claude Code : répondre oui.

## Poser une question

Ouvrir **Ubuntu** (Windows) ou le **Terminal** (Mac, Linux), puis :

```bash
cd ~/neolab-travail && claude
```

(`codex` à la place de `claude` pour Codex.) La première fois, l'assistant demande de se connecter à votre
compte et d'autoriser les outils `neolab-warehouse` : accepter.

Le script branche aussi les applications déjà installées : **Codex** (application ou extension VS Code),
**VS Code** (GitHub Copilot, mode Agent) et **Claude Desktop**. Les redémarrer après l'installation ; pour une
application installée plus tard, relancer le script.

Exemple : « Quels projets EcoTaxa sont dans le warehouse, et quelle part de leurs objets est validée ? »
L'assistant répond à partir de la base, explique ses choix et liste les requêtes qu'il a exécutées.

## Les fois suivantes

Lancer **Docker Desktop** (Windows, Mac) : la base redémarre toute seule. Puis l'assistant, comme ci-dessus.

## Si ça bloque

Le script s'arrête en affichant `ÉCHEC :` et la raison. Faire ce qu'il demande, puis le relancer : il reprend
là où il s'était arrêté. Sinon, envoyer une capture d'écran du message à la personne qui vous a remis la copie.

## Ce que contient la base

| Source | Contenu |
|---|---|
| EcoTaxa | 23 projets (UVP, Zooscan, LOKI), 6 138 samples, 15 millions d'objets : taxon et lignée, statut d'annotation (validé, prédit, douteux), date et heure, profondeur, taille et forme, lien vers l'image |
| EcoPart (UVP) | 12 projets, 686 profils : volumes échantillonnés, particules, abondances par taxon |
| CTD Amundsen | 456 profils, 5,1 millions de mesures (température, salinité, densité, oxygène, nitrate, fluorescence, pression ; pas de pH) |
| Référentiels | 65 zones maritimes, stades de copépodes, taxonomie EcoTaxa |

## À savoir

- **Validé ou prédit** : beaucoup d'objets sont classés automatiquement. Exemple : copépodes 0–200 m en Baie de
  Baffin (am_leg3, 2024) : 750,9 ind/m³ avec tous les objets, 2,1 avec les seuls validés.
- **Projets en double** : 149, 20880, 20890 et 13224 contiennent les mêmes images GreenEdge 2016 ; 149 seul
  donne GreenEdge 2016 sans doublon.
- **Non chargé** : FILET. Les tailles LOKI sont en pixels seulement.
- **Données exploratoires**, à vérifier avant publication.
- **Confidentialité** : la copie contient les noms et courriels des responsables de projets et donne accès à
  tous les projets. Ne pas la transmettre sans l'accord de la personne qui vous l'a remise.
- Pour interroger la base soi-même (DBeaver, R, Python) : `IDEA/docs/WAREHOUSE_SQL_GUIDE.md`.

---

# Annexe — installation à la main

À suivre seulement si le script ne convient pas. Fichiers de la copie : `installer_windows.bat`,
`installer_mac.command` et `installer.sh` (installation automatique), `IDEA-code.tar.gz` (le code),
`neolab_warehouse_20261108_232541.dump.part0` et `.part1` (la base en deux morceaux, un par zip, 657 Mo en tout),
`neolab_warehouse_20261108_232541.dump.sha256` (l'empreinte pour vérifier la base). Les deux zips se
décompressent dans le même dossier `neolab_warehouse_20261108`. Aucun mot de passe n'est inclus.

## Partie 1 — Installer les outils

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
4. **Copier le dossier dans Ubuntu.** Les deux zips téléchargés sont côté Windows (par exemple dans
   Téléchargements). Dans le terminal Ubuntu, en remplaçant `VotreNom` par votre nom d'utilisateur Windows :
   ```bash
   cp /mnt/c/Users/VotreNom/Downloads/neolab_warehouse_20261108_*sur2.zip ~/
   cd ~ && unzip -o neolab_warehouse_20261108_1sur2.zip && unzip -o neolab_warehouse_20261108_2sur2.zip
   ```
   Le dossier `~/neolab_warehouse_20261108` est celui des parties suivantes.

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
4. Décompresser les deux zips **dans le Terminal** (le Finder mettrait le second dans un autre dossier) :
   ```bash
   cd ~/Downloads && unzip -o neolab_warehouse_20261108_1sur2.zip && unzip -o neolab_warehouse_20261108_2sur2.zip
   cd neolab_warehouse_20261108
   ```

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
4. **Installer Node.js (version 20 ou plus)** :
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
   sudo apt install -y nodejs
   ```
5. Décompresser : `cd` vers le dossier des zips, puis
   `unzip -o neolab_warehouse_20261108_1sur2.zip && unzip -o neolab_warehouse_20261108_2sur2.zip` et
   `cd neolab_warehouse_20261108`.

### Vérifier (tous les systèmes)

```bash
docker --version && docker compose version && python3 --version && psql --version && node --version
```

Chaque ligne doit afficher une version : Docker Compose 2 ou plus, Python 3.10 ou plus, psql 16 ou plus,
Node 20 ou plus. Une erreur « command not found » indique l'outil à réinstaller.

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

Toutes les commandes se tapent dans le terminal, **depuis le dossier `neolab_warehouse_20261108`**.

### 3.1 Recoller la base, la vérifier et décompresser le code

```bash
cat neolab_warehouse_20261108_232541.dump.part0 neolab_warehouse_20261108_232541.dump.part1 > neolab_warehouse_20261108_232541.dump
sha256sum -c neolab_warehouse_20261108_232541.dump.sha256        # macOS : shasum -a 256 -c …
tar xzf IDEA-code.tar.gz
cd IDEA
```

La vérification doit afficher `OK` (sinon, un des deux zips est incomplet : le retélécharger). On est maintenant dans le dossier `IDEA`.

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

La seconde ligne donne aux commandes suivantes les mots de passe choisis en 3.3. Garder **ce même terminal**
jusqu'à la fin de la partie 4. Dans un nouveau terminal, retaper d'abord, depuis `IDEA` :
`. .venv/bin/activate` puis `set -a; . ./.env.warehouse; set +a`.

Le premier lancement télécharge environ 1 Go et prépare la base (quelques minutes). Vérifier :

```bash
docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml ps
```

`neolab-warehouse-db` doit indiquer `healthy`.

### 3.5 Installer les données

```bash
python scripts/backup_warehouse.py --restore ../neolab_warehouse_20261108_232541.dump --yes
python scripts/deploy_warehouse_postgres.py --check
```

Compter 5 à 10 minutes. La dernière ligne doit être `PRÊT: le warehouse peut être ouvert aux comptes.`

---

## Partie 4 — Brancher l'assistant au warehouse (MCP)

L'assistant ne reçoit jamais le mot de passe principal : on lui crée un compte personnel, en lecture seule.
Dans le terminal de la partie 3 (sinon, voir la fin de 3.4).

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

Enfin, créer le dossier de travail (il dit à l'assistant que les questions portent sur le warehouse), puis
poser une question comme dans la partie principale :

```bash
python scripts/warehouse_connect.py workspace ~/neolab-travail
```

## En cas de problème (installation à la main)

| Symptôme | Que faire |
|---|---|
| `docker: command not found` ou `Cannot connect to the Docker daemon` | lancer Docker Desktop (Windows : vérifier l'intégration WSL d'Ubuntu, partie 1) ; Linux : `sudo systemctl start docker`, et s'être reconnecté après `usermod` |
| `externally-managed-environment` en installant avec pip | l'environnement Python n'est pas activé : `. .venv/bin/activate` (partie 3.2) |
| `No module named psycopg` | même cause : activer `.venv` |
| `port is already allocated` | un autre logiciel utilise le port : changer `WAREHOUSE_POSTGRES_PORT` (55432) ou `WAREHOUSE_NAVIGATOR_PORT` (8090) dans `.env.warehouse`, puis relancer 3.4 |
| `psql: command not found` ou version < 16 | réinstaller le client PostgreSQL (partie 1) ; macOS : `brew link --force libpq`, puis fermer et rouvrir le Terminal |
| erreur de version ou de compression pendant la restauration | client PostgreSQL trop ancien : installer la version 16+, ou restaurer depuis le conteneur : `docker exec -i neolab-warehouse-db sh -c 'cat > /tmp/w.dump && pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/w.dump; rm /tmp/w.dump' < ../neolab_warehouse_20261108_232541.dump`, puis `python scripts/deploy_warehouse_postgres.py --check` |
| `WAREHOUSE_POSTGRES_PASSWORD est requis` | nouveau terminal : depuis `IDEA`, `. .venv/bin/activate` puis `set -a; . ./.env.warehouse; set +a`, et relancer la commande |
| `check` ne finit pas par `PASS` | `IDEA/docs/WAREHOUSE_CONNECT.md`, section Dépannage |
| tout recommencer | `docker compose --env-file .env.warehouse -f docker-compose.warehouse.yml down -v` (efface la base locale), puis reprendre à 3.4 |
