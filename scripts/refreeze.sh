#!/usr/bin/env bash
# refreeze.sh — the ONLY path by which frozen TPM artifacts change (D-31).
#
# The TPM (frontier LLM in a human-operated web chat) authors the spec: PRD,
# ERD prose, machine-readable contracts, and the test suite. The operator
# saves the TPM's output (initial spec or an escalation delta) under a staging
# directory and runs this script, which:
#
#   1. runs every mechanical preflight (D-56 externals, D-78 satisfiability,
#      D-87 static-asset reachability, D-88 smoke-check quotes, INV-4 test
#      surface, staged-test parse+lint+determinism),
#   2. shows the full diff and its DIFF-SHA,
#   3. by default: proceeds automatically when every preflight is green
#      (D-95 — the y/N approval was ceremonial once every material check
#      already ran; a verdict nobody consumes is not a gate). Halts on any
#      preflight failure with the specific finding.
#      Explicit paths remain: --diff (print diff, apply nothing),
#      --approve <sha> (D-42 hash-bound apply), --interactive (opt-in y/N
#      for the rare "I want to eyeball this one" case).
#   4. applies the files, re-collects test node-ids, records the delta,
#   5. re-freezes: bumps VERSION, regenerates the hash manifest,
#      commits [refreeze vN].
#
# Wrongness gets a protocol instead of a workaround: frozen artifacts can be
# legitimately revised (bounded, versioned, human-approved) and can NEVER be
# silently mutated — every gate run verifies the frozen-manifest, fail-closed.
#
# Usage:
#   refreeze.sh [<staging-dir>]             auto: preflight-green → apply
#                                           (D-95 default; halts on any
#                                           preflight failure)
#   refreeze.sh --diff [<staging-dir>]      validate + print full diff and its
#                                           DIFF-SHA, apply nothing (agent flow
#                                           step 1: conductor shows this to the CEO)
#   refreeze.sh --approve <sha> [<staging-dir>]
#                                           explicit-apply, D-42: the sha
#                                           must match the recomputed diff hash;
#                                           the conductor's "ask" permission
#                                           prompt on this exact command is the
#                                           human gate — the CEO approves a
#                                           command carrying the hash of the
#                                           diff they read.
#   refreeze.sh --interactive [<staging-dir>]
#                                           opt-in y/N (the pre-D-95 default).
#                                           For the rare case where the CEO
#                                           wants to eyeball this specific
#                                           freeze before it applies.
# Default staging dir: scripts/.approved/incoming
# Staging layout — ONLY the changed files, full new content, paths preserved:
#   PRD.md  ERD.md  ERD-DELTA.md  contracts.json
#                                           -> installed to scripts/.approved/
#                                              (ERD-DELTA.md is required for
#                                              every behavioral re-freeze and
#                                              carries the current milestone;
#                                              ERD.md is standing architecture.)
#   tests/<file>.py ...                     -> installed to tests/
#   REMOVED                                 -> repo paths to retire (one per
#                                              line, tests/*.py only), deleted
#                                              on apply as part of the delta
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
APPROVED="scripts/.approved"

MODE="auto"
APPROVE_SHA=""
case "${1:-}" in
  --diff)        MODE="diff"; shift ;;
  --approve)     MODE="approve"; APPROVE_SHA="${2:?usage: refreeze.sh --approve <sha> [staging-dir]}"; shift 2 ;;
  --interactive) MODE="interactive"; shift ;;
esac
IN="${1:-$APPROVED/incoming}"

die() { echo "REFREEZE FAIL: $*" >&2; exit 1; }

[ -d "$IN" ] || die "staging dir not found: $IN (see docs/ESCALATION.md for the layout)"
[ "$MODE" != "interactive" ] || [ -t 0 ] \
  || die "--interactive requires a terminal — drop the flag (D-95 auto mode) or use --diff / --approve <sha> (D-42)"

V=$(cat "$APPROVED/VERSION" 2>/dev/null || echo 0)
NEW=$((V + 1))
mkdir -p "$APPROVED" tests

# --- Validate staging contents: only known artifact paths ---
# D-104: refreeze and both TPM shuttle directions consume one policy; adding
# an artifact at one boundary cannot silently leave another boundary stale.
if ! ALLOWED_ARTIFACTS=$(python3 scripts/spec_artifacts.py describe); then
  die "shared spec-artifact policy could not be read"
