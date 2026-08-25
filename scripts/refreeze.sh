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
#   3. applies automatically when every preflight is green (D-95, then
#      D-121): the y/N and hash-bound approvals were ceremonial once every
#      material check already ran — a verdict nobody consumes is not a gate.
#      The CEO ruling (2026-08-06): "remove ceo approval for refreeze run —
#      the business ceo or human can't add any value there." There is NO
#      human approval step in this lane; halts on any preflight failure
#      with the specific finding. --diff remains as a read-only dry-run
#      preview (prints the diff and DIFF-SHA, applies nothing).
#   4. applies the files, re-collects test node-ids, records the delta,
#   5. re-freezes: bumps VERSION, regenerates the hash manifest,
#      commits [refreeze vN].
#
# Wrongness gets a protocol instead of a workaround: frozen artifacts can be
# legitimately revised (bounded, versioned, gate-approved) and can NEVER be
# silently mutated — every gate run verifies the frozen-manifest, fail-closed.
#
# Usage:
#   refreeze.sh [<staging-dir>]             auto: preflight-green → apply
#                                           (D-95/D-121; halts on any
#                                           preflight failure)
#   refreeze.sh --diff [<staging-dir>]      validate + print full diff and its
#                                           DIFF-SHA, apply nothing (read-only
#                                           preview; the install is the same
#                                           command without the flag)
# Default staging dir: scripts/.approved/incoming
# Staging layout — ONLY the changed files, full new content, paths preserved:
#   PRD.md  ERD.md  ERD-DELTA.md  contracts.json
#                                           -> installed to scripts/.approved/
#                                              (ERD-DELTA.md is required for
#                                              every behavioral re-freeze;
#                                              apply also preserves its exact
#                                              ERD-DELTA-vN.md snapshot.)
#   tests/<file>.py ...                     -> installed to tests/
#   REMOVED                                 -> repo paths to retire (one per
#                                              line, tests/*.py only), deleted
#                                              on apply as part of the delta
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
APPROVED="scripts/.approved"

MODE="auto"
case "${1:-}" in
  --diff)        MODE="diff"; shift ;;
esac
IN="${1:-$APPROVED/incoming}"

die() { echo "REFREEZE FAIL: $*" >&2; exit 1; }

# D-151: refreeze MUTATES the tree (installs docs/tests, deletes REMOVED
# files, bumps VERSION) before committing; a commit failure on a missing git
# identity would leave the tree half-applied with no recovery. orchestrate.sh
# pre-flights identity for the same reason (its commits deliberately swallow
# failures); refreeze is the destructive one, so it fails closed BEFORE any
# mutation. --diff is read-only and skips this.
if [ "$MODE" != "diff" ]; then
  { [ -n "$(git config user.email || true)" ] && [ -n "$(git config user.name || true)" ]; } \
    || die "git identity missing — the freeze commit would fail after the tree was already mutated: git config --global user.email <addr> && git config --global user.name <name>"
fi

# D-152: fail fast on stock macOS. Operational freezes belong in the Linux
# dev VM (orchestrate.sh hard-dies on Darwin for the same constraint), and
# stock macOS lacks sha256sum — the old failure was a confusing "command not
# found" mid-flow. macOS hosts with GNU coreutils can run the fixture-level
# apply path (the selftest suite does exactly that), so those proceed with a
# loud warning instead of a blanket die.
if [ "$(uname -s)" = "Darwin" ]; then
  if ! command -v sha256sum >/dev/null 2>&1; then
    die "sha256sum not found — refreeze needs GNU coreutils (macOS ships shasum -a 256 instead); run operational freezes inside the Linux dev VM (docs/DEV-VM-SETUP.md) or install coreutils"
  fi
  echo "WARNING: running refreeze on macOS — operational freezes belong inside the Linux dev VM (docs/DEV-VM-SETUP.md)" >&2
fi

case "${1:-}" in
  --approve|--interactive)
    die "the ${1} approval path was removed (D-121) — refreeze installs by gate verdict once every preflight is green; use --diff for a read-only preview" ;;
