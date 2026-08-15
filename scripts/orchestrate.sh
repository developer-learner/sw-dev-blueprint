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
# Exit codes: 0 feature done (delta-mapped tests green) · 1 hard failure or
# gate violation · 2 halted awaiting TPM (escalation batch written).
#
# Verdict scope (D-112): milestone completion is judged by the delta's
# dependent set — the union of every test node-id the plan mapped — never by
# the carried-forward suite. The FULL frozen suite is an on-demand regression
# check: scripts/orchestrate.sh --full-suite.
set -euo pipefail

MAX_TASK_STRIKES="${MAX_TASK_STRIKES:-2}"      # coder attempts per brief (D-70: 2 arms the escalation ladder — consult/verdicts were dead code for ~23 milestones under 1; D-69's run budget bounds the thrash fail-fast guarded against)
MAX_BRIEF_REVISIONS="${MAX_BRIEF_REVISIONS:-1}" # EM brief_wrong rewrites per task
MAX_PLAN_REVISIONS="${MAX_PLAN_REVISIONS:-2}"   # EM plan re-emits per run (validation retries + decomposition_wrong); default 2: the validator's error feedback demonstrably fixes plans on the second emit (testchat M6)
AGENT_TIMEOUT="${AGENT_TIMEOUT:-1800}"
CONTEXT_BUDGET_TOOL="scripts/context-budget.py"

# Wave 1 (D-107-class): the required plan/task keys, named verbatim in every
# plan-emission prompt. The EM is stateless (D-53) and response_format is only
# advisory when the server ignores it; naming keys inline stops the model
# inventing key names (observed 2026-08-02 model-add: top-level "plan" for
# "tasks", per-task "test_nodes" for "tests").
EM_TASK_KEYS='SCHEMA — name these keys verbatim; the validator rejects any others. Top-level object: {"erd_version": N, "version": N, "tasks": [ ... ]} — the tasks array is under the key "tasks" (never "plan"). Each task object has EXACTLY these six keys: {"id": "...", "file": "...", "depends_on": [], "brief": "...", "contracts": [], "tests": ["<node-id>", ...]}. The names test_nodes, acceptance, regression, and status are NOT valid task keys and are rejected.'
# Phase 3: the never-invent-contract-id rule, stated verbatim at every
# plan-emission site next to EM_TASK_KEYS. The rule alone was inoperative —
# the EM still emitted dotted-path guesses like "src.api.models" for
# "src/api/models.py" (5 of 32 archived plan-gate rejections, all subtree
# re-plans) — so the shell also prints the flat verbatim id list (contract_ids)
# the validator accepts. Copying beats deriving.
EM_CONTRACT_ID_RULE='CONTRACT IDS — the task "contracts" array holds ONLY exact strings from the valid-id list the shell prints after this rule (or is empty). Copy ids VERBATIM: a registered id is its exact string — never convert a file path to dotted form (src/api/models.py is a path; "src.api.models" is not a registered id), never add or drop a file extension, never invent a prefix. The validator rejects any contracts entry not on the list.'
contract_ids() {
  # D-124: the verbatim id list is scoped to this milestone, not the
  # accumulated all-milestone dump. Entries whose owner file is in the plan
  # inventory are kept; unattributable ids (ui/external) are kept only when
  # the inventory is frontend or ERD-DELTA names them; entry_points are kept
  # by module match. The validator + contract-repair still reject/drop
  # anything the scope misses, and an empty contracts array is always legal.
  python3 - "$APPROVED/contracts.json" \
    "${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" <<'PY'
import json, os, sys
c = json.load(open(sys.argv[1]))
try:
    erd = open(sys.argv[2]).read()
except OSError:
    erd = ""
active = os.environ.get("SWBP_CONTRACT_FILES")
files = set(active.splitlines()) if active is not None else set(c.get("files", []))
mods = {f[:-3].replace("/", ".") if f.endswith(".py") else f for f in files}
frontend = any(f.startswith("src/static/") for f in files)
ids = []
def add(x):
    if isinstance(x, str):
        ids.append(x)
    elif isinstance(x, dict) and "id" in x:
        if x.get("file") in files:
            ids.append(x["id"])
        elif not x.get("file") and (frontend or x["id"] in erd):
            ids.append(x["id"])
for key in ("files", "entry_points", "routes", "schemas", "errors", "externals", "ui", "smoke_checks"):
    for x in (c.get(key) or []):
        if isinstance(x, str) and key == "entry_points":
            base = x.split(":", 1)[0]
            if any(base == m or base.startswith(m + ":") for m in mods):
                ids.append(x)
        else:
            add(x)
print(", ".join(dict.fromkeys(ids)))
PY
}
# D-119: the delta-scoped node-id set for re-plan calls. The plan maps only
# node-ids that exercise delta files (carried coverage is shell-routed), so
# the plan's own union IS the delta scope — the same extraction as the
# D-112 verdict union. Re-plan calls print it as a flat list instead of
# shipping the full 198-id test-nodeids file; the EM keeps its safe-omit
# rule, and the validator names any node-id it must still map.
plan_mapped_ids() {
  python3 -c "
import json
try:
    p = json.load(open('tasks/plan.json'))
except (OSError, ValueError):
    print('(none)')
    raise SystemExit(0)
ids = []
for t in p.get('tasks', []):
    for n in t.get('tests', []):
        if n not in ids:
            ids.append(n)
print(', '.join(ids) if ids else '(none)')"
}
# D-69: wall-clock budget for the WHOLE run, in seconds (0 disables). With
# D-60 atomic tasks and a non-thinking local coder, a healthy run finishes in
# minutes — a run that blows past this is thrashing (thinking drift, EM loops,
# misconfiguration), and fail-fast applies to time the same as to strikes.
# Checked BETWEEN phases only (never kills a call mid-flight); on breach the
# run halts and prints the phase-timing table. State persists (D-24): a
# re-run resumes from completed tasks, so a budget halt is cheap.
SWBP_RUN_BUDGET="${SWBP_RUN_BUDGET:-1200}"
# Edit-mode output allowance for the coder (D-59 anchored SEARCH/REPLACE
# blocks). Historically hardcoded to 4096 — half of create mode — because
# testchat M17 showed edit replies are small by design and a smaller budget
# halves the wall-clock cost of a runaway attempt. Made overridable after
# M33 v76 escalated with two attempts truncated mid-prose at the 4096-token
# limit; the seat had exhausted its budget on explanation and never reached
# an edit block. This is a bounded diagnostic control — the default stays
# 4096, and the correct next step for a persistent budget bind is a seat
# or prompt fix, not raising the default silently.
SWBP_CODER_EDIT_MAX_OUTPUT="${SWBP_CODER_EDIT_MAX_OUTPUT:-4096}"
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
#   mypy-green/<sha256>  successful mypy result for one exact source/config state
#   briefs/<id>          EM-revised brief overriding the plan's brief
#   logs/<id>-a<n>.raw|.log   coder attempt transcripts; em-last.raw|.err
#   escalations/<id>/bundle.md, escalations/BATCH.md   TPM bundles (D-29)
# Successful task definitions + output hashes live separately in the tracked
# .pipeline-completions.json ledger (D-108). Runtime state is still ephemeral.
# Accepted D-77 exceptions live in tracked .pipeline-flakes.json (D-111).
STATE_DIR=".pipeline-state"
TASK_STATE="$STATE_DIR/tasks"
BRIEF_DIR="$STATE_DIR/briefs"
LOG_DIR="$STATE_DIR/logs"
ESC_DIR="$STATE_DIR/escalations"
COMPLETION_LEDGER=".pipeline-completions.json"
COMPLETION_LEDGER_TOOL="scripts/completion-ledger.py"
FLAKE_LEDGER=".pipeline-flakes.json"
FLAKE_LEDGER_TOOL="scripts/flake-ledger.py"
METRICS_REPORT_TOOL="scripts/metrics-report.py"
FLAKE_ESCALATION_THRESHOLD="${SWBP_FLAKE_ESCALATION_THRESHOLD:-3}"
APPROVED="scripts/.approved"
mkdir -p "$STATE_DIR" "$TASK_STATE" "$BRIEF_DIR" "$LOG_DIR" "$ESC_DIR"

# Durable archive of every EM call (survives rm -rf .pipeline-state on success).
# Pure capture — nothing reads these during a run; they feed offline bench-testing
# (scripts/em-bench.sh, backlog item 6).
ARCHIVE_DIR=".em-archive"
mkdir -p "$ARCHIVE_DIR"
# Self-ignoring: the archive must never surface in the clean-tree pre-flight
# or the lane gates — including in children whose repo .gitignore predates
# this feature (.gitignore is not template-owned and never syncs, the same
# gap class as ci.yml). The directory carries its own ignore rule instead of
# depending on one. testchat 2026-07-19 needed a hand-applied ignore line;
# this removes that class.
[ -f "$ARCHIVE_DIR/.gitignore" ] || printf '*\n' > "$ARCHIVE_DIR/.gitignore"
LAST_ARCHIVE_ENTRY=""

# Durable run-measurement sink (Phase 5 instrumentation, 2026-08-06): one
# timestamped row per firing in .measurement/counters. Survives the success
# teardown's rm -rf .pipeline-state (timings.tsv is wiped with it). Pure
# capture — nothing reads it during a run, and a write can never fail the run.
# Same self-ignoring pattern as .em-archive so it never surfaces in the
# clean-tree pre-flight.
MEAS_DIR=".measurement"
mkdir -p "$MEAS_DIR" 2>/dev/null || true
[ -f "$MEAS_DIR/.gitignore" ] || printf '*\n' > "$MEAS_DIR/.gitignore" 2>/dev/null || true
meas() { printf '%s\t%s\n' "$(date -u +%FT%TZ)" "$1" >> "$MEAS_DIR/counters" 2>/dev/null || true; }

die() { echo "FAIL: $*" >&2; exit 1; }

# D-112: verdict scope. Default: milestone done = the delta's mapped
# (dependent) tests green. --full-suite opts the verdict run into the whole
# frozen suite as an on-demand/periodic regression check, where the D-77
# flake triage and the DRIFT halt below apply unchanged.
FULL_SUITE_CHECK=0
for _arg in "$@"; do
  case "$_arg" in
    --full-suite) FULL_SUITE_CHECK=1 ;;
    *) die "unknown argument: $_arg (supported: --full-suite)" ;;
  esac
done

# Single-writer lock on the state dir. Every counter in .pipeline-state/
# (strikes, plan_revisions, phase, task_target, spec_version) is a plain
# file with a write-then-read pattern that assumes no concurrent runs.
# flock -n fails immediately if another orchestrate is already holding
# the lock, so a second run halts with a clear message instead of
# silently corrupting the state files of the run in progress.
# flock(1) ships with Linux/util-linux but not stock macOS. Where it exists,
# use it — the kernel releases the lock automatically when the process exits,
# even on a crash. Where it doesn't, fall back to an atomic mkdir lock keyed by
# owner pid: mkdir is a portable test-and-set, and a liveness check on the
# recorded pid reclaims a lock left by a crashed run (the release flock gets
# for free). Either path makes a second concurrent run halt with a clear
# message instead of corrupting the in-flight run's counter files.
if command -v flock >/dev/null 2>&1; then
  exec 200> "$STATE_DIR/.lock"
  flock -n 200 \
    || die "another scripts/orchestrate.sh is already running (holds $STATE_DIR/.lock) — wait for it to finish or kill it, then retry"
else
  _lockdir="$STATE_DIR/.lockdir"
  if ! mkdir "$_lockdir" 2>/dev/null; then
    _owner=$(cat "$_lockdir/pid" 2>/dev/null || true)
    if [ -n "$_owner" ] && kill -0 "$_owner" 2>/dev/null; then
      die "another scripts/orchestrate.sh is already running (pid $_owner, holds $_lockdir) — wait for it to finish or kill it, then retry"
    fi
    # stale lock from a dead run — reclaim it
    rm -f "$_lockdir/pid"; rmdir "$_lockdir" 2>/dev/null || true
    mkdir "$_lockdir" 2>/dev/null \
      || die "could not acquire state lock $_lockdir (stale-lock reclaim failed) — inspect and remove it manually, then retry"
  fi
  printf '%s\n' "$$" > "$_lockdir/pid"
fi

# --- state helpers (files, not shell vars: crash checkpoint per D-24) ---
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
tstat()       { [ -f "$TASK_STATE/$1.status" ] && cat "$TASK_STATE/$1.status" || echo pending; }
set_tstat()   { printf '%s\n' "$2" > "$TASK_STATE/$1.status"; }
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_counter() { printf '%s\n' "$3" > "$TASK_STATE/$1.$2"; }

