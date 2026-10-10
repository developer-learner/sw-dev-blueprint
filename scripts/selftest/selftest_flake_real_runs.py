"""D-219/D-220: the flake triage against REAL pytest runs, not a scripted stub.

drive-drift.sh pins the triage's branching with a stub run_tests. These tests
run the real pieces end to end on tiny projects: the real run_tests() and the
real D-77 triage block (both extracted from orchestrate.sh at run time), the
real test-verdict.py and flake-ledger.py, and real pytest with
pytest-json-report. Only the podman sandbox is replaced, by a pass-through that
runs the same pytest command on the host.

The re-runs are evidence, not proof, and the cases below pin both sides:

- shared state: test A damages module state, B fails after it but passes
  alone. The isolated passes alone would accept B as a flake; the same-order
  re-run fails B again, so the suite stays red.
- a genuine flake that fails once: accepted, and the run is labelled
  "WITH ACCEPTED FLAKE" — never a plain clean pass.
- a genuine flake that fails again on the re-run: stays red. This is the
  known cost of the fail-closed rule (a false red, never a false green).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
ORCHESTRATE = SCRIPTS / "orchestrate.sh"

pytest.importorskip("pytest_jsonreport")

# The sandbox stand-in: run whatever follows `--` on the host. The pipeline
# only ever runs pytest or mypy through it; mypy is not part of these cases.
SANDBOX = """#!/usr/bin/env bash
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
shift
case "$1" in
  mypy) exit 0 ;;
  pytest) shift; exec python3 -m pytest "$@" ;;
  *) exec "$@" ;;
esac
"""

DRIVER = r"""set -euo pipefail
cd "$1"
ORCH="$2"
PLANE_DIR=$(pwd -P)
STATE_DIR=.pipeline-state
ACTIVE_DELTA_FILES=()
BUILD_DIRS=("src/")
FROZEN_V=7
SWBP_RUN_BUDGET=0
FLAKE_LEDGER=.pipeline-flakes.json
FLAKE_LEDGER_TOOL="$PLANE_DIR/scripts/flake-ledger.py"
FLAKE_ESCALATION_THRESHOLD=3
mark() { :; }
run_elapsed() { echo 0; }
die() { echo "FAIL: $*" >&2; exit 1; }
eval "$(sed -n '/^run_tests() {/,/^}/p' "$ORCH")"
BLOCK=$(sed -n '/^# BEGIN D-77 flake triage/,/^# END D-77 flake triage/p' "$ORCH" | sed '1d;$d')

