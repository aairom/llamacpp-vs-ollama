#!/usr/bin/env bash
# =============================================================================
# launch.sh — Start the llama.cpp vs Ollama comparison app in detached mode
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Always operate from the project root so paths resolve correctly
cd "$ROOT_DIR"

# Load .env file if present (sets PORT, DEBUG, etc.)
if [ -f "$ROOT_DIR/.env" ]; then
    set -o allexport
    # shellcheck source=/dev/null
    source "$ROOT_DIR/.env"
    set +o allexport
fi

LOG_FILE="$ROOT_DIR/output/app.log"
PID_FILE="$ROOT_DIR/output/app.pid"
VENV_DIR="$ROOT_DIR/venv"
PORT="${PORT:-8088}"

# Create output directory if it doesn't exist
mkdir -p "$ROOT_DIR/output"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  App is already running (PID $OLD_PID)."
        echo "   ➜  http://localhost:${PORT}"
        echo "   Run ./scripts/stop.sh to stop it first."
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Set up or activate virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "🔧  Creating virtual environment…"
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "📦  Installing / verifying dependencies…"
pip install -q -r "$ROOT_DIR/requirements.txt"

# Start in background
echo "🚀  Starting comparison app…"
nohup python3 "$ROOT_DIR/app.py" > "$LOG_FILE" 2>&1 &
APP_PID=$!

echo "$APP_PID" > "$PID_FILE"

# Wait briefly to confirm it started
sleep 1
if kill -0 "$APP_PID" 2>/dev/null; then
    echo ""
    echo "  ✅  llama.cpp vs Ollama Comparison App is running!"
    echo "  ➜   http://localhost:${PORT}"
    echo ""
    echo "  PID   : $APP_PID"
    echo "  Log   : $LOG_FILE"
    echo "  Stop  : ./scripts/stop.sh"
    echo ""
else
    echo "❌  App failed to start. Check $LOG_FILE for details."
    cat "$LOG_FILE"
    exit 1
fi
