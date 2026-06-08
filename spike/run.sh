#!/bin/bash
set -euo pipefail

SPIKE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="/tmp/inv2-spike/.venv"
RESULT_FILE="$SPIKE_DIR/RESULT.md"

echo "=== INV-2 / OpenHands Spike — Launch Script ==="
echo "Started: $(date)"
echo ""

# ── Copy test project to /tmp for consistent paths with the hook ──────
echo "[1/5] Copying test project to /tmp/inv2-spike/test-project/..."
mkdir -p /tmp/inv2-spike
rm -rf /tmp/inv2-spike/test-project
cp -a "$SPIKE_DIR/test-project" /tmp/inv2-spike/test-project
echo "  OK — /tmp/inv2-spike/test-project ready"

# ── Pre-flight: LM Studio ──────────────────────────────────────────────
echo "[2/5] Checking LM Studio at http://127.0.0.1:1234/v1..."
if curl -sf http://127.0.0.1:1234/v1/models > /dev/null 2>&1; then
    echo "  OK — LM Studio is responding"
else
    echo "  FAIL — LM Studio not reachable. Start LM Studio server first."
    echo "INCOMPLETE — LM Studio unreachable" > "$RESULT_FILE"
    exit 1
fi

# ── Python venv + deps ────────────────────────────────────────────────
echo "[3/5] Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q openhands-sdk openhands-tools 2>&1 | tail -1
echo "  OK — openhands-sdk installed"

# ── Ensure hook is executable ──────────────────────────────────────────
chmod 755 "$SPIKE_DIR/inv2-hook.sh"

# ── Run spike (keeps Mac awake) ────────────────────────────────────────
echo "[4/5] Running spike harness (caffeinate active)..."
echo ""
caffeinate -i "$VENV_DIR/bin/python3" "$SPIKE_DIR/run-spike.py"
SPIKE_EXIT=$?

# ── Done ───────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Spike complete (exit: $SPIKE_EXIT)"
echo "Finished: $(date)"
echo "Results:"
cat "$RESULT_FILE" 2>/dev/null || echo "(no RESULT.md)"
exit $SPIKE_EXIT
