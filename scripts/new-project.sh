#!/usr/bin/env bash
set -e

PROJECT_NAME="$1"
TARGET_DIR="$(pwd)/$PROJECT_NAME"
LLM_PORT="${SANDBOX_LLM_PORT:-1234}"
LLM_URL="http://localhost:$LLM_PORT/v1/chat/completions"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo "--- $* ---"; }

# Step 0: Pre-flight check (Hard Rule 1 & 4)
# Model-agnostic: probe whatever model the CEO has loaded — never hardcode one.
step "Pre-flight: checking local LLM at $LLM_URL ..."
LOADED_MODELS="$(curl -s --max-time 10 "http://localhost:$LLM_PORT/v1/models" \
  | python3 -c 'import sys,json
try:
    for m in json.load(sys.stdin)["data"]:
        print(m["id"])
except Exception:
    pass' || true)"
[ -n "$LOADED_MODELS" ] || die "no model loaded in LM Studio. Load one (any non-thinking model) and retry."
LOADED_MODEL="$(printf '%s\n' "$LOADED_MODELS" | head -1)"
if [ "$(printf '%s\n' "$LOADED_MODELS" | wc -l | tr -d ' ')" -gt 1 ]; then
  echo "  WARNING: multiple models loaded — probing the first:"
  printf '%s\n' "$LOADED_MODELS" | sed 's/^/    /'
  echo "  (make sure your OpenCode global config maps agents to the intended ones)"
fi
echo "  probing model: $LOADED_MODEL"

PREFLIGHT_RAW="$(curl -s --max-time 30 "$LLM_URL" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$LOADED_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":5,\"temperature\":0}" \
  || true)"

[ -n "$PREFLIGHT_RAW" ] || die "no response from LM Studio. Is the server up with a model loaded?"

CONTENT="$(printf '%s' "$PREFLIGHT_RAW" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    msg = d["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    if not content and reasoning:
        print("THINKING_MODEL", end="")
    else:
        print(content, end="")
except Exception as e:
    print("PARSE_ERROR:" + str(e), end="")
')"

case "$CONTENT" in
  "")             die "pre-flight returned empty content. Model misconfigured?" ;;
  THINKING_MODEL) die "pre-flight: THINKING MODEL loaded (content empty, reasoning present). Load the non-thinking coder model (Hard Rule 1)." ;;
  PARSE_ERROR:*)  die "pre-flight JSON parse failed: ${CONTENT#PARSE_ERROR:}" ;;
  *)              echo "  ok: local LLM responded: $CONTENT" ;;
esac

# Step 1: Bootstrap
step "Running bootstrap..."
[ -x scripts/bootstrap.sh ] || die "scripts/bootstrap.sh missing or not executable."
./scripts/bootstrap.sh "$PROJECT_NAME" || die "bootstrap failed."

# Step 2: Git
step "Initializing git..."
git init || die "git init failed"

cat <<DONE
READY: $PROJECT_NAME is instantiated, bootstrapped, and pre-flight-verified.
Location: $TARGET_DIR

Next steps (do these while awake):
1. cd $TARGET_DIR
2. source .venv/bin/activate  (if not already active)
3. Adapt stack if needed (Rule 3): edit ci.yml / requirements if not FastAPI+SQLite
4. Load one or two non-thinking models in LM Studio (your choice — D-41: the
   repo never names a model) and map roles in ~/.config/sw-dev-blueprint/models.env
   (SWBP_MODEL_EM=<name>, SWBP_MODEL_CODER=<name>).
5. Author the frozen spec (PRD/ERD/contracts/tests) with your TPM chat, stage
   under scripts/.approved/incoming/, run scripts/refreeze.sh.
6. scripts/orchestrate.sh — the shell drives EM and coder over HTTP
   directly (D-53), no agent harness needed. A conductor (Claude Code,
   OpenCode, anything) is optional for CEO ergonomics only.

Tests are ground truth (Rule 5).
Two strikes on the same error then stop (Rule 2).
DONE
