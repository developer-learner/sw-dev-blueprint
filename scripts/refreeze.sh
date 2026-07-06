#!/usr/bin/env bash
# refreeze.sh — the ONLY path by which frozen TPM artifacts change (D-31).
#
# The TPM (frontier LLM in a human-operated web chat) authors the spec: PRD,
# ERD prose, machine-readable contracts, and the test suite. The operator
# saves the TPM's output (initial spec or an escalation delta) under a staging
# directory and runs this script, which:
#
#   1. shows the human a full diff of what would change,
#   2. requires human approval — interactive y/N, or the D-42 hash-bound
#      --diff / --approve flow (THE approval gate — no honor-strings),
#   3. applies the files, re-collects test node-ids, records the delta,
#   4. re-freezes: bumps VERSION, regenerates the hash manifest,
#      commits [refreeze vN].
#
# Wrongness gets a protocol instead of a workaround: frozen artifacts can be
# legitimately revised (bounded, versioned, human-approved) and can NEVER be
# silently mutated — every gate run verifies the frozen-manifest, fail-closed.
#
# Usage:
#   refreeze.sh [<staging-dir>]             interactive y/N (default gate, D-31)
#   refreeze.sh --diff [<staging-dir>]      validate + print full diff and its
#                                           DIFF-SHA, apply nothing (agent flow
#                                           step 1: conductor shows this to the CEO)
#   refreeze.sh --approve <sha> [<staging-dir>]
#                                           non-interactive apply, D-42: the sha
#                                           must match the recomputed diff hash;
#                                           the OpenCode "ask" permission prompt
#                                           on this exact command is the human
#                                           gate — the CEO approves a command
#                                           carrying the hash of the diff they read.
# Default staging dir: scripts/.approved/incoming
# Staging layout — ONLY the changed files, full new content, paths preserved:
#   PRD.md  ERD.md  contracts.json          -> installed to scripts/.approved/
#   tests/<file>.py ...                     -> installed to tests/
#   REMOVED                                 -> repo paths to retire (one per
#                                              line, tests/*.py only), deleted
#                                              on apply as part of the delta
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
APPROVED="scripts/.approved"

MODE="interactive"
APPROVE_SHA=""
case "${1:-}" in
  --diff)    MODE="diff"; shift ;;
  --approve) MODE="approve"; APPROVE_SHA="${2:?usage: refreeze.sh --approve <sha> [staging-dir]}"; shift 2 ;;
esac
IN="${1:-$APPROVED/incoming}"

die() { echo "REFREEZE FAIL: $*" >&2; exit 1; }

[ -d "$IN" ] || die "staging dir not found: $IN (see docs/ESCALATION.md for the layout)"
[ "$MODE" != "interactive" ] || [ -t 0 ] \
  || die "interactive refreeze requires a terminal — the human diff-approval IS the gate (agents: use --diff then --approve <sha>, D-42)"

V=$(cat "$APPROVED/VERSION" 2>/dev/null || echo 0)
NEW=$((V + 1))
mkdir -p "$APPROVED" tests

# --- Validate staging contents: only known artifact paths ---
BAD=$(cd "$IN" && find . -type f \
  ! -path "./PRD.md" ! -path "./ERD.md" ! -path "./contracts.json" \
  ! -path "./REMOVED" ! -path "./tests/*" ! -path "./captures/*" | sed 's|^\./||')
if [ -n "$BAD" ]; then
  die "staging contains unexpected files (only PRD.md, ERD.md, contracts.json, REMOVED, tests/*, captures/* are frozen artifacts):
$BAD"
fi

CHANGED_DOCS=""
for f in PRD.md ERD.md contracts.json; do
  [ -f "$IN/$f" ] && CHANGED_DOCS="$CHANGED_DOCS $f"
done
CHANGED_TEST_FILES=$(cd "$IN" && find tests -type f 2>/dev/null | sed 's|^\./||' || true)
CHANGED_CAPTURES=$(cd "$IN" && find captures -type f 2>/dev/null | sed 's|^\./||' || true)

