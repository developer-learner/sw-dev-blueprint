#!/usr/bin/env bash
# drive-plan-live.sh — live-EM twin of drive-plan.sh for the A''' milestone-
# run differential: trimmed vs full EM plan context against one real,
# changed-bearing milestone (v84 by default), with a real model through the
# pipeline's OWN llm-call.sh. Not a hand-rolled prompt copy anywhere.
#
# Identical anti-drift machinery to drive-plan.sh — extracts the REAL
# ensure_plan / em_call / build_context / D-113 block from orchestrate.sh at
# run time — the only difference from the selftest driver is that the
# llm-call.sh stub is replaced by the repo's real script (D-53 model mapping
# from ~/.config/sw-dev-blueprint/models.env), so each arm spends exactly one
# real EM call.
#
#   ARM=full     pre-trim context  — STANDING_SUMMARY/CONTRACTS_DELTA unset,
#                 ACTIVE_DELTA_FILES unset, so build_context ships the whole
#                 ERD.md / contracts.json / test-nodeids.
#   ARM=trimmed  current context   — the D-113 block stages the active delta
#                 range (union of changed_tests => nodeids-scope.txt) and the
#                 two generators slice standing/contracts context.
#
# Usage: drive-plan-live.sh <workdir> <full|trimmed>
# The workdir must already hold scripts/.approved/{ERD.md,ERD-DELTA.md,
# contracts.json,test-nodeids,VERSION} (DELTA-vN*.json optional; present
# only for the trimmed arm's range). One EM call per run by design.
set -euo pipefail

WORK="${1:?usage: drive-plan-live.sh <workdir> <full|trimmed>}"
ARM="${2:?usage: drive-plan-live.sh <workdir> <full|trimmed>}"
case "$ARM" in full|trimmed) ;; *) echo "drive-plan-live: ARM must be full or trimmed" >&2; exit 64 ;; esac
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f scripts/.approved/VERSION ] || { echo "drive-plan-live: no scripts/.approved/VERSION in $WORK" >&2; exit 64; }
mkdir -p scripts/schemas tasks .opencode/prompts prompts
cp "$REPO/scripts/validate-plan.py" scripts/
cp "$REPO/scripts/schemas/plan.schema.json" scripts/schemas/
cp "$REPO/scripts/standing-summary.py" scripts/
cp "$REPO/scripts/contracts-delta.py" scripts/
# The real EM brief and the real llm-call transport — no stub, no fake.
cp "$REPO/.opencode/prompts/em.md" .opencode/prompts/em.md
cp "$REPO/.opencode/prompts/em-plan.md" .opencode/prompts/em-plan.md
cp "$REPO/scripts/llm-call.sh" scripts/llm-call.sh
chmod +x scripts/llm-call.sh

# Lane/integrity gate is out of scope for the differential; stub green.
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
AGENT_TIMEOUT=900
MAX_PLAN_REVISIONS=1
SWBP_RUN_BUDGET=0
FROZEN_V=$(cat "$APPROVED/VERSION")
# Anti-drift mirrors, same rule as drive-plan.sh.
EM_TASK_KEYS=$(sed -n "s/^EM_TASK_KEYS='\(.*\)'$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$EM_TASK_KEYS" ] || { echo "drive-plan-live: could not extract EM_TASK_KEYS" >&2; exit 65; }
EM_CONTRACT_ID_RULE=$(sed -n "s/^EM_CONTRACT_ID_RULE='\(.*\)'$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$EM_CONTRACT_ID_RULE" ] || { echo "drive-plan-live: could not extract EM_CONTRACT_ID_RULE" >&2; exit 65; }
MEAS_BODY=$(sed -n "s/^meas() { \(.*\) }$/\1/p" "$REPO/scripts/orchestrate.sh")
[ -n "$MEAS_BODY" ] || { echo "drive-plan-live: could not extract meas()" >&2; exit 65; }
meas() { eval "$MEAS_BODY"; }
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
mark() { :; }

# D-113 active-delta range + the two generators — the trimmed arm's wiring.
# The full arm leaves the fallback paths in build_context active.
if [ "$ARM" = "trimmed" ]; then
  _D113_BLOCK=$(sed -n '/^# BEGIN D-113 active-delta range/,/^# END D-113 active-delta range/p' "$REPO/scripts/orchestrate.sh")
  [ -n "$_D113_BLOCK" ] || { echo "drive-plan-live: could not extract the D-113 block" >&2; exit 77; }
  DELTA_BASELINE_V=${DELTA_BASELINE_V:-$(read_state delta_baseline_spec)}
  DELTA_BASELINE_V=${DELTA_BASELINE_V:-$FROZEN_V}
  eval "$_D113_BLOCK"
  STANDING_SUMMARY="$STATE_DIR/standing-summary.md"
  CONTRACTS_DELTA="$STATE_DIR/contracts-delta.json"
  python3 scripts/standing-summary.py "$APPROVED/ERD.md" > "$STANDING_SUMMARY" \
    || STANDING_SUMMARY="$APPROVED/ERD.md"
  python3 scripts/contracts-delta.py "$APPROVED/contracts.json" > "$CONTRACTS_DELTA" \
    || CONTRACTS_DELTA="$APPROVED/contracts.json"
fi

extract() {
  local first body
  first=$(grep -m1 "^$1() {" "$REPO/scripts/orchestrate.sh" || true)
  case "$first" in
    *\}) printf '%s\n' "$first"; return 0 ;;
  esac
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-plan-live: could not extract $1()" >&2; exit 77; }
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
echo "ARM=$ARM PLAN=ok"