esac

[ -d "$IN" ] || die "staging dir not found: $IN (see docs/ESCALATION.md for the layout)"

V=$(cat "$APPROVED/VERSION" 2>/dev/null || echo 0)
NEW=$((V + 1))
mkdir -p "$APPROVED" tests

# --- In-the-wild catch ledger (D-170) --------------------------------------
# A gate that rejects a real delta is evidence of utility. Each hard gate
# below records its catch before dying; tiering + cost accounting reads the
# ledger. The record is best-effort and must never mask the gate's verdict —
# the die is the gate, the ledger is the witness.
record_catch() {
  python3 scripts/catch-ledger.py record --gate "$1" --spec-version "$NEW" \
    >/dev/null 2>&1 || true
}

# --- Staging exclusion is structural, not conventional (vortex 2026-08-22) --
# Every lane check downstream scopes itself with ':(exclude)<staging>' and
# trusts that exclusion; if the staging dir is NOT gitignored, staged
# artifacts ride `git add -A` into a [refreeze] commit — they did exactly
# that in vortex's first freeze — and orchestrate's clean-tree preflight
# misfires on leftover staging. Verify with git itself instead of trusting
# each child's .gitignore to be right.
if [ -d "$IN" ] && ! git check-ignore -q "$IN"; then
  die "$IN is not gitignored — add '$IN/' to .gitignore. The frozen lane excludes this path by name everywhere; an unignored staging dir leaks staged artifacts into freeze commits and dirties every clean-tree preflight."
fi

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
  while IFS= read -r f; do
    [ -n "$f" ] || continue
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
  done <<< "$REMOVED_FILES"
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
# --- D-136: staged contracts merge (PRODUCER, never authority) ---------------
# contracts.json enters as a STAGED MERGE ARTIFACT, not a full-file
# replacement: the TPM stages only changed/new id-array entries (each
# `file`-pinned) plus D-137's explicit family-scoped `remove` tombstones;
# contracts-merge.py reconstructs the full contracts.json by overlaying them
# onto the standing file, proving mechanically that it touched nothing it did
# not name (byte-identical carried remainder; a staged entry identical to
# standing fails closed; omission never deletes). The merge runs BEFORE every
# contracts-consuming gate so each sees the MERGED file, never the raw partial:
# check-spec-delta (D-107/D-122 — a partial would read every omitted id-array
# as changed and defeat the invisible-change guard), D-56, INV-4, the D-78
# preflight, the DELTA, the apply, the manifest. The merge is transparent — the
# gates see the same full contracts a return would have produced. At v1 (no
# standing) the staged file IS the full spec, so no merge runs. Runs in --diff
# too, so the CEO never previews a merge the pipeline will reject.
MERGED_CONTRACTS="$IN/contracts.json"
if [ -f "$IN/contracts.json" ] && [ "$V" -gt 0 ] && [ -f "$APPROVED/contracts.json" ]; then
  mkdir -p .pipeline-state
  MERGED_CONTRACTS=".pipeline-state/refreeze-merged-contracts.json"
  python3 scripts/contracts-merge.py "$APPROVED/contracts.json" "$IN/contracts.json" \
    > "$MERGED_CONTRACTS" \
    || die "staged contracts merge rejected (D-136/D-137) — see the id named above; the TPM stages only changed/new entries or explicit removals onto the standing contracts.json"
fi

if ! SPEC_DELTA_KIND=$(python3 scripts/check-spec-delta.py \
  --staging "$IN" --approved "$APPROVED" --repo . --current-version "$V" \
  --contracts "$MERGED_CONTRACTS"); then
  record_catch check-spec-delta
  die "current-milestone ERD delta rejected (D-107)"
fi
RETIRE_ERD_DELTA=0
if [ "$SPEC_DELTA_KIND" = "nonbehavioral" ] \
   && [ -f "$APPROVED/ERD-DELTA.md" ] \
   && [ -f "$IN/ERD.md" ] \
   && [ ! -f "$IN/ERD-DELTA.md" ]; then
  RETIRE_ERD_DELTA=1
