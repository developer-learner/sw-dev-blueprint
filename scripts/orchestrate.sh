#!/usr/bin/env bash
# orchestrate.sh v3 — walks the EM's task DAG from a frozen TPM spec.
#
# Shell owns ALL procedure (D-05 applied uniformly, D-26): ordering, state,
# completion, escalation counters. LLM tiers only produce artifacts:
#   EM    -> tasks/plan.json (decomposition) and tasks/diagnosis.json (consults)
#   coder -> exactly one file per task, gate-enforced
# Tests are TPM-authored, frozen in scripts/.approved/ + tests/, and RUN by
# this script via pytest --json-report. There is no test-authoring agent.
#
# D-53: EM/coder are called over bare HTTP (scripts/llm-call.sh), one
# completion per call — no agent harness in the loop. The shell gathers
# context (reads the frozen files a call needs) into the prompt, sends it,
# and writes the model's answer to disk itself: a JSON artifact for the EM
# (schema-constrained), the one named file for the coder (sentinel-wrapped,
# same convention refreeze/tpm-unpack already use). This retires the
# `opencode serve` / `--attach` / agent-mode machinery (D-40..D-52), whose
# seams caused every failure of the first three supervised runs and caught
# none of them — the actual trust boundary was always the sandbox lanes and
# the gates below, never the harness.
#
# The TPM is a human-operated web chat: escalations are packaged as batched,
# copy-pasteable bundles under .pipeline-state/escalations/ (D-29), and its
# answers come back as a delta applied by scripts/refreeze.sh (D-31).
#
# Exit codes: 0 feature done (full frozen suite green) · 1 hard failure or
# gate violation · 2 halted awaiting TPM (escalation batch written).
set -euo pipefail

MAX_TASK_STRIKES="${MAX_TASK_STRIKES:-2}"      # coder attempts per brief (D-70: 2 arms the escalation ladder — consult/verdicts were dead code for ~23 milestones under 1; D-69's run budget bounds the thrash fail-fast guarded against)
MAX_BRIEF_REVISIONS="${MAX_BRIEF_REVISIONS:-1}" # EM brief_wrong rewrites per task
MAX_PLAN_REVISIONS="${MAX_PLAN_REVISIONS:-2}"   # EM plan re-emits per run (validation retries + decomposition_wrong); default 2: the validator's error feedback demonstrably fixes plans on the second emit (testchat M6)
AGENT_TIMEOUT="${AGENT_TIMEOUT:-1800}"
# D-69: wall-clock budget for the WHOLE run, in seconds (0 disables). With
# D-60 atomic tasks and a non-thinking local coder, a healthy run finishes in
# minutes — a run that blows past this is thrashing (thinking drift, EM loops,
# misconfiguration), and fail-fast applies to time the same as to strikes.
# Checked BETWEEN phases only (never kills a call mid-flight); on breach the
# run halts and prints the phase-timing table. State persists (D-24): a
# re-run resumes from completed tasks, so a budget halt is cheap.
SWBP_RUN_BUDGET="${SWBP_RUN_BUDGET:-1200}"
RUN_T0=$(date +%s)

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

# .pipeline-state/ layout (orchestrator-owned, gitignored; delete only as a
# whole — partial deletes desync counters). Documented because a conductor
# once guessed "task-state/" and burned 30 minutes (testchat M4):
#   phase                current phase (em|task|"") — crash checkpoint (D-24)
#   task_target          file the in-flight coder task writes
#   spec_version         frozen VERSION last seen (re-freeze detection)
#   plan_revisions       EM plan re-emit counter (cap: MAX_PLAN_REVISIONS)
#   tasks/<id>.status    pending|done|escalated|blocked
#   tasks/<id>.strikes|.revisions|.fp|.lastfail   per-task counters/fingerprint
#   briefs/<id>          EM-revised brief overriding the plan's brief
#   logs/<id>-a<n>.raw|.log   coder attempt transcripts; em-last.raw|.err
#   escalations/<id>/bundle.md, escalations/BATCH.md   TPM bundles (D-29)
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
APPROVED="scripts/.approved"
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

die() { echo "FAIL: $*" >&2; exit 1; }

# Single-writer lock on the state dir. Every counter in .pipeline-state/
# (strikes, plan_revisions, phase, task_target, spec_version) is a plain
# file with a write-then-read pattern that assumes no concurrent runs.
# flock -n fails immediately if another orchestrate is already holding
# the lock, so a second run halts with a clear message instead of
# silently corrupting the state files of the run in progress.
exec 200> "$STATE_DIR/.lock"
flock -n 200 \
  || die "another scripts/orchestrate.sh is already running (holds $STATE_DIR/.lock) — wait for it to finish or kill it, then retry"

# --- state helpers (files, not shell vars: crash checkpoint per D-24) ---
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
tstat()       { [ -f "$TASK_STATE/$1.status" ] && cat "$TASK_STATE/$1.status" || echo pending; }
set_tstat()   { printf '%s\n' "$2" > "$TASK_STATE/$1.status"; }
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_counter() { printf '%s\n' "$3" > "$TASK_STATE/$1.$2"; }

# --- run clock (D-69): phase-timing log + wall-clock budget ------------------
# timings.tsv gets one row per phase boundary; the budget halt prints it, and
# post-run tuning reads it — no historical run had per-phase numbers, so every
# "where did 45 minutes go" was guesswork.
case "$SWBP_RUN_BUDGET" in
  ''|*[!0-9]*) die "SWBP_RUN_BUDGET must be a non-negative integer (seconds), got '$SWBP_RUN_BUDGET'" ;;
esac
run_elapsed() { echo $(( $(date +%s) - RUN_T0 )); }
mark() { printf '%s\t%ss\t%s\n' "$(date '+%H:%M:%S')" "$(run_elapsed)" "$1" >> "$LOG_DIR/timings.tsv"; }
check_budget() {  # check_budget <checkpoint> — between-phase gate, fail-closed
  [ "$SWBP_RUN_BUDGET" -gt 0 ] || return 0
  local e; e=$(run_elapsed)
  [ "$e" -gt "$SWBP_RUN_BUDGET" ] || return 0
  mark "BUDGET-HALT at $1"
  echo ""
  echo "=========================================="
  echo "  HALT: run budget exceeded — ${e}s elapsed > SWBP_RUN_BUDGET=${SWBP_RUN_BUDGET}s"
  echo "  checkpoint: $1"
  echo "=========================================="
  echo "  Phase timings ($LOG_DIR/timings.tsv):"
  sed 's/^/    /' "$LOG_DIR/timings.tsv"
  die "run over budget at '$1' — state persists; a re-run resumes from completed tasks. Healthy-but-slow (cold model load, big suite): raise SWBP_RUN_BUDGET or set 0. Otherwise the timing table names the phase that ate the clock — fix that, don't raise the budget."
}

# --- Pre-flight ---
echo "=== Pre-flight ==="
mark "run start (budget ${SWBP_RUN_BUDGET}s)"

