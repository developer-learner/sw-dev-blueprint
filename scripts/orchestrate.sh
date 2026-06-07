#!/usr/bin/env bash
# orchestrate.sh — drives the build->test loop from an approved PRD.
set -euo pipefail

MAX_ITERS=10
MAX_REPLANS=2
PORT=4567
SERVER_URL="http://127.0.0.1:$PORT"

cd "$(cd "$(dirname "$0")/.." && pwd)"

# --- Pre-flight ---
echo "=== Pre-flight ==="
python3 --version >/dev/null 2>&1 || { echo "FAIL: python3 required"; exit 1; }
git --version >/dev/null 2>&1    || { echo "FAIL: git required"; exit 1; }
[ -f .gate-paths ]               || { echo "FAIL: .gate-paths not found"; exit 1; }
python3 -c "import json, hashlib" 2>/dev/null || { echo "FAIL: python3 json/hashlib required"; exit 1; }
echo "OK"

# --- Gate on approval ---
echo "=== Checking PRD approval ==="
if ! grep -q '^\*\*Status:\*\*.*Approved' tasks/CURRENT.md; then
  echo "FAIL: PRD not approved (Status != Approved in tasks/CURRENT.md)"
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

# --- run_agent helper ---
run_agent() {
  local name="$1"
  local prompt="$2"
  echo "--- Agent: $name ---"
  opencode run --attach "$SERVER_URL" --agent "$name" "$prompt"
}

# --- Architect ---
echo "=== Phase: Architect ==="
run_agent architect "Produce/refresh the engineering plan from the approved PRD in tasks/CURRENT.md. Write ARCHITECTURE.md and DECISIONS.md. Do not build."
git add -A && git commit -m "[plan]" 2>/dev/null || true

# --- Build/test loop ---
iter=0
replans=0
last_sig=""
repeat=0
failing_info=""

while [ "$iter" -lt "$MAX_ITERS" ]; do
  iter=$((iter + 1))
  echo "=== Iteration $iter/$MAX_ITERS ==="

  # Build
  echo "--- Build ---"
  run_agent build "Implement per the plan. Failing tests to fix: $failing_info"
  bash scripts/phase-gate.sh build
  git add -A && git commit -m "[build] iter $iter" 2>/dev/null || true

  # Test
  echo "--- Test ---"
  run_agent test "Write/refresh tests from the PRD acceptance criteria (EARS clauses). One test per clause. Do not read src to decide correctness."
  bash scripts/phase-gate.sh test
  git add -A && git commit -m "[test] iter $iter" 2>/dev/null || true

  # Run tests
  echo "--- Running tests ---"
  mkdir -p .cache
  pytest --json-report --json-report-file=.cache/test-report.json 2>/dev/null || true

  # Parse JSON report: exit 0 = all pass, exit 1 = failures, exit 2 = no report
  if result=$(python3 -c '
import json, hashlib, sys
try:
    with open(".cache/test-report.json") as f:
        r = json.load(f)
except FileNotFoundError:
    print("no report found")
    sys.exit(2)
tests = r.get("tests", [])
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
    git add -A && git commit -m "[success]" 2>/dev/null || true
    exit 0
  else
    _rc=$?
    if [ "$_rc" -eq 2 ]; then
      echo "WARN: no test report — no tests written yet"
      sig=""
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
        run_agent architect "These tests keep failing: $failing_info. Revise the plan/approach in ARCHITECTURE.md. Do not edit src or tests."
        git add -A && git commit -m "[replan] attempt $replans" 2>/dev/null || true
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