fi
if ! BAD=$(python3 scripts/spec_artifacts.py invalid-under "$IN"); then
  die "shared spec-artifact policy could not validate staging"
fi
if [ -n "$BAD" ]; then
  die "staging contains unexpected files (allowed: $ALLOWED_ARTIFACTS):
$BAD"
fi

CHANGED_DOCS=""
for f in $(python3 scripts/spec_artifacts.py documents); do
  [ -f "$IN/$f" ] && CHANGED_DOCS="$CHANGED_DOCS $f"
done
# Whole-suite TPM returns are common. Presence in staging does not make a
# test changed: only new or byte-different files may widen the delta, trigger
# staged-test gates, or be reinstalled.
CHANGED_TEST_FILES=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if [ ! -f "$f" ] || ! cmp -s "$IN/$f" "$f"; then
    CHANGED_TEST_FILES="${CHANGED_TEST_FILES}${CHANGED_TEST_FILES:+
}$f"
  fi
done < <(cd "$IN" && find tests -type f 2>/dev/null | sed 's|^\./||' | sort || true)
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
    # Bash case-globs match '/', so a literal `tests/*.py` accepts
    # `tests/../scripts/foo.py` — a whitelist the TPM could bypass to
    # rm -f arbitrary paths at apply. Reject traversal before the pattern.
    case "$f" in
      /*|*/../*|../*|*/..|..) die "REMOVED entries must be repo-relative tests/*.py paths (no traversal), got: $f" ;;
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

# --- Lint gate for staged tests (D-67): frozen files cannot be lint-fixed
# without a full refreeze ceremony, so lint debt must be rejected at the
# door — testchat carried 7 unused imports across 30+ freezes because CI
# lints only src/ and nothing linted the incoming suite. Fail-closed on a
# missing ruff by design: a gate that skips silently is not a gate.
if [ -n "$CHANGED_TEST_FILES" ]; then
  command -v ruff >/dev/null 2>&1 \
    || die "ruff not found — the staged-test lint gate (D-67) requires it: pip install ruff"
  for f in $CHANGED_TEST_FILES; do
    case "$f" in
      *.py)
        LINT_OUT=$(ruff check --no-cache "$IN/$f" 2>&1) \
          || die "staged test $f fails lint (D-67 gate):
$LINT_OUT
  -> fix the TPM output and restage; frozen lint debt outlives the freeze"
        ;;
    esac
  done
fi

# --- Determinism gate for staged UI tests (D-58): a flaky frozen test is a
# spec defect, zero retries. Sleeps and timeout-tuned waits are the flake
# factory — reject them at the door; Playwright auto-waiting is the law.
for f in $CHANGED_TEST_FILES; do
  case "$f" in
    *.py)
      if grep -qE '^\s*(import playwright|from playwright)' "$IN/$f"; then
        # Any sleep CALL, under any alias (time.sleep, t.sleep after
        # `import time as t`, bare sleep after `from time import sleep`,
        # asyncio.sleep) — the literal 'time\.sleep' string missed every
        # aliased form (audit find, 2026-07-11). Crude and strict on
        # purpose: a false positive blocks a freeze loudly; a false
        # negative freezes a flake factory silently.
        BAD=$(grep -nE '(^|[^a-zA-Z_])sleep[[:space:]]*\(|wait_for_timeout' "$IN/$f" || true)
        [ -z "$BAD" ] || die "staged UI test $f uses sleep/timeout waits (D-58 determinism gate):
$BAD
  -> rely on Playwright auto-waiting (expect(), locator actions); fix the TPM output and restage"
      fi
      ;;
  esac
done

# --- First freeze must be a complete spec ---
# ERD-DELTA.md is deliberately NOT required at v1: a child project's initial
# freeze is a whole-project spec, not a delta. The split becomes valuable
# once a project accumulates enough standing content that per-milestone diffs
# would otherwise be un-reviewable — an opportunistic upgrade at the next
# spec cycle, not a machinery requirement.
if [ "$V" -eq 0 ]; then
  for f in PRD.md ERD.md contracts.json; do
    [ -f "$IN/$f" ] || die "initial freeze (v1) requires $f in $IN"
  done
  [ -n "$CHANGED_TEST_FILES" ] || die "initial freeze (v1) requires the TPM test suite under $IN/tests/"
fi

