#!/usr/bin/env bash
# Lance le serveur FastAPI + LangGraph Studio en parallèle.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate 2>/dev/null || true

echo "[start] Launching FastAPI server..."
python serve.py &
SERVE_PID=$!

echo "[start] Launching LangGraph Studio (tunnel)..."
langgraph dev --tunnel &
STUDIO_PID=$!

echo "[start] FastAPI PID=$SERVE_PID  Studio PID=$STUDIO_PID"
echo "[start] Ctrl-C to stop both."

trap "echo '[start] Stopping...'; kill $SERVE_PID $STUDIO_PID 2>/dev/null; exit 0" INT TERM

wait