# Constraint 3: conductors live inside the VM; running on macOS is a structural error.
[ "$(uname -s)" != "Darwin" ] \
  || die "orchestrate.sh must run inside the Linux dev VM, not on the macOS host — see docs/DEV-VM-SETUP.md constraint 3"

python3 --version >/dev/null 2>&1 || die "python3 required"
git --version >/dev/null 2>&1    || die "git required"
[ -x scripts/llm-call.sh ]       || die "scripts/llm-call.sh missing or not executable"
[ -f .gate-paths ]               || die ".gate-paths not found"
[ -f scripts/.manifest-template ] || die "scripts/.manifest-template not found"
[ -f scripts/.manifest-project ]  || die "scripts/.manifest-project not found"
python3 -c "import json, hashlib" 2>/dev/null || die "python3 json/hashlib required"
if [ "${SANDBOX:-1}" != "1" ]; then
  die "SANDBOX must be 1 (test/smoke execution runs untrusted generated code — containerization is mandatory, AC9)"
fi
# Fail fast on an unreachable local LLM (Hard Rule 4) rather than deep inside
# the first EM call. Model calls happen directly against this endpoint now —
# no attach protocol, no harness in between (D-53).
: "${SANDBOX_LLM_HOST:=localhost}"
: "${SANDBOX_LLM_PORT:=1234}"
curl -s --max-time 5 -o /dev/null "http://$SANDBOX_LLM_HOST:$SANDBOX_LLM_PORT/v1/models" \
  || die "no LLM reachable at http://$SANDBOX_LLM_HOST:$SANDBOX_LLM_PORT/v1/models — start it and retry (in the VM, set SANDBOX_LLM_HOST=host.lima.internal)"
# The interactive/human commit path is only gated if bootstrap.sh ran. The
# testchat M4 run proved this can be silently absent for an entire project
# lifetime — a conductor hand-committed src/ changes with no gate firing.
# Fail closed here, same as the manifest check below.
[ "$(git config core.hooksPath || true)" = ".githooks" ] \
  || die "core.hooksPath is not '.githooks' — run scripts/bootstrap.sh first (the pre-commit lane gate is mandatory, not optional)"
# The orchestrator's own [plan]/[task] commits swallow failures on purpose
# (nothing-to-commit is normal) — which also swallows a missing git identity,
# so every commit silently no-ops (scratch-rung drill 2026-07-16: the dev VM
# had no identity and the plan commit vanished). Fail closed here instead.
{ [ -n "$(git config user.email || true)" ] && [ -n "$(git config user.name || true)" ]; } \
  || die "git identity missing — [plan]/[task] commits would silently no-op (their failures are deliberately swallowed): git config --global user.email <addr> && git config --global user.name <name>"
# A dirty tree poisons the lane gate: phase-gate diffs the working tree
# against a phase-start ref, so pre-existing uncommitted changes get blamed
# on whichever tier runs first (testchat M2: the EM was accused of touching
# requirements.txt and src/ it never saw).
[ -z "$(git status --porcelain)" ] \
  || die "working tree not clean — commit or stash first (uncommitted changes would be misattributed to the first tier the lane gate checks): $(git status --porcelain | head -5 | tr '\n' ' ')"
# Control-plane + frozen-artifact integrity (phase-gate verifies both, fail-closed)
bash scripts/phase-gate.sh manifest HEAD
# The frozen spec IS the human approval: it only exists via scripts/refreeze.sh,
# which requires an interactive human y/N on the diff (D-31). No honor-string.
[ -f "$APPROVED/frozen-manifest" ] || die "no frozen TPM spec — install PRD/ERD/contracts/tests via scripts/refreeze.sh"
[ -f "$APPROVED/VERSION" ]         || die "$APPROVED/VERSION missing — run scripts/refreeze.sh"
FROZEN_V=$(cat "$APPROVED/VERSION")
# D-55 round-trip smoke test: a bug in the model-call path is invisible to
# static review — only a real round-trip catches it (correction log 2026-07-03).
# Runs last in pre-flight: all free checks (hooksPath, clean tree, manifest)
# pass before we spend a model call. The budget must absorb a COLD model
# start — LM Studio loads the mapped model on first request, and a large
# model takes minutes, not seconds (testchat M6: 30s budget, 122B EM, false
# pre-flight failure).
SMOKE_MAX_TIME="${SMOKE_MAX_TIME:-240}"
echo "  LLM round-trip smoke test (budget ${SMOKE_MAX_TIME}s — cold model start counts)..."
_smoke_sys=$(mktemp)
printf 'You are a test probe. Reply with exactly the text the user sends.' > "$_smoke_sys"
SMOKE_REPLY=$(printf 'SMOKE_OK' | scripts/llm-call.sh em "$_smoke_sys" --max-time "$SMOKE_MAX_TIME" 2>/dev/null || true)
rm -f "$_smoke_sys"
[ -n "$SMOKE_REPLY" ] \
  || die "LLM smoke test failed — llm-call.sh returned empty output for a trivial prompt within ${SMOKE_MAX_TIME}s (check SANDBOX_LLM_HOST=$SANDBOX_LLM_HOST, model mapping, model server; a cold large model may need SMOKE_MAX_TIME raised)"
# D-62: LM Studio drift probe — any model reload resets instance config
# (context window, thinking toggle, chat_template_kwargs). A thinking model
# puts output in reasoning_content and leaves content empty, which breaks
# every downstream parser. Check the smoke reply for the thinking-model
# signature: content is empty or absent while reasoning tokens are present.
# Also warn if the reply looks nothing like the echo (model misconfigured).
case "$SMOKE_REPLY" in
  ""|THINKING_MODEL)
    die "LM Studio drift: model returned empty content (likely in thinking mode). Open LM Studio → model settings → disable Reasoning toggle → save as default, then retry." ;;
esac
if ! printf '%s' "$SMOKE_REPLY" | grep -q 'SMOKE_OK'; then
  echo "  WARNING: smoke reply did not echo 'SMOKE_OK' — got '$(printf '%s' "$SMOKE_REPLY" | head -c 80)'. Model may be misconfigured (thinking mode, wrong model, stale instance config). Proceeding, but verify behavior."
fi
echo "OK (frozen spec v$FROZEN_V)"
mark "pre-flight done (spec v$FROZEN_V)"