# --- D-107: current-milestone spec consistency ------------------------------
# A long-lived project cannot ask the EM to infer the current change from a
# standing ERD that has accumulated dozens of prior milestones. Every
# behavioral re-freeze therefore carries a fresh ERD-DELTA.md with four
# mechanically recognizable sections. The checker also proves that newly
# introduced AC ids and contracts.changed_files occur in that delta.
# A non-behavioral standing-ERD refresh retires the prior delta automatically:
# folding the completed milestone into standing architecture is the explicit
# consolidation point, and the next EM cannot mistake the old slice for new.
if ! SPEC_DELTA_KIND=$(python3 scripts/check-spec-delta.py \
  --staging "$IN" --approved "$APPROVED" --repo . --current-version "$V"); then
  die "current-milestone ERD delta rejected (D-107)"
fi
RETIRE_ERD_DELTA=0
if [ "$SPEC_DELTA_KIND" = "nonbehavioral" ] \
   && [ -f "$APPROVED/ERD-DELTA.md" ] \
   && [ -f "$IN/ERD.md" ] \
   && [ ! -f "$IN/ERD-DELTA.md" ]; then
  RETIRE_ERD_DELTA=1
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

# --- D-78: freeze-time satisfiability preflight ---
# The plan gate's exact plan↔inventory bijection means a new route or
# entry_point whose implementing file is outside contracts.files is
# unimplementable by ANY EM — every plan gets rejected, and the ladder burns
# EM strikes and model swaps against an impossible spec (testchat v51/M28:
# ~75 minutes, two EM swaps, one seat escalation). The unsatisfiability is
# provable from the spec alone, so it is proved HERE, before the human reads
# the diff — in --diff mode too, so the CEO never reviews a doomed delta.
if [ -f "$IN/contracts.json" ]; then
  python3 scripts/validate-plan.py --spec-preflight "$APPROVED/contracts.json" "$IN/contracts.json" \
    || die "satisfiability preflight rejected the delta (D-78) — add the named implementing file(s) to contracts.files (or fix the entry_point) and restage"
fi

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
  if [ "$RETIRE_ERD_DELTA" -eq 1 ]; then
    echo ""
    echo "--- $APPROVED/ERD-DELTA.md (RETIRED — no behavioral delta) ---"
    # Labels suppress diff's file timestamps. /dev/null's timestamp changes
    # between --diff and --approve, which otherwise changes DIFF-SHA even
    # though staging is byte-identical (D-109).
    diff -u --label "$APPROVED/ERD-DELTA.md" --label /dev/null \
      "$APPROVED/ERD-DELTA.md" /dev/null || true
  fi
  for f in $REMOVED_FILES; do
    echo ""
    echo "--- $f (REMOVED) ---"
    diff -u --label "$f" --label /dev/null "$f" /dev/null || true
  done
} > "$DIFF_FILE"
DIFF_SHA=$(sha256sum "$DIFF_FILE" | awk '{print $1}')

echo "=============================================="
echo "  Re-freeze: spec v$V -> v$NEW"
echo "=============================================="
cat "$DIFF_FILE"

# --- D-56 visibility: the capture gate only fires on DECLARED externals, and
# nothing mechanical can prove a spec touches no external interface. The only
# non-gate action is a heuristic: when a spec declares ZERO externals but the
# staged artifacts reference URLs, surface a focused warning — declaring
# externals is the one actor the human knows about, and testchat froze v8 and
# v9 with externals undeclared (the capture gate could never fire). Zero
# externals with no URL evidence is silent by design — it is the common case
# and the unconditional note was retired 2026-08-02 (repeated warnings
# desensitize; the plan gate and the freeze-time human review remain).
EXT_COUNT=$(SWBP_C="$EXT_CONTRACTS" python3 -c \
  "import json,os; print(len(json.load(open(os.environ['SWBP_C'])).get('externals') or []))" \
  2>/dev/null || echo 0)
if [ "$EXT_COUNT" -eq 0 ]; then
  _http_hits=$( { grep -rlE 'https?://' "$IN/tests" "$IN/contracts.json" 2>/dev/null || true; } | head -5)
  if [ -n "$_http_hits" ]; then
    echo ""
    echo "  WARNING (D-56): staged artifacts reference http(s):// URLs but the"
    echo "  spec declares ZERO external interfaces — likely undeclared externals"
    echo "  (the v8/v9 class). HALT and demand probes+captures from the TPM"
    echo "  before running the pipeline:"
    echo "$_http_hits" | sed 's/^/    /'
  fi