# --- Test-file removals: staging may carry a REMOVED file listing repo
# paths (one per line, tests/*.py only) to retire as part of this delta.
# Retiring a test is a spec change like any other — it goes through the
# same human-approved diff, never a hand-delete in the frozen lane
# (testchat M2: stale echo tests had to be hand-deleted, a conductor
# lane-cross forced by the tool).
REMOVED_FILES=""
if [ -f "$IN/REMOVED" ]; then
  REMOVED_FILES=$(grep -vE '^\s*(#|$)' "$IN/REMOVED" || true)
  for f in $REMOVED_FILES; do
    case "$f" in
      tests/*.py) ;;
      *) die "REMOVED entries must be tests/*.py paths, got: $f" ;;
    esac
    [ -f "$f" ] || die "REMOVED lists a file that does not exist in the repo: $f"
    [ ! -f "$IN/$f" ] || die "REMOVED lists a file also present in staging (conflict — pick one): $f"
  done
fi
[ -n "$CHANGED_DOCS$CHANGED_TEST_FILES$CHANGED_CAPTURES$REMOVED_FILES" ] || die "staging dir is empty — nothing to freeze"

# --- Staged tests must at least parse (testchat M4: TPM shipped tests with
# broken indentation and bare `---` lines; discovering it post-freeze cost a
# full refreeze cycle v4->v5). ast.parse is the cheapest possible gate and
# needs none of the suite's imports to exist.
for f in $CHANGED_TEST_FILES; do
  case "$f" in
    *.py)
      SWBP_STAGED="$IN/$f" python3 - <<'PYEOF' || exit 1
import ast, os, sys
p = os.environ["SWBP_STAGED"]
try:
    ast.parse(open(p).read(), filename=p)
except SyntaxError as e:
    sys.exit(f"REFREEZE FAIL: staged test does not parse: {p}:{e.lineno}: {e.msg} — fix the TPM output and restage")
PYEOF
      ;;
  esac
done

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

# --- D-56: declared externals must carry captured reality ---
# Every contracts.externals entry names a capture (raw probe output recorded
# from the REAL dependency). A freeze that declares an external without its
# capture is the v6/M5 failure mode — mocks built from the TPM's imagination
# — and is rejected here. Staged captures nobody references are also
# rejected (dead weight in the frozen spec).
EXT_CONTRACTS="$APPROVED/contracts.json"
[ -f "$IN/contracts.json" ] && EXT_CONTRACTS="$IN/contracts.json"
if [ -f "$EXT_CONTRACTS" ]; then
  SWBP_IN="$IN" SWBP_APPROVED="$APPROVED" python3 - "$EXT_CONTRACTS" <<'PYD56' || exit 1
import json, os, sys
from pathlib import Path
c = json.load(open(sys.argv[1]))
staging, approved = os.environ["SWBP_IN"], os.environ["SWBP_APPROVED"]
errs, referenced = [], set()
for e in c.get("externals", []):
    if not (isinstance(e, dict) and e.get("id") and e.get("probe") and e.get("capture")):
        errs.append("every contracts.externals entry needs id, probe and capture"); break
    cap = e["capture"]
    if not cap.startswith("captures/") or ".." in cap:
        errs.append(f"{e['id']}: capture must be a captures/ path, got {cap!r}"); continue
    referenced.add(cap)
    src = Path(staging, cap) if Path(staging, cap).is_file() else Path(approved, cap)
    if not src.is_file():
        errs.append(f"{e['id']}: capture not found in staging or {approved}: {cap} "
                    f"(run the probe against the real dependency and stage its raw output)")
    elif cap.endswith(".json"):
        try:
            json.load(open(src))
        except json.JSONDecodeError as ex:
            errs.append(f"{e['id']}: capture is not valid JSON: {cap}: {ex}")
cap_dir = Path(staging, "captures")
staged = {str(p.relative_to(staging)) for p in cap_dir.rglob("*") if p.is_file()} if cap_dir.is_dir() else set()
orphans = sorted(staged - referenced)
if orphans:
    errs.append("staged captures not referenced by any contracts.externals entry: " + ", ".join(orphans))
if errs:
    sys.exit("REFREEZE FAIL (D-56): " + "; ".join(errs))
PYD56
elif [ -n "$CHANGED_CAPTURES" ]; then
  die "staging has captures/ but no contracts.json declares them (D-56: captures enter only via contracts.externals)"
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
for f in $REMOVED_FILES; do rm -f "$PREVIEW/$f"; done   # preview reflects the post-delta suite
INV4_CONTRACTS="$APPROVED/contracts.json"
[ -f "$IN/contracts.json" ] && INV4_CONTRACTS="$IN/contracts.json"
python3 scripts/check-test-surface.py --tests-dir "$PREVIEW/tests" --contracts "$INV4_CONTRACTS" \
  || die "INV-4 rejected the delta — fix the tests or lock the surface in contracts.json, then restage"

# --- Build the full diff (deterministic — its hash is the approval token) ---
DIFF_FILE=".pipeline-state/refreeze-pending.diff"
mkdir -p .pipeline-state
show_diff() {  # $1 current-path  $2 incoming-path
  if [ -f "$1" ]; then
    diff -u "$1" "$2" || true   # rc 1 = differences; that is the point
  else
    echo "(new file)"
    cat "$2"
  fi
}
{
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
  for f in $CHANGED_CAPTURES; do
    echo ""
    echo "--- $APPROVED/$f ---"
    show_diff "$APPROVED/$f" "$IN/$f"
  done
  for f in $REMOVED_FILES; do
    echo ""
    echo "--- $f (REMOVED) ---"
    diff -u "$f" /dev/null || true   # full current content shown as deletions
  done
} > "$DIFF_FILE"
DIFF_SHA=$(sha256sum "$DIFF_FILE" | awk '{print $1}')

echo "=============================================="
echo "  Re-freeze: spec v$V -> v$NEW"
echo "=============================================="
cat "$DIFF_FILE"

if [ "$MODE" = "diff" ]; then
  echo ""
  echo "DIFF-SHA: $DIFF_SHA"
  echo "(nothing applied — to install, the CEO approves:"
  echo "  scripts/refreeze.sh --approve $DIFF_SHA $IN)"
  exit 0
fi

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
if [ "$MODE" = "approve" ]; then
  # D-42: non-interactive path. The human gate is the OpenCode "ask" prompt on
  # this exact command line — approving it means approving THIS diff, because
  # the sha on the command line must equal the hash of the recomputed diff.
  [ "$APPROVE_SHA" = "$DIFF_SHA" ] \
    || die "diff hash mismatch — staging changed since the CEO reviewed it (expected $DIFF_SHA, got $APPROVE_SHA). Re-run --diff and re-approve."
  echo ""
  echo "approved via diff-hash $DIFF_SHA (D-42)"
else
  echo ""
  printf 'Approve this delta and re-freeze as v%s? [y/N] ' "$NEW"
  read -r ANSWER
  case "$ANSWER" in
    y|Y|yes|YES) ;;
    *) echo "aborted — nothing changed"; exit 1 ;;
  esac
fi

# --- Apply ---
for f in $CHANGED_DOCS; do
  cp "$IN/$f" "$APPROVED/$f"
done
for f in $CHANGED_TEST_FILES; do
  mkdir -p "$(dirname "$f")"
  cp "$IN/$f" "$f"
done
for f in $REMOVED_FILES; do
  rm -f "$f"    # `git add tests/` below stages the deletion
done
for f in $CHANGED_CAPTURES; do
  mkdir -p "$APPROVED/$(dirname "$f")"
  cp "$IN/$f" "$APPROVED/$f"
done

# --- Re-collect the frozen test node-ids ---
# D-51 revised: AST extraction is the PRIMARY method, not a fallback.
# INV-1 means tests are written before the code they import — pytest
# --collect-only can fail partially (symbols not yet created) or fully
# (modules not yet created), producing incomplete node-id sets that corrupt
# the manifest. AST extraction finds every def test_* without importing
# anything. pytest is tried second as a SUPPLEMENT: if it succeeds and
# finds MORE node-ids (parametrized tests expand at collect time), its set
# replaces the AST set. If it fails or finds fewer, AST wins.
echo "collecting test node-ids..."
AST_NODEIDS=$(python3 - <<'PYEOF'
import ast
from pathlib import Path
out = []
for f in sorted(Path("tests").rglob("*.py")):
    name = f.name
    if not (name.startswith("test_") or name.endswith("_test.py")):
        continue
    tree = ast.parse(f.read_text(), filename=str(f))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out.append(f"{f}::{node.name}")
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test"):
                    out.append(f"{f}::{node.name}::{m.name}")
print("\n".join(out))
PYEOF
)
AST_COUNT=$(printf '%s\n' "$AST_NODEIDS" | grep -c '::' || true)
if [ "$AST_COUNT" -eq 0 ]; then
  die "AST found no test functions in tests/ — a frozen spec without a suite cannot gate anything"
fi
echo "  AST: $AST_COUNT node-ids"

COLLECT_OUT=".pipeline-state/refreeze-collect.out"
COLLECT_ERR=".pipeline-state/refreeze-collect.err"
scripts/sandbox-run.sh -- pytest --collect-only -q -p no:cacheprovider \
  >"$COLLECT_OUT" 2>"$COLLECT_ERR" || true
PYTEST_NODEIDS=$(grep '::' "$COLLECT_OUT" || true)
PYTEST_COUNT=$(printf '%s\n' "$PYTEST_NODEIDS" | grep -c '::' || true)

if [ "$PYTEST_COUNT" -gt "$AST_COUNT" ]; then
  echo "  pytest: $PYTEST_COUNT node-ids (>AST, using pytest — parametrized expansion)"
  NODEIDS="$PYTEST_NODEIDS"
elif [ "$PYTEST_COUNT" -eq "$AST_COUNT" ]; then
  echo "  pytest: $PYTEST_COUNT node-ids (matches AST, using pytest)"
  NODEIDS="$PYTEST_NODEIDS"
else
  echo "  pytest: $PYTEST_COUNT node-ids (<AST — import errors likely, using AST)"
  NODEIDS="$AST_NODEIDS"
fi
rm -f "$COLLECT_OUT" "$COLLECT_ERR"
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
  if [ -d "$APPROVED/captures" ]; then
    find "$APPROVED/captures" -type f | sort | while read -r f; do sha256sum "$f"; done
  fi
} > "$APPROVED/frozen-manifest"
echo "$NEW" > "$APPROVED/VERSION"

# --- Commit the durable record; consume the staging dir ---
git add tests/ "$APPROVED/frozen-manifest" "$APPROVED/VERSION" \
  "$APPROVED/test-nodeids" "$APPROVED/DELTA-v$NEW.json"
for f in $CHANGED_DOCS; do git add "$APPROVED/$f"; done
for f in $CHANGED_CAPTURES; do git add "$APPROVED/$f"; done
git commit -m "[refreeze v$NEW]"
rm -rf "$IN"

echo ""
echo "=============================================="
echo "  Frozen as v$NEW"
echo "  Next: run scripts/orchestrate.sh — only the"
echo "  affected subtree is reset and re-run."
echo "=============================================="