# The verdict run: the full frozen suite, in collection order.
VERDICT_RUN_ARGS=()
VERDICT_SKIP_TOLERATED=""
run_tests
echo "VERDICT_RC=$TESTS_RC"
echo "VERDICT_FAILING=$FAILING"
eval "$BLOCK"
echo "FINAL_TESTS_RC=$TESTS_RC"
echo "FLAKE_RECORDS=$(printf '%s' "$FLAKE_RECORDS" | cut -f1 | paste -sd, -)"
echo "FLAKE_NOTE=$(printf '%s' "$FLAKE_NOTE" | tr '\n' ' ')"
"""

STATE_TESTS = '''\
STATE = {"ready": True}


def test_a_leaves_state_broken():
    STATE["ready"] = False


def test_b_needs_clean_state():
    assert STATE["ready"]
'''

# Fails on the invocations listed in FLAKY_FAIL_ON (1 = the verdict run,
# 2 and 3 = the two isolated runs, 4 = the same-order re-run).
FLAKY_TESTS = '''\
import os
from pathlib import Path


def test_flaky():
    counter = Path(os.environ["FLAKY_COUNTER"])
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    assert str(n) not in os.environ["FLAKY_FAIL_ON"].split(",")
'''


def _project(tmp_path: Path, test_file: str, body: str, nodeids: list[str]) -> Path:
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "src").mkdir()
    (work / "tests" / test_file).write_text(body)
    scripts = work / "scripts"
    (scripts / ".approved").mkdir(parents=True)
    (scripts / ".approved" / "test-nodeids").write_text("\n".join(nodeids) + "\n")
    for tool in ("test-verdict.py", "flake-ledger.py"):
        (scripts / tool).write_bytes((SCRIPTS / tool).read_bytes())
    sandbox = scripts / "sandbox-run.sh"
    sandbox.write_text(SANDBOX)
    sandbox.chmod(0o755)
    (work / ".cache").mkdir()
    (work / "tasks").mkdir()
    # Nothing is mapped to a task: every failure is a carried node, the only
    # kind the flake triage may accept.
    (work / "tasks" / "plan.json").write_text(json.dumps({"version": 1, "tasks": []}))
    return work


def _drive(work: Path, **env: str) -> dict[str, str]:
    driver = work.parent / "driver.sh"
    driver.write_text(DRIVER)
    r = subprocess.run(["bash", str(driver), str(work), str(ORCHESTRATE)],
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env},
                       timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = {}
    for line in r.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.isupper():
            out[key] = value
    out["_stdout"] = r.stdout
    return out


def test_shared_state_regression_stays_red_despite_isolated_passes(tmp_path):
    b = "tests/test_state.py::test_b_needs_clean_state"
    work = _project(tmp_path, "test_state.py", STATE_TESTS,
                    ["tests/test_state.py::test_a_leaves_state_broken", b])
    out = _drive(work)
    assert out["VERDICT_RC"] == "1"
    assert out["VERDICT_FAILING"] == b
    assert f"{b}: 2/2 isolated passes" in out["_stdout"]   # isolation alone would accept it
    assert f"suite-order re-run red again (repeated: {b})" in out["_stdout"]
    assert out["FINAL_TESTS_RC"] == "1"
    assert out["FLAKE_RECORDS"] == ""
    assert not (work / ".pipeline-flakes.json").exists()


def test_genuine_flake_failing_once_is_accepted_and_labelled(tmp_path):
    node = "tests/test_flaky.py::test_flaky"
    work = _project(tmp_path, "test_flaky.py", FLAKY_TESTS, [node])
    out = _drive(work, FLAKY_COUNTER=str(tmp_path / "count"), FLAKY_FAIL_ON="1")
    assert out["VERDICT_RC"] == "1"
    assert "suite-order re-run green" in out["_stdout"]
    assert out["FINAL_TESTS_RC"] == "0"
    assert out["FLAKE_RECORDS"] == node            # drives the D-220 label
    assert "accepted as a flake" in out["FLAKE_NOTE"]
    assert (tmp_path / "count").read_text() == "4"  # verdict + 2 isolated + re-run


def test_flake_failing_again_on_the_rerun_stays_red(tmp_path):
    """The reviewer's point, pinned: a flake can fail twice. The rule is
    fail-closed, so this is a false red (the milestone halts), not a pass."""
    node = "tests/test_flaky.py::test_flaky"
    work = _project(tmp_path, "test_flaky.py", FLAKY_TESTS, [node])
    out = _drive(work, FLAKY_COUNTER=str(tmp_path / "count"), FLAKY_FAIL_ON="1,4")
    assert f"{node}: 2/2 isolated passes" in out["_stdout"]
    assert f"suite-order re-run red again (repeated: {node})" in out["_stdout"]
    assert out["FINAL_TESTS_RC"] == "1"
    assert out["FLAKE_RECORDS"] == ""


def test_failure_that_never_passes_alone_stays_red_without_a_rerun(tmp_path):
    node = "tests/test_flaky.py::test_flaky"
    work = _project(tmp_path, "test_flaky.py", FLAKY_TESTS, [node])
    out = _drive(work, FLAKY_COUNTER=str(tmp_path / "count"), FLAKY_FAIL_ON="1,2,3")
    assert f"{node}: 0/2 isolated passes" in out["_stdout"]
    assert "suite-order re-run" not in out["_stdout"]
    assert out["FINAL_TESTS_RC"] == "1"
    assert (tmp_path / "count").read_text() == "3"
