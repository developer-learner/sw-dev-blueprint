#!/usr/bin/env bash
# orchestrate.sh — drives the build->test loop from an approved PRD.
set -euo pipefail

MAX_ITERS=10
MAX_REPLANS=2
PORT=4567
SERVER_URL="http://127.0.0.1:$PORT"

# Timeout for each agent call (seconds). 30 minutes allows complex
# test generation and build iterations.
# Container timeout is managed by sandbox-run.sh --timeout; the script-level
# AGENT_TIMEOUT is inherited but no longer used at this level (sandbox is
# mandatory per AC9, so sandbox-run.sh handles all timeout enforcement).
AGENT_TIMEOUT="${AGENT_TIMEOUT:-1800}"

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

# --- Pipeline state directory ---
STATE_DIR=".pipeline-state"
mkdir -p "$STATE_DIR"

# LLM host address for container — single overridable default, inherited by sandbox-run.sh
: "${SANDBOX_LLM_HOST:=host.containers.internal}"; export SANDBOX_LLM_HOST

# --- Pre-flight ---
echo "=== Pre-flight ==="
python3 --version >/dev/null 2>&1 || { echo "FAIL: python3 required"; exit 1; }
git --version >/dev/null 2>&1    || { echo "FAIL: git required"; exit 1; }
[ -f .gate-paths ]               || { echo "FAIL: .gate-paths not found"; exit 1; }
[ -f scripts/.control-plane-manifest ] || { echo "FAIL: scripts/.control-plane-manifest not found"; exit 1; }
python3 -c "import json, hashlib" 2>/dev/null || { echo "FAIL: python3 json/hashlib required"; exit 1; }
if [ "${SANDBOX:-1}" != "1" ]; then
  echo "FAIL: SANDBOX must be 1 (containerized execution is mandatory per AC9)"
  exit 1
fi
echo "OK"

