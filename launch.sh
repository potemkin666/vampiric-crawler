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

# ── Prompt for a target when launched without CLI args ───────
if [ "$#" -eq 0 ]; then
    if [ -t 0 ] || [ -n "${VAMPIRIC_LAUNCH_PROMPT:-}" ]; then
        printf "Enter target URL (for example https://example.com): "
        IFS= read -r TARGET_URL
        if [ -z "$TARGET_URL" ]; then
            echo "[☠] No prey specified. Closing the coffin."
            exit 1
        fi
        set -- -u "$TARGET_URL"
    else
        echo "[☠] No target provided. Re-run with -u <URL>."
        exit 1
    fi
fi

# ── Run ─────────────────────────────────────────────────────
cd "$SCRIPT_DIR"
$PYTHON vampire.py "$@"
