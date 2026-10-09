"""D-211 / D-212: human-intervention metrics and existing-suite regression evidence.

D-211: metrics-report.py counts hand commits to the build lane — during a
milestone (`human_edits`) and after the previous one was declared done
(`post_success_fixes`) — from the D-174 `Swbp-Role` trailers.

D-212: legacy-regression.py turns a pytest json-report of the project's
pinned pre-existing suite into a report-only record, and orchestrate.sh's
legacy_regression() (extracted and run for real) wires it into success.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
METRICS = SCRIPTS / "metrics-report.py"
LEGACY = SCRIPTS / "legacy-regression.py"


def git(root: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(root: Path, subject: str, role: str | None, path: str = "src/app.py") -> None:
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(p.read_text() + "x\n" if p.exists() else "x\n")
    git(root, "add", "-A")
    msg = subject + (f"\n\nSwbp-Role: {role}\nSwbp-Run: r1\n" if role else "")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=/dev/null",
        "commit", "-qm", msg)


@pytest.fixture
def history(tmp_path):
    """Two milestones, each with one hand edit mid-run. Between them: one
    hand fix to the build lane, one hand docs commit (not the build lane)."""
    git(tmp_path, "init", "-q", "-b", "main")
    commit(tmp_path, "adopted legacy code", None)               # before any milestone
    commit(tmp_path, "[refreeze v1]", "tpm", "tests/test_a.py")
    commit(tmp_path, "[task T1] attempt 1", "coder")
    commit(tmp_path, "hand tweak during the run", "human")      # human_edits (v1)
    commit(tmp_path, "[success] spec v1", "pipeline", "tasks/CURRENT.md")
    v1 = git(tmp_path, "rev-parse", "HEAD")
    commit(tmp_path, "fix what v1 shipped", None)               # post_success_fixes (v2)
    commit(tmp_path, "notes", None, "docs/notes.md")            # not build lane
    commit(tmp_path, "[refreeze v2]", "tpm", "tests/test_b.py")
    commit(tmp_path, "[task T2] attempt 1", "coder")
    commit(tmp_path, "hand tweak during v2", "human")           # human_edits (v2)
    commit(tmp_path, "[success] spec v2", "pipeline", "tasks/CURRENT.md")
    return tmp_path, v1


def evidence(root: Path, milestone: str = "HEAD") -> str:
    r = subprocess.run([sys.executable, str(METRICS), "--root", str(root),
                        "--milestone", milestone, "--evidence"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_hand_fix_after_success_is_counted_against_the_next_milestone(history):
    root, _ = history
    out = evidence(root)
    assert "human_edits=1  post_success_fixes=1" in out   # the mid-v2 edit is not a fix


def test_hand_edit_during_a_milestone_is_counted_and_first_milestone_has_no_prior(history):
    root, v1 = history
    out = evidence(root, v1)
    assert "human_edits=1  post_success_fixes=n/a" in out


def test_build_lane_comes_from_gate_paths(history):
    root, _ = history
    (root / ".gate-paths").write_text("build=lib/\n")
    assert "human_edits=0  post_success_fixes=0" in evidence(root)
    (root / ".gate-paths").write_text("build=src/ docs/\n")
    assert "post_success_fixes=2" in evidence(root)   # the docs commit now counts


def test_legacy_regressions_column_reads_this_specs_record(history):
    root, _ = history
    (root / ".measurement").mkdir()
    (root / ".measurement" / "legacy-v2.json").write_text(
        json.dumps({"regressions": ["t.py::a", "t.py::b"]}))
    (root / ".measurement" / "legacy-v1.json").write_text(json.dumps({"regressions": ["x"]}))
    assert "legacy_regressions=2" in evidence(root)
    (root / ".measurement" / "legacy-v2.json").unlink()
    assert "legacy_regressions=n/a" in evidence(root)


def test_old_metrics_table_gets_new_columns_without_losing_rows(history):
    root, _ = history
    old_cols = ["milestone", "date", "feature", "gate_hours", "selftest_count",
                "selftest_s", "em_calls", "em_waste", "flakes", "success_runs", "retry_runs"]
    (root / ".measurement").mkdir()
    tsv = root / ".measurement" / "metrics.tsv"
    tsv.write_text("\t".join(old_cols) + "\nold1\t2026-01-01\tv0" + "\t0" * 8 + "\n")
    r = subprocess.run([sys.executable, str(METRICS), "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = tsv.read_text().splitlines()
    assert lines[0].endswith("retry_runs\thuman_edits\tpost_success_fixes\tlegacy_regressions")
    assert lines[1].startswith("old1\t") and lines[1].count("\t") == lines[0].count("\t")
    assert lines[2].split("\t")[11:] == ["1", "1", ""]


# --- D-212: legacy-regression.py -----------------------------------------

def pin_project(root: Path, known: list[str] | None = None) -> None:
    import hashlib
    (root / "tests").mkdir(parents=True, exist_ok=True)
    files = {}
    for name, body in (("tests/test_old.py", "def test_a(): pass\n"),
                       ("tests/conftest.py", ""),
                       ("tests/.pytest_cache/README.md", "cache")):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        files[name] = hashlib.sha256(body.encode()).hexdigest()
    pin = {"files": files}
    if known is not None:
        pin["known_failing"] = known
    (root / "legacy-pin.json").write_text(json.dumps(pin))


def report(root: Path, tests: list[dict], collectors: list[dict] | None = None,
           rc: int = 1, write: bool = True) -> tuple[str, dict]:
    rpt = root / "r.json"
    if write:
        rpt.write_text(json.dumps({"tests": tests, "collectors": collectors or []}))
    out = root / "rec.json"
    r = subprocess.run([sys.executable, str(LEGACY), "--root", str(root), "report",
                        "--report", str(rpt), "--pytest-rc", str(rc), "--spec", "3",
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout, json.loads(out.read_text())


def test_targets_are_the_pinned_test_files_only(tmp_path):
    r = subprocess.run([sys.executable, str(LEGACY), "--root", str(tmp_path), "targets"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""          # no pin: nothing to run
    pin_project(tmp_path)
    r = subprocess.run([sys.executable, str(LEGACY), "--root", str(tmp_path), "targets"],
                       capture_output=True, text=True)
    assert r.stdout.split() == ["tests/test_old.py"]


def test_new_failures_are_regressions_known_failures_are_not(tmp_path):
    pin_project(tmp_path, known=["test_old.py::test_flaky"])
    line, rec = report(tmp_path, [
        {"nodeid": "test_old.py::test_a", "outcome": "passed"},
        {"nodeid": "test_old.py::test_b", "outcome": "failed"},
        {"nodeid": "test_old.py::test_c", "outcome": "error"},
        {"nodeid": "test_old.py::test_flaky", "outcome": "failed"},
        {"nodeid": "test_old.py::test_s", "outcome": "skipped"},
    ], collectors=[{"nodeid": "test_broken.py", "outcome": "failed"}])
    assert rec["regressions"] == ["test_broken.py", "test_old.py::test_b", "test_old.py::test_c"]
    assert rec["known_failing_seen"] == ["test_old.py::test_flaky"]
    assert (rec["passed"], rec["skipped"]) == (1, 1)
    assert "3 REGRESSION(S)" in line


def test_clean_run_says_so(tmp_path):
    pin_project(tmp_path)
    (tmp_path / "tests" / ".pytest_cache" / "README.md").unlink()   # caches come and go
    line, rec = report(tmp_path, [{"nodeid": "t::a", "outcome": "passed"}], rc=0)
    assert rec["regressions"] == [] and "no regressions — 1 passed" in line
    assert rec["changed_files"] == []                    # cache files never count


def test_changed_pinned_file_is_reported(tmp_path):
    pin_project(tmp_path)
    (tmp_path / "tests" / "test_old.py").write_text("def test_a(): assert 0\n")
    line, rec = report(tmp_path, [{"nodeid": "t::a", "outcome": "passed"}], rc=0)
    assert rec["changed_files"] == ["tests/test_old.py"]
    assert "1 pinned test file(s) changed" in line


def test_a_suite_that_could_not_run_is_not_reported_as_clean(tmp_path):
    pin_project(tmp_path)
    line, rec = report(tmp_path, [], rc=4, write=False)
    assert "NOT RUN" in line and rec["run_problem"]
    line, rec = report(tmp_path, [], rc=5)
    assert "NOT RUN" in line and "no tests" in rec["run_problem"]


# --- D-212: orchestrate.sh legacy_regression(), extracted and run ----------

HARNESS = r"""
set -uo pipefail
cd "$1"
PLANE_DIR="$2"; FROZEN_V=3; MEAS_DIR=.measurement
mark() { :; }
meas() { echo "$1" >> meas.log; }
eval "$(sed -n '/^legacy_regression() {/,/^}/p' "$PLANE_DIR/scripts/orchestrate.sh")"
legacy_regression || echo "legacy_regression returned nonzero"
printf 'NOTE=[%s]\n' "$LEGACY_NOTE"
"""


def run_hook(tmp_path: Path, sandbox_body: str) -> str:
    plane = tmp_path / "plane"
    (plane / "scripts").mkdir(parents=True)
    (plane / "scripts" / "orchestrate.sh").write_text((SCRIPTS / "orchestrate.sh").read_text())
    (plane / "scripts" / "legacy-regression.py").write_text(LEGACY.read_text())
    sb = plane / "scripts" / "sandbox-run.sh"
    sb.write_text("#!/usr/bin/env bash\n" + sandbox_body)
    sb.chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir()
    if "NOPIN" not in sandbox_body:
        pin_project(proj)
    r = subprocess.run(["bash", "-c", HARNESS, "h", str(proj), str(plane)],
                       capture_output=True, text=True, timeout=60)
    assert "returned nonzero" not in r.stdout, r.stdout + r.stderr
    return r.stdout


FAILING_SUITE = """printf '%s' '{"tests": [{"nodeid": "test_old.py::test_a", "outcome": "failed"}]}' \
  > .cache/legacy-report.json
