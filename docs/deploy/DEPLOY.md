# Déploiement prod — provider-agnostic

Guide pour héberger l'assistant copépodes (`copepod-agent` + `mcp-ecotaxa` +
`open-webui` + `postgres`) sur n'importe quel hôte Linux avec Docker.

Le compose `docker-compose.prod.yml` et le `Caddyfile` à la racine du repo
ne contiennent **aucune référence à un fournisseur précis**. Le domaine,
l'email TLS, les mots de passe et les clés d'API sont tous injectés via
`.env`. Migrer d'un hôte à un autre = recopier `.env` + lancer le compose.

> Si tu n'as pas encore de serveur 24/7 mais tu veux **partager une URL aux
> testeurs maintenant** depuis ton Mac local, va directement à
> [l'annexe Cloudflare Tunnel](#annexe--partage-rapide-via-cloudflare-tunnel-depuis-le-mac-local)
> en bas du document.

---

## 1. Pré-requis sur l'hôte

- Linux récent (Ubuntu 22.04 / 24.04 LTS, Debian 12 — testé). Architecture
  amd64 **ou** arm64 : le workflow GitHub Actions build des images
  multi-arch (`linux/amd64,linux/arm64`).
- Au moins **2 vCPU / 4 GB RAM** pour faire tourner les 5 services
  confortablement (8 GB recommandés si beaucoup de testeurs concurrents).
- ~20 GB de disque pour les images Docker, le chroma_db et les volumes.
- Ports **80** et **443** ouverts au public dans le firewall du provider
  (security group / cloud firewall). Tous les autres ports doivent rester
  fermés au public — le compose les bind sur `127.0.0.1`.
- Un nom de domaine (ou sous-domaine) qui pointe vers l'IP publique de
  l'hôte. Voir section *Domaine* plus bas.

### Exemples de hosts qui marchent
- **Oracle Cloud Always Free** — VM ARM Ampere A1 (4 vCPU / 24 GB / 200 GB)
  gratuite à vie. C'est le scénario "zéro coût infra" actuel.
- **Hetzner Cloud** — `cax11` (ARM) à ~3 €/mois si tu veux un fournisseur
  EU plus stable que Always Free.
- **VM Université Laval** — si un sous-domaine `*.ulaval.ca` ou un serveur
  interne devient disponible, c'est la cible préférée pour la gouvernance.
- **Tout autre VPS x86 ou ARM** — les images sont multi-arch.

---

## 2. Hardening de l'hôte (à faire avant Docker)

```bash
# User non-root pour le déploiement
sudo adduser deploy
sudo usermod -aG sudo deploy

# Clés SSH uniquement
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
# PubkeyAuthentication yes
# PermitRootLogin no
sudo systemctl restart sshd

# Firewall : SSH + HTTP + HTTPS uniquement
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Patchs sécurité auto
sudo apt update && sudo apt install -y unattended-upgrades fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades

# Docker + compose plugin
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker deploy
# Re-login pour que le groupe docker soit pris en compte.
```

---

## 3. Domaine

L'app a besoin d'un nom DNS pour le TLS auto via Let's Encrypt. Trois
voies, du plus simple au plus propre :

1. **Sous-domaine DNS dynamique gratuit** — DuckDNS, NoIP, afraid.org.
   Donne `tonprojet.duckdns.org`. URL pas jolie mais c'est gratuit à vie
   et ça marche. Migration triviale : tu changes `PROD_DOMAIN` dans `.env`.
2. **Domaine personnel** — ~10 $/an chez Porkbun, Cloudflare, Namecheap.
   Tu pointes un record `A` vers l'IP publique de l'hôte.
3. **Sous-domaine institutionnel Université Laval** — demander à l'admin
   sys du DMS. C'est le plus propre pour la confiance des profs qui ouvrent
   l'URL, mais demande du temps administratif.

**Note migration** : si l'IP change (changement de provider), il suffit de
mettre à jour le record DNS — le compose et le Caddyfile ne changent pas.

---

## 4. Récupération du repo et configuration

```bash
# Sur l'hôte, en tant que deploy
git clone https://github.com/TidianeCisse777/IDEA.git /opt/idea
cd /opt/idea

# Créer le .env à partir d'un modèle
cp .env.example .env  # si tu maintiens un .env.example, sinon copie ton .env de dev
nano .env
```

Variables **obligatoires** à fournir dans `.env` pour la prod :

```bash
# Identité de l'instance
PROD_DOMAIN=tonprojet.duckdns.org
PROD_TLS_EMAIL=admin@tonprojet.org   # pour les alertes Let's Encrypt

# Postgres
POSTGRES_PASSWORD=<mot de passe fort généré, jamais réutilisé>

# Agent
OPENAI_API_KEY=<clé OpenAI dédiée prod, avec usage cap>
LLM_MODEL=gpt-5.4-mini

# Tracing (optionnel)
LANGCHAIN_API_KEY=<clé LangSmith si tu veux les traces>
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=copepod-prod

# MCP EcoTaxa
MCP_AUTH_TOKEN=<token aléatoire>
ECOTAXA_TOKEN=<token EcoTaxa>
```

**Permissions** :
```bash
chmod 600 .env
chown deploy:deploy .env
```

---

## 5. Lancement

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f caddy
```

Caddy va demander un certificat Let's Encrypt automatiquement la première
fois. Si tu vois `certificate obtained successfully` dans les logs, tout
est OK. Ouvre `https://$PROD_DOMAIN` dans un navigateur.

---

## 6. Bootstrap Open WebUI

- Premier compte créé = administrateur. **Crée-le immédiatement avec ton
  email** avant de partager l'URL.
- `ENABLE_SIGNUP=false` et `DEFAULT_USER_ROLE=pending` sont déjà set dans
  le compose : aucune création de compte spontanée, et si jamais un endpoint
  laisse passer, les nouveaux comptes sont en attente d'approbation admin.
- Pour ajouter un prof : Settings → Admin Panel → Users → Add User.

---

## 7. Mise à jour continue

Le service `watchtower` du compose est en mode opt-in
(`WATCHTOWER_LABEL_ENABLE=true`). Seuls les containers avec le label
`com.centurylinklabs.watchtower.enable=true` sont surveillés :
`copepod-agent` et `mcp-ecotaxa`.

**Flow attendu** :
1. Tu push sur `main`
2. GitHub Actions build et push une image multi-arch sur `ghcr.io`
3. Watchtower poll toutes les 5 min, détecte le nouveau digest, pull,
   redémarre le container
4. Les testeurs rafraîchissent l'URL et voient la nouvelle version

Postgres et Open WebUI **ne sont pas auto-updatés** — voulu, pour ne pas
casser les chats / la base sur une montée de version.

---

## 8. Backups

Cron quotidien sur l'hôte :

```bash
sudo crontab -e
```

```cron
# Postgres dump à 03h00 UTC
0 3 * * * /usr/bin/docker exec copepod_postgres pg_dump -U copepod copepod_sessions | gzip > /opt/idea/backups/pg_$(date +\%Y\%m\%d).sql.gz

# Chroma + open-webui data à 03h15
15 3 * * * /usr/bin/tar czf /opt/idea/backups/data_$(date +\%Y\%m\%d).tar.gz -C /var/lib/docker/volumes copepod_data open_webui_data

# Nettoyage > 14 jours
0 4 * * * /usr/bin/find /opt/idea/backups -mtime +14 -delete
```

Pour exporter hors VM : `rclone` vers Backblaze B2 (10 GB gratuits) ou
S3-compatible.

---

## 9. Monitoring

- **UptimeRobot** (gratuit) : ping `https://$PROD_DOMAIN/health` toutes les
  5 min, alerte email/Slack si down.
- Logs docker rotatés automatiquement (`max-size: 10m, max-file: 3`
  dans le compose).
- Pour les traces LLM en détail : LangSmith (`LANGCHAIN_TRACING_V2=true`).

---

## 10. Migration vers un autre hôte

Tout ce qui caractérise *cette* instance est dans `.env` + les volumes
Docker. Pour migrer :

1. Sur l'ancien hôte : arrêter le compose, dump postgres, tar les volumes.
2. Copier les artefacts (`.env`, dumps, tar) sur le nouvel hôte.
3. Restaurer les volumes (`docker volume create` + extract).
4. Mettre à jour le DNS pour pointer vers la nouvelle IP.
5. `docker compose -f docker-compose.prod.yml up -d` — Caddy refera un
   certificat Let's Encrypt sur le même domaine, transparent côté testeurs.

Aucune ligne du compose, du Caddyfile ou du code Python à toucher.

---

## 11. Checklist post-déploiement

- [ ] `https://$PROD_DOMAIN` répond en HTTPS valide
- [ ] Login admin Open WebUI fait, mot de passe stocké en password manager
- [ ] `ENABLE_SIGNUP=false` confirmé dans l'UI (Settings → Admin)
- [ ] Test d'une question copépode end-to-end depuis l'UI
- [ ] `docker compose -f docker-compose.prod.yml ps` — tous `healthy`
- [ ] Backup cron créé et premier run validé
- [ ] UptimeRobot configuré
- [ ] `.env` sauvegardé chiffré hors VM (Bitwarden, age, 1Password…)
- [ ] Ports `5433` / `8000` / `8001` non joignables depuis l'extérieur
      (test depuis une autre machine : `curl -v http://$PUBLIC_IP:8000` doit
      timeout)

---

## Annexe — Partage rapide via Cloudflare Tunnel depuis le Mac local

Mode "démo / partage avant qu'on ait une vraie VM". Le compose dev tourne
sur ton Mac, Cloudflare expose Open WebUI en HTTPS public sans port
forwarding et sans toucher au firewall réseau. URL utilisable tant que
le Mac est allumé et le tunnel actif.

### Prérequis (à valider une seule fois)

1. **Compose dev up** : `docker compose up -d` (Open WebUI répond sur
   `http://localhost:3000`).
2. **`cloudflared` installé** : `brew install cloudflared` puis
   `cloudflared --version`.
3. **Open WebUI sécurisé AVANT d'exposer** — sinon le premier visiteur de
   l'URL devient admin :
   - Va sur `http://localhost:3000` et crée le compte admin (le premier
     compte enregistré est admin par défaut).
   - Settings → Admin Panel → Auth :
     - `Enable New User Sign Ups` → **OFF**
     - `Default User Role` → **Pending**
   - Crée toi-même un compte par testeur, ou laisse les comptes en
     `Pending` que tu approuves manuellement.

### Démarrer le tunnel (relance manuelle)

```bash
cloudflared tunnel --url http://localhost:3000 --no-autoupdate --protocol http2
```

La commande imprime dans la sortie une ligne du type :

```
https://random-words-1234.trycloudflare.com
```

C'est l'URL publique à partager aux testeurs. Tant que la commande
tourne (terminal ouvert), l'URL répond.

### Faire tourner en arrière-plan sans monopoliser le terminal

```bash
mkdir -p ~/Library/Logs/cloudflared
nohup cloudflared tunnel --url http://localhost:3000 --no-autoupdate --protocol http2 \
  > ~/Library/Logs/cloudflared/tunnel.log 2>&1 &
sleep 15
grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/cloudflared/tunnel.log | head -1
```

La dernière ligne extrait l'URL du log. Le process tourne en background
détaché du terminal — tu peux fermer le terminal sans tuer le tunnel.

### Arrêter le tunnel

```bash
pkill -f "cloudflared tunnel --url"
```

### À savoir absolument

- **L'URL change à chaque relance** du tunnel. C'est une limite des
  *quick tunnels* anonymes. Pour une URL stable, il faut un compte
  Cloudflare gratuit + un domaine sur leur zone DNS (out of scope ici).
- **Le tunnel meurt si le Mac s'éteint, dort longtemps ou perd le Wi-Fi**.
  À chaque redémarrage du Mac, il faut relancer la commande à la main.
- **Pas d'auto-start configuré** (volontairement — c'est une persistance
  système sensible). Pour le mettre en LaunchAgent plus tard, voir la
  section dédiée plus bas.