# --- Parse .gate-paths for the build lane ---
build_dir="src/"
_raw=$(grep '^build=' .gate-paths | cut -d= -f2- || true)
if [ -n "$_raw" ]; then
  _raw="${_raw#./}"; _raw="${_raw%"${_raw##*[![:space:]]}"}"; build_dir="${_raw%/}/"
fi

# --- Re-freeze detection (the reset itself runs after the plan is fresh) ---
LAST_V=$(read_state spec_version); LAST_V=${LAST_V:-$FROZEN_V}
SPEC_ADVANCED=0
if [ "$FROZEN_V" != "$LAST_V" ]; then
  SPEC_ADVANCED=1
  echo "frozen spec advanced v$LAST_V -> v$FROZEN_V"
  rm -rf "$ESC_DIR"; mkdir -p "$ESC_DIR"   # bundles answered by this delta are consumed
fi

# --- Plan-revision budget is per freeze: keyed to the spec version itself.
# NOT keyed to the spec-advance event above — spec_version is only written
# after a plan validates, so a pre-plan halt leaves it missing and the
# ${LAST_V:-$FROZEN_V} default masks the advance forever (testchat M7: two
# revisions burned against a validator bug blocked every later run, twice —
# the first fix keyed to the advance event and never fired). Same-spec
# re-runs keep their spent budget: refreshing it needs either a re-freeze
# or the CEO clearing .pipeline-state/plan_revisions* by hand.
if [ "$(read_state plan_revisions_spec)" != "$FROZEN_V" ]; then
  write_state plan_revisions 0
  write_state plan_revisions_spec "$FROZEN_V"
fi

# --- Agent runners (D-53) ----------------------------------------------------
# No harness, no filesystem tools for either tier: the shell reads whatever
# context a call needs, sends ONE completion via scripts/llm-call.sh, and
# writes the model's answer to disk itself. phase-gate.sh remains the
# mechanical backstop (D-26/D-15/D-22) even though the shell is now the sole
# writer — a bug in this script should still be caught the same way a rogue
# agent would have been.

# build_context "label:path" [...] -> labeled fenced blocks for the ones that
# exist (silently skips missing paths — e.g. no prior plan.json to show yet).
build_context() {
  for pair in "$@"; do
    local label="${pair%%:*}" path="${pair#*:}"
    [ -f "$path" ] || continue
    printf '\n### %s (%s)\n```\n' "$label" "$path"
    cat "$path"
    printf '\n```\n'
  done
}

# em_call <out-file> <schema> <instruction> <context "label:path" ...>
# Calls the EM once, validates the reply is well-formed JSON (the *semantic*
# validation — schema, coverage, DAG — is validate-plan.py's job, unchanged),
# and writes it to <out-file>. The --schema constrains generation when the
# server supports it; either way validate-plan.py is the real gate.
em_call() {
  local out="$1" schema="$2" instr="$3"; shift 3
  local phase_start; phase_start=$(git rev-parse HEAD)
  write_state phase em
  mark "em-call start -> $out"
  { printf '%s\n' "$instr"; build_context "$@"; } \
    | timeout "$AGENT_TIMEOUT" scripts/llm-call.sh em .opencode/prompts/em.md \
        --schema "$schema" --max-time "$AGENT_TIMEOUT" \
    > "$LOG_DIR/em-last.raw" 2> "$LOG_DIR/em-last.err" \
    || { cat "$LOG_DIR/em-last.err" >&2; die "EM call failed (see $LOG_DIR/em-last.err)"; }
  if ! python3 -c "import json; json.load(open('$LOG_DIR/em-last.raw'))" 2>/dev/null; then
    # EM_JSON_SOFT=1 (consult_em's D-71 retry loop): report failure to the
    # caller instead of halting — a malformed reply there earns one retry.
    [ "${EM_JSON_SOFT:-0}" = "1" ] \
      || die "EM returned invalid JSON (see $LOG_DIR/em-last.raw)"
    echo "  EM reply was not valid JSON (see $LOG_DIR/em-last.raw)" >&2
    write_state phase ""
    mark "em-call invalid-json -> $out"
    return 1
  fi
  cp "$LOG_DIR/em-last.raw" "$out"
  # Explicit die: em_call may run inside an if-condition (D-71), where set -e
  # is suppressed for the whole function body — the lane gate must stay fatal.
  bash scripts/phase-gate.sh em "$phase_start" || die "EM lane/integrity gate failed"
  write_state phase ""
  mark "em-call done -> $out"
}

# run_coder <task-id> <file> <brief> <attempt> — one completion, sentinel-
# wrapped reply (same "=== FILE: path ===" convention as the TPM shuttle,
# D-38), shell extracts and writes exactly the named file. A response that
# omits the block or names a different path is a coder FAILURE (evidence for
# retry/consult), never written to disk.
run_coder() {
  local id="$1" file="$2" brief="$3" attempt="$4"
  local phase_start; phase_start=$(git rev-parse HEAD)
  write_state phase task
  write_state task_target "$file"
  mark "coder $id attempt $attempt start ($file)"
  # D-59: existing files are EDITED via anchored blocks, never retyped —
  # full-file regeneration made local coders silently delete working logic
  # (testchat M5..M7). New files still arrive as one sentinel-wrapped file.
  local instr existing=""
  if [ -f "$file" ]; then
    existing="existing:$file"
    instr="$brief

Reply with ONLY edit blocks in this exact format, nothing else:
<<<<<<< SEARCH
(an EXACT, character-for-character copy of a short existing section — 3 to 10 lines)
=======
(that same section with the change applied)
>>>>>>> REPLACE
Rules:
- Each SEARCH must appear EXACTLY ONCE in the file. Copy it verbatim — same spaces, same quotes.
- Several small blocks, not one big one. Do not touch code outside your blocks. Do not reformat or reorder anything.
- Never include any line containing a think tag in a SEARCH section — anchor on nearby tag-free lines instead.
- In new code, never write the think tag as one literal string — construct it by concatenation, e.g. '<' + 'think>'.
- If the file already satisfies the brief, reply with exactly this line and nothing else: === NO CHANGES ===
- Verify each SEARCH against the file one more time before answering.
- Your reply's VERY FIRST line must be '<<<<<<< SEARCH' (or the NO CHANGES line). Do not analyze, plan, or explain anything — every design decision is already made in the brief. Prose before the blocks burns your output budget and truncates the edit mid-block.
- Every block must be COMPLETE working code — never a stub, placeholder, or '...' body. If the brief needs a new function, write its full body in the block."
  else
    instr="$brief

Reply with ONLY this, nothing before or after it:
=== FILE: $file ===
<the complete file content>
=== END FILE ===
Your reply's VERY FIRST line must be the === FILE: line. Do not analyze,
plan, or explain anything — every design decision is already made in the
brief; transcribe it into working code immediately."
  fi
  # Edit-mode replies are small by design (a few anchored blocks); cap them
  # at half the create-mode budget so a runaway attempt fails in half the
  # wall-clock time (testchat M17). Create mode keeps the full default.
  local out_budget=""
  [ -n "$existing" ] && out_budget=4096
  { printf '%s\n' "$instr"; build_context "contracts:$APPROVED/contracts.json" "$existing"; } \
    | SWBP_MAX_OUTPUT="$out_budget" timeout "$AGENT_TIMEOUT" scripts/llm-call.sh coder .opencode/prompts/coder.md \
        --max-time "$AGENT_TIMEOUT" \
    > "$LOG_DIR/$id-a$attempt.raw" 2> "$LOG_DIR/$id-a$attempt.log" \
    || { CODER_EVIDENCE="coder call failed: $(tail -3 "$LOG_DIR/$id-a$attempt.log" | tr '\n' ' ')"; write_state phase ""; return 1; }
  if [ -n "$existing" ]; then
    # D-59 edit-block path: fail-closed applier; target untouched on any error
    if ! CODER_EVIDENCE=$(python3 scripts/apply-edit-blocks.py "$file" "$LOG_DIR/$id-a$attempt.raw" 2>&1); then
      write_state phase ""
      return 1
    fi
  elif ! CODER_EVIDENCE=$(python3 - "$file" "$LOG_DIR/$id-a$attempt.raw" "$LOG_DIR/$id-a$attempt.log" <<'PYEOF'
import re, sys
path, raw_path, log_path = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(raw_path).read()
m = re.search(r"^=== FILE: (.+?) ===\n(.*?)\n=== END FILE ===$", text, re.M | re.S)
if not m:
    # Tolerant pass (testchat M7): a local coder glued the opening sentinel to
    # the tail of its own prose ('- "hello === FILE: ... ===') and a complete,
    # well-formed file followed. Accept an opening sentinel anywhere on a line
    # — the distinctive token cannot occur in generated file content by
    # accident without the closing pair also parsing. Content rules unchanged.
    m = re.search(r"=== FILE: (.+?) ===\n(.*?)\n=== END FILE ===$", text, re.M | re.S)
    if m:
        print("warning: opening sentinel was mid-line — accepted by tolerant pass", file=sys.stderr)
if not m:
    # Missing closing sentinel (testchat M7 T3: the coder writes the whole
    # file then stops at end-of-code without '=== END FILE ==='). Accept an
    # EOF-terminated block ONLY when llm-call's log proves the model stopped
    # naturally (finish_reason=stop) — a 'length' stop means real truncation
    # and must stay a failure. Never guess completeness from the content.
    try:
        log = open(log_path).read()
    except OSError:
        log = ""
    if "finish_reason=stop" in log:
        m = re.search(r"=== FILE: (.+?) ===\n(.*)\Z", text, re.S)
        if m:
            print("warning: no closing sentinel — accepted EOF-terminated block "
                  "(finish_reason=stop proves natural completion)", file=sys.stderr)
if not m:
    sys.exit("coder reply had no '=== FILE: ... ===' block")
got_path, content = m.group(1).strip(), m.group(2)
if got_path != path:
    sys.exit(f"coder wrote to '{got_path}', task named '{path}'")
if not content.strip():
    sys.exit("coder reply block was empty")
import os; os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
open(path, "w").write(content)
PYEOF
  ); then
    write_state phase ""
    CODER_EVIDENCE="$CODER_EVIDENCE"
    return 1
  fi
  # D-68 swallowed-error gate, both apply modes: a silent error swallow is a
  # task failure (strike + retry brief), not a hard halt — the finding names
  # the line and the fix (handle it, or justify the swallow in a comment).
  if ! SWALLOW_FINDINGS=$(python3 scripts/check-swallowed-errors.py "$file" 2>&1); then
    CODER_EVIDENCE="swallowed-error gate (D-68): $SWALLOW_FINDINGS"
    # Reset the file to HEAD — apply-edit-blocks (or create-mode write)
    # succeeded before D-68 rejected the result, so the working tree
    # carries the failed attempt. Without this, a downstream EM consult
    # runs phase-gate.sh em against a dirty non-tasks/ file and gets
    # mis-blamed for the coder's diff (testchat M25 T7 hit this).
    if git ls-files --error-unmatch "$file" >/dev/null 2>&1; then
      git checkout HEAD -- "$file"
    else
      rm -f "$file"
    fi
    write_state phase ""
    return 1
  fi
  # Explicit die: run_coder always runs inside an if-condition, where set -e
  # is suppressed for the whole function body — without this the gate's exit
  # code was silently discarded and the task committed anyway (same class as
  # em_call's D-71 fix). Violation = hard halt (D-15/D-22), never a strike.
  bash scripts/phase-gate.sh task "$phase_start" "$file" \
    || die "task lane/integrity gate failed ($file) — hard halt (D-15/D-22)"
  write_state phase ""
  write_state task_target ""
  return 0
}

# run_tests [nodeid...] — full frozen suite when no args.
# Sets TESTS_RC (0 pass · 1 fail · 3 no verdict), FAILING (ids, |-joined) and
# FAIL_DETAIL (D-73: crash message / longrepr tail per failure, bounded — the
# report always carried this text; only the node-ids ever reached the evidence
# string, and an EM diagnosing from bare ids misdiagnosed twice in the
# 2026-07-16 drill).
run_tests() {
  mkdir -p .cache
  mark "tests start ($# node-id(s); 0 = full suite)"
  scripts/sandbox-run.sh --rw .cache -- pytest -p no:cacheprovider --json-report \
    --json-report-file=.cache/test-report.json "$@" >/dev/null 2>&1 || true
  local out
  if out=$(python3 - <<'PYEOF'
import json, re, sys
from pathlib import Path

# Cleared first: stale detail from a previous run must never leak into a
# later attempt's evidence.
DETAIL = Path(".cache/test-failures.txt")
DETAIL.write_text("")

def tail(s, n=240):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else "..." + s[-n:]

try:
    with open(".cache/test-report.json") as f:
        r = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    print("NO_REPORT"); sys.exit(3)
tests = r.get("tests", [])
summary = r.get("summary", {})
total = summary.get("total", 0) if isinstance(summary, dict) else 0
failed_collectors = [c for c in r.get("collectors", [])
                     if c.get("outcome") == "failed"]
if total == 0 and not failed_collectors:
    print("NO_TESTS"); sys.exit(3)

def crash_text(t):
    # The tail is the informative end: a longrepr's final line is the error;
    # the crash message (when the plugin recorded one) is already terse.
    for phase in ("call", "setup", "teardown"):
        p = t.get(phase) or {}
        msg = (p.get("crash") or {}).get("message") or p.get("longrepr")
        if msg:
            return tail(msg)
    return ""

failed_tests = sorted((t for t in tests
                       if t.get("outcome") in ("failed", "error")),
                      key=lambda t: t["nodeid"])
failed = [t["nodeid"] for t in failed_tests]
detail = [f"{t['nodeid']}: {crash_text(t)}"
          for t in failed_tests[:3] if crash_text(t)]
for c in failed_collectors[:1]:
    detail.append(f"collection: {tail(c.get('longrepr', ''))}")
if failed_collectors:
    failed.append("COLLECTION_ERROR (see .cache/test-report.json)")
if not failed:
    sys.exit(0)
if detail:
    DETAIL.write_text(" || ".join(detail) + "\n")
print("|".join(failed))
sys.exit(1)
PYEOF
  ); then
    TESTS_RC=0; FAILING=""; FAIL_DETAIL=""
  else
    TESTS_RC=$?; FAILING="$out"
    FAIL_DETAIL=$(head -c 900 .cache/test-failures.txt 2>/dev/null | tr -d '\n' || true)
  fi
  mark "tests done (rc=$TESTS_RC)"
}

# --- Plan phase: EM emits/revises, validator gates, bounded retries ----------
plan_revisions_used() { read_state plan_revisions | grep . || echo 0; }

ensure_plan() {
  local verrs revs
  while :; do
    if [ -f tasks/plan.json ] && verrs=$(python3 scripts/validate-plan.py 2>&1); then
      echo "plan ok (v$(python3 -c 'import json;print(json.load(open("tasks/plan.json"))["version"])'))"
      git add tasks/plan.json && git commit -m "[plan] validated against spec v$FROZEN_V" 2>/dev/null || true
      return 0
    fi
    verrs=$(python3 scripts/validate-plan.py 2>&1 || true)
    revs=$(plan_revisions_used)
    [ "$revs" -lt "$MAX_PLAN_REVISIONS" ] || {
      echo "$verrs"
      # --- D-79: audit the puzzle before blaming the solver ------------------
      # Exhausting the plan budget is as much evidence about the SPEC as about
      # the EM: testchat M28 saw two different EM models fail identically at
      # this gate because v51/v52 were unimplementable by ANY EM — and the
      # ladder, which only knows how to escalate the ACTOR, burned ~75 minutes
      # of model swaps and a seat escalation against an impossible spec. Before
      # halting toward the actor path, re-run the D-78 satisfiability audit on
      # the frozen spec against the current tree (old={} form: everything
      # already registered/on disk passes; what remains must be buildable by
      # the inventory). If the spec is the defect, route straight to the TPM
      # bundle — no further EM strikes, no model swaps.
      local audit
      if ! audit=$(python3 scripts/validate-plan.py --spec-preflight /dev/null "$APPROVED/contracts.json" 2>&1); then
        echo ""
        echo "SPEC DEFECT (D-79): the frozen spec is unimplementable — the plan"
        echo "gate would reject EVERY decomposition. Swapping or escalating the"
        echo "EM cannot fix this; the delta below belongs to the TPM."
        echo "$audit"
        package_escalation "spec-defect" "SPEC-DEFECT" "plan gate rejected $revs consecutive EM plans; last validator output:
$verrs

D-78/D-79 satisfiability audit of frozen spec v$FROZEN_V (mechanical, spec-only):
$audit" "-"
        finalize_batch
      fi
      die "plan invalid after $revs EM revisions — halting for the human (Rule 4).
  The D-79 spec audit found no unsatisfiable contract, so the spec is not
  provably at fault — the ladder's actor path (EM model quality, prompt, or a
  spec problem the audit cannot see) applies.
  If the halt's cause was fixed OUTSIDE the spec (e.g. a gate defect), the CEO
  may refresh the budget: rm .pipeline-state/plan_revisions*   — otherwise the
  fix belongs in a re-freeze, which refreshes it automatically."
    }
    check_budget "plan revision $((revs + 1))"
    write_state plan_revisions $((revs + 1))
    echo "=== EM: emit/revise plan (revision $((revs + 1))/$MAX_PLAN_REVISIONS) ==="
    em_call tasks/plan.json scripts/schemas/plan.schema.json \
      "Decompose the frozen ERD into atomic ONE-FILE tasks and reply with ONLY the plan as JSON matching the schema you were given — no prose, no markdown fence. Requirements: exactly one task per file in contracts.json's files array; every test node-id in test-nodeids that exercises a file in contracts.json's files array mapped to exactly one task (the task after which it should pass, given its depends_on) — node-ids testing only carried-forward files are handled by the shell: do NOT map them and do NOT emit a 'regression' key (the validator rejects it); when unsure, omit the node-id — the validator names any you must map; every task's contracts list uses ids that exist in contracts.json; every brief self-contained per BLUEPRINT.md Rule 8 (exact path, signatures, inputs/outputs, acceptance) — the coder sees only the brief. Do NOT include a smoke_check field — smoke checks are TPM-authored and live in contracts.json. Set erd_version to $FROZEN_V. Set the top-level version key to an integer >= 1 (1 for a fresh plan; bump it on every re-emit). NO status fields.${verrs:+ The previous plan failed validation with these errors — fix all of them: $verrs}" \
      "ERD:$APPROVED/ERD.md" "contracts:$APPROVED/contracts.json" "test-nodeids:$APPROVED/test-nodeids" "plan-being-revised:tasks/plan.json"
  done
}

