#!/usr/bin/env bash
# regen-manifest.sh <manifest-file> — refresh every hash in a manifest,
# preserving its file list. Errors on missing files rather than dropping them
# (a vanished control-plane file is a signal, not a cleanup opportunity).
#
# Per the correction-log rule (2026-06-30): whenever any control-plane file is
# edited, regenerate EVERY entry, not just the one touched — partial updates
# are how silent drift happened last time.
set -euo pipefail

# Portable SHA-256 (D-152 class): this is the repair command the drift guard
# tells the operator to run — it must work wherever the guard does, including
# a stock macOS host. Output format matches sha256sum ("<hash>  <path>").
# Inline copy — selftest fixtures copy scripts by bytes, so keep this
# in sync with the helpers in manifest-drift-guard.sh, check-drift.sh,
# update-template.sh (sync-pinned by selftest_gates.py).
sha256_line() {
  local hex
  if command -v sha256sum >/dev/null 2>&1; then
    hex=$(sha256sum "$1") || return 1
  elif command -v shasum >/dev/null 2>&1; then
    hex=$(shasum -a 256 -- "$1") || return 1
  else
    echo "regen-manifest: no sha256sum or shasum found — cannot hash $1" >&2
    return 1
  fi
  printf '%s\n' "$hex"
}

MANIFEST="${1:?usage: regen-manifest.sh <manifest-file>}"
[ -f "$MANIFEST" ] || { echo "regen-manifest: not found: $MANIFEST" >&2; exit 1; }

TMP="$MANIFEST.tmp.$$"
while IFS='  ' read -r _hash path; do
  [ -z "$path" ] && continue
  if [ ! -f "$path" ]; then
    rm -f "$TMP"
    echo "regen-manifest: listed file missing on disk: $path" >&2
    echo "  (remove its line from $MANIFEST deliberately if the removal is intended)" >&2
    exit 1
  fi
  sha256_line "$path"
done < "$MANIFEST" > "$TMP"
mv "$TMP" "$MANIFEST"
echo "regenerated: $MANIFEST ($(wc -l < "$MANIFEST" | tr -d ' ') entries)"