fi

# --- S5: state-changing ACs must carry post-condition clauses -----------
# The M29 defect class: ACs specifying mechanisms ("SIGINT the process")
# without observable postconditions ("such that the health endpoint returns
# 503") produce tests that cannot fail and implementations that can fail
# silently (5 of 8 process-lifecycle ACs; correction log 2026-07-25). Any
# staged PRD or ERD-DELTA carrying a state-changing AC without a "such that"
# clause is rejected before it enters the frozen spec.
S5_FILES=""
for _s5f in PRD.md ERD-DELTA.md; do
  [ -f "$IN/$_s5f" ] && S5_FILES="$S5_FILES $IN/$_s5f"
done
if [ -n "$S5_FILES" ]; then
  python3 scripts/check-ac-postconditions.py $S5_FILES \
    || { record_catch check-ac-postconditions; die "S5 rejected: state-changing AC(s) without 'such that' post-condition clause — every AC that spawns/terminates/kills/unloads/evicts/deletes/releases/clears/cancels MUST name an observable check"; }
fi

# --- D-136: PRD additive-only guard ------------------------------------------
# The PRD is the standing product record; a milestone adds to it, never
# silently drops from it. A staged PRD must carry the standing product capsule
# unchanged and retain every historical AC id — a vanished criterion is either
# an accident or an unrecorded supersession, and supersessions go through the
# ERD-DELTA (D-107), which keeps the id. Runs only over an existing PRD (v>1);
# fires in --diff too, so the CEO never previews a lossy PRD.
if [ -f "$IN/PRD.md" ] && [ -f "$APPROVED/PRD.md" ]; then
  python3 scripts/check-prd-additive.py "$APPROVED/PRD.md" "$IN/PRD.md" \
    || { record_catch check-prd-additive; die "PRD additive guard rejected the delta (D-136) — a staged PRD must carry the standing product capsule and every historical AC id; record supersessions in ERD-DELTA.md, do not delete the criterion"; }
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
if not isinstance(c.get("files"), list):
    errs.append("contracts.files must be an array (empty means no behavioral build work)")
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
[ -f "$IN/contracts.json" ] && EXT_CONTRACTS="$MERGED_CONTRACTS"
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
while IFS= read -r f; do [ -n "$f" ] || continue; rm -f "$PREVIEW/$f"; done <<< "$REMOVED_FILES"   # preview reflects the post-delta suite
INV4_CONTRACTS="$APPROVED/contracts.json"
[ -f "$IN/contracts.json" ] && INV4_CONTRACTS="$MERGED_CONTRACTS"
python3 scripts/check-test-surface.py --tests-dir "$PREVIEW/tests" --contracts "$INV4_CONTRACTS" \
  || { record_catch check-test-surface; die "INV-4 rejected the delta — fix the tests or lock the surface in contracts.json, then restage"; }

# --- S6: reverse-direction test lint (live tests vs NEW ACs) ------------
# The v58 defect class (correction log 2026-07-25): the forward lints check
# STAGED tests against live ACs, but a carried-forward test that mocked every
# URL silently coupled with a new AC the other way — the AC's guard never ran
# and an unsatisfiable assertion shipped. Runs on the merged preview (current
# frozen suite + incoming overlay), scoped to the tests this delta touches
# (D-128 amend): any whole-world mock the delta introduces, and any
# carried-forward test citing an AC this delta adds, is rejected at freeze.
# A legacy whole-world mock in an UNtouched carried test is grandfathered —
# a hard halt on old content would freeze the pipeline (9 such patterns
# exist in testchat's live suite as of this writing).
python3 scripts/check-test-direction.py --tests-dir "$PREVIEW/tests" \
  --staging "$IN" --approved "$APPROVED" --repo-tests tests \
  || { record_catch check-test-direction; die "S6 rejected the delta (reverse-direction lint) — see findings above; restage a URL-scoped test or re-attribute the AC"; }

