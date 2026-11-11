# Warehouse NeoLab — installation

Une copie complète du warehouse NeoLab (EcoTaxa, EcoPart/UVP, CTD Amundsen), à installer sur votre ordinateur
pour l'interroger avec un assistant IA (Claude Code, Codex, GitHub Copilot ou Claude Desktop). Tout tourne dans
un conteneur Docker : il ne faut que **Docker Desktop**.

## Avant de commencer

- Un ordinateur Windows 10/11, Mac ou Linux avec 8 Go de mémoire et 20 Go d'espace libre.
- Les droits d'administrateur (pour installer Docker Desktop s'il manque).
- Un compte pour l'assistant : abonnement Claude (Pro ou plus), ou accès à Codex.
- Les deux fichiers reçus : `neolab_warehouse_20261108_1sur2.zip` et `neolab_warehouse_20261108_2sur2.zip`.
- 15 à 30 minutes la première fois (surtout des téléchargements).

## Installation rapide : depuis le registre privé (recommandé)

La base est déjà installée dans l'image : rien à restaurer. Il faut Docker Desktop, environ 25 Go libres, un
compte GitHub qui a reçu l'accès au paquet `neolab-warehouse`, et un jeton GitHub classique avec le droit
`read:packages` (github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)).

- **Windows** : double-cliquer `install_from_registry_windows.bat`. Le compte GitHub et le jeton sont demandés
  une seule fois; le jeton se colle comme mot de passe et ne s'affiche pas.
- **Mac, Linux** : `bash install_from_registry.sh`.

Le téléchargement prend 10 à 60 minutes la première fois, puis le script démarre la base, vérifie le serveur
MCP et branche les assistants installés (Claude Code, Codex, OpenCode, VS Code, Claude Desktop). Sous Windows,
les scripts de branchement et de mise à jour sont copiés dans `Documents\neolab`.

Publier l'image (responsable du warehouse, depuis le PC installé avec les zips et à jour) :
`powershell -ExecutionPolicy Bypass -File scripts\publish_prebuilt_image.ps1 -Owner VOTRE_COMPTE_GITHUB`,
puis donner l'accès au paquet sur GitHub (Packages → neolab-warehouse → Package settings → Manage access).

## Installer avec les deux zips

### Windows

1. Mettre les deux zips dans **Téléchargements**.
2. Clic droit sur `neolab_warehouse_20261108_1sur2.zip` → **Extraire tout** → **Extraire**.
3. Dans le dossier qui s'ouvre, double-cliquer **`installer_windows.bat`**.
   Si Windows affiche un avertissement : **Informations complémentaires** → **Exécuter quand même**.
4. S'il manque, le script installe Docker Desktop : accepter ses conditions dans sa fenêtre. Il fait ensuite le
   reste seul.

### Mac

1. Télécharger les deux zips, puis double-cliquer le premier (`…_1sur2.zip`).
2. Dans le dossier `neolab_warehouse_20261108`, double-cliquer **`installer_mac.command`**.
   Si macOS bloque : clic droit → **Ouvrir** → **Ouvrir** (ou **Réglages Système → Confidentialité et sécurité →
   Ouvrir quand même**).
3. Si Docker Desktop manque, l'installer depuis https://www.docker.com/products/docker-desktop/ (Apple silicon ou
   Intel), l'ouvrir, puis relancer `installer_mac.command`.

### Linux (Ubuntu)

```bash
unzip -o neolab_warehouse_20261108_1sur2.zip && unzip -o neolab_warehouse_20261108_2sur2.zip
bash neolab_warehouse_20261108/installer.sh
```

C'est fini quand le script affiche **`INSTALLATION TERMINÉE.`** Il a construit l'image, installé la base dans
le conteneur `neolab-warehouse` et branché les assistants trouvés (Claude Code, Codex, VS Code, Claude Desktop).
S'il n'y a aucun assistant, il propose d'installer Claude Code.

## Poser une question

Ouvrir **PowerShell** (Windows) ou le **Terminal** (Mac, Linux), puis :

```bash
cd ~/neolab-travail
claude
```

(`codex` ou `opencode` à la place de `claude` pour Codex ou OpenCode.) La première fois, l'assistant demande de se connecter à votre
compte et d'autoriser les outils `neolab-warehouse` : accepter. VS Code (Copilot, mode Agent) et Claude Desktop
sont aussi branchés s'ils étaient installés : les redémarrer.

Exemple : « Quels projets EcoTaxa sont dans le warehouse, et quelle part de leurs objets est validée ? »
L'assistant répond à partir de la base, explique ses choix et liste les requêtes qu'il a exécutées.

