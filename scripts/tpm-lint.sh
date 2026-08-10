#!/usr/bin/env bash
# tpm-lint.sh — pre-ship mechanical lint for a staged TPM bundle (D-38).
#
# The TPM web-chat return is relayed by a human (docs/TPM-ROLE.md). Before
# anyone calls that relay "done" — and before refreeze.sh's auto-apply
# surprises anyone mid-session — this script runs the EXACT same mechanical
# preflights refreeze.sh would run, read-only, and prints a short verdict
# instead of the full diff. It is a wrapper on purpose: the gate logic lives
# in refreeze.sh's --diff mode (the S-checks, D-56/D-78/D-87/D-88/D-104,
# INV-4, staged-test parse/lint/determinism gates). A copy here would drift
# (D-34 correction log: "a gate removed is only complete when no doc tells
# an operator to invoke the removed capability" — the complement: a gate
# added must be reachable from the pre-ship review, same channel).
#
# Exit 0: staging passes every mechanical preflight (DIFF-SHA printed).
# Exit 1: staging is defective — refreeze WILL halt; fix before relay.
#
# Usage: tpm-lint.sh [<staging-dir>]
#   default staging dir: scripts/.approved/incoming
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
IN="${1:-scripts/.approved/incoming}"

[ -d "$IN" ] || { echo "tpm-lint: staging dir not found: $IN" >&2; exit 64; }

OUT="$(mktemp "${TMPDIR:-/tmp}/tpm-lint.XXXXXX")"
trap 'rm -f "$OUT"' EXIT

if ! scripts/refreeze.sh --diff "$IN" >"$OUT" 2>&1; then
  echo "tpm-lint: FAIL — refreeze --diff halted (see findings below)" >&2
  grep -E "^REFREEZE FAIL" "$OUT" >&2 || tail -n 20 "$OUT" >&2 || true
  exit 1
fi

SHA=$(grep -m1 -E '^DIFF-SHA: ' "$OUT" | awk '{print $2}' || true)
echo "tpm-lint: PASS — staging is preflight-green; refreeze will auto-apply${SHA:+ (DIFF-SHA $SHA)}"