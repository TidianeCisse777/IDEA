#!/usr/bin/env bash
# Lance ou redémarre serve.py + Open WebUI.
# Usage : ./scripts/start_dev.sh [restart]
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"
PORT="${SERVE_PORT:-8000}"
WEBUI_URL="http://localhost:3000"
API_URL="http://localhost:$PORT"
CMD="${1:-start}"

_kill_serve() {
  local pids
  pids=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "→ Arrêt serve.py (pid $pids) ..."
    kill "$pids" 2>/dev/null || true
    sleep 1
    echo "✓ Arrêté"
  else
    echo "  (aucun processus sur :$PORT)"
  fi
}

if [ "$CMD" = "restart" ]; then
  _kill_serve
fi

# --- serve.py ---
echo "→ Démarrage serve.py sur $API_URL ..."
source "$VENV"
cd "$REPO_DIR"
python serve.py &
SERVE_PID=$!

# Attend que l'API réponde
for i in $(seq 1 20); do
  if curl -sf "$API_URL/" > /dev/null 2>&1; then
    echo "✓ API prête ($API_URL)"
    break
  fi
  sleep 0.5
done

# --- Open WebUI ---
echo "→ Démarrage Open WebUI ..."
docker start open-webui > /dev/null 2>&1 && echo "✓ Open WebUI démarré ($WEBUI_URL)" \
  || echo "⚠ open-webui container introuvable — crée-le avec :"
echo "    docker run -d --name open-webui -p 3000:8080 ghcr.io/open-webui/open-webui:main"

echo ""
echo "─────────────────────────────────────────────────"
echo "  API   : $API_URL/v1"
echo "  WebUI : $WEBUI_URL"
echo "  Clé   : copepod-key"
echo "  Modèle: copepod-agent"
echo "─────────────────────────────────────────────────"
echo "  Ctrl+C pour arrêter serve.py"
echo ""

wait $SERVE_PID
