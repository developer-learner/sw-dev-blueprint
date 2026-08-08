#!/usr/bin/env bash
# doc-consistency.sh — warning-only scan for retired-decision prose (2026-08-07).
#
# NOT a gate. Every D-entry that retires a flag/criterion (D-121 removed the
# refreeze approval path; D-112 replaced the full-suite completion criterion)
# leaves a doc ripple: state-describing docs keep instructing the removed
# behavior until someone sweeps them, and grep-based sweeps keep missing
# phrasings (four passes, six instances, 2026-08-07). This script is the
# regression insurance: it greps the ENUMERATED state-describing docs for
# the ENUMERATED retired tokens and WARNS on a reintroducing commit.
#
# Why warning-only: doc prose has zero runtime impact (nothing reads it),
# so per D-115 (gate strength ∝ blast radius) a blocking gate over prose is
# disproportionate. The pre-commit hook calls this and never fails on it.
#
# Maintenance rule (the only way it stays honest): when a future decision
# retires a flag, criterion, or default, add its distinctive stale phrase to
# TOKENS in the same commit. Historical records (DECISIONS.md, project-trail,
# correction log) are deliberately NOT in DOCS — they stay verbatim.
#
# Usage: doc-consistency.sh [--root DIR]   (default: git toplevel / CWD)
# Exit: 0 always (warning). Silent when clean.
set -euo pipefail

ROOT="${PWD}"
if [ "${1:-}" = "--root" ]; then
  ROOT="${2:?--root needs a dir}"
elif [ -n "${1:-}" ]; then
  echo "doc-consistency: unknown argument: $1" >&2
  exit 2
fi
[ -d "$ROOT" ] || { echo "doc-consistency: not a dir: $ROOT" >&2; exit 2; }

# State-describing docs only. Historical records stay verbatim and excluded:
# DECISIONS.md, project-trail/, correction-log tables, HANDOFF files.
DOCS=(
  "INTRO.md"
  "BLUEPRINT.md"
  "CLAUDE.md"
  "README.md"
  "QUICKSTART.md"
  "CONVENTIONS.md"
  "docs/CEO-PLAYBOOK.md"
  "docs/TPM-ROLE.md"
  "docs/CONDUCTOR-ROLE.md"
  "docs/ESCALATION.md"
  "docs/ARCHITECTURE.md"
  "docs/TESTING.md"
  "docs/BROWSER-ORACLE-DESIGN.md"
  "tasks/CURRENT.md"
  "examples/minimal-spec/README.md"
)

# Retired-decision tokens, regex, case-insensitive. Add one line per future
# decision that retires a flag/criterion/default. Tokens must match ONLY the
# stale instruction — the canonical replacement wording often embeds the old
# phrase in negative/qualified form ("no human approval step", "the full
# frozen suite is an on-demand regression check") and must NOT warn.
TOKENS=(
  "frozen suite is green"                    # D-112: full-suite completion criterion
  "frozen suite green"                       # D-112: same, = done / bare form
  "full suite green"                         # D-112: example-doc variant
  "only definition of done"                  # D-112: claim wording
  "ONE full-suite run closes the milestone"  # D-112: TESTING.md cadence
  "interactive y/N"                          # D-121/D-96: y/N as the refreeze/update flow
  "through your y/N"                         # D-121: escalation routing
  "CEO approval"                             # D-121: removed approval step
  "approve.*the freeze"                      # D-121: removed approval step
)

# CLAUDE.md embeds the correction log (historical table rows, verbatim).
# Filter rows that start with "| 20..." so they never warn.
claude_filter() {
  grep -vE '^[0-9]+:\| *20'
}

found=0
for doc in "${DOCS[@]}"; do
  [ -f "$ROOT/$doc" ] || continue
  for tok in "${TOKENS[@]}"; do
    if [ "$doc" = "CLAUDE.md" ]; then
      hits=$(grep -inE "$tok" "$ROOT/$doc" | claude_filter || true)
    else
      hits=$(grep -inE "$tok" "$ROOT/$doc" || true)
    fi
    if [ -n "$hits" ]; then
      [ "$found" -eq 0 ] && {
        echo ""
        echo "DOC-CONSISTENCY WARNING (non-blocking, 2026-08-07): stale retired-decision prose"
        echo "  These lines still instruct a removed flag/criterion. Fix them before this"
        echo "  commit merges, or the next reader gets the pre-decision mental model."
        echo ""
      }
      found=1
      echo "$hits" | while IFS= read -r line; do
        echo "  $doc: $line"
      done
    fi
  done
done

if [ "$found" -eq 1 ]; then
  echo ""
  echo "  (warning only — commit proceeds. Historical records are exempt by design.)"
fi
exit 0