else
  echo ""
  echo "  D-56: $EXT_COUNT declared external interface(s); captures verified above."
fi

# --- D-80: D-68 debt sweep on the delta's inventory (advisory) ---------------
# The D-68 gate fires on a file's FIRST post-D-68 pipeline edit, so
# pre-existing unjustified handlers in a legacy inventory file fail the gate
# mid-run regardless of the new work. Fired twice: app.js (2026-07-17,
# cleared by live-fix) and models.py T11 (M28 — forced the v54 recut, and
# both local EMs revised the WRONG handler during the escalation). The
# 07-17 template-debt note recorded the class; recording is not mechanizing.
# Surface the debt HERE, at spec time, so remediation directives (M28c
# style) enter the spec on day one. Advisory by design: the right response
# may be a justification comment, a remediation directive, or acceptance —
# a TPM/CEO call, not a freeze blocker.
SWEEP_FILES=$(SWBP_C="$INV4_CONTRACTS" python3 -c "
import json, os, pathlib
c = json.load(open(os.environ['SWBP_C']))
print('\n'.join(f for f in c.get('files', []) if pathlib.Path(f).is_file()))" 2>/dev/null || true)
if [ -n "$SWEEP_FILES" ]; then
  SWEEP_ARGS=()
  while IFS= read -r _f; do [ -n "$_f" ] && SWEEP_ARGS+=("$_f"); done <<< "$SWEEP_FILES"
  if ! SWEEP_OUT=$(python3 scripts/check-swallowed-errors.py "${SWEEP_ARGS[@]}"); then
    echo ""
    echo "  WARNING (D-80): pre-existing D-68 debt in this delta's inventory —"
    echo "  each file's first pipeline edit will FAIL the swallowed-error gate"
    echo "  on these OLD handlers regardless of the new work (M28 v54 recut"
    echo "  class). Get remediation directives into THIS spec, or bounce it:"
    echo "$SWEEP_OUT" | sed 's/^/    /'
  fi
fi

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

# --- Approval gate ---
# D-95 auto (default): every mechanical preflight above already died on hard
# failure — reaching this line means the artifact IS approved by the gates
# the pipeline actually enforces. The old interactive y/N prompted the CEO
# after that point, on artifacts the gates had already cleared, on a diff
# the CEO could not judge (~62KB re-touched ERDs turned it into a
# rubber-stamp for five straight testchat refreezes v60–v64; CEO delegated
# the approval to the model 2026-07-27 as an interim). Auto proceeds; the
# DIFF-SHA above is the audit trail; the escalation paths that DO summon
# the CEO stay untouched (--diff for pre-review, --approve <sha> for
# D-42 explicit apply, --interactive for opt-in eyeball).
case "$MODE" in
  approve)
    # D-42: hash-bound explicit apply. The human gate is the conductor's
    # "ask" permission prompt on this exact command — approving it means
    # approving THIS diff, because the sha on the command line must equal
    # the hash of the recomputed diff.
    [ "$APPROVE_SHA" = "$DIFF_SHA" ] \
      || die "diff hash mismatch — staging changed since the CEO reviewed it (expected $DIFF_SHA, got $APPROVE_SHA). Re-run --diff and re-approve."
    echo ""
    echo "approved via diff-hash $DIFF_SHA (D-42)"
    ;;
  interactive)
    # Opt-in eyeball path — rare, for freezes the CEO chose to inspect.
    echo ""
    printf 'Approve this delta and re-freeze as v%s? [y/N] ' "$NEW"
    read -r ANSWER
    case "$ANSWER" in
      y|Y|yes|YES) ;;
      *) echo "aborted — nothing changed"; exit 1 ;;
    esac
    ;;
  auto)
    echo ""
    echo "auto-approved (D-95): all mechanical preflights green; DIFF-SHA $DIFF_SHA"
    ;;
esac

# --- Apply ---
for f in $CHANGED_DOCS; do
  cp "$IN/$f" "$APPROVED/$f"
done
if [ "$RETIRE_ERD_DELTA" -eq 1 ]; then
  rm -f "$APPROVED/ERD-DELTA.md"
