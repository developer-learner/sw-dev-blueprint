#!/usr/bin/env bash
# orchestrate.sh — drives the build->test loop from an approved PRD.
set -euo pipefail

MAX_ITERS=10
MAX_REPLANS=2
PORT=4567
SERVER_URL="http://127.0.0.1:$PORT"

# Timeout command: use gtimeout on macOS (brew install coreutils),
# timeout on Linux. Fail fast if neither is available.
if command -v gtimeout &>/dev/null; then
  TIMEOUT_CMD="gtimeout"
elif command -v timeout &>/dev/null; then
  TIMEOUT_CMD="timeout"
else
  echo "ERROR: Neither timeout nor gtimeout available. Install coreutils (brew install coreutils) on macOS." >&2
  exit 1
fi

# Timeout for each agent call (seconds). 30 minutes allows complex
# test generation and build iterations.
AGENT_TIMEOUT="${AGENT_TIMEOUT:-1800}"

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

# LLM host address for container — single overridable default, inherited by sandbox-run.sh
: "${SANDBOX_LLM_HOST:=host.containers.internal}"; export SANDBOX_LLM_HOST

# --- Pre-flight ---
echo "=== Pre-flight ==="
python3 --version >/dev/null 2>&1 || { echo "FAIL: python3 required"; exit 1; }
git --version >/dev/null 2>&1    || { echo "FAIL: git required"; exit 1; }
[ -f .gate-paths ]               || { echo "FAIL: .gate-paths not found"; exit 1; }
python3 -c "import json, hashlib" 2>/dev/null || { echo "FAIL: python3 json/hashlib required"; exit 1; }
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

# --- run_agent helper ---
run_agent() {
  local name="$1"
  local prompt="$2"
  echo "--- Agent: $name ---"
  if [ "${SANDBOX:-0}" = "1" ]; then
    scripts/sandbox-run.sh timeout "${AGENT_TIMEOUT}" opencode run \
      --attach "http://${SANDBOX_LLM_HOST}:$PORT" \
      --agent "$name" "$prompt"
  else
    $TIMEOUT_CMD "${AGENT_TIMEOUT}" opencode run \
      --attach "$SERVER_URL" \
      --agent "$name" "$prompt"
  fi
}

# --- Architect ---
echo "=== Phase: Architect ==="
run_agent architect "Produce/refresh the engineering plan from the approved PRD in tasks/CURRENT.md. Write ARCHITECTURE.md and DECISIONS.md. Do not build."
git add docs/ && git commit -m "[plan]" 2>/dev/null || true

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
  run_agent build "Implement src/ per the plan and PRD. Write src/ only. Do not write tests."
  if ! bash scripts/phase-gate.sh build; then
    cat >> tasks/CURRENT.md <<EOF

## Notes / Context

Orchestrator halted: build phase violated INV-2 (touched $test_dir). See phase-gate output.
EOF
    exit 1
  fi
  git add "$build_dir" && git commit -m "[build] iter $iter" 2>/dev/null || true

  # Test
  echo "--- Test ---"
  run_agent test "Write/refresh tests from the PRD acceptance criteria (EARS clauses). One test per clause. Write tests/ only. Do not write src/. Do not read src to decide correctness."
  if ! bash scripts/phase-gate.sh test; then
    cat >> tasks/CURRENT.md <<EOF

## Notes / Context

Orchestrator halted: test phase violated INV-2 (touched $build_dir). See phase-gate output.
EOF
    exit 1
  fi
  git add "$test_dir" && git commit -m "[test] iter $iter" 2>/dev/null || true

  # Install deps in container (ephemeral — build phase install is lost on exit)
  if [ "${SANDBOX:-0}" = "1" ]; then
    scripts/sandbox-run.sh pip install fastapi uvicorn httpx pytest pytest-asyncio 2>&1 || true
  fi

  # Run tests
  echo "--- Running tests ---"
  mkdir -p .cache
  if [ "${SANDBOX:-0}" = "1" ]; then
    scripts/sandbox-run.sh pytest --json-report --json-report-file=.cache/test-report.json 2>/dev/null || true
  else
    pytest --json-report --json-report-file=.cache/test-report.json 2>/dev/null || true
  fi

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
        run_agent architect "These tests keep failing: $failing_info. Revise the plan/approach in ARCHITECTURE.md. Do not edit src or tests."
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
