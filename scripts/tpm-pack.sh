#!/usr/bin/env bash
# tpm-pack.sh — assemble the TPM chat bundle (D-38).
#
# The TPM is a frontier LLM in a human-operated web chat with NO repo access
# (docs/TPM-ROLE.md — the air gap is the design, not a limitation). This
# script removes the operator's courier burden: one command packs the small
# milestone slice a TPM session needs into a single copy-pasteable blob.
#
# Milestone relevance (D-116/D-117/D-120): the product context is a capsule
# plus the current changed-acceptance slice; the standing architecture is
# rules plus a generated file map; contracts contain only in-scope bodies.
# Every missing or failed slice falls back to its full artifact with a stderr
# warning — never a silent context loss.
#
# It deliberately packs NOTHING from src/ or tests/: oracle independence
# (INV-1) means the TPM never sees the implementation, and it re-authors
# tests from spec, never from the previously frozen suite's text.
#
# Usage: tpm-pack.sh [--clipboard]
#   default: write the bundle to stdout (D-49 — agents run this and must
#   relay the FULL output verbatim to the CEO; TTY auto-detection misfired
#   inside agent harnesses that allocate a pty, silently eating the bundle);
#   --clipboard: copy to clipboard instead (pbcopy/wl-copy/xclip) — the
#   human-at-a-terminal convenience, now opt-in. --stdout is accepted as a
#   no-op for backward compatibility.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd -P)"

APPROVED="scripts/.approved"
ALLOWED_ARTIFACTS=$(python3 scripts/spec_artifacts.py describe) || {
  echo "tpm-pack: shared spec-artifact policy unavailable" >&2
  exit 1
}
WANT_CLIPBOARD=0
case "${1:-}" in
  --clipboard) WANT_CLIPBOARD=1 ;;
  --stdout|"") ;;
  *) echo "tpm-pack: unknown option ${1} (usage: tpm-pack.sh [--clipboard])" >&2; exit 1 ;;
esac

emit() {  # emit <path> [label]
  echo "=== CONTEXT FILE: ${2:-$1} ==="
  cat "$1"
  # A packed file may lack a trailing newline (contracts.schema.json ends
  # in `}`, ERD-DELTA.md in a backtick) — that would glue the END marker
  # onto its last line (review 2026-08-13 P2). Separate unconditionally.
  [ -z "$(tail -c 1 "$1" 2>/dev/null | tr -d '\n')" ] || echo
  echo "=== END CONTEXT FILE ==="
  echo
}

generate_role_slice() {
  python3 - "$1" <<'PY'
"""Chat-bundle role slice (review 2026-08-13 P2): the agent-mode annex is
the tpm-agent.sh seat's instruction set (D-39) — the chat TPM never runs
agent mode, so the bundle drops the annex and de-dangles its forward
reference. The repo file keeps the annex verbatim (institutional memory —
do not discard); this is a pack-only view, like the PRD/delta slices."""
import re
import sys
from pathlib import Path

try:
    text = Path(sys.argv[1]).read_text()
except OSError:
    sys.exit(1)

text = re.sub(r"\n## Agent mode \(annex\)\n.*\Z", "\n", text, flags=re.S)
# De-dangle: the reference sentence points at a section the slice removed.
text = text.replace(
    "Its full procedure is\n"
    "in the **Agent mode (annex)** at the end; everything from here on is written for\n"
    "chat-mode intake.",
    "It is a separate seat (D-39) whose procedure this chat bundle does not carry.",
)
if not text.strip():
    sys.exit(1)
sys.stdout.write(text)
PY
}

generate_prd_slice() {
  python3 - "$1" "$2" <<'PY'
"""Derive a product capsule and current criteria from frozen truth (D-117)."""
import re
import sys
from pathlib import Path


def first_paragraph(lines: list[str], start: int) -> str:
    """Read one Markdown paragraph after a product heading (D-117)."""
    paragraph: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if not line.strip():
            if paragraph:
                break
            continue
        paragraph.append(line.strip())
    return re.sub(r"\s+", " ", " ".join(paragraph)).strip()


def product_capsule(prd: str) -> str:
    """Select the PRD's product-introduction paragraph (D-117)."""
    lines = prd.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+(what\b|product\b|overview\b)", line, re.I):
            return first_paragraph(lines, index + 1)
    for index, line in enumerate(lines):
        if line.startswith("#") or not line.strip():
            continue
        paragraph = first_paragraph(lines, index)
        if paragraph:
            return paragraph
    return ""


def changed_acceptance(delta: str) -> str:
    """Extract the authoritative current PRD criteria from D-107's delta."""
    match = re.search(
        r"^## Changed acceptance criteria\s*$\n(.*?)(?=^##\s|\Z)",
        delta,
        re.M | re.S | re.I,
    )
    return match.group(1).strip() if match else ""


def bounded(text: str, limit: int = 700) -> str:
    """Keep the product capsule short without cutting a word (D-117)."""
    if len(text) <= limit:
        return text
    prefix = text[: limit - 3].rsplit(" ", 1)[0].rstrip(" ,;:")
    return prefix + "..."


prd_path, delta_path = map(Path, sys.argv[1:3])
try:
    prd = prd_path.read_text()
    capsule = product_capsule(prd)
    criteria = changed_acceptance(delta_path.read_text())
except OSError:
    sys.exit(1)
if not capsule or not criteria:
    sys.exit(1)
output = (
    "# Product milestone context\n\n"
    f"## Product capsule\n\n{bounded(capsule)}\n\n"
    f"## Current PRD delta (from ERD-DELTA.md)\n\n{criteria}\n"
)
if len(output.encode()) > len(prd.encode()):
    sys.exit(1)
sys.stdout.write(output)
PY
}

