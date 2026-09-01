#!/usr/bin/env bash
# drive-plan.sh — selftest harness for orchestrate.sh's ensure_plan
# (D-79 spec-defect rung + the Fix A subtree re-plan path).
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
: > .opencode/prompts/em-plan.md

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
PLANE_DIR=$(pwd -P)
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
MEAS_DIR=".measurement"
APPROVED="scripts/.approved"
AGENT_TIMEOUT=60
MAX_PLAN_REVISIONS="${MAX_PLAN_REVISIONS:-2}"
SWBP_RUN_BUDGET=0
FROZEN_V=$(cat "$APPROVED/VERSION")
# T7 M1 (D-174): ensure_plan's [plan] commit routes through the broker —
# source the REAL one (anti-drift, same rule as the function extract() above).
source "$REPO/scripts/git-provenance.sh"
# Wave 1: ensure_plan's extracted prompt references EM_TASK_KEYS (defined in
# orchestrate.sh's init, not exported) — mirror it by extraction, same
# anti-drift rule as the function extract() above. Fail loudly if the
# assignment shape changes.
EM_TASK_KEYS=$(sed -n "s/^EM_TASK_KEYS='\(.*\)'$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$EM_TASK_KEYS" ] || { echo "drive-plan: could not extract EM_TASK_KEYS from orchestrate.sh" >&2; exit 65; }
# Phase 3: same anti-drift mirror for the contract-id rule and the id-list
# helper (both are interpolated into ensure_plan's prompts at runtime).
EM_CONTRACT_ID_RULE=$(sed -n "s/^EM_CONTRACT_ID_RULE='\(.*\)'$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$EM_CONTRACT_ID_RULE" ] || { echo "drive-plan: could not extract EM_CONTRACT_ID_RULE from orchestrate.sh" >&2; exit 65; }
# Phase 5 instrumentation: same anti-drift mirror for meas() (ensure_plan
# calls it; the body is a one-liner defined in orchestrate's init, so it is
# not covered by the function extract() above). The shape check fails loudly
# if meas stops being a one-liner of this form.
MEAS_BODY=$(sed -n "s/^meas() { \(.*\) }$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$MEAS_BODY" ] || { echo "drive-plan: could not extract meas() from orchestrate.sh" >&2; exit 65; }
meas() { eval "$MEAS_BODY"; }
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
mark() { :; }

# D-124: ensure_plan now scopes the full-emission test-nodeids context to the
# active delta range (union of changed_tests). Production computes
# ACTIVE_DELTA_FILES at top level; mirror that block by extraction so drive
# tests exercise the scope, not just the because-net fallback. Fail loudly on
# marker/block drift (same anti-drift rule as the function extract()).
_D113_BLOCK=$(sed -n '/^# BEGIN D-113 active-delta range/,/^# END D-113 active-delta range/p' "$REPO/scripts/orchestrate.sh")
[ -n "$_D113_BLOCK" ] || { echo "drive-plan: could not extract the D-113 active-delta block from orchestrate.sh" >&2; exit 65; }
DELTA_BASELINE_V=${DELTA_BASELINE_V:-$(read_state delta_baseline_spec)}
DELTA_BASELINE_V=${DELTA_BASELINE_V:-$FROZEN_V}
eval "$_D113_BLOCK"

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
eval "$(extract contract_ids)"
eval "$(extract plan_revisions_used)"
eval "$(extract plan_subtree_prepare)"
eval "$(extract ensure_plan)"
eval "$(extract package_escalation)"
eval "$(extract finalize_batch)"

ensure_plan
echo "CALLS=$(cat .calls 2>/dev/null || echo 0) PLAN=ok"
