#!/usr/bin/env bash
# refreeze.sh — the ONLY path by which frozen TPM artifacts change (D-31).
#
# The TPM (frontier LLM in a human-operated web chat) authors the spec: PRD,
# ERD prose, machine-readable contracts, and the test suite. The operator
# saves the TPM's output (initial spec or an escalation delta) under a staging
# directory and runs this script, which:
#
#   1. shows the human a full diff of what would change,
#   2. requires an interactive y/N (THE approval gate — no honor-strings),
#   3. applies the files, re-collects test node-ids, records the delta,
#   4. re-freezes: bumps VERSION, regenerates the hash manifest,
#      commits [refreeze vN].
#
# Wrongness gets a protocol instead of a workaround: frozen artifacts can be
# legitimately revised (bounded, versioned, human-approved) and can NEVER be
# silently mutated — every gate run verifies the frozen-manifest, fail-closed.
#
# Usage: refreeze.sh <staging-dir>          (default: scripts/.approved/incoming)
# Staging layout — ONLY the changed files, full new content, paths preserved:
#   PRD.md  ERD.md  contracts.json          -> installed to scripts/.approved/
#   tests/<file>.py ...                     -> installed to tests/
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
APPROVED="scripts/.approved"
IN="${1:-$APPROVED/incoming}"

die() { echo "REFREEZE FAIL: $*" >&2; exit 1; }

[ -d "$IN" ] || die "staging dir not found: $IN (see docs/ESCALATION.md for the layout)"
[ -t 0 ] || die "refreeze requires an interactive terminal — the human diff-approval IS the gate"

V=$(cat "$APPROVED/VERSION" 2>/dev/null || echo 0)
NEW=$((V + 1))
mkdir -p "$APPROVED" tests

# --- Validate staging contents: only known artifact paths ---
BAD=$(cd "$IN" && find . -type f \
  ! -path "./PRD.md" ! -path "./ERD.md" ! -path "./contracts.json" \
  ! -path "./tests/*" | sed 's|^\./||')
if [ -n "$BAD" ]; then
  die "staging contains unexpected files (only PRD.md, ERD.md, contracts.json, tests/* are frozen artifacts):
$BAD"
fi

CHANGED_DOCS=""
for f in PRD.md ERD.md contracts.json; do
  [ -f "$IN/$f" ] && CHANGED_DOCS="$CHANGED_DOCS $f"
done
CHANGED_TEST_FILES=$(cd "$IN" && find tests -type f 2>/dev/null | sed 's|^\./||' || true)
[ -n "$CHANGED_DOCS$CHANGED_TEST_FILES" ] || die "staging dir is empty — nothing to freeze"

# --- First freeze must be a complete spec ---
if [ "$V" -eq 0 ]; then
  for f in PRD.md ERD.md contracts.json; do
    [ -f "$IN/$f" ] || die "initial freeze (v1) requires $f in $IN"
  done
  [ -n "$CHANGED_TEST_FILES" ] || die "initial freeze (v1) requires the TPM test suite under $IN/tests/"
fi

# --- Sanity-check incoming contracts against the schema's structural core ---
if [ -f "$IN/contracts.json" ]; then
  python3 - "$IN/contracts.json" "$NEW" <<'PYEOF' || exit 1
import json, sys
p, new_v = sys.argv[1], int(sys.argv[2])
try:
    c = json.load(open(p))
except json.JSONDecodeError as e:
    sys.exit(f"REFREEZE FAIL: contracts.json is not valid JSON: {e}")
errs = []
if not isinstance(c.get("files"), list) or not c["files"]:
    errs.append("contracts.files must be a non-empty array (the ERD build inventory)")
if not isinstance(c.get("entry_points"), list):
    errs.append("contracts.entry_points must be an array")
if c.get("erd_version") != new_v:
    errs.append(f"contracts.erd_version must be {new_v} (the version being frozen), got {c.get('erd_version')!r}")
for key in ("routes", "schemas", "errors"):
    for e in c.get(key, []):
        if not isinstance(e, dict) or not e.get("id"):
            errs.append(f"every entry in contracts.{key} needs an 'id'")
            break
if errs:
    sys.exit("REFREEZE FAIL: " + "; ".join(errs))
PYEOF
fi

# --- INV-4: test-visible surface ⊆ locked surface, checked on the MERGED
# preview (current frozen state + incoming overlay) BEFORE the human sees the
# approval prompt. A TPM test that reaches past the contracts is rejected
# here — it never gets frozen (D-32).
PREVIEW="$(mktemp -d)"
trap 'rm -rf "$PREVIEW"' EXIT
mkdir -p "$PREVIEW/tests"
[ -d tests ] && cp -R tests/. "$PREVIEW/tests/" 2>/dev/null || true
[ -d "$IN/tests" ] && cp -R "$IN/tests/." "$PREVIEW/tests/"
INV4_CONTRACTS="$APPROVED/contracts.json"
[ -f "$IN/contracts.json" ] && INV4_CONTRACTS="$IN/contracts.json"
python3 scripts/check-test-surface.py --tests-dir "$PREVIEW/tests" --contracts "$INV4_CONTRACTS" \
  || die "INV-4 rejected the delta — fix the tests or lock the surface in contracts.json, then restage"

