#!/usr/bin/env bash
# Lance l'assistant copépodes : Postgres + Open WebUI (Docker) + agent (local).
# Partage réseau : LAN via IP locale, ou internet via tunnel Cloudflare.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. infrastructure Docker ───────────────────────────────────────────────────
echo "[start] Démarrage Postgres + Open WebUI..."
docker compose up postgres open-webui -d

echo "[start] Attente de Postgres..."
until docker compose exec -T postgres pg_isready -U copepod -d copepod_sessions -q 2>/dev/null; do
  sleep 1
done
echo "[start] Postgres OK"

# ── 2. environnement Python ────────────────────────────────────────────────────
source .venv/bin/activate 2>/dev/null || true

# ── 3. URL de partage ──────────────────────────────────────────────────────────
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null \
  || ipconfig getifaddr en1 2>/dev/null \
  || hostname -I 2>/dev/null | awk '{print $1}' \
  || echo "localhost")

SHARE_URL="http://${LAN_IP}:3000"

# Tunnel Cloudflare si disponible (lien internet sans compte)
TUNNEL_PID=""
if command -v cloudflared &>/dev/null; then
  echo "[start] Tunnel Cloudflare en cours..."
  cloudflared tunnel --url http://localhost:3000 --no-autoupdate 2>&1 \
    | grep --line-buffered "trycloudflare.com" \
    | awk '{print "[tunnel] Lien public : " $NF}' &
  TUNNEL_PID=$!
fi

echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "  Assistant copépodes — NeoLab, Université Laval"
echo "  LAN  : ${SHARE_URL}"
if [ -z "$TUNNEL_PID" ]; then
echo "  Internet : installe cloudflared pour un lien public"
echo "             brew install cloudflare/cloudflare/cloudflared"
fi
echo "└─────────────────────────────────────────────────┘"
echo ""

trap 'echo "[start] Arrêt..."; [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null; docker compose stop open-webui postgres; exit 0' INT TERM

# ── 4. agent ───────────────────────────────────────────────────────────────────
python serve.py
