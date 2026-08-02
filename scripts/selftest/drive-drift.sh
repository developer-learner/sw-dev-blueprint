#!/usr/bin/env bash
# drive-drift.sh — selftest harness for orchestrate.sh's D-77 flake-triage
# block (the code that may convert a red full-suite run into flake-green +
# [success] when every failure is carried-forward AND each failing node
# passes at least one isolation run). That block has the highest blast radius
# in orchestrate.sh — the
# ONLY code that flips a failing frozen suite to `exit 0` + `[success]`
# commit + `rm -rf` of state — and per Rule 9 (D-81, gate strength ∝
# blast radius) it needs the same drive-*.sh selftest coverage the lower-
# consequence rungs already have (D-71 consult / D-79 spec-defect /
# run_coder gate propagation).
#
# The block is top-level bash (not a function), so extraction is by
# sentinel-marker sed range instead of the `name() { ... }` heuristic the
# other drives use. Markers live in orchestrate.sh:
#   # BEGIN D-77 flake triage (drive-drift.sh extracts this block)
#   ...
#   # END D-77 flake triage
#
# Pytest side supplies the block's inputs via env; this driver stubs the
# two things the block calls out to (`run_tests` and `run_elapsed`) and
# prints the resulting state on stdout. The stubbed `run_tests` reads a
# scripted colon-separated queue of TESTS_RC values from RT_OUTCOMES —
# and it clobbers FAILING/FAIL_DETAIL the same way the real one does, so
# the save-and-restore dance around the isolation loop is under test too.
#
# Usage: drive-drift.sh <workdir>
# Env inputs (all optional; sensible defaults for the guarded-out cases):
#   TESTS_RC       initial TESTS_RC (usually "1" to enter the flake block)
#   FAILING        pipe-separated failing node-ids ("" or COLLECTION_ERROR
#                  → block guard trips, no isolation runs)
#   FAIL_DETAIL    initial FAIL_DETAIL string (survival under isolation
#                  clobber is a pinned behavior)
#   RT_OUTCOMES    colon-separated queue of stub run_tests TESTS_RC values
#                  (e.g. "0:0" for two isolation passes; "1:1" for two
#                  isolation failures; empty when the block should never
#                  reach the isolation loop)
#   SWBP_ELAPSED   value the stubbed run_elapsed returns (for the
#                  fbfc1f0 budget-skip path)
#   SWBP_RUN_BUDGET  budget the block compares SWBP_ELAPSED against
#   SWBP_FLAKE_ESCALATION_THRESHOLD  accepted occurrence that closes the
#                  bypass (default 3)
#   FROZEN_V       current frozen spec used for idempotent flake projection;
#                  defaults to 3 so the existing v1/v2 threshold fixture
#                  models a genuinely new occurrence
# Workdir inputs:
#   tasks/plan.json  the mapping data the block queries per failing id
#
# Stdout on exit:
#   FINAL_TESTS_RC=<n>
#   FINAL_FAILING=<original-or-restored>
#   FINAL_FAIL_DETAIL=<original-or-restored>
#   FLAKE_NOTE=<one-line-encoded, empty when block did not fire flake path>
#   RECURRING_FLAKE=<0|1>
#   ISO_EVIDENCE=<the recorded isolation evidence string>
#   RT_CALLS=<how many times the stub run_tests was invoked>
set -euo pipefail

WORK="${1:?usage: drive-drift.sh <workdir>}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
[ -f tasks/plan.json ] || { echo "drive-drift: tasks/plan.json missing in $WORK" >&2; exit 64; }

# Extract the marker-delimited flake block verbatim; strip the marker
# lines themselves so what remains is executable bash. Fail loudly if the
# markers were renamed (the block moved and the harness never noticed).
BLOCK=$(sed -n '/^# BEGIN D-77 flake triage/,/^# END D-77 flake triage/p' \
        "$REPO/scripts/orchestrate.sh" | sed '1d;$d')
printf '%s' "$BLOCK" | grep -q '^FLAKE_NOTE=""' \
  || { echo "drive-drift: could not extract flake block from orchestrate.sh — did the BEGIN/END markers move?" >&2; exit 65; }

# --- Env inputs (env → shell vars with defaults) ---
TESTS_RC="${TESTS_RC:-1}"
FROZEN_V="${FROZEN_V:-3}"
FAILING="${FAILING:-}"
FAIL_DETAIL="${FAIL_DETAIL:-}"
RT_OUTCOMES="${RT_OUTCOMES:-}"
SWBP_ELAPSED="${SWBP_ELAPSED:-0}"
SWBP_RUN_BUDGET="${SWBP_RUN_BUDGET:-0}"
FLAKE_LEDGER="${FLAKE_LEDGER:-.pipeline-flakes.json}"
FLAKE_LEDGER_TOOL="$REPO/scripts/flake-ledger.py"
FLAKE_ESCALATION_THRESHOLD="${SWBP_FLAKE_ESCALATION_THRESHOLD:-3}"

# --- Stubs the block calls out to -------------------------------------
# The real run_tests parses .cache/test-report.json and sets TESTS_RC,
# FAILING, FAIL_DETAIL. The block cares only about TESTS_RC here (checks
# `if [ "$TESTS_RC" -eq 0 ]` to count an isolation pass), but the real
# function clobbers FAILING and FAIL_DETAIL as a side effect — so this
# stub does too, or the save/restore dance would look correct only
# because nothing ever touched the vars.
RT_CALLS=0
_rt_queue="$RT_OUTCOMES"
run_tests() {
  RT_CALLS=$((RT_CALLS + 1))
  local outcome=""
  if [ -n "$_rt_queue" ]; then
    outcome="${_rt_queue%%:*}"
    case "$_rt_queue" in
      *:*) _rt_queue="${_rt_queue#*:}" ;;
      *)   _rt_queue="" ;;
    esac
  fi
  TESTS_RC="${outcome:-1}"
  FAILING=""     # match real run_tests's clobber pattern
  FAIL_DETAIL="" # ditto
}

run_elapsed() { echo "$SWBP_ELAPSED"; }
mark() { :; }   # phase-timing sink — irrelevant here
die() { echo "FAIL: $*" >&2; exit 1; }

# --- Execute the extracted block --------------------------------------
eval "$BLOCK"

# --- Report --------------------------------------------------------------
# Encode FLAKE_NOTE onto one line so the pytest side can grep for exact
# substrings without wrestling with the leading newline in the real value.
_fn_encoded=$(printf '%s' "${FLAKE_NOTE:-}" | tr '\n' ' ' | sed 's/^ *//;s/ *$//')
echo "FINAL_TESTS_RC=$TESTS_RC"
echo "FINAL_FAILING=$FAILING"
echo "FINAL_FAIL_DETAIL=$FAIL_DETAIL"
echo "FLAKE_NOTE=$_fn_encoded"
echo "FLAKE_RECORDS=${FLAKE_RECORDS:-}"
echo "RECURRING_FLAKE=${RECURRING_FLAKE:-0}"
echo "ISO_EVIDENCE=${iso_evidence:-}"
echo "RT_CALLS=$RT_CALLS"