# --- Parse .gate-paths for scoped git adds ---
build_dir="src/"
test_dir="tests/"
if [ -f .gate-paths ]; then
  _raw=$(grep '^build=' .gate-paths | cut -d= -f2- || true)
  if [ -n "$_raw" ]; then
    _raw="${_raw#./}"; _raw="${_raw%"${_raw##*[![:space:]]}"}"; build_dir="${_raw%/}/"
  fi
  _raw=$(grep '^test=' .gate-paths | cut -d= -f2- || true)
  if [ -n "$_raw" ]; then
    _raw="${_raw#./}"; _raw="${_raw%"${_raw##*[![:space:]]}"}"; test_dir="${_raw%/}/"
  fi
fi

# --- Gate on approval ---
echo "=== Checking PRD approval ==="
if ! grep -qE '^\*\*Status:\*\* *Approved *$' tasks/CURRENT.md; then
  echo "FAIL: PRD not approved (Status must be exactly 'Approved')"
  exit 1
fi
echo "OK"

# --- Start headless server ---
echo "=== Starting server on port $PORT ==="
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT
opencode serve --port "$PORT" &
SERVER_PID=$!
sleep 2
echo "Server running at $SERVER_URL"

# --- Phase-start wrapper: records ref before agent runs ---
run_phase() {
  local name="$1"
  local prompt="$2"
  local gate_arg="$3"  # build|test|architect
  shift 3
  local phase_start
  phase_start=$(git rev-parse HEAD)
  echo "--- Agent: $name (phase-start=$phase_start) ---"
  if [ "${SANDBOX:-1}" != "1" ]; then
    echo "FAIL: SANDBOX must be 1 (containerized execution is mandatory per AC9)"
    exit 1
  fi
  scripts/sandbox-run.sh timeout "${AGENT_TIMEOUT}" opencode run \
    --attach "http://${SANDBOX_LLM_HOST}:$PORT" \
    --agent "$name" "$prompt"
  bash scripts/phase-gate.sh "$gate_arg" "$phase_start"
}

# --- State persistence: read/write loop state ---
read_state() {
  local file="$STATE_DIR/$1"
  if [ -f "$file" ]; then cat "$file"; fi
}
write_state() {
  local key="$1" value="$2"
  printf '%s\n' "$value" > "$STATE_DIR/$key"
}
write_state_full() {
  # Write all loop variables at once — called before each run_phase.
  # This is the crash checkpoint: if the orchestrator dies after this
  # write, the next invocation can resume from this state.
  write_state "iteration" "$iter"
  write_state "replans_used" "$replans"
  write_state "last_failure_sig" "${last_sig:-}"
  write_state "repeat_count" "${repeat:-0}"
  write_state "failing_info" "${failing_info:-}"
  write_state "phase" "$1"
}

# --- Architect ---
echo "=== Phase: Architect ==="
run_phase architect "Produce/refresh the engineering plan from the approved PRD in tasks/CURRENT.md. Write ARCHITECTURE.md and DECISIONS.md. Do not build." architect
git add docs/ && git commit -m "[plan]" 2>/dev/null || true

# Freeze the API contract — test agent reads this, not the live ARCHITECTURE.md
# Lives in scripts/.approved/ (outside every agent's writable lane) so no re-plan
# architect can overwrite the tester's frozen oracle.
mkdir -p scripts/.approved
cp docs/ARCHITECTURE.md scripts/.approved/ARCHITECTURE.approved.md 2>/dev/null || true
git add scripts/.approved/ARCHITECTURE.approved.md && git commit -m "[contract] frozen at approval" 2>/dev/null || true

# --- Build/test loop ---
iter=0
replans=0
last_sig=""
repeat=0
failing_info=""

# --- Resume from state if this is a restart ---
iter=$(read_state "iteration" || echo 0); iter=${iter:-0}
replans=$(read_state "replans_used" || echo 0); replans=${replans:-0}
last_sig=$(read_state "last_failure_sig" || true)
repeat=$(read_state "repeat_count" || echo 0); repeat=${repeat:-0}

while [ "$iter" -lt "$MAX_ITERS" ]; do
  iter=$((iter + 1))
  echo "=== Iteration $iter/$MAX_ITERS ==="

  # Build
  echo "--- Build ---"
  write_state_full "build"
  run_phase build "Implement src/ per the plan and PRD. Write src/ only. Do not write tests." build
  git add "$build_dir" && git commit -m "[build] iter $iter" 2>/dev/null || true

  # Test
  echo "--- Test ---"
  write_state_full "test"
  run_phase test "Write/refresh tests from the PRD acceptance criteria (EARS clauses). One test per clause. Write tests/ only. Do not write src/. Do not read src to decide correctness." test
  git add "$test_dir" && git commit -m "[test] iter $iter" 2>/dev/null || true

  # Install deps in container (ephemeral — build phase install is lost on exit)
  if [ "${SANDBOX:-1}" != "1" ]; then
    echo "FAIL: SANDBOX must be 1 (containerized execution is mandatory per AC9)"
    exit 1
  fi
  if [ -f requirements.txt ]; then
    scripts/sandbox-run.sh pip install -r requirements.txt 2>&1 || true
  fi

  # Run tests
  echo "--- Running tests ---"
  mkdir -p .cache
  scripts/sandbox-run.sh pytest --json-report --json-report-file=.cache/test-report.json 2>/dev/null || true

  # Parse JSON report: exit 0 = all pass, exit 1 = failures, exit 2 = no file, exit 3 = no/malformed tests
  if result=$(python3 -c '
import json, hashlib, sys
try:
    with open(".cache/test-report.json") as f:
        r = json.load(f)
except FileNotFoundError:
    print("no report found"); sys.exit(2)
except json.JSONDecodeError:
    print("malformed report"); sys.exit(3)
tests = r.get("tests", [])
summary = r.get("summary", {})
total = summary.get("total", 0) if isinstance(summary, dict) else 0
if total == 0 or not tests:
    print("NO_TESTS"); sys.exit(3)
failed = sorted(t["nodeid"] for t in tests if t.get("outcome") in ("failed", "error"))
if not failed:
    sys.exit(0)
sig = hashlib.sha1("|".join(failed).encode()).hexdigest()
print(f"SIG:{sig}")
for n in failed:
    print(n)
' 2>&1); then
    # SUCCESS
    echo ""
    echo "=========================================="
    echo "  ALL TESTS PASS"
    echo "=========================================="
    cat >> tasks/CURRENT.md <<EOF

## Results

All tests pass. Feature built and validated in $iter iteration(s).
EOF
    rm -rf "$STATE_DIR"
    git add tasks/CURRENT.md && git commit -m "[success]" 2>/dev/null || true
    exit 0
  else
    _rc=$?
    if [ "$_rc" -eq 2 ]; then
      echo "WARN: no test report"
      sig=""
    elif [ "$_rc" -eq 3 ]; then
      echo "FAIL: test phase produced no verdict"
      cat >> tasks/CURRENT.md <<EOF

## Notes / Context

Orchestrator halted: test phase produced no passing-or-failing signal.
The loop cannot proceed without a verdict — inspect the tester,
the acceptance criteria (EARS mapping), and test collection.
EOF
      exit 1
    else
      sig=$(echo "$result" | grep '^SIG:' | head -1 | cut -d: -f2-) || true
      failing_info=$(echo "$result" | grep -v '^SIG:' | grep -v '^$' | head -20 | paste -sd ' | ' -) || true
      echo "Failing: $failing_info"

      # Two-strike: identical failing set twice in a row?
      if [ "$sig" = "$last_sig" ]; then
        repeat=$((repeat + 1))
      else
        repeat=1
        last_sig="$sig"
      fi

      if [ "$repeat" -ge 2 ]; then
        replans=$((replans + 1))
        echo "=== Same failure twice -> re-plan ($replans/$MAX_REPLANS) ==="
        if [ "$replans" -gt "$MAX_REPLANS" ]; then
          echo "MAX_REPLANS exceeded."
          cat >> tasks/CURRENT.md <<EOF

## Notes / Context

Orchestrator halted after $replans re-plans. Tests keep failing:
$failing_info
The PRD may be ambiguous or the approach needs rethinking (Rule 4).
EOF
          exit 1
        fi
         run_phase architect "These tests keep failing: $failing_info. Revise the plan/approach in ARCHITECTURE.md. Do not edit src or tests." architect
        git add docs/ && git commit -m "[replan] attempt $replans" 2>/dev/null || true
        repeat=0
      fi
    fi
  fi
done

# MAX_ITERS exhausted without success
echo ""
echo "=========================================="
echo "  HALT: MAX_ITERS ($MAX_ITERS) reached"
echo "=========================================="
cat >> tasks/CURRENT.md <<EOF

## Notes / Context

Orchestrator halted after $iter iterations without passing all tests.
Last failing tests: $failing_info
EOF
exit 1