# --- D-78: freeze-time satisfiability preflight ---
# The plan gate's exact plan↔inventory bijection means a new route or
# entry_point whose implementing file is outside contracts.files is
# unimplementable by ANY EM — every plan gets rejected, and the ladder burns
# EM strikes and model swaps against an impossible spec (testchat v51/M28:
# ~75 minutes, two EM swaps, one seat escalation). The unsatisfiability is
# provable from the spec alone, so it is proved HERE, before the human reads
# the diff — in --diff mode too, so the CEO never reviews a doomed delta.
if [ -f "$IN/contracts.json" ]; then
  python3 scripts/validate-plan.py --spec-preflight "$APPROVED/contracts.json" "$MERGED_CONTRACTS" \
    || { record_catch validate-plan; die "satisfiability preflight rejected the delta (D-78) — add the named implementing file(s) to contracts.files (or fix the entry_point) and restage"; }
fi

# --- Item 1: every changed test function must carry an owning-file pin ---
# testchat v99: the AC-161 oracle was a genuinely NEW test riding no
# test_mapping pin — the file-granular milestone slice emptied its task and
# the default verdict could pass without running it. The function-level delta
# (finding-1) names exactly which test functions this freeze adds or modifies;
# each must pin its owner file in contracts.test_mapping or the ERD-DELTA
# "## Test-to-file mapping" section AT FREEZE TIME. Infra-level changes
# (fixtures/helpers/imports) and carried tests stay grandfathered — only the
# function-granular term is gated (S6/D-128 lesson: a whole-file pin demand
# would halt every freeze on a 50-test file whose fixture changed). Runs in
# --diff mode too, so the CEO never reviews a delta the pipeline will reject.
PIN_GATE_ARGS=(--old-root . --new-root "$IN")
[ -f "$IN/contracts.json" ] && PIN_GATE_ARGS+=(--test-mapping "$IN/contracts.json")
[ -f "$IN/ERD-DELTA.md" ] && PIN_GATE_ARGS+=(--erd-delta "$IN/ERD-DELTA.md")
if ! python3 scripts/refreeze_delta.py pin-gate "${PIN_GATE_ARGS[@]}" \
    $CHANGED_TEST_FILES; then
  record_catch refreeze_delta-pin-gate
  die "owning-file pin gate rejected the delta — every added or modified test function must name its owner file in contracts.test_mapping (or the ERD-DELTA '## Test-to-file mapping' section); see the listing above and restage"
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
    if [ "$f" = "contracts.json" ]; then
      show_diff "$APPROVED/$f" "$MERGED_CONTRACTS"   # D-136: preview the merged result, not the delta
    else
      show_diff "$APPROVED/$f" "$IN/$f"
    fi
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
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    echo ""
    echo "--- $f (REMOVED) ---"
    diff -u --label "$f" --label /dev/null "$f" /dev/null || true
  done <<< "$REMOVED_FILES"
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
  _http_hits=$( { grep -rlE 'https?://' "$IN/tests" "$MERGED_CONTRACTS" 2>/dev/null || true; } | head -5)
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
  echo "(nothing applied — dry-run preview. Install by re-running without flags:"
  echo "  scripts/refreeze.sh $IN)"
  echo "  The mechanical preflights above ARE the verdict (D-121)."
  exit 0
fi