generate_delta_slice() {
  python3 - "$1" <<'PY'
"""Strip the execution-side decomposition from the ERD-DELTA before it reaches
the TPM bundle. Starting intake of the NEXT feature does not need the CURRENT
milestone's coder briefs, DAG, or task scheduling (~8 KB of dead weight); the
TPM re-derives all of that when it authors the next delta. Keep exactly the
spec-side content: ACs, supersessions, changed files, test-to-file mapping.

Pack-only: the execution lane (orchestrate.sh plan assembly) still reads the
full ERD-DELTA.md on disk — this view is generated into a temp file for the
bundle and never written back."""
import re
import sys
from pathlib import Path

try:
    text = Path(sys.argv[1]).read_text()
except OSError:
    sys.exit(1)

kept: list[str] = []
in_briefs = False
for line in text.splitlines(keepends=True):
    # Drop the whole "## Coder briefs (verbatim)" section (heading through the
    # next top-level heading or EOF).
    if re.match(r"^##\s+Coder briefs \(verbatim\)\s*$", line):
        in_briefs = True
        continue
    if in_briefs:
        if re.match(r"^##\s+", line):
            in_briefs = False  # a new section resumes normal handling
        else:
            continue
    # Drop DAG scheduling wherever it sits: `A` depends on `B` statements and
    # any Task-order chain (parser forms in validate-plan.py:_parse_delta_dag).
    if re.search(r"`[^`]+`\s+depends on\s+`[^`]+`", line):
        continue
    if "Task order:" in line:
        continue
    kept.append(line)

# Second pass: drop any "## " heading whose body is now empty — a dedicated
# DAG heading emptied above leaves an orphan title otherwise. The kept spec
# sections (ACs, supersessions "None.", changed files, mapping) always carry
# content, so this only removes headings the strip hollowed out.
lines = kept
out: list[str] = []
i = 0
while i < len(lines):
    if re.match(r"^##\s+", lines[i]):
        j = i + 1
        while j < len(lines) and not re.match(r"^##\s+", lines[j]):
            j += 1
        if not "".join(lines[i + 1:j]).strip():
            i = j  # heading + empty body: skip both
            continue
    out.append(lines[i])
    i += 1

result = re.sub(r"\n{3,}", "\n\n", "".join(out)).rstrip("\n") + "\n"
if not result.strip():
    sys.exit(1)
sys.stdout.write(result)
PY
}

