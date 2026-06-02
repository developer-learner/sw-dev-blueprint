#!/bin/bash
# new-project.sh — One-command project instantiation from sw-dev-blueprint.
#
# Usage: ./scripts/new-project.sh <project-name>
#
# Takes you from "nothing" to "verified ready to build":
#   1. Instantiate a fresh repo from the template (gh)
#   2. Clone it locally
#   3. Run bootstrap (venv + deps + placeholder rename)
#   4. PRE-FLIGHT: verify the local LLM returns non-empty content (Hard Rule 1)
#   5. Stop and hand off — YOU write CURRENT.md and start Aider while awake.
#
# Deliberately does NOT auto-run the architect/editor loop. Per the founding
# lesson: agents fabricate success at failure points; a human stays at the
# moment of code generation. This script removes setup friction only.
#
# Every step halts loudly on failure (Hard Rule 4: halt-and-notify).

set -euo pipefail

TEMPLATE="developer-learner/sw-dev-blueprint"
DEV_DIR="$HOME/dev"
LLM_URL="http://localhost:1234/v1/chat/completions"

die()  { echo "HALT: $*" >&2; exit 1; }
step() { echo ""; echo ">> $*"; }

PROJECT_NAME="${1:-}"
[ -n "$PROJECT_NAME" ] || die "no project name. Usage: new-project.sh <project-name>"

TARGET_DIR="$DEV_DIR/$PROJECT_NAME"
[ -e "$TARGET_DIR" ] && die "$TARGET_DIR already exists. Pick another name or remove it."

step "Checking prerequisites..."
command -v gh         >/dev/null || die "gh not on PATH."
command -v aider      >/dev/null || die "aider not on PATH. Run: pipx install aider-chat --python python3.12"
command -v python3.12 >/dev/null || die "python3.12 not on PATH."
command -v curl       >/dev/null || die "curl not on PATH."
command -v python3    >/dev/null || die "python3 not on PATH."
gh auth status >/dev/null 2>&1   || die "gh not authenticated. Run: gh auth login"
echo "  ok: tools present, gh authenticated"

step "Creating repo '$PROJECT_NAME' from template $TEMPLATE..."
mkdir -p "$DEV_DIR"
cd "$DEV_DIR"
gh repo create "$PROJECT_NAME" --template "$TEMPLATE" --private --clone \
  || die "gh repo create failed (name taken on GitHub? template flag off?)."
cd "$TARGET_DIR" || die "clone did not produce $TARGET_DIR."

step "Running bootstrap..."
[ -x scripts/bootstrap.sh ] || die "scripts/bootstrap.sh missing or not executable."
./scripts/bootstrap.sh "$PROJECT_NAME" || die "bootstrap failed."

step "Pre-flight: checking local LLM at $LLM_URL ..."
PREFLIGHT_RAW="$(curl -s --max-time 30 "$LLM_URL" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":50,"temperature":0}' \
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
  *)              echo "  ok: local LLM responded: \"$CONTENT\"" ;;
esac

cat <<DONE

READY: $PROJECT_NAME is instantiated, bootstrapped, and pre-flight-verified.

  Location: $TARGET_DIR

Next (do these while awake):
  1. cd $TARGET_DIR
  2. source .venv/bin/activate
  3. Adapt stack if needed (Rule 3): edit ci.yml / requirements if not FastAPI+Postgres
  4. Write your spec in tasks/CURRENT.md (What + Acceptance Criteria)
  5. export OPENAI_API_BASE=http://localhost:1234/v1
     export OPENAI_API_KEY=lm-studio
  6. aider --architect --message "Implement the task in tasks/CURRENT.md" <files...>

The loop is yours to start. Tests are ground truth (Rule 5); two strikes on the
same error then stop (Rule 2).
DONE