fi
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
#
# pytest runs only in the sandbox (the canonical Linux environment). Static
# AST collection remains the non-executing fallback when imports are not yet
# buildable; generated tests never execute on the operator's host.
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
COLLECT_VIA="sandbox"
scripts/sandbox-run.sh -- pytest tests/ --collect-only -q -p no:cacheprovider \
  >"$COLLECT_OUT" 2>"$COLLECT_ERR" || true
PYTEST_NODEIDS=$(grep '::' "$COLLECT_OUT" || true)
PYTEST_COUNT=$(printf '%s\n' "$PYTEST_NODEIDS" | grep -c '::' || true)

if [ "$PYTEST_COUNT" -gt "$AST_COUNT" ]; then
  echo "  pytest: $PYTEST_COUNT node-ids via $COLLECT_VIA (>AST, using pytest — parametrized expansion)"
  NODEIDS="$PYTEST_NODEIDS"
elif [ "$PYTEST_COUNT" -eq "$AST_COUNT" ]; then
  echo "  pytest: $PYTEST_COUNT node-ids via $COLLECT_VIA (matches AST, using pytest)"
  NODEIDS="$PYTEST_NODEIDS"
else
  echo "  pytest: $PYTEST_COUNT node-ids (<AST in sandbox — import errors likely, using static AST; tests were not run on the host)"
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
# D-86: changed_files is a PER-DELTA declaration. A freeze that does not stage
# contracts.json declares no scope of its own — inheriting the previous
# version's list would silently widen this delta.
CONTRACTS_STAGED=0
case " $CHANGED_DOCS " in *" contracts.json "*) CONTRACTS_STAGED=1 ;; esac
python3 - "$NEW" "$APPROVED/test-nodeids" "$CONTRACTS_STAGED" <<'PYEOF'
import json, sys
from pathlib import Path
new_v, nodeids_path = int(sys.argv[1]), sys.argv[2]
contracts_staged = sys.argv[3] == "1"
def lines(p):
    return [line for line in Path(p).read_text().splitlines() if line.strip()]
old_nodeids = set(lines(".pipeline-state/refreeze-old-nodeids"))
new_nodeids = set(lines(nodeids_path))
changed_files = set(lines(".pipeline-state/refreeze-changed-files"))
changed_tests = sorted(
    (old_nodeids - new_nodeids)                                      # removed
    | {n for n in new_nodeids if n.split("::")[0] in changed_files}  # in changed files
)
# D-86: the TPM's own scope declaration. Until D-86 this was hardcoded [],
# so the coder's editable set was reachable only through the EM's test
# mapping — scope, a containment boundary, set implicitly by the mid tier.
# validate-plan.py's preflight has already proved every entry is an editable
# inventory member, so copy it through verbatim.
declared_files = []
if contracts_staged:
    contracts = json.load(open("scripts/.approved/contracts.json"))
    declared_files = [f for f in contracts.get("changed_files", []) if f]
delta = {
    "changed_contract_ids": lines(".pipeline-state/refreeze-changed-contracts"),
    "changed_tests": changed_tests,
    "changed_files": declared_files,
}
with open(f"scripts/.approved/DELTA-v{new_v}.json", "w") as f:
    json.dump(delta, f, indent=2)
if not (delta["changed_contract_ids"] or changed_tests or declared_files):
    print("  WARNING (D-86): this delta scopes NOTHING — no changed tests, no "
          "changed contract ids, no declared changed_files. With the inverted "
          "no-edit default every existing file is untouchable, so a run will "
          "invoke the coder for nothing and report normally. If a milestone is "
          "unbuilt, declare its files in contracts.changed_files and re-freeze.")
PYEOF
rm -f "$TMP/refreeze-old-nodeids" "$TMP/refreeze-changed-files" "$TMP/refreeze-changed-contracts"

