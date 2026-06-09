#!/usr/bin/env bash
# Lance serve.py + Open WebUI pour tester l'agent manuellement.
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"
PORT="${SERVE_PORT:-8000}"
WEBUI_URL="http://localhost:3000"
API_URL="http://localhost:$PORT"

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

# Garde serve.py au premier plan
wait $SERVE_PID
