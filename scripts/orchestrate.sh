#!/usr/bin/env bash
# orchestrate.sh v2 — walks the EM's task DAG from a frozen TPM spec.
#
# Shell owns ALL procedure (D-05 applied uniformly, D-26): ordering, state,
# completion, escalation counters. LLM tiers only produce artifacts:
#   EM    -> tasks/plan.json (decomposition) and tasks/diagnosis.json (consults)
#   coder -> exactly one file per task, gate-enforced
# Tests are TPM-authored, frozen in scripts/.approved/ + tests/, and RUN by
# this script via pytest --json-report. There is no test-authoring agent.
#
# The TPM is a human-operated web chat: escalations are packaged as batched,
# copy-pasteable bundles under .pipeline-state/escalations/ (D-29), and its
# answers come back as a delta applied by scripts/refreeze.sh (D-31).
#
# Exit codes: 0 feature done (full frozen suite green) · 1 hard failure or
# gate violation · 2 halted awaiting TPM (escalation batch written).
set -euo pipefail

MAX_TASK_STRIKES="${MAX_TASK_STRIKES:-2}"      # coder attempts per brief before EM consult
MAX_BRIEF_REVISIONS="${MAX_BRIEF_REVISIONS:-2}" # EM brief_wrong rewrites per task
MAX_PLAN_REVISIONS="${MAX_PLAN_REVISIONS:-2}"   # EM plan re-emits per run (validation retries + decomposition_wrong)
PORT=4567
AGENT_TIMEOUT="${AGENT_TIMEOUT:-1800}"

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
APPROVED="scripts/.approved"
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

: "${SANDBOX_LLM_HOST:=host.containers.internal}"; export SANDBOX_LLM_HOST

die() { echo "FAIL: $*" >&2; exit 1; }

# --- state helpers (files, not shell vars: crash checkpoint per D-24) ---
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
tstat()       { [ -f "$TASK_STATE/$1.status" ] && cat "$TASK_STATE/$1.status" || echo pending; }
set_tstat()   { printf '%s\n' "$2" > "$TASK_STATE/$1.status"; }
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_counter() { printf '%s\n' "$3" > "$TASK_STATE/$1.$2"; }

# --- Pre-flight ---
echo "=== Pre-flight ==="
python3 --version >/dev/null 2>&1 || die "python3 required"
git --version >/dev/null 2>&1    || die "git required"
[ -f .gate-paths ]               || die ".gate-paths not found"
[ -f scripts/.control-plane-manifest ] || die "scripts/.control-plane-manifest not found"
python3 -c "import json, hashlib" 2>/dev/null || die "python3 json/hashlib required"
if [ "${SANDBOX:-1}" != "1" ]; then
  die "SANDBOX must be 1 (containerized execution is mandatory per AC9)"
fi
# Control-plane + frozen-artifact integrity (phase-gate verifies both, fail-closed)
bash scripts/phase-gate.sh manifest HEAD
# The frozen spec IS the human approval: it only exists via scripts/refreeze.sh,
# which requires an interactive human y/N on the diff (D-31). No honor-string.
[ -f "$APPROVED/frozen-manifest" ] || die "no frozen TPM spec — install PRD/ERD/contracts/tests via scripts/refreeze.sh"
[ -f "$APPROVED/VERSION" ]         || die "$APPROVED/VERSION missing — run scripts/refreeze.sh"
FROZEN_V=$(cat "$APPROVED/VERSION")
echo "OK (frozen spec v$FROZEN_V)"

