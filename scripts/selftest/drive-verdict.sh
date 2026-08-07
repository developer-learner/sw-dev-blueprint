#!/usr/bin/env bash
# drive-verdict.sh — selftest harness for orchestrate.sh's D-112 verdict-scope
# block (the code that decides WHAT runs at milestone completion: the union of
# delta-mapped node-ids by default, the whole frozen suite under --full-suite,
# and nothing when the plan mapped no tests). This block is where the pipeline
# decides "feature done" — its blast radius is the [success] commit — so it
# gets the same drive-*.sh selftest coverage as the D-77 flake triage.
#
# The block is top-level bash, extracted by sentinel-marker sed range. Markers
# live in orchestrate.sh:
#   # BEGIN D-112 verdict scope (drive-verdict.sh extracts this block)
#   ...
#   # END D-112 verdict scope
#
# Pytest side supplies inputs via env; this driver stubs `run_tests` (capturing
# the argv it is called with — the mapped union vs the whole suite vs never)
# and `check_budget`, then prints the resulting state on stdout.
#
# Usage: drive-verdict.sh <workdir>
# Env inputs (all optional):
#   FULL_SUITE_CHECK  1 -> the verdict runs the whole suite (run_tests with no
#                  args); 0 (default) -> the mapped union from tasks/plan.json
#   RT_OUTCOMES    colon-separated queue of stub run_tests TESTS_RC values
#                  (e.g. "0" for a green verdict, "1" for red)
# Workdir inputs:
#   tasks/plan.json  the mapping whose union forms the default verdict scope
#
# Stdout on exit:
#   RT_CALLS=<n>            how many times the stub run_tests was invoked
#   RT_ARGS=<space-joined>  the node-ids a verdict run invoked ("" = the whole
#                           suite, or no run at all)
#   FINAL_TESTS_RC=<n>
set -euo pipefail

WORK="${1:?usage: drive-verdict.sh <workdir>}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f tasks/plan.json ] || { echo "drive-verdict: tasks/plan.json missing in $WORK" >&2; exit 64; }

# Extract the marker-delimited verdict block verbatim; strip the marker lines
# themselves so what remains is executable bash. Fail loudly if the markers
# were renamed (the block moved and the harness never noticed).
BLOCK=$(sed -n '/^# BEGIN D-112 verdict scope/,/^# END D-112 verdict scope/p' \
        "$REPO/scripts/orchestrate.sh" | sed '1d;$d')
printf '%s' "$BLOCK" | grep -q '^check_budget "feature verdict"' \
  || { echo "drive-verdict: could not extract verdict block from orchestrate.sh — did the BEGIN/END markers move?" >&2; exit 65; }

# --- Env inputs (env → shell vars with defaults) ---
FULL_SUITE_CHECK="${FULL_SUITE_CHECK:-0}"
RT_OUTCOMES="${RT_OUTCOMES:-}"

# --- Stubs the block calls out to -------------------------------------
# The real run_tests runs the sandboxed pytest and sets TESTS_RC (0 pass ·
# 1 fail · 3 no verdict). The block cares only about TESTS_RC, but the
# verdict scope is defined by WHICH argv run_tests receives — so the stub
# captures it.
RT_CALLS=0
RT_ARGS=""
_rt_queue="$RT_OUTCOMES"
run_tests() {
  RT_CALLS=$((RT_CALLS + 1))
  RT_ARGS="$*"
  local outcome=""
  if [ -n "$_rt_queue" ]; then
    outcome="${_rt_queue%%:*}"
    case "$_rt_queue" in
      *:*) _rt_queue="${_rt_queue#*:}" ;;
      *)   _rt_queue="" ;;
    esac
  fi
  TESTS_RC="${outcome:-0}"
}

check_budget() { :; }   # between-phase budget gate — irrelevant here
die() { echo "FAIL: $*" >&2; exit 1; }

# --- Execute the extracted block --------------------------------------
eval "$BLOCK"

# --- Report --------------------------------------------------------------
echo "RT_CALLS=$RT_CALLS"
echo "RT_ARGS=$RT_ARGS"
echo "FINAL_TESTS_RC=${TESTS_RC:-0}"
