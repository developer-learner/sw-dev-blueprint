#!/usr/bin/env bash
# tpm-unpack.sh — split a TPM chat reply into refreeze staging (D-38).
#
# Reads the TPM's reply (file argument, else the clipboard, else stdin),
# extracts every "=== FILE: <path> ===" ... "=== END FILE ===" block, and
# writes the files under scripts/.approved/incoming/ for refreeze.sh.
#
# This script only STAGES. The trust model is unchanged: nothing is installed
# until the human reads the diff and answers y at refreeze.sh's prompt.
# Paths are validated against the refreeze whitelist, fail-closed — one bad
# path (traversal, src/, anything unexpected) rejects the whole reply.
#
# Usage: tpm-unpack.sh [--force] [reply-file]
#   --force   replace a non-empty staging dir (previous milestone leftovers)
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd -P)"

IN_DIR="scripts/.approved/incoming"
die() { echo "TPM-UNPACK FAIL: $*" >&2; exit 1; }

FORCE=0 SRC=""
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    -*) die "unknown flag: $a (usage: tpm-unpack.sh [--force] [reply-file])" ;;
    *) SRC="$a" ;;
  esac
done

if [ -n "$SRC" ]; then
  [ -f "$SRC" ] || die "reply file not found: $SRC"
  INPUT=$(cat "$SRC")
elif [ ! -t 0 ]; then
  INPUT=$(cat)
elif command -v pbpaste >/dev/null 2>&1; then
  INPUT=$(pbpaste)
elif command -v wl-paste >/dev/null 2>&1; then
  INPUT=$(wl-paste)
elif command -v xclip >/dev/null 2>&1; then
  INPUT=$(xclip -selection clipboard -o)
else
  die "no reply source: pass a file, pipe stdin, or install a clipboard tool"
fi
[ -n "$INPUT" ] || die "reply is empty"

if [ -d "$IN_DIR" ] && [ -n "$(find "$IN_DIR" -type f 2>/dev/null | head -1)" ]; then
  if [ "$FORCE" -eq 1 ]; then
    rm -rf "$IN_DIR"
  else
    die "staging dir not empty: $IN_DIR (leftovers from a previous freeze?) — rerun with --force to replace"
  fi
fi
mkdir -p "$IN_DIR"

# The reply goes through a temp file: python3 - takes its PROGRAM from stdin,
# so the heredoc below owns stdin and a pipe would be silently clobbered.
REPLY_TMP=$(mktemp)
trap 'rm -f "$REPLY_TMP"' EXIT
printf '%s\n' "$INPUT" > "$REPLY_TMP"

python3 - "$IN_DIR" "$REPLY_TMP" <<'PYEOF'
import re
import sys
from pathlib import Path

in_dir = Path(sys.argv[1])
text = Path(sys.argv[2]).read_text()

# Same whitelist refreeze.sh enforces — validated here too so a bad reply
# fails at unpack with a named culprit, not later with a vaguer error.
ALLOWED = re.compile(r"^(PRD\.md|ERD\.md|contracts\.json|tests/[A-Za-z0-9_\-]+\.py)$")
BLOCK = re.compile(
    r"^=== FILE: (.+?) ===\n(.*?)^=== END FILE ===$", re.M | re.S
)

blocks = BLOCK.findall(text)
if not blocks:
    sys.exit(
        "TPM-UNPACK FAIL: no '=== FILE: <path> ===' blocks found in the reply — "
        "ask the TPM to resend using the mandatory reply format"
    )

errs, files = [], {}
for raw_path, content in blocks:
    path = raw_path.strip()
    if not ALLOWED.match(path):
        errs.append(f"disallowed path: {path!r} (allowed: PRD.md, ERD.md, contracts.json, tests/<name>.py)")
        continue
    if not content.strip():
        errs.append(f"empty content for {path}")
        continue
    if path in files:
        errs.append(f"duplicate block for {path}")
        continue
    files[path] = content

if errs:
    for e in errs:
        print(f"TPM-UNPACK FAIL: {e}", file=sys.stderr)
    sys.exit(1)

for path, content in files.items():
    dest = in_dir / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    print(f"staged: {dest} ({len(content.splitlines())} lines)")
PYEOF

echo
echo "tpm-unpack: staged under $IN_DIR — review and install with: scripts/refreeze.sh"