# --- D-75: red-before-green check on the delta (warn-only) -------------------
# INV-1 means a newly frozen test is written before the code it gates. Run the
# delta's tests NOW, against the pre-implementation tree: any that already
# PASS will never observe the milestone being built and gate nothing — the
# green-suite/broken-app family (v6/M5 imagined mocks; M16's hit-counter
# counting hidden DOM text). Legitimate early passes exist (no_edit_files
# acceptance per D-65, carried-forward behavior), so this surfaces a claim
# for the human, never a halt. changed_tests includes REMOVED node-ids —
# filter to ids that exist in the new frozen set before running.
RED_IDS=$(python3 - "$NEW" "$APPROVED/test-nodeids" <<'PYEOF'
import json, sys
from pathlib import Path
new_v, nodeids_path = sys.argv[1], sys.argv[2]
current = set(Path(nodeids_path).read_text().splitlines())
delta = json.load(open(f"scripts/.approved/DELTA-v{new_v}.json"))
print("\n".join(t for t in delta.get("changed_tests", []) if t in current))
PYEOF
)
if [ -n "$RED_IDS" ]; then
  echo "red-before-green check (D-75): running $(printf '%s\n' "$RED_IDS" | grep -c '::') delta test(s) against the pre-implementation tree..."
  mkdir -p .cache
  RED_ARGS=()
  while IFS= read -r _t; do [ -n "$_t" ] && RED_ARGS+=("$_t"); done <<< "$RED_IDS"
  rm -f .cache/redcheck-report.json
  scripts/sandbox-run.sh --rw .cache -- pytest -p no:cacheprovider --json-report \
    --json-report-file=.cache/redcheck-report.json "${RED_ARGS[@]}" >/dev/null 2>&1 || true
  if ! python3 -c 'import json; json.load(open(".cache/redcheck-report.json"))' 2>/dev/null; then
    die "red-before-green sandbox produced no readable report — run refreeze inside the Linux dev VM; staged tests are never executed on the host"
  fi
  python3 - <<'PYEOF'
import json
r = json.load(open(".cache/redcheck-report.json"))
passed = sorted(t["nodeid"] for t in r.get("tests", [])
                if t.get("outcome") == "passed")
print("  red-check ran via: sandbox")
if passed:
    print("")
    print("  WARNING (D-75): delta test(s) ALREADY PASS with no implementation done:")
    for n in passed:
        print(f"    {n}")
    print("  A test that never goes red gates nothing. Expected only for no_edit_files")
    print("  acceptance (D-65) or carried-forward behavior — anything else is a vacuous")
    print("  test: bounce it back to the TPM before running the pipeline.")
else:
    print("  red-check: all delta tests red pre-implementation, as INV-1 expects")
PYEOF
  rm -f .cache/redcheck-report.json
else
  echo "red-before-green check (D-75): delta carries no runnable test changes — nothing to check"
fi

# --- Re-freeze: hash-pin every frozen artifact, bump VERSION ---
{
  for f in $(python3 scripts/spec_artifacts.py documents) test-nodeids; do
    [ -f "$APPROVED/$f" ] && sha256sum "$APPROVED/$f"
  done
  # Pin every file under tests/ (not only .py): non-.py fixtures a TPM
  # could stage would otherwise install unpinned, and the phase-gate
  # cross-check (INV-1 addition coverage) requires the disk set and
  # pinned set to be equal. Bytecode caches (__pycache__, .pytest_cache)
  # are runtime artifacts a pytest run creates — hashing them
  # into the manifest guarantees a "spec tampered" halt on the next
  # test run (testchat M25 hit this three times in one session).
  find tests -type f \
    -not -path '*/__pycache__/*' \
    -not -path '*/.pytest_cache/*' \
    | sort | while read -r f; do sha256sum "$f"; done
  if [ -d "$APPROVED/captures" ]; then
    find "$APPROVED/captures" -type f | sort | while read -r f; do sha256sum "$f"; done
  fi
} > "$APPROVED/frozen-manifest"
echo "$NEW" > "$APPROVED/VERSION"

# --- Commit the durable record; consume the staging dir ---
git add tests/ "$APPROVED/frozen-manifest" "$APPROVED/VERSION" \
  "$APPROVED/test-nodeids" "$APPROVED/DELTA-v$NEW.json"
for f in $CHANGED_DOCS; do git add "$APPROVED/$f"; done
if [ "$RETIRE_ERD_DELTA" -eq 1 ]; then git add "$APPROVED/ERD-DELTA.md"; fi
for f in $CHANGED_CAPTURES; do git add "$APPROVED/$f"; done
git commit -m "[refreeze v$NEW]"
rm -rf "$IN"

echo ""
echo "=============================================="
echo "  Frozen as v$NEW"
echo "  Next: run scripts/orchestrate.sh — only the"
echo "  affected subtree is reset and re-run."
echo "=============================================="