# BEGIN D-113 prior-spec resolution (selftest extracts this function)
resolve_last_spec_version() {
  local last_v
  # A runtime version without any task checkpoint can survive partial state
  # loss. It is not authoritative: fall back to the last complete success so
  # every intervening delta is replayed before completions are trusted.
  if [ -n "$(ls -A "$TASK_STATE" 2>/dev/null || true)" ]; then
    last_v=$(read_state spec_version)
  else
    last_v=""
  fi
  if [ -z "$last_v" ] && [ -f "$COMPLETION_LEDGER" ]; then
    last_v=$(python3 "$COMPLETION_LEDGER_TOOL" latest \
      --ledger "$COMPLETION_LEDGER") \
      || die "durable completion ledger could not supply the prior spec version"
    [ "$last_v" != "0" ] || last_v=""
  fi
  last_v=${last_v:-$FROZEN_V}
  case "$last_v" in
    ''|*[!0-9]*|0) die "invalid prior spec version '$last_v'" ;;
  esac
  [ "$last_v" -le "$FROZEN_V" ] \
    || die "prior successful spec v$last_v is newer than frozen spec v$FROZEN_V"
  printf '%s\n' "$last_v"
}
# END D-113 prior-spec resolution

# guard_task_state — distinguish intentional post-success cleanup from loss
# during an unfinished milestone. Both present as an empty gitignored state
# directory, but their git histories differ: after a completed run, the newest
# task commit is an ancestor of the newest [success] commit. If a task landed
# after the last success, state disappeared while work was in flight and the
# fail-closed halt still applies.
guard_task_state() {
  [ -z "$(ls -A "$TASK_STATE" 2>/dev/null || true)" ] || return 0
  local latest_task latest_success
  latest_task=$(git log --grep='^\[task ' -1 --format=%H 2>/dev/null || true)
  [ -n "$latest_task" ] || return 0
  latest_success=$(git log --grep='^\[success\]' -1 --format=%H 2>/dev/null || true)
  if [ -n "$latest_success" ] \
     && git merge-base --is-ancestor "$latest_task" "$latest_success" 2>/dev/null; then
    echo "  pipeline task-state: clean post-success state — durable completion restore is allowed"
    return 0
  fi
  if [ "${SWBP_REBUILD_FROM_SCRATCH:-0}" = "1" ]; then
    echo "  WARNING: empty task-state accepted by explicit SWBP_REBUILD_FROM_SCRATCH=1"
    return 0
  fi
  die "pipeline task-state is empty, but the newest [task] commit is not covered by a later [success] — .pipeline-state/tasks/ was LOST mid-milestone.
  Every unfinished task would read 'pending' and the coder could be handed files no delta touches.
  Recover the task status/fingerprint files from the run record before retrying.
  If a full rebuild is genuinely intended, make that destructive scope explicit:
    SWBP_REBUILD_FROM_SCRATCH=1 scripts/orchestrate.sh"
}

# --- run clock (D-69): phase-timing log + wall-clock budget ------------------
# timings.tsv gets one row per phase boundary; the budget halt prints it, and
# post-run tuning reads it — no historical run had per-phase numbers, so every
# "where did 45 minutes go" was guesswork.
case "$SWBP_RUN_BUDGET" in
  ''|*[!0-9]*) die "SWBP_RUN_BUDGET must be a non-negative integer (seconds), got '$SWBP_RUN_BUDGET'" ;;
esac
case "$SWBP_CODER_EDIT_MAX_OUTPUT" in
  ''|*[!0-9]*|0) die "SWBP_CODER_EDIT_MAX_OUTPUT must be a positive integer (tokens), got '$SWBP_CODER_EDIT_MAX_OUTPUT'" ;;
esac
case "$FLAKE_ESCALATION_THRESHOLD" in
  ''|*[!0-9]*|0) die "SWBP_FLAKE_ESCALATION_THRESHOLD must be a positive integer, got '$FLAKE_ESCALATION_THRESHOLD'" ;;
esac
run_elapsed() { echo $(( $(date +%s) - RUN_T0 )); }
mark() { printf '%s\t%ss\t%s\n' "$(date '+%H:%M:%S')" "$(run_elapsed)" "$1" >> "$LOG_DIR/timings.tsv"; }

# --- exit trap: record how the run ended, always ------------------------------
# M33 v76 (2026-08-02): the run died mid-T1 with no HALT, no escalation, no
# final timing mark — orchestrate crashed under `set -euo pipefail` and every
# subsequent measurement was blind because no artifact recorded the exit.
#
# Persist one run's terminal measurement while its timing source still exists.
# The success path calls this before teardown; record_exit covers every other
# termination path. Measurement remains report-only and can never fail a run.
record_measurement() {  # record_measurement <rc> <phase> <task>
  local rc="$1" phase="$2" task="$3"
  mkdir -p "$MEAS_DIR" 2>/dev/null || true
  if [ -d "$MEAS_DIR" ]; then
    [ -f "$LOG_DIR/timings.tsv" ] \
      && cp "$LOG_DIR/timings.tsv" "$MEAS_DIR/timings-$(date -u +%FT%TZ).tsv" 2>/dev/null || true
    meas "exit rc=$rc phase=${phase:-<none>} task=${task:-<none>} spec=${FROZEN_V:-unknown} revisions=$(plan_revisions_used) elapsed=$(run_elapsed)s"
  fi
}

# trap runs on EVERY exit path (success, die, uncaught error) and appends one
# row to run-exit.log: iso-timestamp, exit code, last recorded phase, current
# task target, last timings row. It does NOT invent an escalation for an
# unexpected crash — that would blur real defects with harness bugs. Its
# invariant is only: after this trap runs, the next feature-summary can
# distinguish "died silently" from "halted cleanly", and can bound the
# unaccounted wall-clock window.
record_exit() {
  local rc=$?
  local phase task last_ts
  phase=$( [ -f "$STATE_DIR/phase" ] && cat "$STATE_DIR/phase" 2>/dev/null || echo "" )
  task=$( [ -f "$STATE_DIR/task_target" ] && cat "$STATE_DIR/task_target" 2>/dev/null || echo "" )
  last_ts=$( [ -f "$LOG_DIR/timings.tsv" ] && tail -1 "$LOG_DIR/timings.tsv" 2>/dev/null | tr '\t' ' ' || echo "" )
  # The success teardown removes .pipeline-state/ (LOG_DIR included) BEFORE this
  # EXIT trap fires, so an unguarded append failed and — under set -e — flipped
  # a green run's exit code to 1 (misleading any exit-code-keyed automation).
  # Recreate the dir so every exit (success included) is still recorded, and
  # guard the write so it can never itself fail the run.
  mkdir -p "$LOG_DIR" 2>/dev/null || true
  if [ -d "$LOG_DIR" ]; then
    printf '%s\trc=%s\tphase=%s\ttask=%s\telapsed=%ss\tlast_mark=%s\n' \
      "$(date -u +%FT%TZ)" "$rc" "${phase:-<none>}" "${task:-<none>}" \
      "$(run_elapsed)" "${last_ts:-<none>}" \
      >> "$LOG_DIR/run-exit.log"
  fi
  # Success has already persisted the same terminal event before deleting its
  # timing source. Do not append a duplicate rc=0 row from this EXIT trap.
  if [ "${SUCCESS_RECORDED:-0}" != "1" ]; then
    record_measurement "$rc" "$phase" "$task"
  fi
  return $rc
}
trap 'record_exit' EXIT

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

# check_ci_health — D-85: a red CI stops the line.
#
# CI is the one check that runs OUTSIDE this pipeline's own gates, so it is
# the only thing that catches what the gates structurally cannot (type errors,
# lint, a stale lockfile, anything the frozen suite does not assert). Nothing
# consumed its verdict until now: testchat ran RED for 7 days and 46 runs on a
# single mypy error, and shipped `[success] spec v56` during the blackout —
# every internal gate green and correct, the external one shouting into a void
# (2026-07-24). The 2026-07-14 correction-log rule already said to verify CI
# before trusting any quality claim; it had no teeth, so it decayed.
#
# Fail-closed on a RED verdict; explicitly INCONCLUSIVE (warn, proceed) when
# the answer cannot be obtained. A check that did not run must say so rather
# than imply green — Rule 4, and the D-75 precedent for advisory reporting.
# The escape hatch is deliberate and named: running the pipeline is often
# exactly how a red CI gets fixed, and a gate with no override in that
# situation is a deadlock, not a safeguard.
check_ci_health() {
  if [ "${SWBP_SKIP_CI_CHECK:-0}" = "1" ]; then
    echo "  CI health: SKIPPED (SWBP_SKIP_CI_CHECK=1)"
    return 0
  fi
  local remote branch runs_json verdict state detail
  remote=$(git remote get-url origin 2>/dev/null || true)
  if [ -z "$remote" ]; then
    echo "  CI health: no 'origin' remote — skipped (CI cannot exist yet; the 2026-07-14 meta-rule)"
    return 0
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "  WARNING: CI health INCONCLUSIVE — 'gh' not installed, cannot read CI status. Proceeding."
    return 0
  fi
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  [ -n "$branch" ] && [ "$branch" != "HEAD" ] || {
    echo "  WARNING: CI health INCONCLUSIVE — detached HEAD, no branch to query. Proceeding."
    return 0
  }
  # One network call, bounded; python3 (already a hard requirement) parses it,
  # so this adds no jq dependency.
  runs_json=$(timeout 20 gh run list --branch "$branch" --limit 20 \
      --json conclusion,status,workflowName 2>/dev/null || true)
  if [ -z "$runs_json" ]; then
    echo "  WARNING: CI health INCONCLUSIVE — 'gh run list' returned nothing (not authenticated, no runs, or network). Proceeding."
    return 0
  fi
  verdict=$(printf '%s' "$runs_json" | python3 -c '
import json, sys
try:
    runs = json.load(sys.stdin)
except Exception:
    print("INCONCLUSIVE|gh output was not valid JSON"); sys.exit(0)
if not runs:
    print("NONE|no CI runs on this branch yet"); sys.exit(0)
# gh returns newest first; keep the newest run of EACH workflow. Checking only
# the single newest run would let a green sibling workflow (check-drift) mask a
# red CI, which is exactly the blackout this decision exists to prevent.
latest = {}
for r in runs:
    latest.setdefault(r.get("workflowName") or "?", r)
red = sorted(n for n, r in latest.items()
             if r.get("status") == "completed" and r.get("conclusion") == "failure")
pending = sorted(n for n, r in latest.items() if r.get("status") != "completed")
if red:
    print("RED|" + ", ".join(red))
elif pending:
    print("PENDING|" + ", ".join(pending))
else:
    print("GREEN|" + ", ".join(sorted(latest)))
' 2>/dev/null || true)
  state="${verdict%%|*}"; detail="${verdict#*|}"
  case "$state" in
    GREEN)   echo "  CI health: green on '$branch' ($detail)" ;;
    PENDING) echo "  CI health: run(s) still in flight on '$branch' ($detail) — not a failure; proceeding" ;;
    NONE)    echo "  CI health: $detail — proceeding" ;;
    RED)
      die "CI is RED on branch '$branch' — failing workflow(s): $detail.
  The pipeline would build on a codebase whose external checks are failing.
  CI catches what these gates structurally cannot (types, lint, packaging);
  testchat shipped a [success] during a 7-day CI blackout because nothing
  consumed this verdict (2026-07-24). That is what this check exists to stop.
    see it:     gh run list --branch $branch --limit 5
    diagnose:   gh run view --log-failed
  If the failure is unrelated to this run — or you are running the pipeline
  precisely in order to fix it — re-run with the override:
    SWBP_SKIP_CI_CHECK=1 scripts/orchestrate.sh" ;;
    *)       echo "  WARNING: CI health INCONCLUSIVE — ${detail:-unrecognized verdict}. Proceeding." ;;
  esac
}

