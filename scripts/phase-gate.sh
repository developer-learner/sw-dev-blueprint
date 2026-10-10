#!/usr/bin/env bash
# phase-gate.sh <em|task|manifest> [phase-start-ref] [task-target]
# Inverted whitelist gate: fail if the phase touched anything outside its
# permitted lane. Defaults to diffing against current HEAD; pass a
# phase-start ref (recorded before the agent ran) to catch committed changes.
#
# Phases:
#   em        — tasks/ only (the EM's sole write lane, D-26)
#   task      — EXACTLY ONE file may change: the task target passed as $3
#               (structural atomicity for the coder, D-26)
#   manifest  — integrity checks only (control plane + frozen spec); used by
#               the orchestrator pre-flight and the pre-commit hook
#
# Retired 2026-07-22 (D-25/D-37 amended): the `build`, `test`, and
# `architect` phases + their INV-3 check ran under the pre-D-53 architecture
# where distinct agent tiers wrote src/, tests/, and docs/. Post-D-53 only
# the shell writes those paths (coder via `task`, EM via `em`, tests only
# via refreeze); nothing invokes the retired phases and INV-3 sat unrun for
# ~3 weeks, so keeping them was mechanical theater. The build_dir/test_dir
# path readers here went with them — orchestrate.sh and validate-plan.py
# read `build=` from `.gate-paths` themselves for their pathing needs.
set -e

PHASE="$1"
PHASE_START="${2:-HEAD}"

# Portable SHA-256 (D-152 failure class): this gate also runs from the
# pre-commit hook wherever the CEO commits, including a stock macOS host
# that ships shasum but not sha256sum. Same digest either way; fail closed
# with a clear message if neither binary exists. MISSING semantics for an
# absent file are preserved by the callers below.
hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" 2>/dev/null | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1
  else
    # >&2: hash_file runs inside $(...) — a plain echo would be captured by
    # the caller and swallowed when set -e halts on the non-zero status.
    echo "GATE FAIL: no sha256sum or shasum found — cannot verify integrity" >&2
    exit 1
  fi
}

# D-186: a builder-targeted app (marked by .swbp) hosts no plane — it runs
# from a content-addressed snapshot of the pinned builder ref, so there is
# nothing here to hash. The frozen-spec check below still runs. (The linked-
# child structural pass went with the sync layer at stage F, D-218.)
APP_MODE=0
[ -f .swbp ] && APP_MODE=1

# Control-plane hash check, split by ownership (D-33):
#   .manifest-template — template-owned logic; drift against the template repo
#                        (the builder's own control plane)
#   .manifest-project  — per-project adaptations (Rule 3); never drift-checked
# Both are required and both fail closed.
for MANIFEST in scripts/.manifest-template scripts/.manifest-project; do
  [ "$APP_MODE" = 1 ] && break
  if [ ! -f "$MANIFEST" ]; then
    echo "GATE FAIL: control-plane manifest missing: $MANIFEST"
    exit 1
  fi
  while IFS='  ' read -r expected_hash path; do
    [ -z "$expected_hash" ] && continue
    [ -z "$path" ] && continue
    if [ -f "$path" ]; then
      actual=$(hash_file "$path")
    else
      actual="MISSING"
    fi
    if [ "$actual" != "$expected_hash" ]; then
      echo "GATE FAIL: control plane tampered — $path (expected $expected_hash, got $actual)"
      exit 1
    fi
  done < "$MANIFEST"
done

