#!/usr/bin/env bash
# =============================================================================
# stop.sh — Gracefully stop the llama.cpp vs Ollama comparison app
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$ROOT_DIR/output/app.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "ℹ️  No PID file found. App may not be running."
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "🛑  Stopping app (PID $PID)…"
    kill -TERM "$PID"
    # Wait up to 5 seconds
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  Process did not stop gracefully; forcing kill."
        kill -KILL "$PID"
    fi
    rm -f "$PID_FILE"
    echo "✅  App stopped."
else
    echo "ℹ️  Process $PID is not running. Cleaning up PID file."
    rm -f "$PID_FILE"
fi