# --- Parse .gate-paths for the build lane ---
build_dir="src/"
_raw=$(grep '^build=' .gate-paths | cut -d= -f2- || true)
if [ -n "$_raw" ]; then
  _raw="${_raw#./}"; _raw="${_raw%"${_raw##*[![:space:]]}"}"; build_dir="${_raw%/}/"
fi

# --- Re-freeze delta: reset tasks invalidated since the last run (D-31) ---
LAST_V=$(read_state spec_version); LAST_V=${LAST_V:-$FROZEN_V}
if [ "$FROZEN_V" != "$LAST_V" ] && [ -f "$APPROVED/DELTA-v$FROZEN_V.json" ] && [ -f tasks/plan.json ]; then
  echo "=== Frozen spec advanced v$LAST_V -> v$FROZEN_V: resetting affected subtree ==="
  if affected=$(python3 scripts/validate-plan.py --affected "$APPROVED/DELTA-v$FROZEN_V.json" 2>/dev/null); then
    for id in $affected; do
      echo "  reset: $id"
      set_tstat "$id" pending
      rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" 2>/dev/null || true
    done
  else
    echo "  plan stale against v$FROZEN_V — EM will re-derive it"
  fi
  rm -rf "$ESC_DIR"; mkdir -p "$ESC_DIR"   # bundles answered by this delta are consumed
fi
write_state spec_version "$FROZEN_V"

# --- Headless server ---
echo "=== Starting server on port $PORT ==="
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT
opencode serve --port "$PORT" &
SERVER_PID=$!
sleep 2

# --- Agent runners -----------------------------------------------------------
# NOTE: sandbox lane narrowing (repo ro + lane rw) lands with the sandbox flip;
# until then phase-gate is the enforcement backstop after every phase.
run_em() {  # $1 prompt
  local phase_start; phase_start=$(git rev-parse HEAD)
  write_state phase em
  scripts/sandbox-run.sh timeout "$AGENT_TIMEOUT" opencode run \
    --attach "http://${SANDBOX_LLM_HOST}:$PORT" --agent em "$1" \
    2>&1 | tee "$LOG_DIR/em-last.log" || true
  bash scripts/phase-gate.sh em "$phase_start"
  write_state phase ""
}

run_coder() {  # $1 task-id  $2 file  $3 brief  $4 attempt
  local phase_start; phase_start=$(git rev-parse HEAD)
  write_state phase task
  write_state task_target "$2"
  scripts/sandbox-run.sh timeout "$AGENT_TIMEOUT" opencode run \
    --attach "http://${SANDBOX_LLM_HOST}:$PORT" --agent coder "$3" \
    2>&1 | tee "$LOG_DIR/$1-a$4.log" || true
  bash scripts/phase-gate.sh task "$phase_start" "$2"   # violation = hard halt (D-15/D-22)
  write_state phase ""
  write_state task_target ""
}

# run_tests [nodeid...] — full frozen suite when no args.
# Sets TESTS_RC (0 pass · 1 fail · 3 no verdict) and FAILING (ids, |-joined).
run_tests() {
  mkdir -p .cache
  scripts/sandbox-run.sh pytest -p no:cacheprovider --json-report \
    --json-report-file=.cache/test-report.json "$@" >/dev/null 2>&1 || true
  local out
  if out=$(python3 - <<'PYEOF'
import json, sys
try:
    with open(".cache/test-report.json") as f:
        r = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print("NO_REPORT"); sys.exit(3)
tests = r.get("tests", [])
summary = r.get("summary", {})
total = summary.get("total", 0) if isinstance(summary, dict) else 0
collect_errors = r.get("collectors") and any(
    c.get("outcome") == "failed" for c in r.get("collectors", []))
if total == 0 and not collect_errors:
    print("NO_TESTS"); sys.exit(3)
failed = sorted(t["nodeid"] for t in tests
                if t.get("outcome") in ("failed", "error"))
if collect_errors:
    failed.append("COLLECTION_ERROR (see .cache/test-report.json)")
if not failed:
    sys.exit(0)
print("|".join(failed))
sys.exit(1)
PYEOF
  ); then
    TESTS_RC=0; FAILING=""
  else
    TESTS_RC=$?; FAILING="$out"
  fi
}

# --- Plan phase: EM emits/revises, validator gates, bounded retries ----------
plan_revisions_used() { read_state plan_revisions | grep . || echo 0; }

ensure_plan() {
  local verrs revs
  while :; do
    if [ -f tasks/plan.json ] && verrs=$(python3 scripts/validate-plan.py 2>&1); then
      echo "plan ok (v$(python3 -c 'import json;print(json.load(open("tasks/plan.json"))["version"])'))"
      git add tasks/plan.json && git commit -m "[plan] validated against spec v$FROZEN_V" 2>/dev/null || true
      return 0
    fi
    verrs=$(python3 scripts/validate-plan.py 2>&1 || true)
    revs=$(plan_revisions_used)
    [ "$revs" -lt "$MAX_PLAN_REVISIONS" ] || {
      echo "$verrs"
      die "plan invalid after $revs EM revisions — halting for the human (Rule 4)"
    }
    write_state plan_revisions $((revs + 1))
    echo "=== EM: emit/revise plan (revision $((revs + 1))/$MAX_PLAN_REVISIONS) ==="
    run_em "Read scripts/.approved/ERD.md, scripts/.approved/contracts.json, scripts/.approved/test-nodeids, and scripts/schemas/plan.schema.json. Write tasks/plan.json: decompose the ERD into atomic ONE-FILE tasks per the schema. Requirements: exactly one task per file in contracts.json .files; every test node-id in test-nodeids mapped to exactly one task (the task after which it should pass, given its depends_on); every task's contracts list uses ids from contracts.json; every brief self-contained per BLUEPRINT.md Rule 8 (exact path, signatures, inputs/outputs, acceptance); tasks with no covering test need a smoke_check. Set erd_version to $FROZEN_V. NO status fields. ${verrs:+The previous plan failed validation with these errors, fix all of them: $verrs}"
  done
}

# --- EM consult: schema-bound diagnosis (D-29) -------------------------------
# $1 task-id (or DRIFT)  $2 evidence text. Sets DIAG_VERDICT, DIAG_FILE.
consult_em() {
  local id="$1" evidence="$2"
  rm -f tasks/diagnosis.json
  run_em "Task consult. Read tasks/plan.json and scripts/schemas/diagnosis.schema.json. Context: task '$id' — $evidence. Read the frozen spec (scripts/.approved/ERD.md, contracts.json) and the relevant frozen tests under tests/. Decide ONE verdict: brief_wrong (the task brief mis-specified the work — include a full revised_brief, Rule 8 discipline), decomposition_wrong (the task split/dependencies are wrong), or contract_or_test_wrong (the frozen contract or test itself is wrong — your reason becomes the evidence a human carries to the TPM, so be specific: name the contract id or test node-id and what about it is wrong). Write tasks/diagnosis.json ONLY, conforming to the schema."
  # A diagnosis consult must not smuggle in a plan edit
  if ! git diff --quiet -- tasks/plan.json; then
    echo "WARN: EM modified tasks/plan.json during a diagnosis consult — reverting"
    git checkout -- tasks/plan.json
  fi
  [ -f tasks/diagnosis.json ] || die "EM produced no diagnosis for $id — halting (Rule 4)"
  DIAG_VERDICT=$(python3 scripts/validate-plan.py --diagnosis tasks/diagnosis.json) \
    || die "EM diagnosis for $id failed schema validation — halting (Rule 4)"
  DIAG_FILE="$STATE_DIR/diagnosis-$id.json"
  mv tasks/diagnosis.json "$DIAG_FILE"
}

# --- Escalation bundle for the web-chat TPM (D-29) ---------------------------
package_escalation() {  # $1 kind  $2 id  $3 evidence  $4 diagnosis-file
  local kind="$1" id="$2" evidence="$3" diag="$4"
  local dir="$ESC_DIR/$id"
  mkdir -p "$dir"
  [ -f .cache/test-report.json ] && cp .cache/test-report.json "$dir/" || true
  {
    echo "## Escalation: $kind — $id (spec v$FROZEN_V)"
    echo
    if [ "$id" != "DRIFT" ]; then
      echo "### Task entry (tasks/plan.json)"
      echo '```json'
      python3 -c "
import json
plan = json.load(open('tasks/plan.json'))
t = next(t for t in plan['tasks'] if t['id'] == '$id')
print(json.dumps(t, indent=2))"
      echo '```'
      echo
    fi
    echo "### Evidence"
    echo '```'
    echo "$evidence"
    echo '```'
    echo
    echo "### EM diagnosis (schema-validated)"
    echo '```json'
    cat "$diag"
    echo '```'
    echo
    echo "### Frozen artifacts involved"
    python3 - "$id" "$evidence" <<'PYEOF'
import json, sys
from pathlib import Path
tid, evidence = sys.argv[1], sys.argv[2]
# contract entries referenced by the task
try:
    plan = json.load(open("tasks/plan.json"))
    contracts = json.load(open("scripts/.approved/contracts.json"))
    if tid != "DRIFT":
        t = next(t for t in plan["tasks"] if t["id"] == tid)
        refs = set(t["contracts"])
        print("Referenced contract entries:")
        for key in ("routes", "schemas", "errors"):
            for e in contracts.get(key, []):
                if e.get("id") in refs:
                    print("```json"); print(json.dumps(e, indent=2)); print("```")
        for ep in contracts.get("entry_points", []):
            if ep in refs:
                print(f"- entry_point: `{ep}`")
except Exception as e:
    print(f"(could not extract contract entries: {e})")
# failing test sources, capped
files = sorted({part.split("::")[0] for part in evidence.split("|")
                if part.strip().startswith("tests/")})
for f in files:
    p = Path(f)
    if p.exists():
        lines = p.read_text().splitlines()[:200]
        print(f"\nFrozen test source `{f}`:")
        print("```python"); print("\n".join(lines)); print("```")
PYEOF
    echo
  } > "$dir/bundle.md"
  echo "escalation packaged: $dir/bundle.md"
}

finalize_batch() {  # writes the single copy-pasteable batch and halts
  local batch="$ESC_DIR/BATCH.md"
  local n
  n=$(find "$ESC_DIR" -name bundle.md | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] || return 0
  {
    echo "# TPM escalation batch — $n item(s) — spec v$FROZEN_V"
    echo
    echo "> Operator: paste everything below this line into the TPM web chat in one message."
    echo "> The TPM must reply with a DELTA: the full new content of ONLY the changed"
    echo "> frozen files (contracts.json and/or files under tests/, plus ERD.md/PRD.md if"
    echo "> affected). Save the reply files under scripts/.approved/incoming/ preserving"
    echo "> paths (tests go in scripts/.approved/incoming/tests/), then run:"
    echo ">     scripts/refreeze.sh scripts/.approved/incoming"
    echo "> and re-run scripts/orchestrate.sh. Only the affected subtree resumes."
    echo
    echo "---"
    find "$ESC_DIR" -name bundle.md | sort | while read -r b; do
      cat "$b"; echo; echo "---"
    done
  } > "$batch"
  echo ""
  echo "=========================================="
  echo "  HALT: $n escalation(s) need the TPM"
  echo "  -> $batch"
  echo "=========================================="
  exit 2
}

# ==============================================================================
echo "=== Phase: plan ==="
ensure_plan

echo "=== Phase: task DAG ==="
while :; do
  TOPO=$(python3 scripts/validate-plan.py --topo) || die "plan invalidated mid-run"

  # fingerprint check: plan entries changed since a task completed -> redo it
  for id in $TOPO; do
    if [ "$(tstat "$id")" = "done" ]; then
      fp_now=$(python3 scripts/validate-plan.py --task "$id" --field fingerprint)
      fp_then=$(cat "$TASK_STATE/$id.fp" 2>/dev/null || true)
      if [ "$fp_now" != "$fp_then" ]; then
        echo "task $id changed in plan — resetting"
        set_tstat "$id" pending
        rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" 2>/dev/null || true
      fi
    fi
  done

  # pick the first actionable task (pending, all deps done)
  NEXT=""
  for id in $TOPO; do
    [ "$(tstat "$id")" = "pending" ] || continue
    deps_ok=1
    for d in $(python3 scripts/validate-plan.py --task "$id" --field depends_on); do
      case "$(tstat "$d")" in
        done) ;;
        escalated|blocked) set_tstat "$id" blocked; deps_ok=0; break ;;
        *) deps_ok=0; break ;;
      esac
    done
    [ "$(tstat "$id")" = "blocked" ] && continue
    [ "$deps_ok" = "1" ] && { NEXT="$id"; break; }
  done
  [ -n "$NEXT" ] || break

  id="$NEXT"
  file=$(python3 scripts/validate-plan.py --task "$id" --field file)
  mapped=$(python3 scripts/validate-plan.py --task "$id" --field tests)
  smoke=$(python3 scripts/validate-plan.py --task "$id" --field smoke_check)
  brief=$(cat "$BRIEF_DIR/$id" 2>/dev/null || python3 scripts/validate-plan.py --task "$id" --field brief)
  strikes=$(counter "$id" strikes)
  echo "--- Task $id -> $file (strike $((strikes + 1))/$MAX_TASK_STRIKES) ---"

  attempt_brief="$brief