# --- Show the human the full diff ---
echo "=============================================="
echo "  Re-freeze: spec v$V -> v$NEW"
echo "=============================================="
show_diff() {  # $1 current-path  $2 incoming-path
  if [ -f "$1" ]; then
    diff -u "$1" "$2" || true   # rc 1 = differences; that is the point
  else
    echo "(new file)"
    cat "$2"
  fi
}
for f in $CHANGED_DOCS; do
  echo ""
  echo "--- $APPROVED/$f ---"
  show_diff "$APPROVED/$f" "$IN/$f"
done
for f in $CHANGED_TEST_FILES; do
  echo ""
  echo "--- $f ---"
  show_diff "$f" "$IN/$f"
done

# --- Record what changes BEFORE applying (drives the affected-subtree reset) ---
OLD_NODEIDS=$(cat "$APPROVED/test-nodeids" 2>/dev/null || true)
DELTA_CONTRACTS=""
if [ -f "$IN/contracts.json" ]; then
  DELTA_CONTRACTS=$(python3 - "$APPROVED/contracts.json" "$IN/contracts.json" <<'PYEOF'
import json, sys
from pathlib import Path
old_p, new_p = sys.argv[1], sys.argv[2]
def entries(path):
    if not Path(path).exists():
        return {}
    c = json.load(open(path))
    out = {}
    for ep in c.get("entry_points", []):
        out[ep] = ("entry_point", ep)
    for key in ("routes", "schemas", "errors"):
        for e in c.get(key, []):
            out[e["id"]] = (key, json.dumps(e, sort_keys=True))
    return out
old, new = entries(old_p), entries(new_p)
changed = sorted(
    set(k for k in old if k not in new)            # removed
    | set(k for k in new if k not in old)          # added
    | set(k for k in new if k in old and old[k] != new[k])  # modified
)
print("\n".join(changed))
PYEOF
  )
fi

# --- The human approval gate ---
echo ""
printf 'Approve this delta and re-freeze as v%s? [y/N] ' "$NEW"
read -r ANSWER
case "$ANSWER" in
  y|Y|yes|YES) ;;
  *) echo "aborted — nothing changed"; exit 1 ;;
esac

# --- Apply ---
for f in $CHANGED_DOCS; do
  cp "$IN/$f" "$APPROVED/$f"
done
for f in $CHANGED_TEST_FILES; do
  mkdir -p "$(dirname "$f")"
  cp "$IN/$f" "$f"
done

# --- Re-collect the frozen test node-ids (inside the sandbox, read-only) ---
echo "collecting test node-ids..."
NODEIDS=$(scripts/sandbox-run.sh -- pytest --collect-only -q -p no:cacheprovider 2>/dev/null \
  | grep '::' || true)
[ -n "$NODEIDS" ] || die "pytest collected no tests — a frozen spec without a suite cannot gate anything"
printf '%s\n' "$NODEIDS" > "$APPROVED/test-nodeids"

# --- Record the delta for the orchestrator's affected-subtree reset (D-31) ---
TMP=".pipeline-state"
mkdir -p "$TMP"
printf '%s\n' "$OLD_NODEIDS"        > "$TMP/refreeze-old-nodeids"
printf '%s\n' "$CHANGED_TEST_FILES" > "$TMP/refreeze-changed-files"
printf '%s\n' "$DELTA_CONTRACTS"    > "$TMP/refreeze-changed-contracts"
python3 - "$NEW" "$APPROVED/test-nodeids" <<'PYEOF'
import json, sys
from pathlib import Path
new_v, nodeids_path = int(sys.argv[1]), sys.argv[2]
def lines(p):
    return [l for l in Path(p).read_text().splitlines() if l.strip()]
old_nodeids = set(lines(".pipeline-state/refreeze-old-nodeids"))
new_nodeids = set(lines(nodeids_path))
changed_files = set(lines(".pipeline-state/refreeze-changed-files"))
changed_tests = sorted(
    (old_nodeids - new_nodeids)                                      # removed
    | {n for n in new_nodeids if n.split("::")[0] in changed_files}  # in changed files
)
delta = {
    "changed_contract_ids": lines(".pipeline-state/refreeze-changed-contracts"),
    "changed_tests": changed_tests,
    "changed_files": [],
}
with open(f"scripts/.approved/DELTA-v{new_v}.json", "w") as f:
    json.dump(delta, f, indent=2)
PYEOF
rm -f "$TMP/refreeze-old-nodeids" "$TMP/refreeze-changed-files" "$TMP/refreeze-changed-contracts"

# --- Re-freeze: hash-pin every frozen artifact, bump VERSION ---
{
  for f in PRD.md ERD.md contracts.json test-nodeids; do
    [ -f "$APPROVED/$f" ] && sha256sum "$APPROVED/$f"
  done
  find tests -type f -name "*.py" | sort | while read -r f; do sha256sum "$f"; done
} > "$APPROVED/frozen-manifest"
echo "$NEW" > "$APPROVED/VERSION"

# --- Commit the durable record; consume the staging dir ---
git add tests/ "$APPROVED/frozen-manifest" "$APPROVED/VERSION" \
  "$APPROVED/test-nodeids" "$APPROVED/DELTA-v$NEW.json"
for f in $CHANGED_DOCS; do git add "$APPROVED/$f"; done
git commit -m "[refreeze v$NEW]"
rm -rf "$IN"

echo ""
echo "=============================================="
echo "  Frozen as v$NEW"
echo "  Next: run scripts/orchestrate.sh — only the"
echo "  affected subtree is reset and re-run."
echo "=============================================="
