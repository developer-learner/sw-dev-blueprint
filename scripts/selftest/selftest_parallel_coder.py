"""Parallel coder calls (2026-09-23) — prefetch_launch / prefetch_take.

When several plan tasks are ready at once, the orchestrator starts their
coder calls together so a batching server (Splash, LM Studio --parallel)
serves them concurrently. Only the model CALL overlaps: replies are applied,
gated, tested and committed one task at a time, and a prefetched reply is
used only when the prompt run_coder builds at consume time is byte-identical
to the one that produced it.

These tests drive the REAL functions (extracted from orchestrate.sh at run
time, never copied) against a fake coder that records how many calls were in
flight at once. They prove: calls truly overlap; a reused reply means no
second call; any prompt change discards the prefetch and calls fresh;
SWBP_PARALLEL_CODERS=1 (the default) never prefetches; no-edit files and
retried tasks are never prefetched.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

HARNESS = r'''
set -euo pipefail
REPO="$1"; PAR="$2"; SCENARIO="$3"
mkdir -p scripts/.approved .opencode/prompts calls running
cp "$REPO/scripts/apply-edit-blocks.py" "$REPO/scripts/check-swallowed-errors.py" scripts/
: > .opencode/prompts/coder.md

# Fake coder: 1 s per call; records peak concurrency and the target file.
cat > scripts/llm-call.sh <<'STUB'
#!/usr/bin/env bash
prompt=$(cat)
target=$(printf '%s\n' "$prompt" | sed -n 's/^Write EXACTLY one file: \([^ ]*\) .*/\1/p' | head -1)
touch "running/$$"
ls running | wc -l | tr -d ' ' >> calls/concurrency
printf '%s\n' "$target" >> calls/targets
sleep 1
rm -f "running/$$"
printf '=== FILE: %s ===\nVALUE = 1\n=== END FILE ===\n' "$target"
STUB
chmod +x scripts/llm-call.sh
cat > scripts/phase-gate.sh <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x scripts/phase-gate.sh

# Plan: T1, T2, T3 independent; T3's file is declared no-edit.
cat > plan.json <<'JSON'
{"tasks": [
  {"id": "T1", "file": "a.py", "depends_on": [], "brief": "make a"},
  {"id": "T2", "file": "b.py", "depends_on": [], "brief": "make b"},
  {"id": "T3", "file": "c.py", "depends_on": [], "brief": "make c"}
]}
JSON
echo '{"no_edit_files": ["c.py"]}' > scripts/.approved/contracts.json
cat > scripts/validate-plan.py <<'PY'
import json, sys
a = sys.argv[1:]
t = {x["id"]: x for x in json.load(open("plan.json"))["tasks"]}[a[a.index("--task") + 1]]
v = t[a[a.index("--field") + 1]]
print("\n".join(v) if isinstance(v, list) else v)
PY

git init -q .
git -c user.email=t@t -c user.name=t add -A
git -c user.email=t@t -c user.name=t commit -qm fixture

PLANE_DIR=$(pwd -P); STATE_DIR=".pipeline-state"; TASK_STATE="$STATE_DIR/tasks"
LOG_DIR="$STATE_DIR/logs"; BRIEF_DIR="$STATE_DIR/briefs"; PREFETCH_DIR="$STATE_DIR/prefetch"
APPROVED="scripts/.approved"; AGENT_TIMEOUT=60; FROZEN_V="7"; CODER_ARCHIVE_DIR=".coder-archive"
SWBP_CODER_EDIT_MAX_OUTPUT=4096; SWBP_PARALLEL_CODERS="$PAR"; DELTA_SCOPED=0; AFFECTED_IDS=""
TOPO="T1 T2 T3"
mkdir -p "$TASK_STATE" "$LOG_DIR" "$BRIEF_DIR"
die() { echo "FAIL: $*" >&2; exit 1; }
read_state()  { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }
write_state() { printf '%s\n' "$2" > "$STATE_DIR/$1"; }
tstat()     { [ -f "$TASK_STATE/$1.status" ] && cat "$TASK_STATE/$1.status" || echo pending; }
counter()   { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_tstat() { printf '%s\n' "$2" > "$TASK_STATE/$1.status"; }
mark() { printf '%s\n' "$1" >> marks; }
extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' || { echo "cannot extract $1" >&2; exit 65; }
  printf '%s\n' "$body"
}
for f in build_context coder_instr task_attempt_brief task_no_edit prefetch_launch prefetch_take prefetch_reap run_coder; do
  eval "$(extract "$f")"
done

take() {  # the DAG loop's sequence for one task: brief, launch others, code
  local id="$1" file="$2"
  local brief; brief=$(task_attempt_brief "$id" "$file")
  prefetch_launch "$id"
  run_coder "$id" "$file" "$brief" 1 || echo "CODER_FAIL $id: $CODER_EVIDENCE"
  set_tstat "$id" done   # as the DAG loop does after acceptance
}

case "$SCENARIO" in
  overlap)
    take T1 a.py
    take T2 b.py ;;
  mismatch)
    brief=$(task_attempt_brief T1 a.py); prefetch_launch T1
    # T2's brief is revised after its prefetch started: the prompt differs.
    printf 'make b differently\n' > "$BRIEF_DIR/T2"; printf '7\n' > "$BRIEF_DIR/T2.spec_version"
    run_coder T1 a.py "$brief" 1; set_tstat T1 done
    take T2 b.py ;;
  retry)
    printf '1\n' > "$TASK_STATE/T2.strikes"
    take T1 a.py ;;
esac
prefetch_reap
echo "CALLS=$(wc -l < calls/targets | tr -d ' ')"
echo "PEAK=$(sort -n calls/concurrency | tail -1)"
echo "TARGETS=$(tr '\n' ',' < calls/targets)"
echo "REUSED=$(grep -c 'prefetched reply reused' marks 2>/dev/null || echo 0)"
echo "FILES=$(ls a.py b.py c.py 2>/dev/null | tr '\n' ',')"
'''


def _run(tmp_path: Path, par: int, scenario: str) -> dict:
    work = tmp_path / f"w-{par}-{scenario}"
    work.mkdir()
    script = work / "harness.sh"
    script.write_text(HARNESS)
    r = subprocess.run(["bash", str(script), str(REPO), str(par), scenario],
                       cwd=work, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.stdout, r.stderr)
    out = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    return out


def test_ready_tasks_are_coded_concurrently_and_the_reply_is_reused(tmp_path):
    out = _run(tmp_path, 4, "overlap")
    # T1 (sequential) and T2 (prefetched) ran at the same time; T2 was not
    # called a second time; T3 (no-edit) was never sent to the coder.
    assert out["PEAK"] == "2"
    assert out["CALLS"] == "2"
    assert sorted(out["TARGETS"].strip(",").split(",")) == ["a.py", "b.py"]
    assert out["REUSED"] == "1"
    assert out["FILES"] == "a.py,b.py,"


def test_a_changed_prompt_discards_the_prefetch_and_calls_fresh(tmp_path):
    out = _run(tmp_path, 4, "mismatch")
    # Prefetch for b.py was made with the OLD brief; run_coder built a
    # different prompt, so the reply was discarded and b.py called again.
    assert out["CALLS"] == "3"
    assert out["REUSED"] == "0"
    assert out["FILES"] == "a.py,b.py,"


def test_default_setting_never_prefetches(tmp_path):
    out = _run(tmp_path, 1, "overlap")
    assert out["PEAK"] == "1"
    assert out["CALLS"] == "2"
    assert out["REUSED"] == "0"


def test_retried_tasks_are_not_prefetched(tmp_path):
    out = _run(tmp_path, 4, "retry")
    # T2 already has a strike: its next prompt carries the failure feedback,
    # so it is left to the sequential path.
    assert out["TARGETS"] == "a.py,"
    assert out["PEAK"] == "1"


def test_orchestrate_wires_prefetch_into_the_dag_loop_and_exit():
    src = (REPO / "scripts" / "orchestrate.sh").read_text()
    loop = src[src.index('echo "=== Phase: task DAG ==="'):]
    assert 'attempt_brief=$(task_attempt_brief "$id" "$file")\n  prefetch_launch "$id"' in loop
    assert 'SWBP_PARALLEL_CODERS="${SWBP_PARALLEL_CODERS:-1}"' in src
    exit_fn = src[src.index("record_exit() {"):]
    assert "prefetch_reap" in exit_fn[:400]