Write EXACTLY one file: $file — the gate rejects any other change, including new files. Before finishing, re-open $file and confirm it satisfies every acceptance condition in this brief."
  last_fail=$(cat "$TASK_STATE/$id.lastfail" 2>/dev/null || true)
  [ -n "$last_fail" ] && attempt_brief="$attempt_brief

The previous attempt failed with: $last_fail. Fix the cause, do not just retry the same content."

  run_coder "$id" "$file" "$attempt_brief" "$((strikes + 1))"
  git add "$file" && git commit -m "[task $id] attempt $((strikes + 1))" 2>/dev/null || true

  # acceptance = projection of the frozen oracle (D-28) + optional smoke
  pass=1
  if [ -n "$mapped" ]; then
    # shellcheck disable=SC2086
    run_tests $mapped
    [ "$TESTS_RC" -eq 0 ] || { pass=0; }
    evidence="mapped tests failing: ${FAILING:-no verdict (rc=$TESTS_RC)}"
  else
    evidence=""
  fi
  if [ "$pass" = "1" ] && [ -n "$smoke" ]; then
    if ! scripts/sandbox-run.sh sh -c "$smoke" >/dev/null 2>&1; then
      pass=0; evidence="smoke_check failed: $smoke"
    fi
  fi

  if [ "$pass" = "1" ]; then
    echo "task $id: PASS"
    set_tstat "$id" done
    python3 scripts/validate-plan.py --task "$id" --field fingerprint > "$TASK_STATE/$id.fp"
    rm -f "$TASK_STATE/$id.lastfail"
    continue
  fi

  echo "task $id: FAIL — $evidence"
  printf '%s\n' "$evidence" > "$TASK_STATE/$id.lastfail"
  strikes=$((strikes + 1))
  set_counter "$id" strikes "$strikes"
  [ "$strikes" -lt "$MAX_TASK_STRIKES" ] && continue   # plain retry with failure appended

  # two strikes -> EM consult, route on schema-bound verdict (D-29)
  echo "=== Task $id failed $strikes times -> EM consult ==="
  consult_em "$id" "failed $strikes attempts on $file. $evidence. Coder log tail: $(tail -5 "$LOG_DIR/$id-a$strikes.log" 2>/dev/null | tr '\n' ' ')"
  case "$DIAG_VERDICT" in
    brief_wrong)
      revs=$(counter "$id" revisions)
      if [ "$revs" -ge "$MAX_BRIEF_REVISIONS" ]; then
        echo "brief revisions exhausted for $id -> escalate to TPM"
        package_escalation "caps-exhausted" "$id" "$evidence" "$DIAG_FILE"
        set_tstat "$id" escalated
      else
        set_counter "$id" revisions $((revs + 1))
        python3 -c "