# --- Record what changes BEFORE applying (drives the affected-subtree reset) ---
OLD_NODEIDS=$(cat "$APPROVED/test-nodeids" 2>/dev/null || true)
DELTA_CONTRACTS=""
if [ -f "$IN/contracts.json" ]; then
  DELTA_CONTRACTS=$(python3 - "$APPROVED/contracts.json" "$MERGED_CONTRACTS" <<'PYEOF'
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
    # "ui" walks with the id-bearing families: pre-fix it was omitted, so a
    # ui-only freeze produced an empty delta — silently pre-D-86, then as a
    # false D-86 halt (testchat M31 break-log finding #5; D-86 alt (b)).
    for key in ("routes", "schemas", "errors", "ui"):
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

# Pre-apply snapshot of the frozen contracts: the M35 smoke red-check
# compares against THIS, not against the installed copy (which by the time
# the check runs has already been overwritten by the apply).
mkdir -p .pipeline-state
cp "$APPROVED/contracts.json" .pipeline-state/refreeze-old-contracts.json 2>/dev/null || true

# --- Apply decision ---
# D-95 (auto default) then D-121 (2026-08-06): every mechanical preflight
# above already died on hard failure — reaching this line means the artifact
# IS approved by the gates the pipeline actually enforces. The old y/N
# prompted the CEO after that point, on artifacts the gates had already
# cleared, on a diff the CEO could not judge (~62KB re-touched ERDs turned
# it into a rubber-stamp for five straight testchat refreezes v60–v64).
# D-121 removes the remaining approval paths (--approve hash-bound apply,
# --interactive y/N) entirely, per the CEO ruling that a human verdict adds
# no value on a machine-authored diff whose gates already ran. The DIFF-SHA
# above is the audit trail.
echo ""
echo "auto-approved (D-121): all mechanical preflights green; DIFF-SHA $DIFF_SHA"

# --- Snapshot the pre-apply test sources (function-level delta, finding-1) ---
# refreeze_delta.py diffs each staged test file's OLD bytes (this snapshot)
# against the NEW bytes (the applied tree) at FUNCTION granularity, so the
# DELTA's changed_tests names exactly the test functions this freeze changed
# instead of every test in a touched file. A brand-new test file has no old
# source: refreeze_delta.py treats it as fully changed, which is correct.
mkdir -p .pipeline-state/old-tests
for f in $CHANGED_TEST_FILES; do
  [ -f "$f" ] || continue
  mkdir -p ".pipeline-state/old-tests/$(dirname "$f")"
  cp "$f" ".pipeline-state/old-tests/$f"
done

# --- Transactional guard (D-151) ---
# The apply below mutates the frozen lane; a failed commit rolls back to HEAD
# (git restore --source=HEAD), which is only sound if the lane had no
# pre-existing uncommitted edits to clobber. The frozen lane is committed by
# every prior refreeze, so dirt here is a real anomaly, not a normal state.
# The incoming/ staging dir is excluded from the lane by construction: it is
# untracked in real repos (gitignored), consumed on success, and preserved
# on failure for retry — the rollback must never touch it.
if [ -n "$(git status --porcelain -- tests/ scripts/.approved/ ':(exclude)scripts/.approved/incoming')" ]; then
  die "frozen lane is dirty before apply (uncommitted changes in tests/ or scripts/.approved/ outside the incoming/ staging dir) — commit or stash them first; a failed freeze commit must roll back to HEAD safely"
fi

# --- Apply ---
# Transactional apply (extends D-151): from the first mutation below until
# the freeze commit succeeds, ANY failure — not only a failed commit — must
# leave the frozen lane exactly as HEAD had it (the Vortex first-freeze run:
# the M35 smoke red-check died after the apply and left tests/spec
# half-applied). The handler chains the PREVIEW cleanup the earlier trap
# owned, restores tracked lane files, and git-cleans files this apply
# CREATED (new DELTA-vN.json / ERD-DELTA-vN.md are untracked if the failure
# precedes git add). incoming/ staging is never touched: it survives a
# failed freeze for retry.
REFREEZE_APPLIED=0
on_refreeze_exit() {
  rc=$?
  rm -rf "$PREVIEW"
  [ "$rc" -eq 0 ] && return 0
  [ "$REFREEZE_APPLIED" = "1" ] || return 0
  echo "REFREEZE FAIL: failure after apply (rc=$rc) — rolling back the applied freeze to HEAD" >&2
  git restore --source=HEAD --staged --worktree -- tests/ scripts/.approved/ ':(exclude)scripts/.approved/incoming' \
    || echo "REFREEZE WARNING: rollback restore failed — inspect tests/ and scripts/.approved/ manually before retrying" >&2
  git clean -f -- tests/ scripts/.approved/ ':(exclude)scripts/.approved/incoming' \
    || echo "REFREEZE WARNING: rollback clean failed — inspect tests/ and scripts/.approved/ manually before retrying" >&2
}
trap on_refreeze_exit EXIT
REFREEZE_APPLIED=1
VERSIONED_ERD_DELTA=""
for f in $CHANGED_DOCS; do
  if [ "$f" = "contracts.json" ]; then
    cp "$MERGED_CONTRACTS" "$APPROVED/$f"   # D-136: install the merged full file
  else
    cp "$IN/$f" "$APPROVED/$f"
  fi
done
if [ -f "$IN/ERD-DELTA.md" ]; then
  VERSIONED_ERD_DELTA="$APPROVED/ERD-DELTA-v$NEW.md"
  cp "$IN/ERD-DELTA.md" "$VERSIONED_ERD_DELTA"
elif [ "$V" -eq 0 ]; then
  # The first freeze is a whole-project instruction slice, so its complete
  # ERD is also the immutable v1 delta snapshot. v1 deliberately does not
  # require the TPM to duplicate that content in ERD-DELTA.md, but D-140's
  # active-range planner still requires a versioned snapshot for every
  # meaningful modern freeze.
  VERSIONED_ERD_DELTA="$APPROVED/ERD-DELTA-v$NEW.md"
  cp "$APPROVED/ERD.md" "$VERSIONED_ERD_DELTA"
fi
if [ "$RETIRE_ERD_DELTA" -eq 1 ]; then
  rm -f "$APPROVED/ERD-DELTA.md"
fi
for f in $CHANGED_TEST_FILES; do
  mkdir -p "$(dirname "$f")"
  cp "$IN/$f" "$f"
done
while IFS= read -r f; do
  [ -n "$f" ] || continue
  rm -f "$f"    # `git add tests/` below stages the deletion
done <<< "$REMOVED_FILES"
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
printf '%s\n' "$REMOVED_FILES"      > "$TMP/refreeze-removed-files"
printf '%s\n' "$DELTA_CONTRACTS"    > "$TMP/refreeze-changed-contracts"
# D-86: changed_files is a PER-DELTA declaration. A freeze that does not stage
# contracts.json declares no scope of its own — inheriting the previous
# version's list would silently widen this delta.
CONTRACTS_STAGED=0
case " $CHANGED_DOCS " in *" contracts.json "*) CONTRACTS_STAGED=1 ;; esac
# Delta computation (incl. the D-116 relabel guard) lives in refreeze_delta.py
# so it has a real producer test; the state files above are its inputs.
python3 scripts/refreeze_delta.py "$NEW" "$APPROVED/test-nodeids" "$CONTRACTS_STAGED"
rm -rf "$TMP/old-tests"
rm -f "$TMP/refreeze-old-nodeids" "$TMP/refreeze-changed-files" "$TMP/refreeze-removed-files" "$TMP/refreeze-changed-contracts"

