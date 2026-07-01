#!/usr/bin/env bash
# regen-manifest.sh <manifest-file> — refresh every hash in a manifest,
# preserving its file list. Errors on missing files rather than dropping them
# (a vanished control-plane file is a signal, not a cleanup opportunity).
#
# Per the correction-log rule (2026-06-30): whenever any control-plane file is
# edited, regenerate EVERY entry, not just the one touched — partial updates
# are how silent drift happened last time.
set -euo pipefail

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
  sha256sum "$path"
done < "$MANIFEST" > "$TMP"
mv "$TMP" "$MANIFEST"
echo "regenerated: $MANIFEST ($(wc -l < "$MANIFEST" | tr -d ' ') entries)"