# --- EM consult: schema-bound diagnosis (D-29, hardened D-71) ----------------
# $1 task-id (or DRIFT)  $2 evidence text. Sets DIAG_VERDICT, DIAG_FILE.
# D-71: the model's reply surface is verdict+reason(+revised_brief) only —
# task_id is the shell's own knowledge, stamped into the artifact below (the
# one production consult ever attempted died on an empty task_id echo,
# testchat M23). An invalid reply — unparseable JSON or failed validation —
# earns exactly ONE retry carrying the validator's errors, the same feedback
# loop that demonstrably fixes plans on the second emit (ensure_plan,
# testchat M6). A second invalid reply halts (Rule 4), as before.
consult_em() {
  local id="$1" evidence="$2"
  rm -f tasks/diagnosis.json
  local ctx=("plan:tasks/plan.json" "ERD:$APPROVED/ERD.md" "contracts:$APPROVED/contracts.json")
  local f
  for f in $(printf '%s' "$evidence" | grep -oE 'tests/[A-Za-z0-9_/]+\.py' | sort -u || true); do
    ctx+=("failing-test:$f")
  done
  local instr="Task consult. Task '$id' — $evidence. Decide ONE verdict: brief_wrong (the task brief mis-specified the work — include a full revised_brief, Rule 8 discipline), decomposition_wrong (the task split/dependencies are wrong), or contract_or_test_wrong (the frozen contract or test itself is wrong — your reason becomes the evidence a human carries to the TPM, so be specific: name the contract id or test node-id and what about it is wrong). Reply with ONLY the diagnosis JSON matching the schema you were given, shaped exactly like this example: {\"verdict\": \"decomposition_wrong\", \"reason\": \"T2 imports the parser T4 creates but does not depend on T4\"}. Do NOT include a task_id field — the orchestrator records it itself."
  local attempt verrs=""
  for attempt in 1 2; do
    [ -z "$verrs" ] \
      || echo "=== EM diagnosis for $id rejected (attempt $((attempt - 1))) — one retry with the validator's errors (D-71) ==="
    if EM_JSON_SOFT=1 em_call tasks/diagnosis.json scripts/schemas/diagnosis.schema.json \
         "$instr${verrs:+ Your previous reply was rejected — fix exactly these errors and reply again with ONLY the corrected JSON: $verrs}" \
         "${ctx[@]}"; then
      python3 -c 'import json, sys
p = "tasks/diagnosis.json"
d = json.load(open(p))
if isinstance(d, dict):
    d["task_id"] = sys.argv[1]
    json.dump(d, open(p, "w"), indent=2)
' "$id"
      if DIAG_VERDICT=$(python3 scripts/validate-plan.py --diagnosis tasks/diagnosis.json 2> "$LOG_DIR/diag-last.err"); then
        DIAG_FILE="$STATE_DIR/diagnosis-$id.json"
        mv tasks/diagnosis.json "$DIAG_FILE"
        return 0
      fi
      verrs=$(tr '\n' ' ' < "$LOG_DIR/diag-last.err")
    else
      verrs="the reply was not parseable JSON at all"
    fi
  done
  die "EM diagnosis for $id still invalid after one retry — halting (Rule 4): $verrs"
}