bundle() {
  cat <<'HDR'
You are the TPM for this project. Your job description and working context
follow as CONTEXT FILE blocks. Read docs/TPM-ROLE.md first — it governs
everything, including your delivery format. After the context, the CEO will
state intent in business terms.
HDR
  echo
  role_slice="$(mktemp "${TMPDIR:-/tmp}/role-slice.XXXXXX")"
  if generate_role_slice docs/TPM-ROLE.md > "$role_slice" 2>/dev/null; then
    emit "$role_slice" "docs/TPM-ROLE.md (chat bundle — agent-mode annex omitted, review 2026-08-13)"
  else
    emit docs/TPM-ROLE.md
    echo "tpm-pack: role slice unavailable — shipped the full TPM-ROLE.md" >&2
  fi
  rm -f "$role_slice"
  schema_slice="$(mktemp "${TMPDIR:-/tmp}/schema-slice.XXXXXX")"
  if [ -f scripts/schemas/contracts.schema.json ] \
    && python3 -c 'import json, sys; json.load(open(sys.argv[1])); json.dump(json.load(open(sys.argv[1])), sys.stdout, separators=(",", ":"), ensure_ascii=False)' \
      scripts/schemas/contracts.schema.json > "$schema_slice" 2>/dev/null; then
    emit "$schema_slice" "scripts/schemas/contracts.schema.json (minified, review 2026-08-13)"
  else
    [ -f scripts/schemas/contracts.schema.json ] && emit scripts/schemas/contracts.schema.json
    echo "tpm-pack: schema minification unavailable — shipped the full schema" >&2
  fi
  rm -f "$schema_slice"
  if [ -f "$APPROVED/VERSION" ]; then
    echo "--- CURRENTLY FROZEN SPEC (v$(cat "$APPROVED/VERSION")) — derive any delta from THIS, not from chat memory ---"
    echo
    prd_slice="$(mktemp "${TMPDIR:-/tmp}/prd-slice.XXXXXX")"
    if [ -f "$APPROVED/PRD.md" ] \
      && [ -f "$APPROVED/ERD-DELTA.md" ] \
      && generate_prd_slice "$APPROVED/PRD.md" "$APPROVED/ERD-DELTA.md" > "$prd_slice" 2>/dev/null; then
      emit "$prd_slice" "$APPROVED/PRD.md"
    else
      [ -f "$APPROVED/PRD.md" ] && emit "$APPROVED/PRD.md"
      echo "tpm-pack: current PRD delta unavailable — shipped the full standing PRD" >&2
    fi
    rm -f "$prd_slice"
    if [ -f "$APPROVED/ERD-DELTA.md" ]; then
      # D-117: milestone slice only — the standing ERD arrives as the
      # generated minimal summary; ERD-DELTA.md is the authoritative
      # current-change slice (D-107). Generation failure falls back to the
      # full standing ERD loudly (stderr — the bundle stays clean).
      summary="$(mktemp "${TMPDIR:-/tmp}/standing-summary.XXXXXX")"
      if [ -f "$APPROVED/ERD.md" ] \
        && python3 scripts/standing-summary.py "$APPROVED/ERD.md" > "$summary" 2>/dev/null; then
        emit "$summary" "standing-summary.md (generated from ERD.md — standing rules + per-file map, D-117)"
      else
        [ -f "$APPROVED/ERD.md" ] && emit "$APPROVED/ERD.md"
        echo "tpm-pack: standing summary generation failed — shipped the full standing ERD" >&2
      fi
      rm -f "$summary"
      # D-38 pack-only: strip the execution-side coder briefs / DAG / task
      # scheduling — irrelevant for starting TPM intake of the next feature.
      # Generation failure falls back to the full delta loudly (stderr).
      delta_slice="$(mktemp "${TMPDIR:-/tmp}/erd-delta-slice.XXXXXX")"
      if generate_delta_slice "$APPROVED/ERD-DELTA.md" > "$delta_slice" 2>/dev/null; then
        emit "$delta_slice" "$APPROVED/ERD-DELTA.md"
      else
        emit "$APPROVED/ERD-DELTA.md"
        echo "tpm-pack: ERD-DELTA slice generation failed — shipped the full delta" >&2
      fi
      rm -f "$delta_slice"
    else
      [ -f "$APPROVED/ERD.md" ] && emit "$APPROVED/ERD.md"
    fi
    contracts_slice="$(mktemp "${TMPDIR:-/tmp}/contracts-delta.XXXXXX")"
    if [ -f "$APPROVED/contracts.json" ] \
      && python3 scripts/contracts-delta.py "$APPROVED/contracts.json" > "$contracts_slice" 2>/dev/null; then
      emit "$contracts_slice" "$APPROVED/contracts.json"
    else
      [ -f "$APPROVED/contracts.json" ] && emit "$APPROVED/contracts.json"
      echo "tpm-pack: contracts slice generation failed — shipped the full contracts.json" >&2
    fi
    rm -f "$contracts_slice"
  else
    echo "--- NO FROZEN SPEC YET — this is the initial freeze (v1): a complete spec is required (PRD.md, ERD.md, contracts.json, and the test suite under tests/) ---"
    echo
  fi
  cat <<FTR
=== REPLY FORMAT (mandatory for spec artifacts) ===
Emit every artifact as a COMPLETE file between sentinels, exactly:

=== FILE: <path> ===
<full file content>
=== END FILE ===

Allowed paths ONLY: $ALLOWED_ARTIFACTS
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

if [ "$WANT_CLIPBOARD" -eq 1 ] && [ -n "$copy_cmd" ]; then
  printf '%s\n' "$OUT" | $copy_cmd
  echo "tpm-pack: bundle copied to clipboard ($(printf '%s' "$OUT" | wc -c | tr -d ' ') bytes, $(printf '%s\n' "$OUT" | wc -l | tr -d ' ') lines)." >&2
  echo "tpm-pack: paste it as the FIRST message of a fresh TPM chat, then state your ask." >&2
else
  printf '%s\n' "$OUT"
fi
