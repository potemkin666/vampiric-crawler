#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$SCRIPT_DIR/webapp.py"

if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[☠] Python not found. Please install Python 3.6+ to awaken the crawler console." >&2
    exit 1
fi

REQ="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    $PYTHON -m pip install -q -r "$REQ" 2>/dev/null || true
fi

if [ ! -f "$APP" ]; then
    echo "[☠] Missing web console entrypoint: $APP" >&2
    exit 1
fi

cd "$SCRIPT_DIR"
$PYTHON "$APP"