# Frozen-spec integrity (D-31). The frozen TPM artifacts (PRD/ERD/contracts/
# tests) may only change via scripts/refreeze.sh, which regenerates this
# manifest after every mechanical preflight passes (D-121). Any other change
# fails closed.
#
# Trigger: once a spec has been frozen (VERSION exists), the manifest is
# required. `[ -f FROZEN ]` alone silently skipped the whole check when the
# manifest itself was the artifact deleted — the wrong direction for a
# fail-closed gate.
FROZEN="scripts/.approved/frozen-manifest"
FROZEN_VERSION="scripts/.approved/VERSION"
if [ -f "$FROZEN_VERSION" ]; then
  [ -f "$FROZEN" ] || {
    echo "GATE FAIL: frozen spec present ($FROZEN_VERSION) but $FROZEN is missing — integrity cannot be verified (D-31)"
    exit 1
  }
  while IFS='  ' read -r expected_hash path; do
    [ -z "$expected_hash" ] && continue
    [ -z "$path" ] && continue
    # Defense-in-depth for manifests frozen before refreeze.sh learned to
    # exclude bytecode caches — skip such entries so an old project isn't
    # forced to re-freeze just to clear a false tamper alarm.
    case "$path" in
      */__pycache__/*|*/.pytest_cache/*) continue ;;
    esac
    if [ -f "$path" ]; then
      actual=$(hash_file "$path")
    else
      actual="MISSING"
    fi
    if [ "$actual" != "$expected_hash" ]; then
      echo "GATE FAIL: frozen spec tampered — $path changed outside scripts/refreeze.sh"
      exit 1
    fi
  done < "$FROZEN"
  # INV-1 addition coverage: the hash loop catches modification and deletion
  # of pinned files, but a hand-added new tests/test_x.py is invisible to it
  # and would run in the frozen suite (and the on-demand --full-suite
  # regression check). Cross-check: every git-visible
  # file (tracked + untracked, gitignore-respecting) under tests/ must be
  # pinned, PLUS every pytest-collectible *.py on disk (a hand-added
  # tests/test_*.py matching an existing ignore rule would otherwise bypass
  # the git-visible scan entirely). gitignored bytecode caches
  # (__pycache__/*, .pytest_cache/*) are runtime artifacts and correctly
  # excluded here.
  pinned_tests=$(awk '{print $2}' "$FROZEN" | grep '^tests/' | sort -u || true)
  disk_tests=$( ( git ls-files -- tests; git ls-files --others --exclude-standard -- tests; \
                  find tests -type f \( -name 'test_*.py' -o -name '*_test.py' -o -name 'conftest.py' \) \
                    -not -path '*/__pycache__/*' 2>/dev/null ) | sort -u )
  unpinned=$(comm -23 <(printf '%s\n' "$disk_tests") <(printf '%s\n' "$pinned_tests"))
  if [ -n "$unpinned" ]; then
    echo "GATE FAIL: unpinned test file(s) — added outside scripts/refreeze.sh (INV-1):"
    printf '  %s\n' $unpinned
    exit 1
  fi
fi

# Collect all changes since phase-start ref: committed + staged + working + untracked
CHANGED=$( {
  git diff --name-only "$PHASE_START" HEAD 2>/dev/null || true
  git diff --cached --name-only
  git diff --name-only
  git ls-files --others --exclude-standard
} | sort -u )

case "$PHASE" in
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
    # Integrity checks above are the whole job. Plus the placeholder-
    # completeness gate (D-160): BLUEPRINT.md Step 7 mechanized. Active only
    # when a `.placeholder-gate` marker exists — written by the retired
    # copy-seed bootstrap (stage F, D-218); the builder and builder-targeted
    # apps do not arm it, so seeded skeleton rows cannot trip it. A repo that
    # carries the marker stays on the enforced side. Same command + exclusions as Step 7:
    # md/json, markdown links filtered, DECISIONS.md/BLUEPRINT.md excluded
    # (intentional bracket content). A bracket directly after an identifier
    # or '.' is code, not a placeholder (`list[DiscoveredModel]`, `x[Key]`) —
    # vortex v43's freeze was rolled back by a Python type in a coder brief.
    if [ -f .placeholder-gate ]; then
      hits=$({ grep -rnE '(^|[^A-Za-z0-9_.])\[[A-Z][A-Za-z0-9_ ]+\]|(^|[^A-Za-z0-9_.])\[[A-Z][a-z]+ [a-z]|(^|[^A-Za-z0-9_.])\[[a-z][a-z_]+ [a-z]' . \
          --include='*.md' --include='*.json' --exclude-dir=.git \
          --exclude-dir=project-trail --exclude-dir=.em-archive \
          --exclude-dir=.pipeline-state --exclude-dir=.measurement \
          --exclude-dir=.tpm --exclude-dir='.venv*' --exclude-dir=.cache \
          --exclude-dir=data \
          --exclude='HANDOFF-*' --exclude='CURRENT.md' --exclude='BACKLOG.md' \
          --exclude='DECISIONS.md' --exclude='BLUEPRINT.md' \
          | grep -vE '\]\(' | grep -vE '^[^:]+:[0-9]+:\| [0-9]{4}-[0-9]{2}-[0-9]{2} ' || true; })
      if [ -n "$hits" ]; then
        echo "GATE FAIL: placeholder tokens survived (BLUEPRINT.md Step 7 — fill then re-run):"
        echo "$hits"
        exit 1
      fi
    fi
    ;;
  *)
    echo "usage: phase-gate.sh <em|task|manifest> [phase-start-ref] [task-target]"
    exit 2
    ;;
esac

echo "gate ok: $PHASE"
