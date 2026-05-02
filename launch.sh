#!/usr/bin/env bash
# ============================================================
#  Vampiric Crawler — launch script
#  Works from any location, including an external hard drive.
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Check for Python 3 ───────────────────────────────────────
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[☠] Python not found. Please install Python 3.6+ to awaken the vampire."
    exit 1
fi

# ── Install dependencies if needed ──────────────────────────
REQ="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    $PYTHON -m pip install -q -r "$REQ" 2>/dev/null || true
fi

# ── Run ─────────────────────────────────────────────────────
cd "$SCRIPT_DIR"
$PYTHON vampire.py "$@"
