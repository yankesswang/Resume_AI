#!/usr/bin/env bash
# Start backend (FastAPI) and frontend (Vite) dev servers.
# Usage: ./start.sh
# Stop both with Ctrl+C.

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Trap Ctrl+C and kill both child processes cleanly
cleanup() {
  echo ""
  echo "Stopping servers…"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

echo "Starting backend on http://0.0.0.0:8000 …"
cd "$ROOT"
uv run python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "Starting frontend on http://0.0.0.0:5173 …"
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

# Detect local LAN IP for convenience
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "<your-ip>")

echo ""
echo "Both servers running. Press Ctrl+C to stop."
echo "  Backend:  http://localhost:8000  |  http://${LAN_IP}:8000"
echo "  Frontend: http://localhost:5173  |  http://${LAN_IP}:5173"
echo ""

wait "$BACKEND_PID" "$FRONTEND_PID"