# --- D-75: red-before-green check on the delta (warn-only) -------------------
# INV-1 means a newly frozen test is written before the code it gates. Run the
# delta's tests NOW, against the pre-implementation tree: any that already
# PASS will never observe the milestone being built and gate nothing — the
# green-suite/broken-app family (v6/M5 imagined mocks; M16's hit-counter
# counting hidden DOM text). Legitimate early passes exist (no_edit_files
# acceptance per D-65, carried-forward behavior), so this surfaces a claim
# for the human, never a halt. changed_tests is the runnable channel; the
# frozen-set filter remains a defensive backstop for legacy artifacts.
rm -f .cache/redcheck-already-green
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
    open(".cache/redcheck-already-green", "w").close()
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

# --- M35: smoke checks must be RED on the pre-implementation tree ------------
# A smoke check that passes on the tree BEFORE the milestone runs gates
# nothing: the task can be accepted with zero implementation. testchat M35:
# the app.js smoke check grepped three pre-existing symbols
# (webToggle/pollStatus/queueRender) and T1 sailed through with no real
# acceptance — the milestone's new behavior was never probed. So a NEW or
# CHANGED smoke check must fail on the current tree. Exemptions: D-65
# no_edit_files (their acceptance is green-on-unchanged BY CONTRACT), and a
# re-freeze over a tree that already carries an earlier run's implementation
# (the D-75 marker above — then the check passes for the right reason and the
# warning is the verdict, not a halt).
if [ "$CONTRACTS_STAGED" = "1" ] && [ -f "$IN/contracts.json" ]; then
  NEW_SMOKE=$(python3 - ".pipeline-state/refreeze-old-contracts.json" "$MERGED_CONTRACTS" <<'PYEOF'
import json, sys

def load(path):
    # First freeze (v0->v1): no standing contracts.json exists yet, so the
    # pre-apply snapshot at :587 was never created. Treat missing prior
    # contracts as {} — every staged smoke check is then new/red-checked,
    # which is the correct semantics for a greenfield freeze.
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}

