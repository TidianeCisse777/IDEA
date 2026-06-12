# Déploiement — Assistant copépodes NeoLab

## Vue d'ensemble

L'application tourne avec 3 containers Docker :

| Container | Rôle | Image |
|---|---|---|
| `copepod_agent` | Agent LangGraph + API FastAPI | `ghcr.io/tidianecisse777/copepod-agent:latest` |
| `open_webui` | Interface chat utilisateur | `openwebui/open-webui:0.9.6` |
| `copepod_postgres` | Base de données sessions | `postgres:16-alpine` |

---

## Prérequis sur le serveur

- Docker >= 24
- Docker Compose >= 2.20
- Accès internet (pour télécharger les images)
- Ports 3000 et 8000 ouverts (ou configurés via reverse proxy)

```bash
# Vérifier Docker
docker --version
docker compose version
```

---

## Déploiement initial

```bash
# 1. Cloner le repo
git clone https://github.com/TidianeCisse777/IDEA.git
cd IDEA

# 2. Créer le fichier de configuration
cp .env.example .env
nano .env
```

Variables obligatoires dans `.env` :

```env
# LLM
OPENAI_API_KEY=sk-...
LLM_MODEL=openai/gpt-4o-mini

# EcoTaxa / EcoPart
ECOTAXA_USER=...
ECOTAXA_PASSWORD=...

# Base de données sessions
POSTGRES_PASSWORD=choisir_un_mot_de_passe_fort

# Tracing (optionnel)
LANGSMITH_API_KEY=...
LANGCHAIN_TRACING_V2=true
```

```bash
# 3. Lancer
docker compose up -d

# 4. Vérifier que tout tourne
docker compose ps
```

L'interface est accessible sur `http://<IP-serveur>:3000`.

---

## Mise à jour

Quand du nouveau code est pushé sur `main`, GitHub Actions rebuild l'image automatiquement. Pour mettre à jour le serveur :

```bash
git pull
docker compose pull copepod-agent
docker compose up -d
```

Les données (sessions PostgreSQL, volumes) sont préservées.

---

## Partage en développement local

Pour tester depuis ton Mac et partager un lien temporaire :

```bash
./start.sh
```

Ce script :
1. Démarre Postgres + Open WebUI en Docker
2. Lance `serve.py` localement
3. Affiche l'IP locale (`http://10.x.x.x:3000`)
4. Si `cloudflared` est installé : génère un lien public temporaire `trycloudflare.com`

Le lien change à chaque redémarrage. Pour un lien permanent → déployer sur serveur.

---

## Architecture réseau

```
Internet / LAN
    │
    ▼ port 3000
open_webui (Docker)
    │ http://host.docker.internal:8000  (local)
    │ http://copepod_agent:8000         (Docker full)
    ▼
copepod_agent — serve.py (port 8000)
    │
    ├── copepod_postgres (port 5432 interne / 5433 exposé)
    └── data/session_store/  (volume copepod_data)
```

---

## Volumes persistants

| Volume | Contenu | Sauvegarde |
|---|---|---|
| `postgres_data` | Métadonnées sessions (table `sessions`) | `pg_dump` |
| `copepod_data` | Fichiers `.pkl` des DataFrames | Copie du répertoire |
| `open_webui_data` | Comptes utilisateurs, historique chats | Copie du répertoire |

```bash
# Sauvegarder la base sessions
docker compose exec postgres pg_dump -U copepod copepod_sessions > backup_sessions.sql

# Restaurer
cat backup_sessions.sql | docker compose exec -T postgres psql -U copepod copepod_sessions
```

---

## Dépannage

```bash
# Voir les logs en temps réel
docker compose logs -f copepod-agent
docker compose logs -f open-webui

# Redémarrer un service
docker compose restart copepod-agent

# Arrêter proprement
docker compose down          # arrête les containers, garde les volumes
docker compose down -v       # arrête ET supprime les volumes (perte de données)
```

---

## Prochaine étape : GitHub Actions

Le fichier `.github/workflows/build.yml` (à créer) buildait et pousse automatiquement l'image `copepod-agent` sur `ghcr.io` à chaque push sur `main`. Sans ça, il faut builder l'image manuellement sur le serveur avec `docker compose up --build`.