- **Pas un setup prod** — pas de TLS pinning sur ton domaine, pas
  d'auth additionnelle au-delà d'Open WebUI, pas de monitoring. À
  utiliser pour démo et tests pendant que la vraie VM est provisionnée.
- **`docker.sock` est monté dans le container agent** en compose dev. Sur
  une exposition publique prolongée c'est un risque — pour la prod
  utiliser `docker-compose.prod.yml` qui retire ce mount.

### Optionnel — LaunchAgent pour relance auto au login Mac

À installer seulement si tu acceptes qu'un service système relance
cloudflared à chaque login. Crée
`~/Library/LaunchAgents/com.cloudflared.copepod.plist` :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.cloudflared.copepod</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/cloudflared</string>
    <string>tunnel</string>
    <string>--url</string>
    <string>http://localhost:3000</string>
    <string>--no-autoupdate</string>
    <string>--protocol</string>
    <string>http2</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/&lt;ton-user&gt;/Library/Logs/cloudflared/tunnel.log</string>
  <key>StandardErrorPath</key><string>/Users/&lt;ton-user&gt;/Library/Logs/cloudflared/tunnel.log</string>
</dict>
</plist>
```

Puis :
```bash
launchctl load -w ~/Library/LaunchAgents/com.cloudflared.copepod.plist
```

Pour désinstaller :
```bash
launchctl unload ~/Library/LaunchAgents/com.cloudflared.copepod.plist
rm ~/Library/LaunchAgents/com.cloudflared.copepod.plist
```

### Migration vers la vraie VM plus tard

Quand la VM (Oracle, Hetzner, Laval) est prête :
1. Arrêter le tunnel et le compose dev sur le Mac.
2. Suivre les sections **1 à 11** de ce document.
3. Donner aux testeurs la nouvelle URL `https://$PROD_DOMAIN` — l'ancienne
   `*.trycloudflare.com` ne sert plus.

Aucune ligne de code à toucher entre les deux modes.
