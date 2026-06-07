#!/usr/bin/env bash
# phase-gate.sh <build|test> — fails if the phase touched the other role's directory.
set -e
PHASE="$1"

# Read .gate-paths config (defaults: src/ and tests/)
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

CHANGED="$( { git diff --name-only HEAD; git diff --cached --name-only; git ls-files --others --exclude-standard; } | sort -u )"
case "$PHASE" in
  build) echo "$CHANGED" | grep -q "^$test_dir" && { echo "GATE FAIL: build modified ${test_dir%/}/ (INV-2)"; exit 1; } ;;
  test)  echo "$CHANGED" | grep -q "^$build_dir" && { echo "GATE FAIL: test modified ${build_dir%/}/ (INV-2)"; exit 1; } ;;
  *) echo "usage: phase-gate.sh <build|test>"; exit 2 ;;
esac
echo "gate ok: $PHASE"