# --- Escalation bundle for the web-chat TPM (D-29) ---------------------------
package_escalation() {  # $1 kind  $2 id  $3 evidence  $4 diagnosis-file
  local kind="$1" id="$2" evidence="$3" diag="$4"
  local dir="$ESC_DIR/$id"
  mkdir -p "$dir"
  [ -f .cache/test-report.json ] && cp .cache/test-report.json "$dir/" || true
  {
    echo "## Escalation: $kind — $id (spec v$FROZEN_V)"
    echo
    if [ "$id" != "DRIFT" ] && [ "$id" != "SPEC-DEFECT" ]; then
      echo "### Task entry (tasks/plan.json)"
      echo '```json'
      python3 -c "
import json
plan = json.load(open('tasks/plan.json'))
t = next(t for t in plan['tasks'] if t['id'] == '$id')
print(json.dumps(t, indent=2))"
      echo '```'
      echo
    fi
    echo "### Evidence"
    echo '```'
    echo "$evidence"
    echo '```'
    echo
    if [ "$diag" = "-" ]; then
      echo "### EM diagnosis"
      echo "(none — detected mechanically by the D-79 spec audit; no EM consult"
      echo "was involved and none is needed: the defect is provable from the"
      echo "spec alone.)"
    else
      echo "### EM diagnosis (schema-validated)"
      echo '```json'
      cat "$diag"
      echo '```'
    fi
    echo
    echo "### Frozen artifacts involved"
    python3 - "$id" "$evidence" <<'PYEOF'
import json, sys
from pathlib import Path
tid, evidence = sys.argv[1], sys.argv[2]
# contract entries referenced by the task
try:
    plan = json.load(open("tasks/plan.json"))
    contracts = json.load(open("scripts/.approved/contracts.json"))
    if tid not in ("DRIFT", "SPEC-DEFECT"):
        t = next(t for t in plan["tasks"] if t["id"] == tid)
        refs = set(t["contracts"])
        print("Referenced contract entries:")
        for key in ("routes", "schemas", "errors"):
            for e in contracts.get(key, []):
                if e.get("id") in refs:
                    print("```json"); print(json.dumps(e, indent=2)); print("```")
        for ep in contracts.get("entry_points", []):
            if ep in refs:
                print(f"- entry_point: `{ep}`")
except Exception as e:
    print(f"(could not extract contract entries: {e})")
# failing test sources, capped
files = sorted({part.split("::")[0] for part in evidence.split("|")
                if part.strip().startswith("tests/")})
for f in files:
    p = Path(f)
    if p.exists():
        lines = p.read_text().splitlines()[:200]
        print(f"\nFrozen test source `{f}`:")
        print("```python"); print("\n".join(lines)); print("```")
PYEOF
    echo
  } > "$dir/bundle.md"
  echo "escalation packaged: $dir/bundle.md"
}

