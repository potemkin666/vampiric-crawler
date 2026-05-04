#!/usr/bin/env bash
# ============================================================
#  Vampiric Crawler — launch script
#  Works from any location, including an external hard drive.
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$SCRIPT_DIR/vampire.py"

# ── Check for Python 3 ───────────────────────────────────────
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[☠] Python not found. Please install Python 3.6+ to awaken the vampire." >&2
    exit 1
fi

# ── Install dependencies if needed ──────────────────────────
REQ="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQ" ]; then
    $PYTHON -m pip install -q -r "$REQ" 2>/dev/null || true
fi

# ── Ensure the entrypoint exists ──────────────────────────────
if [ ! -f "$APP" ]; then
    echo "[☠] Missing entrypoint: $APP" >&2
    exit 1
fi

# ── First-run diagnostics ─────────────────────────────────────
if ! $PYTHON "$APP" --setup-check -o "$SCRIPT_DIR"; then
    echo "[!] First-run diagnostics found issues. Review the output above before continuing." >&2
fi

# ── Prompt for a target when launched without CLI args ───────
if [ "$#" -eq 0 ]; then
    if [ -t 0 ] || [ -n "${VAMPIRIC_LAUNCH_PROMPT:-}" ]; then
        printf "Enter target URL (for example https://example.com): "
        IFS= read -r TARGET_URL
        TARGET_URL="$(printf '%s' "$TARGET_URL" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if [ -z "$TARGET_URL" ]; then
            echo "[☠] No prey specified. Closing the coffin." >&2
            exit 1
        fi
        set -- -u "$TARGET_URL"
    else
        echo "[☠] No target provided. Re-run with -u <URL>." >&2
        exit 1
    fi
fi

# ── Run ─────────────────────────────────────────────────────
cd "$SCRIPT_DIR"
$PYTHON "$APP" "$@"
