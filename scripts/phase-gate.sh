#!/usr/bin/env bash
# phase-gate.sh <build|test|architect|em|task|manifest> [phase-start-ref] [task-target]
# Inverted whitelist gate: fail if the phase touched anything outside its
# permitted lane. Defaults to diffing against current HEAD; pass a
# phase-start ref (recorded before the agent ran) to catch committed changes.
#
# Phases:
#   build     — legacy lane: only the build dir may change
#   test      — legacy lane: only the test dir may change
#   architect — docs/ only, plus the INV-3 decision-traceability check
#   em        — tasks/ only (the EM's sole write lane, D-26)
#   task      — EXACTLY ONE file may change: the task target passed as $3
#               (structural atomicity for the coder, D-26)
#   manifest  — integrity checks only (control plane + frozen spec); used by
#               the orchestrator pre-flight and the pre-commit hook
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

# Control-plane hash check, split by ownership (D-33):
#   .manifest-template — template-owned logic; drift against the template repo
#                        is computed over exactly this list (check-drift.sh)
#   .manifest-project  — per-project adaptations (Rule 3); never drift-checked
# Both are required and both fail closed.
for MANIFEST in scripts/.manifest-template scripts/.manifest-project; do
  if [ ! -f "$MANIFEST" ]; then
    echo "GATE FAIL: control-plane manifest missing: $MANIFEST"
    exit 1
  fi
  while IFS='  ' read -r expected_hash path; do
    [ -z "$expected_hash" ] && continue
    [ -z "$path" ] && continue
    actual=$(sha256sum "$path" 2>/dev/null | cut -d' ' -f1 || echo "MISSING")
    if [ "$actual" != "$expected_hash" ]; then
      echo "GATE FAIL: control plane tampered — $path (expected $expected_hash, got $actual)"
      exit 1
    fi
  done < "$MANIFEST"
done

# Frozen-spec integrity (D-31). The frozen TPM artifacts (PRD/ERD/contracts/
# tests) may only change via scripts/refreeze.sh, which regenerates this
# manifest under an interactive human approval. Any other change fails closed.
FROZEN="scripts/.approved/frozen-manifest"
if [ -f "$FROZEN" ]; then
  while IFS='  ' read -r expected_hash path; do
    [ -z "$expected_hash" ] && continue
    [ -z "$path" ] && continue
    actual=$(sha256sum "$path" 2>/dev/null | cut -d' ' -f1 || echo "MISSING")
    if [ "$actual" != "$expected_hash" ]; then
      echo "GATE FAIL: frozen spec tampered — $path changed outside scripts/refreeze.sh"
      exit 1
    fi
  done < "$FROZEN"
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

    # INV-3: Every non-documentation decision in DECISIONS.md must appear in ARCHITECTURE.md
    if [ -f "docs/DECISIONS.md" ] && [ -f "docs/ARCHITECTURE.md" ]; then
      all_ids=$(grep '^## D-' "docs/DECISIONS.md" | grep -oE 'D-[0-9]+' || true)
      doc_only=$(awk '/^## D-/ {did=$2} /^\*\*Documentation-only:\*\*/ {print did}' "docs/DECISIONS.md")
      missing=""
      while IFS= read -r id; do
        [ -z "$id" ] && continue
        echo "$doc_only" | grep -qF "$id" && continue
        if ! grep -qF "$id" "docs/ARCHITECTURE.md"; then
          missing="$missing $id"
        fi
      done <<< "$all_ids"
      if [ -n "$missing" ]; then
        echo "GATE FAIL: INV-3 — decisions not referenced in ARCHITECTURE.md:$missing"
        exit 1
      fi
    fi
    ;;
  em)
    # Whitelist: only tasks/ may change (plan.json / diagnosis.json lane)
    violations=$(echo "$CHANGED" | { grep -v "^tasks/" || true; } )
    if [ -n "$violations" ]; then
      echo "GATE FAIL: em touched files outside tasks/ (D-26):"
      echo "$violations"
      exit 1
    fi
    ;;
  task)
    # Structural atomicity: EXACTLY the one task-target file may change.
    TARGET="${3:?usage: phase-gate.sh task <phase-start-ref> <target-file>}"
    violations=$(echo "$CHANGED" | { grep -vFx "$TARGET" || true; } | { grep -v '^$' || true; } )
    if [ -n "$violations" ]; then
      echo "GATE FAIL: task phase touched files other than $TARGET (D-26):"
      echo "$violations"
      exit 1
    fi
    ;;
  manifest)
    # Integrity checks above are the whole job.
    ;;
  *)
    echo "usage: phase-gate.sh <build|test|architect|em|task|manifest> [phase-start-ref] [task-target]"
    exit 2
    ;;
esac

echo "gate ok: $PHASE"
