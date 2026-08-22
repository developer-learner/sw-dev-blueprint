#!/usr/bin/env bash
# manifest-drift-guard.sh — warning-only drift advisory (2026-08-08).
#
# The gate (phase-gate.sh manifest) DETECTS control-plane drift fail-closed,
# but nothing prevented INTRODUCING it: a control-plane doc edit lands
# without regenerating the manifest, and the NEXT commit goes red with a
# manual re-pin needed (recurred twice: 2026-06-30, 2026-08-03 7537d83).
# This hook de-risks the introduce: BEFORE the fail-closed manifest check,
# it warns when a STAGED control-plane file's hash differs from the
# manifest, printing the exact repair command. Warning-only, exit 0 always
# — the gate stays the enforcement point.
#
# Why warning-only: control-plane docs have no runtime blast radius (only
# phase-gate reads them), matching the D-115 gate-strength rule and the
# doc-consistency.sh precedent; auto-regen stays banned (Rule 3: it would
# bless any CLAUDE.md change instead of an intended one).
#
# Usage: manifest-drift-guard.sh [--root ROOT]
#        (--root defaults to the git toplevel)
# Exit: 0 always (warning). Silent when no staged control-plane file drifts.
set -uo pipefail

if [ "${1:-}" = "--root" ]; then
  ROOT="${2:?--root needs a dir}"
elif [ -n "${1:-}" ]; then
  echo "manifest-drift-guard: unknown argument: $1" >&2
  exit 2
else
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "${PWD}")"
fi
[ -d "$ROOT" ] || { echo "manifest-drift-guard: not a dir: $ROOT" >&2; exit 2; }

# Portable SHA-256 over stdin (D-152 class): this guard runs from the
# pre-commit hook wherever the CEO commits, including a stock macOS host.
# Same digest either way. Inline copy — selftest fixtures copy scripts by
# bytes, so keep this in sync with the helpers in regen-manifest.sh,
# check-drift.sh, update-template.sh (sync-pinned by selftest_gates.py).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    echo "manifest-drift-guard: no sha256sum or shasum found — cannot compare staged hashes" >&2
    return 1
  fi
}

check_manifest() {
  local manifest="$1"
  local label="$2"
  [ -f "$manifest" ] || return 0  # absent → nothing to compare (gate owns existence checks)
  while read -r _hash path; do
    [ -n "$path" ] || continue
    full="$ROOT/$path"
    # Symlink entries (AGENTS.md -> CLAUDE.md) resolve to the target's hash in
    # the manifest; the target's own regular-file entry already covers drift.
    [ -L "$full" ] && continue
    git -C "$ROOT" diff --cached --quiet -- "$path" 2>/dev/null && continue
    staged_hash="$(git -C "$ROOT" show :"$path" 2>/dev/null | sha256_of || true)"
    if [ -n "$staged_hash" ] && [ "$staged_hash" != "$_hash" ]; then
      WARNED=1
      echo "manifest-drift-guard ($label): STAGED change to $path without a matching manifest update." >&2
      echo "  The next commit/phase-gate manifest check will go RED until you re-pin." >&2
      echo "  Fix: $ cd \"$ROOT\" && scripts/regen-manifest.sh $label" >&2
      echo "  (If this is a deliberate control-plane edit, run the regen in the SAME commit.)" >&2
    fi
  done < "$manifest"
}

WARNED=0
# Both ownership classes: template-owned (shared logic, drift-checked) and
# project-owned adaptations (Rule 3). The phase-gate checks both fail-closed;
# this advisory should warn on the same set.
check_manifest "$ROOT/scripts/.manifest-project" "scripts/.manifest-project"
check_manifest "$ROOT/scripts/.manifest-template" "scripts/.manifest-template"

if [ "$WARNED" -eq 1 ]; then
  echo "manifest-drift-guard: advisory warning only (exit 0)." >&2
fi
exit 0