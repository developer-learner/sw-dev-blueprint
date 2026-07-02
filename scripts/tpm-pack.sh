#!/usr/bin/env bash
# tpm-pack.sh — assemble the TPM chat bundle (D-38).
#
# The TPM is a frontier LLM in a human-operated web chat with NO repo access
# (docs/TPM-ROLE.md — the air gap is the design, not a limitation). This
# script removes the operator's courier burden: one command packs everything
# a TPM session needs into a single copy-pasteable blob — the role doc, the
# contracts schema, and the currently frozen spec (when one exists) so deltas
# are derived from ground truth, not chat memory.
#
# It deliberately packs NOTHING from src/ or tests/: oracle independence
# (INV-1) means the TPM never sees the implementation, and it re-authors
# tests from spec, never from the previously frozen suite's text.
#
# Usage: tpm-pack.sh [--stdout]
#   default: copy to clipboard (pbcopy/xclip/wl-copy) when stdout is a tty;
#   --stdout (or piping) writes the bundle to stdout instead.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd -P)"

APPROVED="scripts/.approved"
FORCE_STDOUT=0
[ "${1:-}" = "--stdout" ] && FORCE_STDOUT=1

emit() {
  echo "=== CONTEXT FILE: $1 ==="
  cat "$1"
  echo "=== END CONTEXT FILE ==="
  echo
}

bundle() {
  cat <<'HDR'
You are the TPM for this project. Your job description and working context
follow as CONTEXT FILE blocks. Read docs/TPM-ROLE.md first — it governs
everything, including your delivery format. After the context, the CEO will
state intent in business terms.
HDR
  echo
  emit docs/TPM-ROLE.md
  emit scripts/schemas/contracts.schema.json
  if [ -f "$APPROVED/VERSION" ]; then
    echo "--- CURRENTLY FROZEN SPEC (v$(cat "$APPROVED/VERSION")) — derive any delta from THIS, not from chat memory ---"
    echo
    for f in PRD.md ERD.md contracts.json; do
      [ -f "$APPROVED/$f" ] && emit "$APPROVED/$f"
    done
  else
    echo "--- NO FROZEN SPEC YET — this is the initial freeze (v1): a complete spec is required (PRD.md, ERD.md, contracts.json, and the test suite under tests/) ---"
    echo
  fi
  cat <<'FTR'
=== REPLY FORMAT (mandatory for spec artifacts) ===
Emit every artifact as a COMPLETE file between sentinels, exactly:

=== FILE: <path> ===
<full file content>
=== END FILE ===

Allowed paths ONLY: PRD.md, ERD.md, contracts.json, tests/<name>.py
The operator installs your reply mechanically (tpm-unpack.sh -> refreeze.sh);
anything outside the sentinels is treated as discussion, not artifact.
FTR
}

OUT="$(bundle)"

copy_cmd=""
if command -v pbcopy >/dev/null 2>&1; then copy_cmd="pbcopy"
elif command -v wl-copy >/dev/null 2>&1; then copy_cmd="wl-copy"
elif command -v xclip >/dev/null 2>&1; then copy_cmd="xclip -selection clipboard"
fi

if [ "$FORCE_STDOUT" -eq 0 ] && [ -t 1 ] && [ -n "$copy_cmd" ]; then
  printf '%s\n' "$OUT" | $copy_cmd
  echo "tpm-pack: bundle copied to clipboard ($(printf '%s' "$OUT" | wc -c | tr -d ' ') bytes, $(printf '%s\n' "$OUT" | wc -l | tr -d ' ') lines)." >&2
  echo "tpm-pack: paste it as the FIRST message of a fresh TPM chat, then state your ask." >&2
else
  printf '%s\n' "$OUT"
fi