# archive_em <out-file> [<outcome>] — persist prompt + reply for offline
# replay (em-bench.sh). Called after every em_call attempt, success AND
# failure — the failed attempts (outcome=invalid_json, or a later
# validation=schema_invalid append) are the corpus the diagnosis-brief work
# (backlog item 6) needs most. consult_em / ensure_plan append verdict and
# gate metadata afterwards.
# Guarded: no-ops when ARCHIVE_DIR is unset (selftest extracts em_call without this).
archive_em() {
  [ -n "${ARCHIVE_DIR:-}" ] || return 0
  local out="$1" outcome="${2:-ok}"
  local ts; ts=$(date '+%Y-%m-%d_%H%M%S')
  local tag; tag=$(basename "$out" .json)
  # Same-second entries must not share a directory (a collision overwrites
  # the earlier record silently) — suffix until unique.
  local entry="$ARCHIVE_DIR/${ts}_${tag}" n=2
  while [ -e "$entry" ]; do entry="$ARCHIVE_DIR/${ts}_${tag}_$n"; n=$((n + 1)); done
  mkdir -p "$entry" || return 0
  cp "$LOG_DIR/em-last.prompt" "$entry/prompt.txt" 2>/dev/null || true
  cp "$LOG_DIR/em-last.raw" "$entry/reply.json" 2>/dev/null || true
  cp "$LOG_DIR/em-last.err" "$entry/stderr.log" 2>/dev/null || true
  cp tasks/plan.json "$entry/plan.json" 2>/dev/null || true
  cp "$APPROVED/contracts.json" "$entry/contracts.json" 2>/dev/null || true
  printf 'spec_version=%s\nout=%s\ntimestamp=%s\noutcome=%s\n' \
    "${FROZEN_V:-unknown}" "$out" "$ts" "$outcome" > "$entry/meta.txt"
  LAST_ARCHIVE_ENTRY="$entry"
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
[ -f "$CONTEXT_BUDGET_TOOL" ]     || die "$CONTEXT_BUDGET_TOOL missing"
[ -f "$COMPLETION_LEDGER_TOOL" ]    || die "$COMPLETION_LEDGER_TOOL missing"
[ -f "$FLAKE_LEDGER_TOOL" ]       || die "$FLAKE_LEDGER_TOOL missing"
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
# S6 (2026-08-06): fail closed on a staged-but-uninstalled spec delta.
# M34's EM plan calls ran against the STAGED spec — the [refreeze vN] commit
# landed after the calls, so plan and spec disagreed by one freeze (~5 h 42 m
# measured from the wrong basis). incoming/ is gitignored, so the clean-tree
# check above cannot see it; this check must be explicit. Install the staging
# dir (refreeze.sh) or clear it before running.
if [ -d scripts/.approved/incoming ] && [ -n "$(ls -A scripts/.approved/incoming 2>/dev/null || true)" ]; then
  die "scripts/.approved/incoming is populated — a staged-but-uninstalled delta would misalign this run against the frozen spec (S6, M34 class). Run scripts/refreeze.sh scripts/.approved/incoming to install it, or clear the staging dir, then retry."
fi
# Lost task-state reads identically to intentional success cleanup unless the
# git history is consulted. Fail closed only when the latest task is not
# covered by a later success; guard_task_state also provides an explicit,
# named full-rebuild override instead of the old ineffective "delete the
# already-empty directory" instruction.
guard_task_state
# Control-plane + frozen-artifact integrity (phase-gate verifies both, fail-closed)
bash scripts/phase-gate.sh manifest HEAD
# The frozen spec is admitted only through scripts/refreeze.sh, which
# auto-installs after every mechanical preflight passes (D-121). No
# honor-string or separate human approval step exists in this lane.
[ -f "$APPROVED/frozen-manifest" ] || die "no frozen TPM spec — install PRD/ERD/contracts/tests via scripts/refreeze.sh"
[ -f "$APPROVED/VERSION" ]         || die "$APPROVED/VERSION missing — run scripts/refreeze.sh"
FROZEN_V=$(cat "$APPROVED/VERSION")
# D-85: the external verdict. Placed after every free local check; a red CI
# costs one bounded API call instead of anything heavier. The D-55 EM round-
# trip smoke is NOT here — it is lazy: it fires only inside em_call, just
# before the first real EM call of a run that actually needs the EM (P1e /
# board finding 6). A run whose plan is mechanically synthesized (B3) never
# calls the EM at all and therefore spends zero model calls on probing.
check_ci_health
echo "OK (frozen spec v$FROZEN_V)"
mark "pre-flight done (spec v$FROZEN_V)"

# D-116: the EM's standing context is a generated minimal summary (standing
# rules + per-file map), never the accumulated standing ERD — the milestone
# slice is ERD-DELTA.md (D-107). A generation failure falls back to the full
# standing ERD; it never silently shrinks the EM's context.
STANDING_SUMMARY="$STATE_DIR/standing-summary.md"
if [ -f "$APPROVED/ERD.md" ] \
  && python3 scripts/standing-summary.py "$APPROVED/ERD.md" > "$STANDING_SUMMARY" 2>/dev/null; then
  python3 "$CONTEXT_BUDGET_TOOL" warn standing-summary "$STANDING_SUMMARY"
  echo "  standing context: generated summary ($(wc -l < "$STANDING_SUMMARY" | tr -d ' ') lines, vs $(wc -l < "$APPROVED/ERD.md" | tr -d ' ') in ERD.md)"
else
  STANDING_SUMMARY="$APPROVED/ERD.md"
  echo "  WARNING: standing summary generation failed — EM context falls back to the full standing ERD"
fi

# --- Parse .gate-paths for the build lane ---
build_dir="src/"
_raw=$(grep '^build=' .gate-paths | cut -d= -f2- || true)
if [ -n "$_raw" ]; then
  _raw="${_raw#./}"; _raw="${_raw%"${_raw##*[![:space:]]}"}"; build_dir="${_raw%/}/"
fi

# --- Re-freeze detection (the reset itself runs after the plan is fresh) ---
# Success intentionally deletes the runtime state, including spec_version.
# Recover that version from the validated durable ledger so a new freeze still
# arms its affected-task reset before any exact-match completion is trusted.
# An explicit from-scratch run bypasses durable history in both places.
if [ "${SWBP_REBUILD_FROM_SCRATCH:-0}" = "1" ]; then
  LAST_V="$FROZEN_V"
else
  LAST_V=$(resolve_last_spec_version)
fi
SPEC_ADVANCED=0
if [ "$FROZEN_V" != "$LAST_V" ]; then
  SPEC_ADVANCED=1
  echo "frozen spec advanced v$LAST_V -> v$FROZEN_V"
  rm -rf "$ESC_DIR"; mkdir -p "$ESC_DIR"   # bundles answered by this delta are consumed
fi

# Keep the last successful baseline for the whole in-progress milestone. After
# the first reset, spec_version advances to the current freeze; without this
# separate checkpoint a retry would narrow D-65 back to the newest delta and
# strand tasks hit only by an earlier skipped freeze (D-113).
if [ "${SWBP_REBUILD_FROM_SCRATCH:-0}" = "1" ]; then
  DELTA_BASELINE_V="$FROZEN_V"
else
  DELTA_BASELINE_V=$(read_state delta_baseline_spec)
  DELTA_BASELINE_V=${DELTA_BASELINE_V:-$LAST_V}
fi
case "$DELTA_BASELINE_V" in
  ''|*[!0-9]*|0) die "invalid delta baseline spec version '$DELTA_BASELINE_V'" ;;
esac
[ "$DELTA_BASELINE_V" -le "$FROZEN_V" ] \
  || die "delta baseline v$DELTA_BASELINE_V is newer than frozen spec v$FROZEN_V"
write_state delta_baseline_spec "$DELTA_BASELINE_V"

# The last successful run can be more than one freeze behind. Every retained
# delta in that range participates in task reset and D-65 edit scope; looking
# only at the newest delta can restore a task affected by an earlier skipped
# milestone. Missing history is not safe to guess through (D-113).
# BEGIN D-113 active-delta range (selftest extracts this block)
ACTIVE_DELTA_FILES=()
if [ "$DELTA_BASELINE_V" -lt "$FROZEN_V" ]; then
  for delta_v in $(seq $((DELTA_BASELINE_V + 1)) "$FROZEN_V"); do
    delta_file="$APPROVED/DELTA-v$delta_v.json"
    [ -f "$delta_file" ] \
      || die "cannot preserve delta scope across v$DELTA_BASELINE_V -> v$FROZEN_V: missing $delta_file"
    ACTIVE_DELTA_FILES+=("$delta_file")
  done
elif [ -f "$APPROVED/DELTA-v$FROZEN_V.json" ]; then
  ACTIVE_DELTA_FILES+=("$APPROVED/DELTA-v$FROZEN_V.json")
fi
# D-138: every validator invocation consumes this same exact D-113 range.
SWBP_ACTIVE_DELTA_FILES=""
if [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
  printf -v SWBP_ACTIVE_DELTA_FILES '%s\n' "${ACTIVE_DELTA_FILES[@]}"
fi
export SWBP_ACTIVE_DELTA_FILES
# END D-113 active-delta range

# D-140: planning consumes every freeze's immutable instruction slice in the
# active D-113 range, never only the newest ERD-DELTA.md. The validator owns
# legacy Git recovery and the exact zero-work packet, so every EM surface
# receives one shared, minimal context file.
ACTIVE_ERD_CONTEXT="$APPROVED/ERD-DELTA.md"
if [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
  ACTIVE_ERD_CONTEXT="$STATE_DIR/active-erd-delta.md"
  python3 scripts/validate-plan.py --active-erd-context \
    "${ACTIVE_DELTA_FILES[@]}" > "$ACTIVE_ERD_CONTEXT" \
    || die "could not assemble complete active milestone instructions"
fi

ACTIVE_INVENTORY_LIST=""
if [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
  ACTIVE_INVENTORY_LIST=$(python3 scripts/validate-plan.py --active-inventory \
    "${ACTIVE_DELTA_FILES[@]}") \
    || die "could not assemble exact active milestone inventory"
else
  ACTIVE_INVENTORY_LIST=$(python3 -c \
    'import json; print("\n".join(json.load(open("scripts/.approved/contracts.json")).get("files", [])))')
fi
ACTIVE_INVENTORY_DISPLAY=$(printf '%s' "$ACTIVE_INVENTORY_LIST" \
  | paste -sd ',' - | sed 's/,/, /g')
ACTIVE_INVENTORY_DISPLAY=${ACTIVE_INVENTORY_DISPLAY:-"(none — zero build tasks)"}
SWBP_CONTRACT_FILES="$ACTIVE_INVENTORY_LIST"
export SWBP_CONTRACT_FILES

# D-120/D-140: slice contract bodies against the same exact active inventory
# the plan gate uses, including every skipped freeze and a legitimate empty
# inventory. DRIFT/SPEC-DEFECT consults still keep the full standing file.
CONTRACTS_DELTA="$STATE_DIR/contracts-delta.json"
if [ -f "$APPROVED/contracts.json" ] \
  && python3 scripts/contracts-delta.py "$APPROVED/contracts.json" \
       > "$CONTRACTS_DELTA" 2>/dev/null; then
  echo "  contracts context: generated active-milestone slice ($(wc -c < "$CONTRACTS_DELTA" | tr -d ' ') bytes, vs $(wc -c < "$APPROVED/contracts.json" | tr -d ' ') in contracts.json)"
else
  CONTRACTS_DELTA="$APPROVED/contracts.json"
  echo "  WARNING: contracts slice generation failed — EM context falls back to the full contracts.json"
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

# em_smoke_probe — D-55 round-trip smoke test, made LAZY (P1e / board finding 6).
# The D-55 property is unchanged: a bug in the model-call path is invisible to
# static review — only a real round-trip catches it (correction log 2026-07-03).
# What changed is WHEN the probe fires: em_call invokes it via a type-guard
# right before the first real EM call of the run, so a run that never needs the
# EM (e.g. a milestone whose plan is mechanically synthesized, B3) spends zero
# model calls on probing, and a red CI or a failing pre-flight costs nothing.
# Idempotent: probes at most once per run (EM_PROBED marker). The budget must
# absorb a COLD model start — LM Studio loads the mapped model on first request,
# and a large model takes minutes, not seconds (testchat M6: 30s budget, 122B
# EM, false pre-flight failure).
em_smoke_probe() {
  [ "${EM_PROBED:-0}" = "1" ] && return 0
  EM_PROBED=1
  local SMOKE_MAX_TIME="${SMOKE_MAX_TIME:-240}"
  echo "  LLM round-trip smoke test (budget ${SMOKE_MAX_TIME}s — cold model start counts)..."
  local _smoke_sys _em_model SMOKE_REPLY
  _smoke_sys=$(mktemp)
  printf 'You are a test probe. Reply with exactly the text the user sends.' > "$_smoke_sys"
  # D-55/P1e: the smoke is seat-specific — resolve the model the EM seat is
  # mapped to (same resolution path as llm-call.sh: env, else models.env) and
  # pass --expect-model so the probe fails closed when the server answers with
  # a DIFFERENT model than the seat's mapping (model-reload drift, D-62 class).
  _em_model="${SWBP_EM_MODEL:-}"
  if [ -z "$_em_model" ] && [ -f "$HOME/.config/sw-dev-blueprint/models.env" ]; then
    # shellcheck disable=SC1090
    . "$HOME/.config/sw-dev-blueprint/models.env"
    _em_model="${SWBP_EM_MODEL:-}"
  fi
  # An unresolvable mapping is llm-call's own hard halt (D-52); no flag then.
  [ -n "$_em_model" ] && echo "  EM seat: expect model '$_em_model'"
  if ! SMOKE_REPLY=$(printf 'SMOKE_OK' | scripts/llm-call.sh em "$_smoke_sys" --max-time "$SMOKE_MAX_TIME" ${_em_model:+--expect-model "$_em_model"} 2>/dev/null); then
    rm -f "$_smoke_sys"
    die "LLM smoke test failed — llm-call.sh could not complete the trivial probe within ${SMOKE_MAX_TIME}s (check SANDBOX_LLM_HOST=$SANDBOX_LLM_HOST, model mapping, model server; a cold large model may need SMOKE_MAX_TIME raised; a seat mismatch means the mapped model is not the one answering)"
  fi
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
}

# em_call <out-file> <schema> <instruction> <context "label:path" ...>
# Calls the EM once, validates the reply is well-formed JSON (the *semantic*
# validation — schema, coverage, DAG — is validate-plan.py's job, unchanged),
# and writes it to <out-file>. The --schema constrains generation when the
# server supports it; either way validate-plan.py is the real gate.
em_call() {
  local out="$1" schema="$2" instr="$3"; shift 3
  # D-55 lazy smoke: fires here (type-guarded so extracted selftest shells and
  # any consumer without em_smoke_probe defined skip it) just before the first
  # real EM call — the failure mode it guards is the model-call path itself.
  type em_smoke_probe &>/dev/null && em_smoke_probe || true
  local phase_start; phase_start=$(git rev-parse HEAD)
  # Plan emission ships em.md PLUS the em-plan.md block (the plan-emission
  # requirements live there since the prompt split); diagnosis calls ship
  # em.md alone. The combined file lands inside .pipeline-state, which the
  # run lifecycle owns. Missing em-plan.md fails the cat loudly (set -e) —
  # the split em.md must never reach the plan call without its block.
  local sys_prompt=".opencode/prompts/em.md"
  if [[ "$schema" == *plan.schema.json ]]; then
    sys_prompt="$LOG_DIR/em-plan.sys"
    cat .opencode/prompts/em.md .opencode/prompts/em-plan.md > "$sys_prompt"
  fi
  write_state phase em
  mark "em-call start -> $out"
  { printf '%s\n' "$instr"; build_context "$@"; } > "$LOG_DIR/em-last.prompt"
  : > "$LOG_DIR/em-last.err"
  local budget_tool="${CONTEXT_BUDGET_TOOL:-scripts/context-budget.py}"
  local budget_warning=""
  if [ -f "$budget_tool" ]; then
    if ! budget_warning=$(python3 "$budget_tool" warn em-context \
      "$sys_prompt" "$schema" "$LOG_DIR/em-last.prompt" 2>&1); then
      die "EM context budget measurement failed: $budget_warning"
    fi
    if [ -n "$budget_warning" ]; then
      printf '%s\n' "$budget_warning" | tee -a "$LOG_DIR/em-last.err" >&2
    fi
  fi
  timeout "$AGENT_TIMEOUT" scripts/llm-call.sh em "$sys_prompt" \
        --schema "$schema" --max-time "$AGENT_TIMEOUT" \
    < "$LOG_DIR/em-last.prompt" \
    > "$LOG_DIR/em-last.raw" 2>> "$LOG_DIR/em-last.err" \
    || { cat "$LOG_DIR/em-last.err" >&2
         # Archive the failed call too (outcome=call_failed): the prompt in
         # em-last.prompt dies with .pipeline-state/ on the next success, and
         # the archive exists precisely because that dir is ephemeral. Not
         # replayable by em-bench (no reply), but the prompt survives.
         type archive_em &>/dev/null && archive_em "$out" call_failed || true
         die "EM call failed (see $LOG_DIR/em-last.err)"; }
  if ! python3 -c "import json; json.load(open('$LOG_DIR/em-last.raw'))" 2>/dev/null; then
    # Archive the failed attempt before any exit path — the invalid replies
    # are the highest-value corpus entries for the brief-variant bench.
    type archive_em &>/dev/null && archive_em "$out" invalid_json || true
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
  type archive_em &>/dev/null && archive_em "$out" || true
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
  [ -n "$existing" ] && out_budget="$SWBP_CODER_EDIT_MAX_OUTPUT"
  # D-116: context minimalism — the coder's brief is self-contained (Rule 8:
  # exact path, signatures, inputs/outputs, acceptance), so the frozen
  # contracts are not pasted per call; the coder gets the brief + the file.
  { printf '%s\n' "$instr"; build_context "$existing"; } \
    | SWBP_MAX_OUTPUT="$out_budget" timeout "$AGENT_TIMEOUT" scripts/llm-call.sh coder .opencode/prompts/coder.md \
        --max-time "$AGENT_TIMEOUT" \
    > "$LOG_DIR/$id-a$attempt.raw" 2> "$LOG_DIR/$id-a$attempt.log" \
    || { CODER_EVIDENCE="coder call failed: $(tail -3 "$LOG_DIR/$id-a$attempt.log" | tr '\n' ' ')"; write_state phase ""; return 1; }
  # Coder-evidence archive (Phase 6, D-115): the flat log name above is a
  # per-run scratchpad — a brief_wrong revision resets the strike counter, so
  # a same-slot retry would silently overwrite the prior brief's only
  # transcript. Archive every attempt verbatim under a version/task/revision/
  # attempt name, best-effort (a full scratch dir must never gate the run).
  # No sequencing, metadata, or pruning: the name is the ordering.
  {
    local coder_revs; coder_revs=$(counter "$id" revisions)
    mkdir -p "$LOG_DIR/archive"
    cp "$LOG_DIR/$id-a$attempt.raw" \
       "$LOG_DIR/archive/$FROZEN_V.$id.$coder_revs.$attempt.raw" || true
    cp "$LOG_DIR/$id-a$attempt.log" \
       "$LOG_DIR/archive/$FROZEN_V.$id.$coder_revs.$attempt.log" || true
  }
  if [ -n "$existing" ]; then
    # D-59 edit-block path: fail-closed applier; target untouched on any error
    if ! CODER_EVIDENCE=$(python3 scripts/apply-edit-blocks.py "$file" "$LOG_DIR/$id-a$attempt.raw" 2>&1); then
      write_state phase ""
      return 1
    fi
  elif ! CODER_EVIDENCE=$(python3 - "$file" "$LOG_DIR/$id-a$attempt.raw" "$LOG_DIR/$id-a$attempt.log" 2>&1 <<'PYEOF'
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
  local test_args=("$@")
  [ "${#test_args[@]}" -gt 0 ] || test_args=(tests/)
  # A sandbox launch/build/timeout failure may produce no report. Remove the
  # prior invocation's report first so that failure cannot replay a stale green
  # verdict; a missing new report is classified NO_REPORT below.
  rm -f .cache/test-report.json
  # Type gate (D-129): mypy was CI-only (post-M29 "a gate that lives only in
  # CI does not exist until a remote does" — testchat shipped 40 spec versions
  # with its type gate dark and went red on first push). Every acceptance
  # type-checks first; a type error fails the verdict with its own
  # classification, never NO_REPORT. --cache-dir=/tmp: the repo mount is
  # read-only and mypy insists on writing its cache. Fail-closed: a missing
  # mypy in the sandbox stack is a hard halt (the next line's `|| true` must
  # not swallow a non-mypy exit — mypy failure rc≠0 short-circuits below).
  #
  # Scoped per-change (audit 2026-08-11 item 2): the whole-tree `src/` check
  # let a type error in a file the task never touched block its verdict. A
  # targeted acceptance/verdict run (node-ids passed, $# > 0) now type-checks
  # only the active delta's changed source files; mypy follows imports, so a
  # reachable error in their dependency closure still surfaces — only genuinely
  # unrelated files stop blocking. The full-suite regression check (no
  # node-ids) keeps the whole-tree `src/` check (fail-closed default). A
  # targeted run whose active delta changed no src/*.py has nothing new to
  # type-check: the gate is skipped (mypy:none) instead of paying whole-app
  # mypy (review 2026-08-13 P2). Unknown delta state (unset/empty
  # ACTIVE_DELTA_FILES) still falls back to the whole tree — absence of
  # state reads as unknown, never as nothing-to-do. The FAILING label names
  # the checked set.
  MYPY_OUT=""
  MYPY_RC=0
  local mypy_targets=()
  if [ "$#" -gt 0 ] && [ "${ACTIVE_DELTA_FILES+set}" = "set" ] \
     && [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
    while IFS= read -r _mf; do
      [ -n "$_mf" ] && mypy_targets+=("$_mf")
    done < <(python3 - "${ACTIVE_DELTA_FILES[@]}" <<'PYSCOPE'
import json, sys
from pathlib import Path
seen = []
for p in sys.argv[1:]:
    try:
        d = json.loads(Path(p).read_text())
    except (OSError, ValueError):
        continue
    for f in d.get("changed_files", []):
        if (f.startswith("src/") and f.endswith(".py")
                and Path(f).exists() and f not in seen):
            seen.append(f)
print("\n".join(seen))
PYSCOPE
)
  fi
  local mypy_label
  if [ "${#mypy_targets[@]}" -gt 0 ]; then
    mypy_label="mypy:$(IFS=,; printf '%s' "${mypy_targets[*]}")"
  elif [ "$#" -eq 0 ] || [ "${ACTIVE_DELTA_FILES+set}" != "set" ] \
     || [ "${#ACTIVE_DELTA_FILES[@]}" -eq 0 ]; then
    mypy_targets=("src/")
    mypy_label="mypy:src"
  else
    mypy_label="mypy:none"
  fi
  local mypy_fingerprint="" mypy_green_dir mypy_green_marker=""
  if [ "$mypy_label" != "mypy:none" ]; then
    # D-142: a green type verdict is reusable only for byte-identical typing
    # inputs.  Hash the exact target set, every Python source mypy may follow,
    # and the config/dependency/sandbox inputs that determine its environment.
    # The cache lives in ephemeral pipeline state and stores successes only:
    # unknown/failing checks always execute and any relevant edit selects a
    # new marker rather than trusting stale green state.
    mypy_fingerprint=$(python3 - "${mypy_targets[@]}" <<'PYMYPYHASH'
import hashlib
import os
import sys
from pathlib import Path

digest = hashlib.sha256()


def add(label: str, data: bytes) -> None:
    digest.update(label.encode())
    digest.update(b"\0")
    digest.update(data)
    digest.update(b"\0")


for target in sys.argv[1:]:
    add("target", target.encode())

inputs = {path for path in Path("src").rglob("*.py") if path.is_file()}
for name in (
    ".mypy.ini", "mypy.ini", "pyproject.toml", "setup.cfg", "tox.ini",
    "requirements.txt", "requirements-dev.txt", "requirements.lock",
    "uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock", "Containerfile",
    "scripts/sandbox-run.sh",
):
    path = Path(name)
    if path.is_file():
        inputs.add(path)
for pattern in ("requirements*.txt", "requirements*.lock"):
    inputs.update(path for path in Path(".").glob(pattern) if path.is_file())

for path in sorted(inputs, key=lambda item: item.as_posix()):
    add(path.as_posix(), path.read_bytes())
for name in ("MYPYPATH", "MYPY_CONFIG_FILE"):
    add(f"env:{name}", os.environ.get(name, "").encode())
print(digest.hexdigest())
PYMYPYHASH
    ) || die "could not fingerprint mypy inputs — refusing stale-cache risk"
    mypy_green_dir="${STATE_DIR:-.pipeline-state}/mypy-green"
    mypy_green_marker="$mypy_green_dir/$mypy_fingerprint"
    if [ -f "$mypy_green_marker" ]; then
      mark "mypy gate cached green ($mypy_label)"
    else
      MYPY_OUT=$(scripts/sandbox-run.sh -- mypy --explicit-package-bases \
        --cache-dir=/tmp/mypy-cache "${mypy_targets[@]}" 2>&1) || MYPY_RC=$?
    fi
  fi
  if [ "$MYPY_RC" -ne 0 ]; then
    mark "mypy gate FAILED (rc=$MYPY_RC)"
    FAILING="$mypy_label"
    FAIL_DETAIL="$(printf '%s' "$MYPY_OUT" | grep -E '^(src|tests)/.*error|^error' | head -c 900 | tr '\n' ' ')" \
      || true
    [ -n "$FAIL_DETAIL" ] || FAIL_DETAIL="mypy exited $MYPY_RC — see run output"
    TESTS_RC=1
    rm -f .cache/test-report.json
    return 0
  fi
  if [ -n "$mypy_green_marker" ] && [ ! -f "$mypy_green_marker" ]; then
    mkdir -p "$mypy_green_dir"
    local mypy_green_tmp="$mypy_green_marker.tmp.$$"
    printf 'green\n' > "$mypy_green_tmp"
    mv "$mypy_green_tmp" "$mypy_green_marker"
  fi
  scripts/sandbox-run.sh --rw .cache -- pytest -p no:cacheprovider --json-report \
    --json-report-file=.cache/test-report.json "${test_args[@]}" >/dev/null 2>&1 || true
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

def xfail_reason(t):
    for record in (t, t.get("setup") or {}, t.get("call") or {},
                   t.get("teardown") or {}):
        if "wasxfail" in record:
            return record.get("wasxfail")
    return None

# The frozen suite is an acceptance oracle: only an ordinary pass is green.
# pytest may encode xfail as a distinct outcome, as "skipped", or as a passed
# call carrying wasxfail metadata (XPASS). Reject every such representation.
nonpassing_tests = sorted(
    (t for t in tests
     if t.get("outcome") != "passed" or xfail_reason(t) is not None),
    key=lambda t: t["nodeid"],
)
failed = [t["nodeid"] for t in nonpassing_tests]
detail = []
for t in nonpassing_tests[:3]:
    reason = crash_text(t)
    if not reason:
        reason = f"outcome={t.get('outcome', 'unknown')}"
        if xfail_reason(t) is not None:
            reason += f", wasxfail={xfail_reason(t)}"
    detail.append(f"{t['nodeid']}: {reason}")
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

# Subtree re-plan (proportionality Fix A): on a re-freeze, the EM re-plans
# ONLY what the delta invalidated. The prior VALIDATED plan is carried
# forward verbatim by the shell; the EM emits tasks only for the affected
# files (plus genuinely new inventory files); the merge is mechanical
# (validate-plan.py --merge-subtree, id discipline rejected-not-repaired);
# and the EXISTING full validate() runs unchanged on the merged artifact —
# the D-64 bijection is a property of the validated artifact, not of who
# authored which part. Plan cost follows delta size instead of inventory
# size (testchat M31: 282s = 68% of the run re-emitting a 19,572-char plan
# for a 3-task delta), and a subtree revision fits the mtplx 32k window
# that a full-plan revision overflows. Greenfield, malformed prior plans,
# inventory removals, missing intermediate deltas, and mappings that cannot
# land on subtree tasks all fall back to full emission — the scope
# computation refuses them, loudly (Rule 4).
plan_subtree_prepare() {
  SUBTREE_MODE=0
  SUBTREE_ATTEMPTS=0
  local prior_v v deltas=()
  [ -f tasks/plan.json ] || return 0
  prior_v=$(python3 -c 'import json;v=json.load(open("tasks/plan.json")).get("erd_version");print(v if isinstance(v,int) else "")' 2>/dev/null) || return 0
  { [ -n "$prior_v" ] && [ "$prior_v" -ge 1 ] && [ "$prior_v" -lt "$FROZEN_V" ]; } || return 0
  for v in $(seq $((prior_v + 1)) "$FROZEN_V"); do
    if [ ! -f "$APPROVED/DELTA-v$v.json" ]; then
      echo "subtree re-plan unavailable: $APPROVED/DELTA-v$v.json missing — full emission"
      return 0
    fi
    deltas+=("$APPROVED/DELTA-v$v.json")
  done
  cp tasks/plan.json "$STATE_DIR/plan-prior.json"
  if ! python3 scripts/validate-plan.py --subtree-scope "$STATE_DIR/plan-prior.json" "${deltas[@]}" \
       > "$STATE_DIR/subtree-scope.json" 2> "$STATE_DIR/subtree-scope.err"; then
    echo "subtree re-plan unavailable ($(tr '\n' ' ' < "$STATE_DIR/subtree-scope.err")) — full emission"
    rm -f "$STATE_DIR/plan-prior.json" "$STATE_DIR/subtree-scope.json" "$STATE_DIR/subtree-scope.err"
    return 0
  fi
  rm -f "$STATE_DIR/subtree-scope.err" tasks/plan-subtree.json
  python3 -c "import json;print(json.dumps(json.load(open('$STATE_DIR/subtree-scope.json'))['carried'], indent=1))" \
    > "$STATE_DIR/carried-summary.json"
  SUBTREE_MODE=1
  echo "subtree re-plan armed: spec v$prior_v -> v$FROZEN_V ($(python3 -c "
import json
s = json.load(open('$STATE_DIR/subtree-scope.json'))
print(f\"{len(s['reemit'])} re-plan + {len(s['new_files'])} new file(s), {len(s['map_nodeids'])} node-id(s) to map, {len(s['carried'])} carried\")"))"
}

ensure_plan() {
  local verrs revs subtree_feedback=""
  plan_subtree_prepare
  # D-130: the full-emission EM call ships the milestone-sliced node-id
  # set, not the raw file-granular changed_tests union. The slice is
  # produced once by validate-plan.py (--milestone-scope) — the exact
  # same producer the subtree path uses for map_ids — so the milestone's
  # scope cannot diverge between the two surfaces (audit 2026-08-08 v87:
  # a 2-line diff staged 58 ids, only 6 pinned; the EM saw 58). Greenfield
  # runs with no active delta range fall back to the whole test-nodeids
  # file; the EM keeps its safe-omit rule either way. Pinned node-ids ride
  # the slice for a pinned freeze, so nothing mapped can be missing from
  # the shipped set — and the D-124 completeness repair (a testid pinned
  # to any file the delta staged rides even if refreeze_delta's
  # changed_tests dropped it) lives inside the producer.
  NODEIDS_SCOPE=""
  if [ "${ACTIVE_DELTA_FILES+set}" = "set" ] && [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
    NODEIDS_SCOPE="$STATE_DIR/nodeids-scope.txt"
    python3 scripts/validate-plan.py --milestone-scope "${ACTIVE_DELTA_FILES[@]}" \
      > "$NODEIDS_SCOPE"
  fi
  while :; do
    # Closure auto-repair (D-64/import/route): a best-effort PRE-PASS that adds
    # the depends_on edges the closure checks would otherwise reject on (only
    # when acyclic). Monotone and bounded — validate() runs next and is the
    # authority, so this can only turn a rejectable plan into a passing one it
    # was one edge away from, never mask a real defect. Prints each edge added.
    [ -f tasks/plan.json ] && python3 scripts/validate-plan.py --repair-closures tasks/plan.json || true
    [ -f tasks/plan.json ] && python3 scripts/validate-plan.py --repair-contracts tasks/plan.json || true
    if [ -f tasks/plan.json ] && verrs=$(python3 scripts/validate-plan.py 2>&1); then
      echo "plan ok (v$(python3 -c 'import json;print(json.load(open("tasks/plan.json"))["version"])'))"
      if [ -n "${LAST_ARCHIVE_ENTRY:-}" ] && [ -d "$LAST_ARCHIVE_ENTRY" ]; then
        printf 'plan_gate=ok\n' >> "$LAST_ARCHIVE_ENTRY/meta.txt"
      fi
      rm -f "$STATE_DIR/plan-prior.json" "$STATE_DIR/subtree-scope.json" \
        "$STATE_DIR/carried-summary.json" tasks/plan-subtree.json
      git add tasks/plan.json && git commit -m "[plan] validated against spec v$FROZEN_V" 2>/dev/null || true
      return 0
    fi
    verrs=$(python3 scripts/validate-plan.py 2>&1 || true)
    if [ -n "$subtree_feedback" ]; then
      # a rejected merge is the actionable feedback; the on-disk plan is
      # still the stale prior, whose errors would only mislead the EM
      verrs="$subtree_feedback"
      subtree_feedback=""
    fi
    # Phase 4 re-check instrument (2026-08-06): identical plan-gate rejection
    # across consecutive revisions — hash the feedback string; equal hash =
    # the EM was handed the same rejection again. Model-free, deterministic;
    # lands in the durable .measurement counter log, which survives the
    # success teardown that wipes .pipeline-state. Phase 4 closed as
    # evidence-ruled-out on archive replay; this is the live post-Phase-5
    # population for the re-check.
    local fb_hash prior_hash
    fb_hash=$(printf '%s' "$verrs" | shasum -a 256 | cut -c1-16)
    prior_hash=$(read_state plan-feedback-hash)
    write_state plan-feedback-hash "$fb_hash"
    if [ -n "$prior_hash" ] && [ "$prior_hash" = "$fb_hash" ]; then
      meas "identical_retry"
    fi
    if [ -n "${LAST_ARCHIVE_ENTRY:-}" ] && [ -d "$LAST_ARCHIVE_ENTRY" ]; then
      printf 'plan_gate=rejected\nplan_gate_errors=%s\n' \
        "$(printf '%s' "$verrs" | tr '\n' ' ')" >> "$LAST_ARCHIVE_ENTRY/meta.txt"
    fi
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
        meas "spec_defect"
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
    # P2-1 (amends D-91): subtree mode is abandoned after the FIRST rejected
    # merge, not the second. revs and SUBTREE_ATTEMPTS increment in lockstep
    # (both written before the merge below), so the old >= 2 threshold could
    # only ever fire after the revision cap: at the default MAX_PLAN_REVISIONS
    # of 2, the budget die above always ran first and the fallback was dead
    # code. With >= 1 the next EM revision is a FULL-plan call — the EM sees
    # the whole inventory, and the rejections it earned are still appended.
    if [ "${SUBTREE_MODE:-0}" = "1" ] && [ "${SUBTREE_ATTEMPTS:-0}" -ge 1 ]; then
      SUBTREE_MODE=0
      echo "subtree re-plan abandoned after $SUBTREE_ATTEMPTS rejected merge(s) — full plan emission (the delta may need mapping beyond the affected subtree)"
    fi
    if [ "${SUBTREE_MODE:-0}" = "1" ] && \
       [ "$(python3 -c "import json;print(int(json.load(open('$STATE_DIR/subtree-scope.json'))['em_needed']))")" = "0" ]; then
      # docs-only / test-retirement delta: nothing to decompose, so nothing
      # for the EM to decide — merge the carried plan mechanically, consume
      # no plan-revision budget, and let the full gate judge the artifact.
      echo "=== delta needs no re-decomposition — carried plan merged mechanically (no EM call) ==="
      SUBTREE_MODE=0   # one shot; if the merged plan fails the gate, full emission takes over
      python3 scripts/validate-plan.py --merge-subtree "$STATE_DIR/plan-prior.json" - "$STATE_DIR/subtree-scope.json" \
        || echo "mechanical merge failed — falling back to full emission"
      continue
    fi
    # --- Cut 2: trivial one-file re-plan — construct mechanically, no EM ---
    # Fires when the delta re-plans exactly one existing file with no contract
    # changes across the delta range (--subtree-scope's trivial_construct).
    # The carried task's brief and contracts still describe what the file
    # does; the coder receives the file's current content anyway (D-59); the
    # only thing that shifts is which node-ids gate acceptance. If the new
    # tests demand behavior the carried brief doesn't cover, mapped tests go
    # red and the escalation ladder (D-70) summons the EM at its consult
    # rung — where its judgment is real, unlike the happy-path emission this
    # replaces. Consumes no plan-revision budget; on merge failure, falls
    # through to the EM subtree branch below (SUBTREE_MODE stays 1).
    if [ "${SUBTREE_MODE:-0}" = "1" ] && \
       [ "$(python3 -c "import json;print(int(json.load(open('$STATE_DIR/subtree-scope.json'))['trivial_construct']))")" = "1" ]; then
      echo "=== delta is one-file re-plan, no contract changes — subtree constructed mechanically (no EM call) ==="
      if python3 scripts/validate-plan.py --construct-one-file "$STATE_DIR/plan-prior.json" "$STATE_DIR/subtree-scope.json" > tasks/plan-subtree.json 2> "$LOG_DIR/construct-one-file.err" \
         && merge_out=$(python3 scripts/validate-plan.py --merge-subtree "$STATE_DIR/plan-prior.json" tasks/plan-subtree.json "$STATE_DIR/subtree-scope.json" 2>&1); then
        echo "$merge_out"
        SUBTREE_MODE=0                  # merged plan will validate on next loop iter
        continue
      else
        echo "mechanical construction rejected — falling through to EM subtree emission"
        [ -s "$LOG_DIR/construct-one-file.err" ] && sed 's/^/  /' "$LOG_DIR/construct-one-file.err"
        [ -n "${merge_out:-}" ] && printf '%s\n' "$merge_out" | sed 's/^/  /'
        rm -f tasks/plan-subtree.json "$LOG_DIR/construct-one-file.err"
        # Fall through with SUBTREE_MODE=1 so the EM branch below fires.
      fi
    fi
    # --- B3: mechanical plan synthesis — the TPM-authored briefs fast path ---
    # When ERD-DELTA carries a verbatim coder brief for every inventory file,
    # a DAG statement, and an ownership pin for every milestone node-id, the
    # plan is fully determined and the EM's full emission is redundant — the
    # plan is transcribed, never judged. Fires once per run (the producer is
    # deterministic, so a retry after its own gate rejection is pointless —
    # but the synthesized draft then feeds the EM's revision loop as
    # plan-being-revised, which gives the EM a concrete draft to fix instead
    # of a blank slate). If the TPM materials are incomplete the command
    # refuses (exit 1, reasons on stderr) and the EM emission continues
    # below — the EM is exception-only in the mechanical lane.
    if [ "${SUBTREE_MODE:-0}" != "1" ] \
       && [ -z "${synthesis_tried:-}" ] \
       && [ "${ACTIVE_DELTA_FILES+set}" = "set" ] && [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
      synthesis_tried=1
      if synth_err=$(python3 scripts/validate-plan.py --synthesize-plan "${ACTIVE_DELTA_FILES[@]}" > tasks/plan.json 2>&1); then
        echo "=== B3: plan synthesized mechanically from the TPM's ERD-DELTA briefs/DAG/pins (no EM call); full gate judges it next ==="
        continue
      else
        echo "mechanical synthesis refused — TPM materials incomplete; EM full emission (reason: $(printf '%s' "$synth_err" | tr '\n' ' '))"
      fi
    fi
    check_budget "plan revision $((revs + 1))"
    write_state plan_revisions $((revs + 1))
    if [ "${SUBTREE_MODE:-0}" = "1" ]; then
      SUBTREE_ATTEMPTS=$((${SUBTREE_ATTEMPTS:-0} + 1))
      local scope_files map_ids
      scope_files=$(python3 -c "
import json
s = json.load(open('$STATE_DIR/subtree-scope.json'))
parts = [f\"{r['file']} (keep id {r['keep_id']})\" for r in s['reemit']]
parts += [f'{f} (new file)' for f in s['new_files']]
print('; '.join(parts))")
      map_ids=$(python3 -c "import json;print(', '.join(json.load(open('$STATE_DIR/subtree-scope.json'))['map_nodeids']) or '(none)')")
      echo "=== EM: re-plan delta subtree (revision $((revs + 1))/$MAX_PLAN_REVISIONS, subtree attempt $SUBTREE_ATTEMPTS) ==="
      em_call tasks/plan-subtree.json scripts/schemas/plan.schema.json \
        "Delta re-plan. The validated plan for the previous spec version is carried forward by the shell; its tasks are immutable and keep their ids (see the carried-plan context: id, file, depends_on only — briefs omitted deliberately). ERD-DELTA is the authoritative current-change slice when present; follow its explicit supersessions over standing ERD prose. The spec has advanced; you re-plan ONLY the delta. $EM_TASK_KEYS $EM_CONTRACT_ID_RULE Valid contract ids (copy verbatim): $(contract_ids) Reply with ONLY a plan JSON matching the schema whose tasks array contains EXACTLY one task per file in this list and NO others: $scope_files. A task for a re-planned file MUST reuse the stated keep id; tasks for new files use fresh T-ids not present in the carried plan. depends_on may reference carried task ids. Map ONLY node-ids from this list, each to exactly one of your tasks: $map_ids. If a listed node-id is not exercised by any file you are planning, OMIT it — the shell routes carried coverage itself; do NOT emit a 'regression' key (the validator rejects it), NO status fields. Placement is gate-owned, never yours: a node-id pinned by contracts.json's test_mapping is auto-placed by the gate at the task owning its pinned file; a node-id from a Playwright-importing test file with no mapping entry is auto-placed at the DAG's final task (D-64) — map every node-id where natural and add NO depends_on edges for this. Every brief self-contained per BLUEPRINT.md Rule 8 (exact path, signatures, inputs/outputs, acceptance; constraints first) — the coder sees only the brief. For a re-planned EXISTING file the brief describes ONLY the change from current behavior (the coder gets the file content and emits anchored edits per D-59 — carried behavior is structurally untouched, so do NOT restate what the file already does; the plan gate rejects an existing-file brief that backticks a symbol the file already defines but the ERD-DELTA never names as changed — D-133); for a NEW file the brief describes the whole file (target under 150 lines). Every contract id must already exist in contracts.json; when no registered id covers a file, use an empty contracts array and never invent one. Do NOT include a smoke_check field. Set erd_version to $FROZEN_V and version to any integer >= 1 — the shell renumbers the merged plan.${verrs:+ The previous attempt failed validation with these errors — fix all of them: $verrs}" \
        "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" "contracts:${CONTRACTS_DELTA:-$APPROVED/contracts.json}" "carried-plan:$STATE_DIR/carried-summary.json" "subtree-being-revised:tasks/plan-subtree.json"
      if ! subtree_feedback=$(python3 scripts/validate-plan.py --merge-subtree "$STATE_DIR/plan-prior.json" tasks/plan-subtree.json "$STATE_DIR/subtree-scope.json" 2>&1); then
        echo "$subtree_feedback"
        continue
      fi
      echo "$subtree_feedback"
      subtree_feedback=""
    else
      echo "=== EM: emit/revise plan (revision $((revs + 1))/$MAX_PLAN_REVISIONS) ==="
      em_call tasks/plan.json scripts/schemas/plan.schema.json \
        "Decompose the frozen ERD into atomic ONE-FILE tasks and reply with ONLY the plan as JSON matching the schema you were given — no prose, no markdown fence. $EM_TASK_KEYS $EM_CONTRACT_ID_RULE Valid contract ids (copy verbatim): $(contract_ids) ERD-DELTA active packet is the authoritative current-change slice; it includes every skipped freeze since the last successful milestone. Requirements: exactly one task per file in this exact active inventory and no others: ${ACTIVE_INVENTORY_DISPLAY:-contracts.json files array}. Every test node-id in test-nodeids that exercises an active-inventory file maps to exactly one task (the task after which it should pass, given its depends_on) — node-ids testing only carried-forward files are handled by the shell: do NOT map them and do NOT emit a 'regression' key (the validator rejects it); when unsure, omit the node-id — the validator names any you must map. Placement is gate-owned, never yours: a node-id pinned by contracts.json's test_mapping is auto-placed by the gate at the task owning its pinned file; a node-id from a Playwright-importing test file with no mapping entry is auto-placed at the DAG's final task (D-64) — map every node-id where natural and add NO depends_on edges for this. Every task's contracts list uses ids that exist in contracts.json; when no registered id covers a file, use an empty contracts array and never invent one. Every brief self-contained per BLUEPRINT.md Rule 8 (exact path, signatures, inputs/outputs, acceptance) — the coder sees only the brief. For an EXISTING file (D-59 edit mode: the coder gets the file content and emits anchored SEARCH/REPLACE blocks; carried behavior is structurally untouched) the brief describes ONLY the change from current behavior — do NOT restate what the file already does (the plan gate rejects an existing-file brief that backticks a symbol the file already defines but the active ERD-delta packet never names as changed — restated carried behavior, D-133); for a NEW file the brief describes the whole file (target under 150 lines). Do NOT include a smoke_check field — smoke checks are TPM-authored and live in contracts.json. Set erd_version to $FROZEN_V. Set the top-level version key to an integer >= 1 (1 for a fresh plan; bump it on every re-emit). NO status fields.${verrs:+ The previous plan failed validation with these errors — fix all of them: $verrs}" \
        "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" "contracts:${CONTRACTS_DELTA:-$APPROVED/contracts.json}" "test-nodeids:${NODEIDS_SCOPE:-$APPROVED/test-nodeids}" "plan-being-revised:tasks/plan.json"
    fi
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
  # D-116: context minimalism. A task consult is about ONE task: ship its
  # plan entry (and the failing test sources appended below), never the full
  # plan + standing ERD + contracts. DRIFT/SPEC-DEFECT consults judge the
  # whole decomposition, so they keep the full plan + contracts + delta.
  local task_entry=""
  if [ "$id" != "DRIFT" ] && [ "$id" != "SPEC-DEFECT" ]; then
    task_entry="$STATE_DIR/consult-task-$id.json"
    if ! python3 -c "
import json, sys
plan = json.load(open('tasks/plan.json'))
entry = next((t for t in plan.get('tasks', []) if t.get('id') == sys.argv[1]), None)
if entry is None:
    sys.exit(1)
json.dump(entry, open(sys.argv[2], 'w'), indent=2)
" "$id" "$task_entry" 2>/dev/null; then
      task_entry=""
    fi
  fi
  local ctx=()
  if [ -n "$task_entry" ]; then
    ctx=("task-entry:$task_entry" "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}")
  else
    ctx=("plan:tasks/plan.json" "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" "contracts:$APPROVED/contracts.json")
  fi
  # D-116: a failing test contributes only the source of the functions the
  # evidence actually names, not the whole file (test_ui.py alone is 1133
  # lines). extract-test-functions.py pulls the named node-ids' functions plus
  # any module-level helpers they call; any failure (no node-ids in the
  # evidence, extraction error, empty output) falls back to the full file, so
  # the excerpt only ever shrinks context, never drops it.
  local f
  for f in $(printf '%s' "$evidence" | grep -oE 'tests/[A-Za-z0-9_/]+\.py' | sort -u || true); do
    local nids=() _nid
    while IFS= read -r _nid; do
      [ -n "$_nid" ] && nids+=("$_nid")
    done < <(printf '%s' "$evidence" \
      | grep -oE "${f}::[A-Za-z0-9_]+(\[[^]]*\])?" | sort -u || true)
    if [ "${#nids[@]}" -gt 0 ]; then
      local excerpt="$STATE_DIR/consult-excerpt-${id}-${f##*/}"
      if python3 scripts/extract-test-functions.py "$f" "${nids[@]}" \
           > "$excerpt" 2>/dev/null && [ -s "$excerpt" ]; then
        ctx+=("failing-test-excerpt:$excerpt")
        continue
      fi
    fi
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
        if [ -n "${LAST_ARCHIVE_ENTRY:-}" ] && [ -d "$LAST_ARCHIVE_ENTRY" ]; then
          printf 'verdict=%s\ntask_id=%s\n' "$DIAG_VERDICT" "$id" >> "$LAST_ARCHIVE_ENTRY/meta.txt"
        fi
        return 0
      fi
      verrs=$(tr '\n' ' ' < "$LOG_DIR/diag-last.err")
      if [ -n "${LAST_ARCHIVE_ENTRY:-}" ] && [ -d "$LAST_ARCHIVE_ENTRY" ]; then
        printf 'validation=schema_invalid\ntask_id=%s\nvalidator_errors=%s\n' \
          "$id" "$verrs" >> "$LAST_ARCHIVE_ENTRY/meta.txt"
      fi
    else
      verrs="the reply was not parseable JSON at all"
      if [ -n "${LAST_ARCHIVE_ENTRY:-}" ] && [ -d "$LAST_ARCHIVE_ENTRY" ]; then
        printf 'task_id=%s\n' "$id" >> "$LAST_ARCHIVE_ENTRY/meta.txt"
      fi
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
      echo "(none — $kind was detected mechanically; no EM consult was"
      echo "involved because the recorded evidence already identifies the"
      echo "frozen-spec defect.)"
    else
      echo "### EM diagnosis (schema-validated)"
      echo '```json'
      cat "$diag"
      echo '```'
    fi
    echo
    # Finding-7: the milestone slice (standing summary + ERD-DELTA, D-118) is
    # shared by every item, so it is emitted ONCE at the batch top in
    # finalize_batch — never re-copied per item, where batching duplicated it N
    # times.
    echo "### Frozen artifacts involved"
    python3 - "$id" <<'PYEOF'
import json, sys
tid = sys.argv[1]
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
PYEOF
    echo
    # Finding-7: failing-test evidence is the EXTRACTED failing function(s) plus
    # the module-level helpers they call (scripts/extract-test-functions.py) —
    # never head -200, which can splice in unrelated tests or omit a failing
    # function that sits below line 200. Node-ids come from the evidence, the
    # same grep pattern run_task_consult uses (D-116). Any failure to extract
    # (no node-id in the evidence, extraction error, empty output) falls back to
    # a bounded 200-line excerpt behind an explicit WARNING line — evidence only
    # ever narrows, it is never silently dropped.
    local ef
    for ef in $(printf '%s' "$evidence" | grep -oE 'tests/[A-Za-z0-9_/]+\.py' | sort -u || true); do
      [ -f "$ef" ] || continue
      local enids=() _enid
      while IFS= read -r _enid; do
        [ -n "$_enid" ] && enids+=("$_enid")
      done < <(printf '%s' "$evidence" \
        | grep -oE "${ef}::[A-Za-z0-9_]+(\[[^]]*\])?" | sort -u || true)
      local xf="$STATE_DIR/esc-excerpt-${id}-${ef##*/}"
      if [ "${#enids[@]}" -gt 0 ] \
         && python3 scripts/extract-test-functions.py "$ef" "${enids[@]}" \
              > "$xf" 2>/dev/null && [ -s "$xf" ]; then
        echo "Failing test function(s) from \`$ef\` — extracted: ${enids[*]}"
        echo '```python'
        cat "$xf"
        echo '```'
      else
        echo "Frozen test source \`$ef\` — WARNING: focused extraction found no"
        echo "named function (no node-id in the evidence, or extraction failed);"
        echo "showing a bounded 200-line excerpt, which may include unrelated"
        echo "tests or omit a failing function below line 200:"
        echo '```python'
        head -200 "$ef"
        echo '```'
      fi
      echo
    done
  } > "$dir/bundle.md"
  echo "escalation packaged: $dir/bundle.md"
}

finalize_batch() {  # writes the single copy-pasteable batch and halts
  local batch="$ESC_DIR/BATCH.md"
  local shared="$STATE_DIR/escalation-shared.md"
  local n
  n=$(find "$ESC_DIR" -name bundle.md | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] || return 0
  {
    echo "## Shared milestone context (applies to every item below — D-118)"
    echo
    echo "### Standing summary"
    echo '```markdown'
    if [ -f "${STANDING_SUMMARY:-$APPROVED/ERD.md}" ]; then
      cat "${STANDING_SUMMARY:-$APPROVED/ERD.md}"
    else
      echo "(standing summary unavailable)"
    fi
    echo '```'
    echo
    echo "### ERD-DELTA.md (spec v$FROZEN_V) — the authoritative current-change slice"
    echo '```markdown'
    if [ -f "${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" ]; then
      cat "${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}"
    else
      echo "(no ERD-DELTA.md — consolidation freeze; the standing ERD is the current reference)"
    fi
    echo '```'
    echo
    echo "---"
  } > "$shared"
  local budget_tool="${CONTEXT_BUDGET_TOOL:-scripts/context-budget.py}"
  if [ -f "$budget_tool" ]; then
    python3 "$budget_tool" warn escalation-shared "$shared" \
      || die "escalation shared-context budget measurement failed"
  fi
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
    echo
    # Finding-7: the milestone slice is shared by every item, so it is emitted
    # ONCE here at the batch top instead of being re-copied inside each bundle
    # (which batching then duplicated N times).
    cat "$shared"
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

# Compute once per validated plan, fail closed, then share the exact result
# between state reset and D-65 edit permission. Plan revisions call both
# helpers again before continuing the DAG (D-113).
# BEGIN D-113 affected helpers (selftest extracts this block)
compute_active_delta_scope() {
  ACTIVE_AFFECTED=""
  DELTA_SCOPED=0
  AFFECTED_IDS=""
  if [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
    ACTIVE_AFFECTED=$(python3 scripts/validate-plan.py --affected \
      "${ACTIVE_DELTA_FILES[@]}") \
      || die "could not compute affected tasks across the active delta range"
    AFFECTED_IDS=" $(printf '%s' "$ACTIVE_AFFECTED" | tr '\n' ' ') "
    DELTA_SCOPED=1
    echo "active delta range touches:${AFFECTED_IDS%% } — every other existing file is no-edit"
  fi
}

reset_active_delta_tasks() {
  if [ "${#ACTIVE_DELTA_FILES[@]}" -gt 0 ]; then
    echo "=== Resetting active delta scope (baseline v$DELTA_BASELINE_V, frozen v$FROZEN_V) ==="
    for id in $ACTIVE_AFFECTED; do
      echo "  reset: $id"
      set_tstat "$id" pending
      rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" "$BRIEF_DIR/$id.spec_version" 2>/dev/null || true
    done
  fi
  # escalated/blocked tasks get a fresh chance under the revised spec/plan
  for f in "$TASK_STATE"/*.status; do
    [ -f "$f" ] || continue
    case "$(cat "$f")" in
      escalated|blocked) printf 'pending\n' > "$f" ;;
    esac
  done
}
# END D-113 affected helpers
compute_active_delta_scope

# D-108: a successful run intentionally removes its runtime checkpoint, but
# the next milestone should not pay to rebuild outputs whose task definitions
# and bytes are unchanged. Restore happens only into an entirely empty task
# state; completion-ledger.py refuses partial/live checkpoints. The explicit
# full-rebuild override bypasses history by definition. This runs BEFORE the
# re-freeze delta reset below, so changed test content still invalidates every
# affected task even when its plan entry and output bytes happen to match.
if [ "${SWBP_REBUILD_FROM_SCRATCH:-0}" = "1" ]; then
  echo "completion ledger: restore bypassed by SWBP_REBUILD_FROM_SCRATCH=1"
else
  python3 "$COMPLETION_LEDGER_TOOL" restore \
    --spec-version "$FROZEN_V" \
    --ledger "$COMPLETION_LEDGER" \
    --task-state "$TASK_STATE" \
    || die "durable completion ledger could not be restored safely"
fi

# --- Re-freeze delta: reset the affected subtree, now that the plan is fresh
# and validated against the new spec (D-31). Tasks whose ENTRIES changed are
# also caught by the fingerprint pass below; this catches the remaining case:
# unchanged entries whose mapped TEST CONTENT changed in the delta.
if [ "$SPEC_ADVANCED" = "1" ]; then
  reset_active_delta_tasks
fi
write_state spec_version "$FROZEN_V"

# --- Delta-scoped edit permission (inverts D-65's default) -------------------
# D-65 kept the coder away from files the spec DECLARED unchanged, via a
# hand-maintained contracts.no_edit_files. Hand-maintained is the flaw: at
# testchat M29 that list held 3 of 12 files, so when .pipeline-state/tasks/
# lost its `done` markers every task read `pending` and the coder was one
# call away from rewriting app.js, chat.py, threads.py, index.html and
# websearch.py — none of which the delta touched. Nothing mechanical would
# have stopped it.
#
# So the default is inverted: a file the current delta does not touch is
# no-edit, rather than fair game. The permitted set is derived from the
# frozen delta (never hand-listed, so it cannot drift), using the same
# --affected computation the re-freeze reset uses — direct hits plus
# transitive dependents, which is precisely the pipeline's own notion of
# "invalidated by this delta".
#
# A file that does NOT yet exist is always editable: that is how greenfield
# and genuinely new files get written, and it keeps an initial build (whose
# delta touches nothing on disk) working unchanged.
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
        rm -f "$TASK_STATE/$id."{strikes,revisions,fp} "$BRIEF_DIR/$id" "$BRIEF_DIR/$id.spec_version" 2>/dev/null || true
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
  # S3 (2026-08-06): a brief revision outlives the spec version that shaped
  # it if a re-freeze lands between consult and re-attempt (M33: a stale v74
  # brief chased the v77 oracle — ~25 min + 4 coder calls for done work).
  # Briefs are stamped with the FROZEN_V at write time; a missing or stale
  # stamp means UNKNOWN, so the override is ignored and the brief is
  # re-derived from the current (plan-gated) spec instead.
  brief=$(cat "$BRIEF_DIR/$id" 2>/dev/null || true)
  if [ -n "$brief" ]; then
    bv=$(cat "$BRIEF_DIR/$id.spec_version" 2>/dev/null || true)
    if [ "$bv" != "$FROZEN_V" ]; then
      echo "brief for $id is stale (spec v${bv:-<unknown>} vs frozen v$FROZEN_V) — re-deriving from the current plan"
      brief=""
    fi
  fi
  [ -n "$brief" ] || brief=$(python3 scripts/validate-plan.py --task "$id" --field brief)
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
  no_edit_reason="frozen contracts.no_edit_files"
  # Inverted default (see the delta-scoped block above): an EXISTING file the
  # current delta does not touch never reaches the coder, whatever the
  # hand-maintained list says. A file that does not exist yet stays editable
  # so it can be created.
  if [ "$no_edit" != "1" ] && [ "$DELTA_SCOPED" = "1" ] && [ -e "$file" ]; then
    case "$AFFECTED_IDS" in
      *" $id "*) ;;
      *) no_edit=1; no_edit_reason="not touched by delta v$FROZEN_V" ;;
    esac
  fi

  # acceptance = projection of the frozen oracle (D-28) + optional smoke.
  # A coder call can now fail before any file exists (bad/missing sentinel
  # block, wrong path) — that's evidence like any other test failure, not a
  # script abort, so it's captured rather than left to `set -e`.
  pass=1
  CODER_EVIDENCE=""
  if [ "$no_edit" = "1" ]; then
    echo "  no-edit file ($no_edit_reason) — coder not invoked; running acceptance only"
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

  # --- Fail-fast (MAX_TASK_STRIKES=1, opt-in since D-70) ---
  # Halt and lay out the failure for human review. Since D-70 the default is
  # MAX_TASK_STRIKES=2, so the EM consult + escalation ladder below is the
  # DEFAULT path; setting MAX_TASK_STRIKES=1 opts back into this bare halt.
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
  revs=$(counter "$id" revisions)
  if [ "$revs" -ge "$MAX_BRIEF_REVISIONS" ]; then
    echo "brief revisions already exhausted for $id -> escalate to TPM without another EM consult"
    package_escalation "caps-exhausted" "$id" "$evidence" "-"
    set_tstat "$id" escalated
    continue
  fi
  consult_em "$id" "failed $strikes attempts on $file. $evidence. Coder log tail: $(tail -5 "$LOG_DIR/$id-a$strikes.log" 2>/dev/null | tr '\n' ' ')"
  case "$DIAG_VERDICT" in
    brief_wrong)
      set_counter "$id" revisions $((revs + 1))
      python3 -c "
import json, sys
d = json.load(open('$DIAG_FILE'))
sys.stdout.write(d['revised_brief'])" > "$BRIEF_DIR/$id"
      write_state "briefs/$id.spec_version" "$FROZEN_V"
      set_counter "$id" strikes 0
      rm -f "$TASK_STATE/$id.lastfail"
      echo "brief revised for $id (revision $((revs + 1))/$MAX_BRIEF_REVISIONS)"
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
          "The decomposition is wrong around task $id: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite the plan fixing it and reply with ONLY the JSON (same requirements as before: one file per task, every inventory-exercising test node-id mapped exactly once, no 'regression' key, erd_version $FROZEN_V, bump plan version, NO status fields). Map ONLY node-ids from this list, each to exactly one of your tasks: $(plan_mapped_ids). If a listed node-id is not exercised by any file you are planning, OMIT it — the shell routes carried coverage itself (D-119). $EM_TASK_KEYS $EM_CONTRACT_ID_RULE Valid contract ids (copy verbatim): $(contract_ids) Keep entries for unrelated tasks byte-identical — completed work is preserved only where entries are unchanged." \
          "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" "contracts:${CONTRACTS_DELTA:-$APPROVED/contracts.json}" "plan-being-revised:tasks/plan.json"
        ensure_plan
        compute_active_delta_scope
        reset_active_delta_tasks
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

# --- all tasks done -> feature verdict is the DELTA's mapped set (D-112) ---
# A feature is judged by what it can touch: the verdict run re-executes the
# union of every node-id the plan mapped (the per-task projections, re-run
# together once as the final signal). Carried-forward tests are NOT part of
# milestone completion (CEO ruling 2026-08-06; see DECISIONS.md D-112); the
# full frozen suite is an on-demand regression check via --full-suite, where
# the D-77 triage and the DRIFT halt below apply unchanged. A failure here in
# mapped scope is real drift by definition — every node was accepted
# per-task, so a red verdict is an inter-task coupling break.
#
# The block between the BEGIN/END markers below is extracted verbatim by
# scripts/selftest/drive-verdict.sh — keep the markers on their own lines.
# BEGIN D-112 verdict scope (drive-verdict.sh extracts this block)
check_budget "feature verdict"
VERDICT_IDS=()
if [ "$FULL_SUITE_CHECK" = "1" ]; then
  echo "=== Full frozen suite (on-demand regression check, D-112) ==="
  run_tests
else
  VERDICT_IDS=()
  while IFS= read -r _vid; do
    [ -n "$_vid" ] && VERDICT_IDS+=("$_vid")
  done < <(python3 -c "
import json, sys
p = json.load(open('tasks/plan.json'))
ids = []
for t in p.get('tasks', []):
    for n in t.get('tests', []):
        if n not in ids:
            ids.append(n)
print('\n'.join(ids))")
  if [ "${#VERDICT_IDS[@]}" -gt 0 ]; then
    echo "=== Verdict: ${#VERDICT_IDS[@]} delta-mapped test(s) (D-112) ==="
    run_tests "${VERDICT_IDS[@]}"
  else
    echo "=== Verdict: no mapped tests — per-task acceptance is the verdict (D-112) ==="
    TESTS_RC=0
  fi
fi
# END D-112 verdict scope

# --- D-77: flake triage before declaring drift -------------------------------
# A failing node that is unmapped in the plan is carried-forward (D-57), but
# that alone does not prove it is flaky: a delta can transitively break carried
# behavior. Every failing carried node is therefore re-run twice in isolation.
# Auto-green requires at least one isolated pass PER node. A node that
# reproduces 0/2, or whose isolation runs cannot execute within budget, keeps
# the original verdict failure red. Any mapped node or collection error also
# keeps the DRIFT path exactly as before. Accepted occurrences persist by spec;
# the recurring threshold closes the bypass and routes a TPM bundle (D-111).
# In mapped verdict scope (D-112) every failing node is mapped, so this block
# is inert: all_carried drops to 0 on the first id and the DRIFT path stands.
#
# The block between the BEGIN/END markers below is extracted verbatim by
# scripts/selftest/drive-drift.sh — keep the markers on their own lines.
# BEGIN D-77 flake triage (drive-drift.sh extracts this block)
FLAKE_NOTE=""
FLAKE_RECORDS=""
RECURRING_FLAKE=0
if [ "$TESTS_RC" -eq 1 ] && [ -n "$FAILING" ] \
  && [[ "$FAILING" != *COLLECTION_ERROR* ]]; then
  all_carried=1
  isolation_supports_flake=1
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
  isolation_records=""
  if [ "$all_carried" -eq 1 ]; then
    for fid in "${_fail_ids[@]}"; do
      # Isolation is corroborating evidence only (never gating), so it is the
      # one phase safe to skip over budget — each re-run is a full sandbox
      # pytest start, and this loop runs after the last check_budget call.
      # A budget die here would fail a run whose suite is flake-green; skip
      # the evidence instead.
      if [ "$SWBP_RUN_BUDGET" -gt 0 ] && [ "$(run_elapsed)" -gt "$SWBP_RUN_BUDGET" ]; then
        iso_evidence="${iso_evidence:+$iso_evidence; }isolation runs skipped — over SWBP_RUN_BUDGET"
        isolation_supports_flake=0
        break
      fi
      iso_pass=0
      for _try in 1 2; do
        run_tests "$fid"
        if [ "$TESTS_RC" -eq 0 ]; then iso_pass=$((iso_pass + 1)); fi
      done
      iso_evidence="${iso_evidence:+$iso_evidence; }$fid: $iso_pass/2 isolated passes"
      isolation_records="${isolation_records}${isolation_records:+$'\n'}${fid}"$'\t'"${iso_pass}"
      [ "$iso_pass" -gt 0 ] || isolation_supports_flake=0
    done
  fi
  FAILING="$saved_failing"; FAIL_DETAIL="$saved_detail"; TESTS_RC=1
  if [ "$all_carried" -eq 1 ] && [ "$isolation_supports_flake" -eq 1 ]; then
    recurring_evidence=""
    while IFS=$'\t' read -r flake_id flake_passes; do
      projected_count=$(python3 "$FLAKE_LEDGER_TOOL" projected-count \
        --ledger "$FLAKE_LEDGER" --nodeid "$flake_id" \
        --spec-version "$FROZEN_V") \
        || die "recurring-flake ledger could not be read safely"
      case "$projected_count" in
        ''|*[!0-9]*) die "recurring-flake ledger returned invalid projected count '$projected_count' for $flake_id" ;;
      esac
      if [ "$projected_count" -ge "$FLAKE_ESCALATION_THRESHOLD" ]; then
        RECURRING_FLAKE=1
        recurring_evidence="${recurring_evidence}${recurring_evidence:+; }$flake_id: occurrence $projected_count (threshold $FLAKE_ESCALATION_THRESHOLD)"
      fi
    done <<< "$isolation_records"
    if [ "$RECURRING_FLAKE" = "1" ]; then
      echo "D-111: recurring flake threshold reached — keeping the suite red"
      echo "  $recurring_evidence"
      FAIL_DETAIL="${FAIL_DETAIL}${FAIL_DETAIL:+; }recurring flake threshold reached: $recurring_evidence; isolation evidence: $iso_evidence"
    else
      echo "WARNING (D-77): every full-suite failure is a carried-forward node,"
      echo "  unmapped in the plan, with an isolated pass — flake, not drift. Isolation evidence: $iso_evidence"
      FLAKE_NOTE="
WARNING (D-77): carried-forward node(s) failed in the full run — flake, not drift ($iso_evidence). Occurrences are tracked; the threshold routes a recurring test defect to the TPM."
      FLAKE_RECORDS="$isolation_records"
      TESTS_RC=0
    fi
  elif [ "$all_carried" -eq 1 ]; then
    echo "D-77: carried-forward failure reproduced or could not be isolated;"
    echo "  keeping the frozen suite red. Isolation evidence: $iso_evidence"
  fi
fi
# END D-77 flake triage

if [ "$TESTS_RC" -eq 0 ]; then
  echo ""
  echo "=========================================="
  if [ "$FULL_SUITE_CHECK" = "1" ]; then
    echo "  ALL FROZEN TESTS PASS — feature done"
  elif [ "${#VERDICT_IDS[@]}" -gt 0 ]; then
    echo "  ALL DELTA-MAPPED TESTS PASS — feature done"
  else
    echo "  PER-TASK ACCEPTANCE PASSED — feature done"
  fi
  echo "  total run time: $(run_elapsed)s (timings were in $LOG_DIR/timings.tsv)"
  echo "=========================================="
  if [ -n "$FLAKE_RECORDS" ]; then
    while IFS=$'\t' read -r flake_id flake_passes; do
      python3 "$FLAKE_LEDGER_TOOL" record \
        --ledger "$FLAKE_LEDGER" \
        --spec-version "$FROZEN_V" \
        --nodeid "$flake_id" \
        --isolation-passes "$flake_passes" \
        || die "full suite passed, but recurring-flake history could not be recorded"
    done <<< "$FLAKE_RECORDS"
  fi
  python3 "$COMPLETION_LEDGER_TOOL" record \
    --spec-version "$FROZEN_V" \
    --ledger "$COMPLETION_LEDGER" \
    --task-state "$TASK_STATE" \
    || die "full suite passed, but durable completion history could not be recorded"
  if [ "$FULL_SUITE_CHECK" = "1" ]; then
    _verdict_note="Full frozen TPM suite green against spec v$FROZEN_V (on-demand regression check, D-112)"
  elif [ "${#VERDICT_IDS[@]}" -gt 0 ]; then
    _verdict_note="Delta-mapped frozen tests green against spec v$FROZEN_V — feature done (verdict scope: mapped tests only, D-112)"
  else
    _verdict_note="Per-task acceptance green against spec v$FROZEN_V — feature done (no mapped tests; verdict scope, D-112)"
  fi
  cat >> tasks/CURRENT.md <<EOF

## Results

  $_verdict_note. Feature built and validated.${FLAKE_NOTE}
EOF
  # D-126 ordering: persist this successful run while timings.tsv still
  # exists, before teardown and before metrics-report reads the durable sink.
  # The EXIT trap observes SUCCESS_RECORDED and does not duplicate the row.
  record_measurement 0 "" ""
  SUCCESS_RECORDED=1
  rm -rf "$STATE_DIR"
  git add tasks/CURRENT.md "$COMPLETION_LEDGER"
  [ ! -f "$FLAKE_LEDGER" ] || git add "$FLAKE_LEDGER"
  # P3-5: the metrics row must bind to THIS milestone's [success] commit —
  # a bare `--milestone HEAD` can bind a STALE ref if the guarded commit
  # above fails (git identity, pre-commit hook, anything else, all muffled
  # by the `|| true`): HEAD would still point at the previous milestone's
  # commit whose subject may already match `[success] spec vN`. Capture the
  # pre-commit SHA and require: HEAD advanced AND the new subject is EXACTLY
  # `[success] spec v$FROZEN_V`; otherwise warn loudly and skip the row.
  pre_success_sha=""
  pre_success_sha=$(git rev-parse HEAD 2>/dev/null || true)
  git diff --cached --quiet \
    || git commit -m "[success] spec v$FROZEN_V" 2>/dev/null || true
  post_success_sha=""
  post_success_sha=$(git rev-parse HEAD 2>/dev/null || true)
  success_subject=""
  success_subject=$(git log -1 --format=%s 2>/dev/null || true)
  if [ -n "$pre_success_sha" ] && [ -n "$post_success_sha" ] \
     && [ "$post_success_sha" != "$pre_success_sha" ] \
     && [ "$success_subject" = "[success] spec v$FROZEN_V" ]; then
    # Metrics row (D-126): computed from DURABLE sources that survive the
    # rm -rf above (..measurement/, .em-archive/, the committed flake ledger).
    # A report — a failure here must never fail the run, but it must be VISIBLE:
    # the int("v99") crash sat hidden for weeks behind `2>/dev/null || true`
    # (correction log 2026-07-16: an `|| true` swallows EVERY failure mode). Keep
    # it non-gating, but surface the tool's error and a warning instead.
    if ! python3 "$METRICS_REPORT_TOOL" --milestone HEAD --feature "v$FROZEN_V"; then
      echo "orchestrate: metrics row NOT recorded for v$FROZEN_V (non-fatal report; see error above)" >&2
    fi
  else
    echo "orchestrate: [success] commit did not land for v$FROZEN_V (HEAD ${pre_success_sha:-none} -> ${post_success_sha:-none}, subject '$success_subject') — metrics row SKIPPED (report-only, never fails a run)" >&2
  fi
  exit 0
fi

# tasks green but the verdict red = SPEC DRIFT: routes EM -> TPM, never coder retries (D-28/D-112)
if [ "$FULL_SUITE_CHECK" = "1" ]; then
  echo "=== SPEC DRIFT: every task passed its projection but the full-suite regression check is red ==="
  drift_evidence="all tasks done and individually green; full-suite regression check failing: ${FAILING:-no verdict (rc=$TESTS_RC)}${FAIL_DETAIL:+ — $FAIL_DETAIL}"
else
  echo "=== SPEC DRIFT: every task passed its projection but the delta-mapped verdict run is red ==="
  drift_evidence="all tasks done and individually green; delta-mapped verdict run failing: ${FAILING:-no verdict (rc=$TESTS_RC)}${FAIL_DETAIL:+ — $FAIL_DETAIL}"
fi

# D-111: a carried node that has repeatedly produced isolated-pass flake
# evidence is now a known frozen-test defect, not an implementation puzzle.
# Route it straight to the TPM bundle; an EM decomposition diagnosis cannot
# repair a flaky frozen oracle and would add a model round-trip without signal.
if [ "$RECURRING_FLAKE" = "1" ]; then
  package_escalation "recurring-flake" "DRIFT" "$drift_evidence" "-"
  finalize_batch
fi

if [ "$MAX_TASK_STRIKES" -le 1 ]; then
  echo ""
  echo "=========================================="
  echo "  HALT: spec drift — verdict run red"
  echo "=========================================="
  echo "  $drift_evidence"
  die "spec drift detected — review failing tests, fix the plan or spec, and re-run"
fi

consult_em "DRIFT" "$drift_evidence"
if [ "$DIAG_VERDICT" = "decomposition_wrong" ] && [ "$(plan_revisions_used)" -lt "$MAX_PLAN_REVISIONS" ]; then
  write_state plan_revisions $(( $(plan_revisions_used) + 1 ))
  em_call tasks/plan.json scripts/schemas/plan.schema.json \
    "Spec drift: $(python3 -c "import json;print(json.load(open('$DIAG_FILE'))['reason'])"). Rewrite the plan to fix the decomposition and reply with ONLY the JSON (same requirements as before; keep unrelated entries byte-identical). Map ONLY node-ids from this list, each to exactly one of your tasks: $(plan_mapped_ids). If a listed node-id is not exercised by any file you are planning, OMIT it — the shell routes carried coverage itself (D-119). $EM_TASK_KEYS $EM_CONTRACT_ID_RULE Valid contract ids (copy verbatim): $(contract_ids)" \
    "standing:${STANDING_SUMMARY:-$APPROVED/ERD.md}" "ERD-delta:${ACTIVE_ERD_CONTEXT:-$APPROVED/ERD-DELTA.md}" "contracts:${CONTRACTS_DELTA:-$APPROVED/contracts.json}" "plan-being-revised:tasks/plan.json"
  ensure_plan
  compute_active_delta_scope
  reset_active_delta_tasks
  echo "plan revised for drift — re-run scripts/orchestrate.sh to resume"
  exit 1
fi
package_escalation "spec-drift" "DRIFT" "$drift_evidence" "$DIAG_FILE"
finalize_batch