finalize_batch() {  # writes the single copy-pasteable batch and halts
  local batch="$ESC_DIR/BATCH.md"
  local n
  n=$(find "$ESC_DIR" -name bundle.md | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] || return 0
  {
    echo "# TPM escalation batch — $n item(s) — spec v$FROZEN_V"
    echo
    echo "> Operator: paste everything below this line into the TPM web chat in one message."
    echo "> The TPM must reply with a DELTA: the full new content of ONLY the changed"
    echo "> frozen files (contracts.json and/or files under tests/, plus ERD.md/PRD.md if"
    echo "> affected). Save the reply files under scripts/.approved/incoming/ preserving"
    echo "> paths (tests go in scripts/.approved/incoming/tests/), then run:"
    echo ">     scripts/refreeze.sh scripts/.approved/incoming"
    echo "> and re-run scripts/orchestrate.sh. Only the affected subtree resumes."
    echo
    echo "---"
    find "$ESC_DIR" -name bundle.md | sort | while read -r b; do
      cat "$b"; echo; echo "---"
    done
  } > "$batch"
  echo ""
  echo "=========================================="
  echo "  HALT: $n escalation(s) need the TPM"
  echo "  -> $batch"
  echo "=========================================="
  exit 2
}

# ==============================================================================
echo "=== Phase: plan ==="
ensure_plan