import json, sys
d = json.load(open('$DIAG_FILE'))
sys.stdout.write(d['revised_brief'])" > "$BRIEF_DIR/$id"
        set_counter "$id" strikes 0
        rm -f "$TASK_STATE/$id.lastfail"
        echo "brief revised for $id (revision $((revs + 1))/$MAX_BRIEF_REVISIONS)"
      fi
      ;;
    decomposition_wrong)
      revs=$(plan_revisions_used)
      if [ "$revs" -ge "$MAX_PLAN_REVISIONS" ]; then
        echo "plan revisions exhausted -> escalate to TPM"
        package_escalation "caps-exhausted" "$id" "$evidence" "$DIAG_FILE"
        set_tstat "$id" escalated
      else
        write_state plan_revisions $((revs + 1))
        echo "=== EM: revise decomposition (revision $((revs + 1))/$MAX_PLAN_REVISIONS) ==="
        run_em "The decomposition is wrong around task $id: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite tasks/plan.json fixing it (schema: scripts/schemas/plan.schema.json; same requirements as before: one file per task, every test node-id mapped exactly once, erd_version $FROZEN_V, bump plan version, NO status fields). Keep entries for unrelated tasks byte-identical — completed work is preserved only where entries are unchanged."
        ensure_plan
        set_counter "$id" strikes 0
        rm -f "$TASK_STATE/$id.lastfail"
      fi
      ;;
    contract_or_test_wrong)
      package_escalation "spec-wrong" "$id" "$evidence" "$DIAG_FILE"
      set_tstat "$id" escalated
      ;;
  esac
