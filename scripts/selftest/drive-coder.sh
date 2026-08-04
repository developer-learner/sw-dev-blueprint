#!/usr/bin/env bash
# drive-coder.sh — selftest harness for orchestrate.sh's run_coder, focused
# on gate-failure propagation (the 2026-07-16 review's blocker #1).
#
# Exercises the REAL run_coder (extracted from orchestrate.sh at run time,
# never copied — a copy would silently drift) with:
#   * a scripted fake coder (stub llm-call.sh replays <workdir>/replies/N)
#   * a controllable phase-gate stub (exits $(cat .gate-rc), default 0)
#   * the REAL apply-edit-blocks.py and check-swallowed-errors.py
#
# CRITICAL SHAPE: run_coder is invoked from an `if` condition below, exactly
# as orchestrate.sh invokes it — that calling context suppresses `set -e`
# for the whole function body, which is the trap that let a failing gate be
# silently ignored (fixed by the explicit `|| die`). The harness then mimics
# the call site's commit: if run_coder reports success, the task file is
# committed. The pytest side asserts on BOTH the exit status and the git
# history: a gate failure must halt the script (die) BEFORE any commit.
#
# Usage: drive-coder.sh <workdir> <task-id> <file> <gate-rc> [budget]
# Optional 5th arg: an explicit SWBP_CODER_EDIT_MAX_OUTPUT value to test the
# budget plumb against the REAL run_coder. When set, the stub llm-call.sh
# records the SWBP_MAX_OUTPUT the shell handed it into <workdir>/envlog and
# the harness echoes it, so pytest can assert the boundary value without
# re-implementing any run_coder logic.
# Stdout on survival: "RC=<rc> COMMITS=<n>"  (die kills the script first on
# a hard halt, so pytest sees a nonzero exit and no RC= line).
set -euo pipefail

WORK="${1:?usage: drive-coder.sh <workdir> <task-id> <file> <gate-rc> [budget]}"
TASK_ID="${2:?task id}"
TASK_FILE="${3:?task file}"
GATE_RC="${4:?gate rc (0=pass, 1=fail)}"
BUDGET="${5:-}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f replies/1 ] || { echo "drive-coder: no replies/1 staged in $WORK" >&2; exit 64; }
mkdir -p scripts/.approved .opencode/prompts prompts
cp "$REPO/scripts/apply-edit-blocks.py" scripts/
cp "$REPO/scripts/check-swallowed-errors.py" scripts/
: > .opencode/prompts/coder.md
[ -f scripts/.approved/contracts.json ] || echo '{}' > scripts/.approved/contracts.json

# Fake coder: replay replies/N in call order; keep each prompt for assertions.
cat > scripts/llm-call.sh <<'STUB'
#!/usr/bin/env bash
n=$(cat .calls 2>/dev/null || echo 0); n=$((n + 1)); printf '%s\n' "$n" > .calls
printf 'SWBP_MAX_OUTPUT=%s\n' "${SWBP_MAX_OUTPUT-<unset>}" >> envlog
cat > "prompts/$n"
cat "replies/$n" 2>/dev/null || printf 'no scripted reply %s\n' "$n"
STUB
chmod +x scripts/llm-call.sh

# Controllable lane gate: the test decides whether it passes or fails.
printf '%s\n' "$GATE_RC" > .gate-rc
cat > scripts/phase-gate.sh <<'STUB'
#!/usr/bin/env bash
rc=$(cat .gate-rc 2>/dev/null || echo 0)
[ "$rc" = "0" ] || echo "GATE FAIL: stubbed lane violation" >&2
exit "$rc"
STUB
chmod +x scripts/phase-gate.sh

# run_coder resolves phase_start from git; the workdir must be a repo.
git init -q .
git -c user.email=selftest@local -c user.name=selftest add -A
git -c user.email=selftest@local -c user.name=selftest commit -qm fixture

# Environment the extracted function expects (mirrors orchestrate.sh's init).
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
LOG_DIR="$STATE_DIR/logs"
APPROVED="scripts/.approved"
AGENT_TIMEOUT=60
FROZEN_V="42"
# Mirrors orchestrate.sh's entry default exactly: unset OR empty means 4096.
SWBP_CODER_EDIT_MAX_OUTPUT="${SWBP_CODER_EDIT_MAX_OUTPUT:-4096}"
mkdir -p "$STATE_DIR" "$TASK_STATE" "$LOG_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
mark() { :; }

# Extract the real functions — repo style is `name() {` and closing `}` both
# at column 0, so the sed range is exact. Fail loudly if the shape changes.
extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-coder: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract build_context)"
eval "$(extract run_coder)"

# The call site, shaped like orchestrate.sh's: run_coder as an if-condition
# (set -e suppressed inside), commit on success — the exact sequence the
# review's blocker #1 broke.
CODER_EVIDENCE=""
if run_coder "$TASK_ID" "$TASK_FILE" "test brief" 1; then
  rc=0
  git add "$TASK_FILE" \
    && git -c user.email=selftest@local -c user.name=selftest \
         commit -qm "[task $TASK_ID] attempt 1" 2>/dev/null || true
else
  rc=1
fi
echo "RC=$rc COMMITS=$(git rev-list --count HEAD) EVIDENCE=${CODER_EVIDENCE:--}"
if [ -n "$BUDGET" ] && [ -f envlog ]; then
  echo "ENVLOG:"
  cat envlog
fi
