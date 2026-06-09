#!/usr/bin/env bash
# Toggle LAN sharing for serve.py + Open WebUI.
# Usage: ./scripts/share_access.sh enable|disable|status
set -e

MODE="${1:-status}"

case "$MODE" in
  enable|on|lan|public)
    echo "→ Activation de l'accès réseau (LAN)"
    START_WEBUI=1 SERVE_ACCESS_MODE=lan bash "$(dirname "$0")/start_dev.sh" restart
    ;;
  disable|off|local)
    echo "→ Désactivation de l'accès réseau partagé"
    START_WEBUI=0 SERVE_ACCESS_MODE=local bash "$(dirname "$0")/start_dev.sh" restart
    ;;
  status)
    echo "SERVE_ACCESS_MODE=${SERVE_ACCESS_MODE:-local}"
    echo "SERVE_BASE_URL=${SERVE_BASE_URL:-http://localhost:8000}"
    ;;
  *)
    echo "Usage: $0 {enable|disable|status}" >&2
    exit 1
    ;;
esac
