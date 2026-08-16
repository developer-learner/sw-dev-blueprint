#!/usr/bin/env bash
# tpm-view.sh — build the materialized TPM view (D-162).
#
# INV-1's read side goes structural: instead of a settings allowlist binding
# only as long as the harness has no gap (the softness tpm-agent.sh admits),
# this materializes a directory the agent is rooted in where the
# implementation physically is not present — no src/, no .git/, no
# project-trail/, no .pipeline-state/. "A tighter policy is not a boundary";
# this is the boundary.
#
# View contents (only what the TPM legitimately reads):
#   spec artifacts   PRD.md, ERD.md, ERD-DELTA.md, contracts.json, captures/
#                    from scripts/.approved/ (the spec_artifacts.py policy set)
#   tests/           copied for delta authoring — never edited in place;
#                    deltas land in outbox/tests/ and refreeze installs them
#   escalations/     BATCH.md + per-item bundle.md — the air-gap-sanctioned
#                    TPM surface (D-29/D-38), minus src/ path lines
#   TPM-ROLE.md      the seat's job description
#   outbox -> ../outbox   symlink: writes land in .tpm/outbox for refreeze
#
# Every absent artifact warns to stderr and is skipped — never a silent
# context loss (the template repo ships no frozen spec of its own).
#
# Usage: tpm-view.sh           (from the project root; then launch with
#     cd .tpm/view && claude --settings ../../scripts/tpm-view-settings.json)
#   or one step: scripts/tpm-agent.sh --view
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd -P)"

APPROVED="scripts/.approved"
VIEW=".tpm/view"
ESC=".pipeline-state/escalations"

mkdir -p .tpm/outbox
rm -rf "$VIEW"
mkdir -p "$VIEW/escalations"

# 1. Spec artifacts — the spec_artifacts.py policy set, absent ones warned.
for doc in PRD.md ERD.md ERD-DELTA.md contracts.json; do
  if [ -f "$APPROVED/$doc" ]; then
    cp "$APPROVED/$doc" "$VIEW/$doc"
  else
    echo "tpm-view: WARNING — no $APPROVED/$doc to materialize (skipped)" >&2
  fi
done
if [ -d "$APPROVED/captures" ]; then
  cp -R "$APPROVED/captures" "$VIEW/captures"
else
  echo "tpm-view: WARNING — no $APPROVED/captures to materialize (skipped)" >&2
fi

# 2. Frozen tests (copy; prune caches).
if [ -d tests ]; then
  cp -R tests "$VIEW/tests"
  find "$VIEW/tests" -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
else
  echo "tpm-view: WARNING — no tests/ to materialize (skipped)" >&2
fi

# 3. Escalation evidence — the sanctioned TPM surface (D-29/D-38), minus
#    src/ path lines (implementation references are not oracle material).
if [ -f "$ESC/BATCH.md" ]; then
  grep -vE '^[[:space:]]*(src|\./src)/' "$ESC/BATCH.md" > "$VIEW/escalations/BATCH.md"
fi
for b in "$ESC"/*/bundle.md; do
  [ -f "$b" ] || continue
  local_n="$(basename "$(dirname "$b")")-bundle.md"
  grep -vE '^[[:space:]]*(src|\./src)/' "$b" > "$VIEW/escalations/$local_n"
done

# 4. The seat's job description.
if [ -f docs/TPM-ROLE.md ]; then
  cp docs/TPM-ROLE.md "$VIEW/TPM-ROLE.md"
else
  echo "tpm-view: WARNING — no docs/TPM-ROLE.md to materialize (skipped)" >&2
fi

# 5. The write lane: outbox symlink -> .tpm/outbox (refreeze's pickup).
ln -s ../outbox "$VIEW/outbox"

ALLOWED=$(python3 scripts/spec_artifacts.py describe) || {
  echo "tpm-view: shared spec-artifact policy unavailable" >&2
  exit 1
}
echo "tpm-view: materialized view at .tpm/view/ — src/ absent by construction"
echo "  spec artifacts (policy): $ALLOWED"
echo "  frozen tests: $(find "$VIEW/tests" -type f 2>/dev/null | wc -l | tr -d ' ') file(s)"
echo "  escalations: $(ls "$VIEW/escalations" 2>/dev/null | wc -l | tr -d ' ') file(s)"
echo "  launch: cd .tpm/view && claude --settings ../../scripts/tpm-view-settings.json"