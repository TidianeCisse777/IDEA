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

# Tunnels Cloudflare si disponible : un pour Open WebUI (3000), un pour serve.py (8000).
# SERVE_BASE_URL est exporté vers serve.py pour que les liens d'images / téléchargements
# pointent vers une URL publique (sinon http://localhost:8000 cassé depuis un browser distant).
TUNNEL_PID=""
TUNNEL_LOG="logs/cloudflared.log"
TUNNEL_URL=""
SERVE_TUNNEL_PID=""
SERVE_TUNNEL_LOG="logs/cloudflared-serve.log"
SERVE_TUNNEL_URL=""
if command -v cloudflared &>/dev/null; then
  mkdir -p logs
  : > "$TUNNEL_LOG"
  : > "$SERVE_TUNNEL_LOG"
  echo "[start] Tunnels Cloudflare en cours (WebUI :3000 + serve :8000)..."
  cloudflared tunnel --url http://localhost:3000 --no-autoupdate \
    > "$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!
  cloudflared tunnel --url http://localhost:8000 --no-autoupdate \
    > "$SERVE_TUNNEL_LOG" 2>&1 &
  SERVE_TUNNEL_PID=$!
  # Attente des URLs (max ~15s par tunnel).
  for _ in $(seq 1 30); do
    [ -z "$TUNNEL_URL" ] && \
      TUNNEL_URL=$( { grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null || true; } | head -1)
    [ -z "$SERVE_TUNNEL_URL" ] && \
      SERVE_TUNNEL_URL=$( { grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$SERVE_TUNNEL_LOG" 2>/dev/null || true; } | head -1)
    [ -n "$TUNNEL_URL" ] && [ -n "$SERVE_TUNNEL_URL" ] && break
    sleep 0.5
  done
  # Exporter SERVE_BASE_URL pour serve.py (override de la valeur du .env)
  if [ -n "$SERVE_TUNNEL_URL" ]; then
    export SERVE_BASE_URL="$SERVE_TUNNEL_URL"
  fi
fi

cleanup() {
  echo ""
  echo "[start] Arrêt..."
  for pid in "$TUNNEL_PID" "$SERVE_TUNNEL_PID"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.3
      done
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
  # Filet de sécurité : tue toute instance résiduelle lancée par ce script
  pkill -f "cloudflared tunnel --url http://localhost:3000" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:8000" 2>/dev/null || true
  docker compose stop open-webui postgres
  exit 0
}
trap cleanup INT TERM EXIT

echo ""
echo "┌─────────────────────────────────────────────────┐"
echo "  Assistant copépodes — NeoLab, Université Laval"
echo "  LAN  : ${SHARE_URL}"
if [ -n "$TUNNEL_URL" ]; then
echo "  WebUI    : ${TUNNEL_URL}"
elif [ -n "$TUNNEL_PID" ]; then
echo "  WebUI    : tunnel en cours, voir ${TUNNEL_LOG}"
else
echo "  WebUI    : installe cloudflared pour un lien public"
echo "             brew install cloudflare/cloudflare/cloudflared"
fi
if [ -n "$SERVE_TUNNEL_URL" ]; then
echo "  Serve    : ${SERVE_TUNNEL_URL} (images/téléchargements)"
fi
echo "└─────────────────────────────────────────────────┘"
echo ""

# ── 4. agent ───────────────────────────────────────────────────────────────────
python serve.py
