"""M2b criterion 4: finalize_success must be RECOVERABLE.

The prior success path deleted the checkpoint and set SUCCESS_RECORDED before a
`... || true`-swallowed [success] commit, so a commit failure (signing under
active provenance, a git-identity or hook error) still exited 0 with the
checkpoint gone. finalize_success now runs persist -> commit -> teardown: a
failed commit surfaces (exit 3, checkpoint kept) while the already-persisted
durable results stand; validation truth (fault_role=none) is unchanged.

These are BEHAVIORAL tests, not source-text checks: they extract the REAL
finalize_success() from orchestrate.sh at run time (the anti-drift pattern of
selftest_b6a), stub swbp_commit to force the clean and failed paths, and assert
the exit code, the checkpoint, and the durable persist directly.
"""

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ORCHESTRATE = REPO / "scripts" / "orchestrate.sh"

HARNESS = r"""#!/usr/bin/env bash
set -uo pipefail
WORK="$1"; REPO="$2"; COMMIT_FAILS="$3"
cd "$WORK"

git init -q -b main
git config user.name "Selftest"
git config user.email "selftest@example.com"
echo seed > README.md
git add README.md
git commit -q -m seed

# The environment finalize_success reads (mirrors orchestrate.sh at the
# success point). record_measurement, swbp_commit and the metrics tool are
# stubbed so the test controls the finalization outcome.
STATE_DIR=".pipeline-state"
FROZEN_V="99"
COMPLETION_LEDGER=".measurement/completion.jsonl"
FLAKE_LEDGER=".measurement/flake.jsonl"   # absent -> not staged
METRICS_REPORT_TOOL="./metrics-stub.sh"
SWBP_PLANE_SHA=""
SUCCESS_RECORDED=0
FAULT_ROLE=""
mkdir -p "$STATE_DIR" .measurement tasks
echo phase > "$STATE_DIR/phase"
echo "results" >> tasks/CURRENT.md
: > "$COMPLETION_LEDGER"

# durable persist marker — written into .measurement, which must survive rm.
record_measurement() { echo "rc=$1 fault=$FAULT_ROLE" >> .measurement/rows.log; }

cat > metrics-stub.sh <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
chmod +x metrics-stub.sh

if [ "$COMMIT_FAILS" = "1" ]; then
  swbp_commit() { echo "swbp_commit stub: forced failure" >&2; return 1; }
else
  swbp_commit() { git commit -q -m "$2"; }   # $1=role $2=subject
fi

extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "could not extract $1() from orchestrate.sh — did its shape change?" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract finalize_success)"

finalize_success
"""


def _drive(tmp_path, commit_fails):
    driver = tmp_path / "harness.sh"
    driver.write_text(HARNESS)
    work = tmp_path / "work"
    work.mkdir()
    r = subprocess.run(
        ["bash", str(driver), str(work), str(REPO),
         "1" if commit_fails else "0"],
        capture_output=True, text=True)
    return r, work


def _log(work):
    return subprocess.run(["git", "-C", str(work), "log", "--oneline"],
                          capture_output=True, text=True).stdout


def test_finalization_failure_exits_nonzero_and_keeps_checkpoint(tmp_path):
    r, work = _drive(tmp_path, commit_fails=True)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "FINALIZATION FAILED" in r.stderr
    # the [success] commit did not land
    assert "success" not in _log(work)
    # checkpoint kept for recovery — NOT torn down on a failed finalization
    assert (work / ".pipeline-state").is_dir()
    # durable results were persisted BEFORE the commit was attempted
    rows = work / ".measurement" / "rows.log"
    assert rows.exists() and "fault=none" in rows.read_text()


def test_finalization_clean_exits_zero_and_tears_down(tmp_path):
    r, work = _drive(tmp_path, commit_fails=False)
    assert r.returncode == 0, r.stdout + r.stderr
    # the [success] commit landed with the exact subject
    subj = subprocess.run(["git", "-C", str(work), "log", "-1", "--format=%s"],
                          capture_output=True, text=True).stdout.strip()
    assert subj == "[success] spec v99"
    # checkpoint torn down on the clean path
    assert not (work / ".pipeline-state").exists()
    assert (work / ".measurement" / "rows.log").exists()