old = load(sys.argv[1]).get("smoke_checks", {})
new = load(sys.argv[2]).get("smoke_checks", {})
no_edit = set(load(sys.argv[2]).get("no_edit_files", []))
for f, cmd in sorted(new.items()):
    if f in no_edit:
        continue
    if old.get(f) != cmd:
        print(f + "\t" + cmd)
PYEOF
)
  if [ -n "$NEW_SMOKE" ]; then
    echo "smoke red-check (M35): running new/changed smoke check(s) against the current tree..."
    SMOKE_RED_FAIL=0
    while IFS=$'\t' read -r _f _cmd; do
      [ -n "$_f" ] || continue
      if [ -n "$_cmd" ] && scripts/sandbox-run.sh -- sh -c "$_cmd" >/dev/null 2>&1; then
        echo "  NOT RED: smoke check for $_f PASSES on the current tree — it gates nothing:"
        echo "    $_cmd"
        SMOKE_RED_FAIL=1
      else
        echo "  red as expected: $_f"
      fi
    done <<< "$NEW_SMOKE"
    if [ "$SMOKE_RED_FAIL" = "1" ]; then
      if [ -e .cache/redcheck-already-green ]; then
        echo "  WARNING: tree already carries this delta's implementation — a passing smoke"
        echo "  check here proves nothing about the milestone; re-verify after the run."
      else
        die "a staged smoke check passes on the pre-implementation tree — it gates nothing (M35: a vacuous app.js smoke check accepted T1 with zero evidence). Reauthor the check to probe the delta's new behavior so it is red before the milestone runs, or pin real tests."
      fi
    fi
    rm -f .cache/redcheck-already-green
  fi
fi

# --- Re-freeze: hash-pin every frozen artifact, bump VERSION ---
{
  for f in $(python3 scripts/spec_artifacts.py documents) test-nodeids; do
    [ -f "$APPROVED/$f" ] && sha256sum "$APPROVED/$f"
  done
  # D-140: an active milestone may span skipped freezes. Keep every immutable
  # per-freeze instruction slice hash-pinned so later planning never receives
  # only the newest ERD-DELTA.md and silently loses earlier work.
  find "$APPROVED" -maxdepth 1 -type f -name 'ERD-DELTA-v*.md' \
    | sort | while read -r f; do sha256sum "$f"; done
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
[ -n "$VERSIONED_ERD_DELTA" ] && git add "$VERSIONED_ERD_DELTA"
if [ "$RETIRE_ERD_DELTA" -eq 1 ]; then git add "$APPROVED/ERD-DELTA.md"; fi
for f in $CHANGED_CAPTURES; do git add "$APPROVED/$f"; done
git commit -m "[refreeze v$NEW]" || {
  # D-151, extended: the on_refreeze_exit trap owns the rollback for EVERY
  # post-apply failure now; this block just reports and exits non-zero.
  commit_rc=$?
  echo "REFREEZE FAIL: freeze commit failed (rc=$commit_rc)" >&2
  exit "$commit_rc"
}
REFREEZE_APPLIED=0   # committed — the exit trap must never roll back a frozen freeze
rm -rf "$IN"

echo ""
echo "=============================================="
echo "  Frozen as v$NEW"
echo "  Next: run scripts/orchestrate.sh — only the"
echo "  affected subtree is reset and re-run."
echo "=============================================="
