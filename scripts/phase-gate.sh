#!/usr/bin/env bash
# phase-gate.sh <build|test> — fails if the phase touched the other role's directory.
set -e
PHASE="$1"
CHANGED="$( { git diff --name-only HEAD; git diff --cached --name-only; git ls-files --others --exclude-standard; } | sort -u )"
case "$PHASE" in
  build) echo "$CHANGED" | grep -q '^tests/' && { echo "GATE FAIL: build modified tests/ (INV-2)"; exit 1; } ;;
  test)  echo "$CHANGED" | grep -q '^src/'   && { echo "GATE FAIL: test modified src/ (INV-2)";  exit 1; } ;;
  *) echo "usage: phase-gate.sh <build|test>"; exit 2 ;;
esac
echo "gate ok: $PHASE"
