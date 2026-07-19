#!/usr/bin/env bash
# drive-plan.sh — D-79 selftest harness for orchestrate.sh's ensure_plan.
#
# Exercises the REAL functions (extracted from orchestrate.sh at run time,
# never copied — a copy would silently drift) against a scripted fake EM,
# exactly like drive-consult.sh: the pytest side stages numbered raw replies
# in <workdir>/replies/N, this driver wires a stub llm-call.sh that plays
# them back in call order (recording each prompt in prompts/N), then runs
# ensure_plan against whatever frozen spec the pytest side staged under
# scripts/.approved/ (and src/ tree, for the D-79 audit's registration scan).
#
# The interesting exits:
#   0 — plan validated
#   1 — plan budget exhausted, spec audit PASSED (actor-path halt, die)
#   2 — plan budget exhausted, spec audit FAILED (D-79 SPEC DEFECT ->
#       TPM bundle; finalize_batch's exit code)
# .calls holds the number of EM calls consumed — the D-79 path must not
# burn more than MAX_PLAN_REVISIONS of them.
#
# Usage: drive-plan.sh <workdir>
set -euo pipefail

WORK="${1:?usage: drive-plan.sh <workdir>}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f replies/1 ] || { echo "drive-plan: no replies/1 staged in $WORK" >&2; exit 64; }
mkdir -p scripts/schemas tasks .opencode/prompts prompts
cp "$REPO/scripts/validate-plan.py" scripts/
cp "$REPO/scripts/schemas/plan.schema.json" scripts/schemas/
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
git config user.email selftest@local
git config user.name selftest

# Environment the extracted functions expect (mirrors orchestrate.sh's init).
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
APPROVED="scripts/.approved"
AGENT_TIMEOUT=60
MAX_PLAN_REVISIONS="${MAX_PLAN_REVISIONS:-2}"
SWBP_RUN_BUDGET=0
FROZEN_V=$(cat "$APPROVED/VERSION")
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
mark() { :; }

# Extract the real functions — repo style is `name() {` and closing `}` both
# at column 0, so the sed range is exact (one-liners like plan_revisions_used
# close on the definition line instead). Fail loudly if the shape changes.
extract() {
  local first body
  first=$(grep -m1 "^$1() {" "$REPO/scripts/orchestrate.sh" || true)
  case "$first" in
    *\}) printf '%s\n' "$first"; return 0 ;;
  esac
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-plan: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract build_context)"
eval "$(extract em_call)"
eval "$(extract check_budget)"
eval "$(extract plan_revisions_used)"
eval "$(extract ensure_plan)"
eval "$(extract package_escalation)"
eval "$(extract finalize_batch)"

ensure_plan
echo "CALLS=$(cat .calls 2>/dev/null || echo 0) PLAN=ok"