exit 1
"""


def test_success_hook_records_a_regression_without_failing(tmp_path):
    out = run_hook(tmp_path, FAILING_SUITE)
    assert "NOTE=[ Existing tests: 1 REGRESSION(S) — test_old.py::test_a" in out
    rec = json.loads((tmp_path / "proj" / ".measurement" / "legacy-v3.json").read_text())
    assert rec["regressions"] == ["test_old.py::test_a"]
    assert "legacy spec=3" in (tmp_path / "proj" / "meas.log").read_text()


def test_success_hook_reports_a_suite_that_could_not_run(tmp_path):
    out = run_hook(tmp_path, "exit 3\n")
    assert "NOTE=[ Existing tests: NOT RUN" in out


def test_success_hook_is_a_no_op_without_a_pin(tmp_path):
    out = run_hook(tmp_path, "# NOPIN\necho ran > sandbox-called\n")
    assert "NOTE=[]" in out
    assert not (tmp_path / "proj" / "sandbox-called").exists()


def test_success_path_calls_the_hook_before_writing_results():
    src = (SCRIPTS / "orchestrate.sh").read_text()
    call = src.index("  legacy_regression || true\n")
    results = src.index("${FLAKE_NOTE}${LEGACY_NOTE:-}")
    assert call < results < src.index("  finalize_success\nfi")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
