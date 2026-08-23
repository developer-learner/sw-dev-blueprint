#!/usr/bin/env bash
# drive-consult.sh — D-71 selftest harness for orchestrate.sh's consult_em.
#
# Exercises the REAL functions (extracted from orchestrate.sh at run time,
# never copied — a copy would silently drift) against a scripted fake EM:
# the pytest side stages numbered raw replies in <workdir>/replies/N, this
# driver wires a stub llm-call.sh that plays them back in call order while
# recording each prompt it was sent (prompts/N, for assertions about the
# retry feedback), then runs consult_em and reports on stdout:
#
#     CALLS=<n> VERDICT=<verdict>
#
# The stamped artifact is left in .pipeline-state/diagnosis-<id>.json for
# the test to inspect. Exit status is consult_em's own (die exits 1).
#
# Usage: drive-consult.sh <workdir> <task-id> <evidence>
set -euo pipefail

WORK="${1:?usage: drive-consult.sh <workdir> <task-id> <evidence>}"
TASK_ID="${2:?task id}"
EVIDENCE="${3:?evidence text}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f replies/1 ] || { echo "drive-consult: no replies/1 staged in $WORK" >&2; exit 64; }
mkdir -p scripts/schemas tasks .opencode/prompts prompts
cp "$REPO/scripts/validate-plan.py" scripts/
cp "$REPO/scripts/schemas/diagnosis.schema.json" scripts/schemas/
: > .opencode/prompts/em.md

# Fake EM: replay replies/N in call order; keep each prompt for assertions.
cat > scripts/llm-call.sh <<'STUB'
#!/usr/bin/env bash
n=$(cat .calls 2>/dev/null || echo 0); n=$((n + 1)); printf '%s\n' "$n" > .calls
cat > "prompts/$n"
cat "replies/$n" 2>/dev/null || printf 'no scripted reply %s\n' "$n"
STUB
chmod +x scripts/llm-call.sh

# Lane gate is out of scope here (it has its own coverage); stub it green.
printf '#!/usr/bin/env bash\nexit 0\n' > scripts/phase-gate.sh
chmod +x scripts/phase-gate.sh

# em_call takes a phase-start ref, so the workdir must be a git repo.
git init -q .
git -c user.email=selftest@local -c user.name=selftest add -A
git -c user.email=selftest@local -c user.name=selftest commit -qm fixture

# Environment the extracted functions expect (mirrors orchestrate.sh's init).
PLANE_DIR=$(pwd -P)
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
APPROVED="scripts/.approved"
AGENT_TIMEOUT=60
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
mark() { :; }

# Extract the real functions — repo style is `name() {` and closing `}` both
# at column 0, so the sed range is exact. Fail loudly if the shape changes.
extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-consult: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract build_context)"
eval "$(extract em_call)"
eval "$(extract consult_em)"

consult_em "$TASK_ID" "$EVIDENCE"
echo "CALLS=$(cat .calls) VERDICT=${DIAG_VERDICT:--}"
