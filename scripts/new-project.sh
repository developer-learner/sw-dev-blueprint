#!/usr/bin/env bash
set -e

PROJECT_NAME="$1"
TARGET_DIR="$(pwd)/$PROJECT_NAME"
LLM_URL="http://localhost:1234/v1/chat/completions"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo "--- $* ---"; }

# Step 0: Pre-flight check (Hard Rule 1 & 4)
step "Pre-flight: checking local LLM at $LLM_URL ..."
PREFLIGHT_RAW="$(curl -s --max-time 30 "$LLM_URL" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder-next","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":5,"temperature":0}' \
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
3. Adapt stack if needed (Rule 3): edit ci.yml / requirements if not FastAPI+Postgres
4. Run: opencode
   In OpenCode: /models → select "Qwen3 Coder Next (local)" under "lms"
   Then just describe what you want to build in plain English

Tests are ground truth (Rule 5).
Two strikes on the same error then stop (Rule 2).
DONE
