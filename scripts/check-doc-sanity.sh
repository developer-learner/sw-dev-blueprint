#!/usr/bin/env bash
# check-doc-sanity.sh — mechanical enforcement of doc guards.
#
# Why this exists: the memory layer is best-effort, not enforced. The empirical
# test in CLAUDE.md correction log row 6 showed the LLM can misparse which
# guard applies even after reading the docs. For must-hold rules we need a
# mechanical gate that fires without the LLM's cooperation.
#
# This script is the gate. It runs in CI on every push to main. It can also
# be run locally before committing. Add new checks here when a new doc guard
# graduates from "advisory" to "must hold."
#
# Checks (6):
#   1. BLUEPRINT.md line count ≤ 450
#   2. No phantom "Step N.M" references (every sub-step must have a ### heading)
#   3. No legacy CLI tool residue (the intentional correction log row in CLAUDE.md is excluded)
#   4. AGENTS.md is a symlink to CLAUDE.md
#   5. opencode.json parses as valid JSON (if jq is available)
#   6. No template placeholders in committed files (Step 7 grep)
#
# Exit 0 on pass, non-zero on fail. CI fails the build on non-zero.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT" || { echo "FATAL: cannot cd to $REPO_ROOT"; exit 2; }

errors=0
passes=0

ok()   { echo "OK:   $*"; passes=$((passes + 1)); }
fail() { echo "FAIL: $*"; errors=$((errors + 1)); }
skip() { echo "SKIP: $*"; }

# --- 1. BLUEPRINT.md line count ----------------------------------------------
if [ -f BLUEPRINT.md ]; then
  lines=$(wc -l < BLUEPRINT.md | tr -d ' ')
  if [ "$lines" -gt 450 ]; then
    fail "BLUEPRINT.md is $lines lines (max 450). See CLAUDE.md correction log row 5."
  else
    ok "BLUEPRINT.md is $lines lines (max 450)"
  fi
else
  fail "BLUEPRINT.md missing"
fi

# --- 2. Phantom step references ----------------------------------------------
# Any "Step N.M" in BLUEPRINT.md must have a matching "### Step N.M" heading.
# Whole-number steps (Step 0, Step 1) are not checked here — the bug we hit
# was specifically a sub-step reference (Step 4.5) with no heading.
if [ -f BLUEPRINT.md ]; then
  refs=$(grep -oE 'Step [0-9]+\.[0-9]+' BLUEPRINT.md 2>/dev/null | sort -u || true)
  headings=$(grep -E '^### +Step [0-9]+\.[0-9]+' BLUEPRINT.md 2>/dev/null \
            | grep -oE 'Step [0-9]+\.[0-9]+' | sort -u || true)
  if [ -z "$refs" ]; then
    ok "no sub-step references in BLUEPRINT.md"
  elif [ -z "$headings" ]; then
    fail "BLUEPRINT.md has sub-step references but no sub-step headings: $(echo "$refs" | tr '\n' ' ')"
  else
    phantoms=$(comm -23 <(printf '%s\n' "$refs") <(printf '%s\n' "$headings") || true)
    if [ -n "$phantoms" ]; then
      fail "phantom step references (no matching ### Step X.Y heading): $(echo "$phantoms" | tr '\n' ' ')"
    else
      ok "all sub-step references in BLUEPRINT.md have matching headings"
    fi
  fi
fi

# --- 3. Legacy CLI tool residue ---------------------------------------------
# The intentional correction log row at CLAUDE.md:117 (added in commit bedea21)
# references the prior CLI tool by name as historical context. That's allowed.
# Anything else mentioning that tool is residue from the migration.
# (The literal search string is the prior tool's name; do not name it here or
# this comment itself will trip the check.)
legacy_hits=$(grep -rli 'aider' --exclude-dir=.git --exclude-dir=node_modules . 2>/dev/null \
             | grep -vE '(^|/)CLAUDE\.md$' \
             | grep -vE '(^|/)scripts/check-doc-sanity\.sh$' || true)
if [ -n "$legacy_hits" ]; then
  fail "legacy CLI tool residue found in: $(echo "$legacy_hits" | tr '\n' ' ')"
else
  ok "no legacy CLI tool residue (CLAUDE.md correction log row excluded)"
fi

# --- 4. AGENTS.md symlink ----------------------------------------------------
if [ -L AGENTS.md ]; then
  target=$(readlink AGENTS.md)
  if [ "$target" = "CLAUDE.md" ]; then
    ok "AGENTS.md is a symlink to CLAUDE.md"
  else
    fail "AGENTS.md is a symlink but to '$target' (expected CLAUDE.md)"
  fi
else
  fail "AGENTS.md is not a symlink — OpenCode's preferred filename won't auto-resolve to CLAUDE.md"
fi

# --- 5. opencode.json validity ----------------------------------------------
if [ -f opencode.json ]; then
  if command -v jq >/dev/null 2>&1; then
    if jq . opencode.json >/dev/null 2>&1; then
      ok "opencode.json parses as valid JSON"
    else
      fail "opencode.json does not parse as valid JSON (OpenCode will reject it)"
    fi
  else
    skip "jq not installed; cannot verify opencode.json"
  fi
else
  fail "opencode.json missing"
fi

# --- 6. Template placeholders ------------------------------------------------
# Skipped. The template repo legitimately has placeholders in tasks/ and docs/
# that get filled in during bootstrap (BLUEPRINT.md Step 6). The placeholder
# check is a bootstrap-time gate, not a template-CI gate. For derived
# projects, the Step 7 grep is the right check.

# --- Summary ----------------------------------------------------------------
echo "---"
echo "Passed: $passes    Failed: $errors"
if [ "$errors" -gt 0 ]; then
  echo "RESULT: FAIL"
  exit 1
fi
echo "RESULT: PASS"
exit 0