Si une application ne voit pas le serveur (« program not found ») ou a été installée après coup : sous
Windows, double-cliquer **`brancher_assistants_windows.bat`** (il rebranche tout sans réinstaller), sous Mac et
Linux relancer l'installeur ; puis quitter complètement l'application et la rouvrir.

## Les fois suivantes

Lancer **Docker Desktop** : la base redémarre toute seule. Puis l'assistant, comme ci-dessus.

## Si ça bloque

Le script s'arrête en affichant `ÉCHEC :` et la raison. Faire ce qu'il demande, puis le relancer : il reprend
là où il s'était arrêté. Sinon, envoyer une capture d'écran du message à la personne qui vous a remis la copie.

## Ce que contient la base

| Source | Contenu |
|---|---|
| EcoTaxa | 23 projets (UVP, Zooscan, LOKI), 6 138 samples, 15 millions d'objets : taxon et lignée, statut d'annotation (validé, prédit, douteux), date et heure, profondeur, taille et forme, lien vers l'image |
| EcoPart (UVP) | 12 projets, 686 profils : volumes échantillonnés, particules, abondances par taxon |
| CTD Amundsen | 1 282 profils (rosette, CTD du Bioness), 7,7 millions de mesures (température, salinité, densité, oxygène, nitrate, fluorescence, pression; pH pour 40 profils de 2011), reliés aux profils UVP et aux déploiements filet |
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

---

# Annexe — à la main, sans le script

Fichiers de la copie : `installer_windows.bat`, `installer_mac.command`, `installer.sh` (installation
automatique), `IDEA-code.tar.gz` (le code, dont l'image `IDEA/docker/allinone`),
`neolab_warehouse_20261108_232541.dump.part0` et `.part1` (la base en deux morceaux, un par zip, 657 Mo en tout),
`neolab_warehouse_20261108_232541.dump.sha256` (l'empreinte). Aucun mot de passe n'est inclus : ils sont
générés dans le conteneur au premier démarrage.

Depuis le dossier `neolab_warehouse_20261108` (les deux zips décompressés dedans), avec Docker Desktop lancé :

```bash
# 1. Recoller et vérifier la base (Windows, dans cmd : copy /b fichier.part0+fichier.part1 fichier)
cat neolab_warehouse_20261108_232541.dump.part0 neolab_warehouse_20261108_232541.dump.part1 > neolab_warehouse_20261108_232541.dump
sha256sum -c neolab_warehouse_20261108_232541.dump.sha256          # macOS : shasum -a 256 -c …
# 2. Construire l'image et la démarrer (la base s'installe dedans : attendre « [neolab] PRÊT »)
tar xzf IDEA-code.tar.gz
docker build -t neolab-warehouse:20261108 -f IDEA/docker/allinone/Dockerfile .
docker run -d --name neolab-warehouse --restart unless-stopped -v neolab_warehouse_data:/var/lib/postgresql/data neolab-warehouse:20261108
docker logs -f neolab-warehouse
docker exec neolab-warehouse neolab-check                           # doit finir par PASS
# 3. Brancher l'assistant
claude mcp add --scope user neolab-warehouse -- docker exec -i neolab-warehouse neolab-mcp
codex mcp add neolab-warehouse -- docker exec -i neolab-warehouse neolab-mcp
opencode mcp add neolab-warehouse -- docker exec -i neolab-warehouse neolab-mcp
```

VS Code (Copilot, mode Agent), fichier `mcp.json` de l'utilisateur (« MCP: Open User Configuration ») :

```json
{"servers": {"neolab-warehouse": {"type": "stdio", "command": "docker", "args": ["exec", "-i", "neolab-warehouse", "neolab-mcp"]}}}
```

Claude Desktop (Réglages → Développeur → Modifier la config) : même bloc avec la clé `mcpServers` au lieu de
`servers`, sans `"type"`.

Dossier de travail (il dit à l'assistant que les questions portent sur le warehouse) :
`docker cp neolab-warehouse:/opt/neolab/workspace/. ~/neolab-travail/`

| Symptôme | Que faire |
|---|---|
| `docker` introuvable ou `Cannot connect to the Docker daemon` | lancer Docker Desktop et attendre « Engine running » ; sous Windows, s'il signale WSL : `wsl --update` dans PowerShell (administrateur), puis redémarrer |
| `[neolab] ÉCHEC` dans `docker logs neolab-warehouse` | tout reprendre : `docker rm -f neolab-warehouse` puis `docker volume rm neolab_warehouse_data`, et relancer le script |
| interroger la base en SQL soi-même | `docker exec -it neolab-warehouse psql -U neolab neolab_warehouse` ; guide des vues : `IDEA/docs/WAREHOUSE_SQL_GUIDE.md` |
