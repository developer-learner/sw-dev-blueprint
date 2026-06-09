#!/usr/bin/env bash
# phase-gate.sh <build|test|architect> [phase-start-ref]
# Inverted whitelist gate: fail if the phase touched anything outside its
# permitted directory. Defaults to diffing against current HEAD; pass a
# phase-start ref (recorded before the agent ran) to catch committed changes.
set -e

PHASE="$1"
PHASE_START="${2:-HEAD}"

# Read .gate-paths config (defaults: src/ and tests/)
# Falls back to built-in defaults if .gate-paths is tampered/missing.
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

# Control-plane hash check. Read manifest, hash each file, compare.
MANIFEST="scripts/.control-plane-manifest"
if [ -f "$MANIFEST" ]; then
  while IFS='  ' read -r expected_hash path; do
    [ -z "$expected_hash" ] && continue
    [ -z "$path" ] && continue
    actual=$(sha256sum "$path" 2>/dev/null | cut -d' ' -f1 || echo "MISSING")
    if [ "$actual" != "$expected_hash" ]; then
      echo "GATE FAIL: control plane tampered — $path (expected $expected_hash, got $actual)"
      exit 1
    fi
  done < "$MANIFEST"
fi

# Collect all changes since phase-start ref: committed + staged + working + untracked
CHANGED=$( {
  git diff --name-only "$PHASE_START" HEAD 2>/dev/null || true
  git diff --cached --name-only
  git diff --name-only
  git ls-files --others --exclude-standard
} | sort -u )

case "$PHASE" in
  build)
    # Whitelist: only src/ may change; anything outside src/ → fail
    violations=$(echo "$CHANGED" | { grep -v "^$build_dir" || true; } )
    if [ -n "$violations" ]; then
      echo "GATE FAIL: build touched files outside $build_dir (INV-2):"
      echo "$violations"
      exit 1
    fi
    ;;
  test)
    # Whitelist: only tests/ may change; anything outside tests/ → fail
    violations=$(echo "$CHANGED" | { grep -v "^$test_dir" || true; } )
    if [ -n "$violations" ]; then
      echo "GATE FAIL: test touched files outside $test_dir (INV-2):"
      echo "$violations"
      exit 1
    fi
    ;;
  architect)
    # Whitelist: only docs/ may change; anything outside docs/ → fail
    violations=$(echo "$CHANGED" | { grep -v "^docs/" || true; } )
    if [ -n "$violations" ]; then
      echo "GATE FAIL: architect touched files outside docs/:"
      echo "$violations"
      exit 1
    fi
    ;;
  *)
    echo "usage: phase-gate.sh <build|test|architect> [phase-start-ref]"
    exit 2
    ;;
esac

echo "gate ok: $PHASE"
