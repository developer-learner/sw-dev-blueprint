#!/usr/bin/env bash
# drive-runtime.sh — selftest harness for orchestrate.sh runtime safeguards.
#
# Extracts the real functions from orchestrate.sh at runtime so the harness
# cannot drift from production behavior. Two modes:
#   tests  — exercise run_tests with a stub sandbox runner
#   state  — exercise guard_task_state against a throwaway git history
#
# Usage: drive-runtime.sh <tests|state> <workdir>
set -euo pipefail

MODE="${1:?usage: drive-runtime.sh <tests|state> <workdir>}"
WORK="${2:?workdir required}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"

extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-runtime: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}

die() { echo "FAIL: $*" >&2; exit 1; }

case "$MODE" in
  tests)
    mkdir -p scripts .cache
    cat > scripts/sandbox-run.sh <<'STUB'
#!/usr/bin/env bash
[ -z "${SANDBOX_REPORT_SOURCE:-}" ] \
  || cp "$SANDBOX_REPORT_SOURCE" .cache/test-report.json
exit "${SANDBOX_STUB_RC:-125}"
STUB
    chmod +x scripts/sandbox-run.sh
    mark() { :; }
    eval "$(extract run_tests)"
    run_tests
    echo "FINAL_TESTS_RC=$TESTS_RC"
    echo "FINAL_FAILING=$FAILING"
    ;;
  state)
    STATE_DIR=".pipeline-state"
    TASK_STATE="$STATE_DIR/tasks"
    mkdir -p "$TASK_STATE"
    eval "$(extract guard_task_state)"
    guard_task_state
    echo "STATE_GUARD=pass"
    ;;
  *)
    echo "drive-runtime: unknown mode: $MODE" >&2
    exit 64
    ;;
esac