# --- Re-freeze delta: reset the affected subtree, now that the plan is fresh
# and validated against the new spec (D-31). Tasks whose ENTRIES changed are
# also caught by the fingerprint pass below; this catches the remaining case:
# unchanged entries whose mapped TEST CONTENT changed in the delta.
if [ "$SPEC_ADVANCED" = "1" ]; then
  if [ -f "$APPROVED/DELTA-v$FROZEN_V.json" ]; then
    echo "=== Resetting subtree affected by delta v$FROZEN_V ==="
    affected=$(python3 scripts/validate-plan.py --affected "$APPROVED/DELTA-v$FROZEN_V.json")
    for id in $affected; do
      echo "  reset: $id"
      set_tstat "$id" pending
      rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" 2>/dev/null || true
    done
  fi
  # escalated/blocked tasks get a fresh chance under the new spec
  for f in "$TASK_STATE"/*.status; do
    [ -f "$f" ] || continue
    case "$(cat "$f")" in
      escalated|blocked) printf 'pending\n' > "$f" ;;
    esac
  done
fi
write_state spec_version "$FROZEN_V"

echo "=== Phase: task DAG ==="
while :; do
  TOPO=$(python3 scripts/validate-plan.py --topo) || die "plan invalidated mid-run"

  # fingerprint check: plan entries changed since a task completed -> redo it
  for id in $TOPO; do
    if [ "$(tstat "$id")" = "done" ]; then
      fp_now=$(python3 scripts/validate-plan.py --task "$id" --field fingerprint)
      fp_then=$(cat "$TASK_STATE/$id.fp" 2>/dev/null || true)
      if [ "$fp_now" != "$fp_then" ]; then
        echo "task $id changed in plan — resetting"
        set_tstat "$id" pending
        rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" 2>/dev/null || true
      fi
    fi
  done

  # pick the first actionable task (pending, all deps done)
  NEXT=""
  for id in $TOPO; do
    [ "$(tstat "$id")" = "pending" ] || continue
    deps_ok=1
    for d in $(python3 scripts/validate-plan.py --task "$id" --field depends_on); do
      case "$(tstat "$d")" in
        done) ;;
        escalated|blocked) set_tstat "$id" blocked; deps_ok=0; break ;;
        *) deps_ok=0; break ;;
      esac
    done
    [ "$(tstat "$id")" = "blocked" ] && continue
    [ "$deps_ok" = "1" ] && { NEXT="$id"; break; }
  done
  [ -n "$NEXT" ] || break

  id="$NEXT"
  check_budget "task $id"
  file=$(python3 scripts/validate-plan.py --task "$id" --field file)
  # Read into an array so parametrized node-ids (containing spaces or '['..']')
  # aren't word-split or glob-expanded by an unquoted expansion.
  mapped_out=$(python3 scripts/validate-plan.py --task "$id" --field tests)
  mapped=()
  while IFS= read -r line; do
    [ -n "$line" ] && mapped+=("$line")
  done <<< "$mapped_out"
  smoke=$(python3 -c "import json,sys; cs=json.load(open('scripts/.approved/contracts.json')).get('smoke_checks',{}); print(cs.get(sys.argv[1],''))" "$file")
  brief=$(cat "$BRIEF_DIR/$id" 2>/dev/null || python3 scripts/validate-plan.py --task "$id" --field brief)
  strikes=$(counter "$id" strikes)
  echo "--- Task $id -> $file (strike $((strikes + 1))/$MAX_TASK_STRIKES) ---"

  attempt_brief="$brief

Write EXACTLY one file: $file — the gate rejects any other change, including new files. Before finishing, re-open $file and confirm it satisfies every acceptance condition in this brief."
  last_fail=$(cat "$TASK_STATE/$id.lastfail" 2>/dev/null || true)
  [ -n "$last_fail" ] && attempt_brief="$attempt_brief

The previous attempt failed with: $last_fail. Fix the cause, do not just retry the same content. NOTE: the file may already contain a previous attempt's partial work — read its CURRENT state, find the SMALLEST remaining delta that satisfies the brief, and emit only that; if the file already satisfies the brief, reply === NO CHANGES ===. Do not re-describe or re-apply work that is already present."

  # D-65: files the frozen spec declares unchanged never reach the coder.
  # "Change nothing" is a negative constraint a local model cannot reliably
  # obey (testchat M16: one no-edit coder call damaged index.html, another
  # added redundant code — both briefs said NO EDIT NEEDED). The declaration
  # lives in frozen contracts.no_edit_files (human-approved at refreeze), so
  # the skipped file's provenance is the spec, not luck. Acceptance below
  # (mapped tests + smoke_check) still runs in full.
  no_edit=$(python3 -c "import json,sys; c=json.load(open('scripts/.approved/contracts.json')); print(1 if sys.argv[1] in c.get('no_edit_files', []) else 0)" "$file")

  # acceptance = projection of the frozen oracle (D-28) + optional smoke.
  # A coder call can now fail before any file exists (bad/missing sentinel
  # block, wrong path) — that's evidence like any other test failure, not a
  # script abort, so it's captured rather than left to `set -e`.
  pass=1
  CODER_EVIDENCE=""
  if [ "$no_edit" = "1" ]; then
    echo "  no-edit file (frozen contracts.no_edit_files) — coder not invoked; running acceptance only"
    coder_ok=1
  elif run_coder "$id" "$file" "$attempt_brief" "$((strikes + 1))"; then
    coder_ok=1
  else
    coder_ok=0
  fi
  if [ "$coder_ok" = "1" ]; then
    git add "$file" && git commit -m "[task $id] attempt $((strikes + 1))" 2>/dev/null || true
    # D-74: lint the one file the coder wrote, BEFORE the mapped tests — lint
    # findings are exact-location retry feedback (the D-71 validator-fed
    # pattern) and cheaper than a sandbox pytest run. CI's src/ lint is dark
    # in any child without a remote (2026-07-14 meta-rule); this gate runs
    # where the pipeline runs. Only .py (ruff's domain) and only files the
    # coder actually touched; staged tests get D-67 at the freeze door.
    # Fail-closed on a missing ruff by design: a gate that skips silently is
    # not a gate.
    if [ "$no_edit" != "1" ]; then
      case "$file" in
        *.py)
          command -v ruff >/dev/null 2>&1 \
            || die "ruff not found — the coder-output lint gate (D-74) requires it: pip install ruff"
          if ! LINT_OUT=$(ruff check --no-cache "$file" 2>&1); then
            pass=0
            evidence="lint failed (D-74): $(printf '%s' "$LINT_OUT" | tr '\n' ' ' | head -c 600)"
          fi
          ;;
      esac
    fi
    if [ "$pass" != "1" ]; then
      :  # lint evidence set above; skip tests — the retry re-runs them
    elif [ "${#mapped[@]}" -gt 0 ]; then
      run_tests "${mapped[@]}"
      [ "$TESTS_RC" -eq 0 ] || { pass=0; }
      evidence="mapped tests failing: ${FAILING:-no verdict (rc=$TESTS_RC)}${FAIL_DETAIL:+ — $FAIL_DETAIL}"
    else
      evidence=""
    fi
    if [ "$pass" = "1" ] && [ -n "$smoke" ]; then
      if ! scripts/sandbox-run.sh -- sh -c "$smoke" >/dev/null 2>&1; then
        pass=0; evidence="smoke_check failed: $smoke"
      fi
    fi
  else
    pass=0; evidence="$CODER_EVIDENCE"
  fi

  if [ "$pass" = "1" ]; then
    echo "task $id: PASS"
    mark "task $id PASS"
    set_tstat "$id" done
    python3 scripts/validate-plan.py --task "$id" --field fingerprint > "$TASK_STATE/$id.fp"
    rm -f "$TASK_STATE/$id.lastfail"
    continue
  fi

  echo "task $id: FAIL — $evidence"
  mark "task $id FAIL (strike $((strikes + 1)))"
  printf '%s\n' "$evidence" > "$TASK_STATE/$id.lastfail"
  strikes=$((strikes + 1))
  set_counter "$id" strikes "$strikes"
  [ "$strikes" -lt "$MAX_TASK_STRIKES" ] && continue   # plain retry with failure appended

  # --- Fail-fast (default: MAX_TASK_STRIKES=1) ---
  # Halt and lay out the failure for human review. The EM consult +
  # escalation ladder below only fires when MAX_TASK_STRIKES > 1 (opt-in).
  if [ "$MAX_TASK_STRIKES" -le 1 ]; then
    echo ""
    echo "=========================================="
    echo "  HALT: task $id failed"
    echo "=========================================="
    echo "  File:     $file"
    echo "  Evidence: $evidence"
    echo ""
    echo "  Logs:"
    for _lf in "$LOG_DIR/$id"-a*.raw "$LOG_DIR/$id"-a*.log; do
      [ -f "$_lf" ] && echo "    $_lf"
    done
    die "task $id failed on first attempt — review the logs, fix the plan or spec, and re-run"
  fi

  # EM consult (only when MAX_TASK_STRIKES > 1)
  echo "=== Task $id failed $strikes times -> EM consult ==="
  consult_em "$id" "failed $strikes attempts on $file. $evidence. Coder log tail: $(tail -5 "$LOG_DIR/$id-a$strikes.log" 2>/dev/null | tr '\n' ' ')"
  case "$DIAG_VERDICT" in
    brief_wrong)
      revs=$(counter "$id" revisions)
      if [ "$revs" -ge "$MAX_BRIEF_REVISIONS" ]; then
        echo "brief revisions exhausted for $id -> escalate to TPM"
        package_escalation "caps-exhausted" "$id" "$evidence" "$DIAG_FILE"
        set_tstat "$id" escalated
      else
        set_counter "$id" revisions $((revs + 1))
        python3 -c "
import json, sys
d = json.load(open('$DIAG_FILE'))
sys.stdout.write(d['revised_brief'])" > "$BRIEF_DIR/$id"
        set_counter "$id" strikes 0
        rm -f "$TASK_STATE/$id.lastfail"
        echo "brief revised for $id (revision $((revs + 1))/$MAX_BRIEF_REVISIONS)"
      fi
      ;;
    decomposition_wrong)
      revs=$(plan_revisions_used)
      if [ "$revs" -ge "$MAX_PLAN_REVISIONS" ]; then
        echo "plan revisions exhausted -> escalate to TPM"
        package_escalation "caps-exhausted" "$id" "$evidence" "$DIAG_FILE"
        set_tstat "$id" escalated
      else
        write_state plan_revisions $((revs + 1))
        echo "=== EM: revise decomposition (revision $((revs + 1))/$MAX_PLAN_REVISIONS) ==="
        em_call tasks/plan.json scripts/schemas/plan.schema.json \
          "The decomposition is wrong around task $id: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite the plan fixing it and reply with ONLY the JSON (same requirements as before: one file per task, every inventory-exercising test node-id mapped exactly once, no 'regression' key, erd_version $FROZEN_V, bump plan version, NO status fields). Keep entries for unrelated tasks byte-identical — completed work is preserved only where entries are unchanged." \
          "ERD:$APPROVED/ERD.md" "contracts:$APPROVED/contracts.json" "test-nodeids:$APPROVED/test-nodeids" "plan-being-revised:tasks/plan.json"
        ensure_plan
        set_counter "$id" strikes 0
        rm -f "$TASK_STATE/$id.lastfail"
      fi
      ;;
    contract_or_test_wrong)
      package_escalation "spec-wrong" "$id" "$evidence" "$DIAG_FILE"
      set_tstat "$id" escalated
      ;;
  esac
done

# --- batch halt if anything escalated (batching goal: one operator round-trip) ---
finalize_batch

# --- all tasks done -> feature verdict is the FULL frozen suite (D-28) -------
check_budget "full frozen suite"
echo "=== Full frozen suite ==="
run_tests

# --- D-77: flake triage before declaring drift -------------------------------
# A failing node that is unmapped in the plan (carried-forward, D-57) was never
# touched by this delta: when EVERY failing node is unmapped, the failure is a
# carried-forward flake, not spec drift, and the suite is treated as green with
# a loud WARNING. The plan mapping is the ONLY discriminator. Each unmapped
# node is also re-run twice in isolation, but the result is recorded as
# corroborating evidence and never flips the classification — M28's AC-42
# flake later failed 4/4 IN ISOLATION under host memory load, so an isolated
# run measures the environment as much as the test. Any mapped node or
# collection error keeps the DRIFT path exactly as before.
FLAKE_NOTE=""
if [ "$TESTS_RC" -eq 1 ] && [ -n "$FAILING" ] \
  && [[ "$FAILING" != *COLLECTION_ERROR* ]]; then
  all_carried=1
  saved_failing="$FAILING" saved_detail="$FAIL_DETAIL"
  IFS='|' read -r -a _fail_ids <<< "$FAILING"
  for fid in "${_fail_ids[@]}"; do
    mapped=$(python3 -c "import json,sys
p = json.load(open('tasks/plan.json'))
print(1 if any(sys.argv[1] in t['tests'] for t in p['tasks']) else 0)" "$fid")
    if [ "$mapped" != "0" ]; then
      all_carried=0; break   # delta-mapped node failing = real drift
    fi
  done
  iso_evidence=""
  if [ "$all_carried" -eq 1 ]; then
    for fid in "${_fail_ids[@]}"; do
      iso_pass=0
      for _try in 1 2; do
        run_tests "$fid"
        if [ "$TESTS_RC" -eq 0 ]; then iso_pass=$((iso_pass + 1)); fi
      done
      iso_evidence="${iso_evidence:+$iso_evidence; }$fid: $iso_pass/2 isolated passes"
    done
  fi
  FAILING="$saved_failing"; FAIL_DETAIL="$saved_detail"; TESTS_RC=1
  if [ "$all_carried" -eq 1 ]; then
    echo "WARNING (D-77): every full-suite failure is a carried-forward node,"
    echo "  unmapped in the plan — flake, not drift. Isolation evidence: $iso_evidence"
    FLAKE_NOTE="
WARNING (D-77): carried-forward node(s) failed in the full run — flake, not drift ($iso_evidence). A recurring flake is a frozen-test defect: it belongs to the TPM at the next refreeze."
    TESTS_RC=0
  fi
fi

if [ "$TESTS_RC" -eq 0 ]; then
  echo ""
  echo "=========================================="
  echo "  ALL FROZEN TESTS PASS — feature done"
  echo "  total run time: $(run_elapsed)s (timings were in $LOG_DIR/timings.tsv)"
  echo "=========================================="
  cat >> tasks/CURRENT.md <<EOF

## Results

Full frozen TPM suite green against spec v$FROZEN_V. Feature built and validated.${FLAKE_NOTE}
EOF
  rm -rf "$STATE_DIR"
  git add tasks/CURRENT.md && git commit -m "[success] spec v$FROZEN_V" 2>/dev/null || true
  exit 0
fi

# tasks green but suite red = SPEC DRIFT: routes EM -> TPM, never coder retries (D-28)
echo "=== SPEC DRIFT: every task passed its projection but the full suite is red ==="
drift_evidence="all tasks done and individually green; full suite failing: ${FAILING:-no verdict (rc=$TESTS_RC)}${FAIL_DETAIL:+ — $FAIL_DETAIL}"

if [ "$MAX_TASK_STRIKES" -le 1 ]; then
  echo ""
  echo "=========================================="
  echo "  HALT: spec drift — full suite red"
  echo "=========================================="
  echo "  $drift_evidence"
  die "spec drift detected — review failing tests, fix the plan or spec, and re-run"
fi

consult_em "DRIFT" "$drift_evidence"
if [ "$DIAG_VERDICT" = "decomposition_wrong" ] && [ "$(plan_revisions_used)" -lt "$MAX_PLAN_REVISIONS" ]; then
  write_state plan_revisions $(( $(plan_revisions_used) + 1 ))
  em_call tasks/plan.json scripts/schemas/plan.schema.json \
    "Spec drift: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite the plan to fix the decomposition and reply with ONLY the JSON (same requirements as before; keep unrelated entries byte-identical)." \
    "ERD:$APPROVED/ERD.md" "contracts:$APPROVED/contracts.json" "test-nodeids:$APPROVED/test-nodeids" "plan-being-revised:tasks/plan.json"
  ensure_plan
  echo "plan revised for drift — re-run scripts/orchestrate.sh to resume"
  exit 1
fi
package_escalation "spec-drift" "DRIFT" "$drift_evidence" "$DIAG_FILE"
finalize_batch