done

# --- batch halt if anything escalated (batching goal: one operator round-trip) ---
finalize_batch

# --- all tasks done -> feature verdict is the FULL frozen suite (D-28) -------
echo "=== Full frozen suite ==="
run_tests
if [ "$TESTS_RC" -eq 0 ]; then
  echo ""
  echo "=========================================="
  echo "  ALL FROZEN TESTS PASS — feature done"
  echo "=========================================="
  cat >> tasks/CURRENT.md <<EOF

## Results

Full frozen TPM suite green against spec v$FROZEN_V. Feature built and validated.
EOF
  rm -rf "$STATE_DIR"
  git add tasks/CURRENT.md && git commit -m "[success] spec v$FROZEN_V" 2>/dev/null || true
  exit 0
fi

# tasks green but suite red = SPEC DRIFT: routes EM -> TPM, never coder retries (D-28)
echo "=== SPEC DRIFT: every task passed its projection but the full suite is red ==="
drift_evidence="all tasks done and individually green; full suite failing: ${FAILING:-no verdict (rc=$TESTS_RC)}"
consult_em "DRIFT" "$drift_evidence"
if [ "$DIAG_VERDICT" = "decomposition_wrong" ] && [ "$(plan_revisions_used)" -lt "$MAX_PLAN_REVISIONS" ]; then
  write_state plan_revisions $(( $(plan_revisions_used) + 1 ))
  run_em "Spec drift: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite tasks/plan.json to fix the decomposition (same schema and requirements; keep unrelated entries byte-identical)."
  ensure_plan
  echo "plan revised for drift — re-run scripts/orchestrate.sh to resume"
  exit 1
fi
package_escalation "spec-drift" "DRIFT" "$drift_evidence" "$DIAG_FILE"
finalize_batch
