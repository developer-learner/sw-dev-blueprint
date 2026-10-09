"""D-207: run-time gate catches are recorded, and the coder can report a spec
problem instead of gaming it.

These drive the REAL functions extracted from orchestrate.sh (run_coder,
coder_instr, fail_attempt, record_catch) and the real catch-ledger.py and
gate-tiering.py — never copies.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
ORCHESTRATE = SCRIPTS / "orchestrate.sh"
REPORT = "=== SPEC PROBLEM: the brief calls parse_rows but contracts.json names it parse_lines ==="


def drive_coder(work: Path, reply: str, file: str = "src/app.py",
                existing: str | None = None) -> tuple[subprocess.CompletedProcess, dict]:
    (work / "replies").mkdir(parents=True)
    (work / "replies" / "1").write_text(reply + "\n")
    if existing is not None:
        (work / file).parent.mkdir(parents=True, exist_ok=True)
        (work / file).write_text(existing)
    r = subprocess.run(["bash", str(SCRIPTS / "selftest/drive-coder.sh"),
                        str(work), "T1", file, "0"], capture_output=True, text=True)
    m = re.search(r"RC=(\d+) COMMITS=(\d+) CATCH=(\S+) SPEC=(\d) EVIDENCE=(.*)", r.stdout)
    assert m, (r.stdout, r.stderr)
    return r, {"rc": m[1], "commits": m[2], "catch": m[3], "spec": m[4], "evidence": m[5]}


# --- Item 2: the coder's sanctioned "this spec is wrong" reply ---------------

def test_spec_report_in_create_mode_writes_nothing_and_is_flagged(tmp_path):
    _r, out = drive_coder(tmp_path, REPORT)
    assert out["rc"] == "1" and out["spec"] == "1"
    assert out["catch"] == "coder-spec-report"
    assert out["evidence"].startswith("coder reported a spec problem: the brief calls parse_rows")
    assert not (tmp_path / "src/app.py").exists()
    assert out["commits"] == "1", "a report must not produce a commit"


def test_spec_report_in_edit_mode_leaves_the_file_untouched(tmp_path):
    _r, out = drive_coder(tmp_path, REPORT, existing="x = 1\n")
    assert out["rc"] == "1" and out["spec"] == "1"
    assert (tmp_path / "src/app.py").read_text() == "x = 1\n"


def test_report_mixed_with_a_change_is_refused_not_applied(tmp_path):
    reply = REPORT + "\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE"
    _r, out = drive_coder(tmp_path, reply, existing="x = 1\n")
    assert out["rc"] == "1" and out["spec"] == "0"
    assert out["catch"] == "coder-reply-format"
    assert (tmp_path / "src/app.py").read_text() == "x = 1\n"


def test_report_wording_inside_code_is_not_a_report(tmp_path):
    reply = "=== FILE: src/app.py ===\nNOTE = '=== SPEC PROBLEM: x === is just a string here'\n=== END FILE ==="
    _r, out = drive_coder(tmp_path, reply)
    assert out["rc"] == "0" and out["spec"] == "0", out


def _shell(script: str, cwd: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True,
                          text=True, env={**os.environ, **env})


EXTRACT = r'''
extract() { sed -n "/^$1() {/,/^}/p" "$ORCH"; }
'''


def test_both_coder_modes_offer_the_report(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/old.py").write_text("x = 1\n")
    r = _shell(EXTRACT + 'eval "$(extract coder_instr)"\n'
               'echo "--EDIT--"; coder_instr src/old.py "brief"\n'
               'echo; echo "--CREATE--"; coder_instr src/new.py "brief"\n',
               tmp_path, ORCH=str(ORCHESTRATE))
    edit, create = r.stdout.split("--CREATE--")
    for mode in (edit, create):
        assert "=== SPEC PROBLEM:" in mode
        assert "never counted against you" in mode


FAIL_HARNESS = EXTRACT + r'''
set -euo pipefail
PLANE_DIR="$REPO"; FROZEN_V=7; MAX_TASK_STRIKES="${MAXS:-2}"
TASK_STATE=state; mkdir -p "$TASK_STATE"
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_counter() { printf '%s\n' "$3" > "$TASK_STATE/$1.$2"; }
meas() { printf '%s\n' "$1" >> meas.log; }
eval "$(extract record_catch)"
eval "$(extract fail_attempt)"
CODER_SPEC_REPORT="$SPEC"
fail_attempt T1 "some evidence" "$GATE" "${SIG:-}" "${FILE:-}"
echo "STRIKES=$(counter T1 strikes)"
'''


def test_spec_report_skips_the_retry_and_goes_to_the_em(tmp_path):
    r = _shell(FAIL_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), REPO=str(REPO),
               SPEC="1", GATE="coder-spec-report")
    assert "STRIKES=2" in r.stdout, (r.stdout, r.stderr)
    assert "consulting the EM" in r.stdout


def test_ordinary_failure_keeps_the_normal_retry(tmp_path):
    r = _shell(FAIL_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), REPO=str(REPO),
               SPEC="0", GATE="test-verdict")
    assert "STRIKES=1" in r.stdout, (r.stdout, r.stderr)


# --- Item 1: which gates catch the local model -------------------------------

def test_failed_attempt_records_its_gate_in_the_ledger(tmp_path):
    r = _shell(FAIL_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), REPO=str(REPO),
               SPEC="0", GATE="test-verdict")
    assert r.returncode == 0, r.stderr
    ledger = json.loads((tmp_path / ".catch-ledger.json").read_text())
    assert ledger["gates"]["test-verdict"] == [{"spec_version": 7}]


def test_no_gate_means_no_catch(tmp_path):
    r = _shell(FAIL_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), REPO=str(REPO),
               SPEC="0", GATE="")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / ".catch-ledger.json").exists()


def test_coder_failures_name_the_gate_that_caught_them(tmp_path):
    cases = {
        "apply-edit-blocks": ("<<<<<<< SEARCH\nnot in the file\n=======\nx = 2\n>>>>>>> REPLACE", "x = 1\n"),
        "coder-reply-format": ("here is some prose and no file block", None),
        "check-swallowed-errors": ("=== FILE: src/app.py ===\ntry:\n    x = 1\nexcept Exception:\n    pass\n=== END FILE ===", None),
    }
    for gate, (reply, existing) in cases.items():
        _r, out = drive_coder(tmp_path / gate, reply, existing=existing)
        assert out["rc"] == "1" and out["catch"] == gate, (gate, out)


def test_empty_file_block_is_refused_not_written(tmp_path):
    """A create-mode reply whose block is empty would write a blank source
    file and spend the test run discovering it; the reply-format gate refuses
    it up front (survivor of the 2026-10-08 mutation pass)."""
    _r, out = drive_coder(tmp_path, "=== FILE: src/app.py ===\n   \n=== END FILE ===")
    assert out["rc"] == "1" and out["catch"] == "coder-reply-format", out
    assert "empty" in out["evidence"], out
    assert not (tmp_path / "src/app.py").exists()


SMOKE_HARNESS = EXTRACT + r'''
set -euo pipefail
PLANE_DIR="$PWD"; mkdir -p scripts
printf '#!/bin/sh\nexit %s\n' "$SANDBOX_RC" > scripts/sandbox-run.sh; chmod +x scripts/sandbox-run.sh
eval "$(extract smoke_gate)"
pass=1; evidence=""; task_catch=""
[ "$pass" = "1" ] && smoke_gate "$SMOKE"
echo "PASS=$pass CATCH=${task_catch:--} EVIDENCE=${evidence:--}"
'''


def test_failing_smoke_check_fails_the_task_and_is_recorded(tmp_path):
    r = _shell(SMOKE_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), SANDBOX_RC="1",
               SMOKE="curl -sf localhost/health")
    assert "PASS=0 CATCH=smoke-check EVIDENCE=smoke_check failed: curl" in r.stdout, (r.stdout, r.stderr)


def test_passing_or_absent_smoke_check_leaves_the_task_green(tmp_path):
    for rc, smoke in (("0", "true"), ("1", "")):
        r = _shell(SMOKE_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), SANDBOX_RC=rc, SMOKE=smoke)
        assert "PASS=1 CATCH=-" in r.stdout, (rc, smoke, r.stdout, r.stderr)


def test_every_runtime_catch_label_is_in_the_gate_inventory():
    """A catch recorded under a name the inventory lacks is invisible in the
    tiering report — the whole point of recording it."""
    text = ORCHESTRATE.read_text()
    labels = set(re.findall(r'record_catch ([a-z][a-z-]+)', text))
    labels |= set(re.findall(r'CODER_CATCH="([a-z-]+)"', text))
    labels |= set(re.findall(r'task_catch="([a-z-]+)"', text))
    labels |= set(re.findall(r'\) task_catch="([a-z-]+)"', text))
    labels |= {"mypy", "test-verdict"}
    inventory = {line.split("\t")[0] for line in
                 (SCRIPTS / "gate-inventory.tsv").read_text().splitlines()}
    missing = sorted(labels - inventory)
    assert not missing, f"catch labels missing from gate-inventory.tsv: {missing}"


def test_tiering_report_shows_runtime_catches(tmp_path):
    ledger = tmp_path / "ledger.json"
    for v in (3, 4):
        subprocess.run(["python3", str(SCRIPTS / "catch-ledger.py"), "record",
                        "--ledger", str(ledger), "--gate", "test-verdict",
                        "--spec-version", str(v)], check=True, capture_output=True)
    r = subprocess.run(["python3", str(SCRIPTS / "gate-tiering.py"), "--ledger", str(ledger)],
                       capture_output=True, text=True)
    row = next(line for line in r.stdout.splitlines() if line.startswith("| test-verdict |"))
    assert "| 2 |" in row and row.rstrip().endswith("| T1 |"), row


def test_ledger_merge_is_a_validated_idempotent_union(tmp_path):
    cl = ["python3", str(SCRIPTS / "catch-ledger.py")]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    subprocess.run(cl + ["record", "--ledger", str(a), "--gate", "mypy", "--spec-version", "2"], check=True, capture_output=True)
    subprocess.run(cl + ["record", "--ledger", str(b), "--gate", "mypy", "--spec-version", "2"], check=True, capture_output=True)
    subprocess.run(cl + ["record", "--ledger", str(b), "--gate", "lint-changed", "--spec-version", "3"], check=True, capture_output=True)
    for _ in range(2):
        subprocess.run(cl + ["merge", "--ledger", str(a), "--from", str(b)], check=True, capture_output=True)
    gates = json.loads(a.read_text())["gates"]
    assert gates == {"mypy": [{"spec_version": 2}], "lint-changed": [{"spec_version": 3}]}
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": 1, "gates": {"x": [{"spec_version": 0}]}}')
    r = subprocess.run(cl + ["merge", "--ledger", str(a), "--from", str(bad)], capture_output=True, text=True)
    assert r.returncode == 1
    assert json.loads(a.read_text())["gates"] == gates, "a rejected merge must not change the ledger"


# --- D-210: more attempts follow new evidence, never a repeat ------------------

def _attempt(tmp_path, sig, file_text=None, **env):
    if file_text is not None:
        (tmp_path / "app.py").write_text(file_text)
    return _shell(FAIL_HARNESS, tmp_path, ORCH=str(ORCHESTRATE), REPO=str(REPO),
                  SPEC="0", GATE="test-verdict", SIG=sig, FILE="app.py", **env)


def _strikes(r):
    m = re.search(r"STRIKES=(\d+)", r.stdout)
    assert m, (r.stdout, r.stderr)
    return int(m[1])


def test_same_failure_and_unchanged_file_goes_straight_to_the_em(tmp_path):
    """Matters when the strike budget is above two (with the default two the
    second failure reaches the EM anyway): a repeat of the same request with
    no change must not burn the remaining retries."""
    assert _strikes(_attempt(tmp_path, "tests:a|b", "x = 1\n", MAXS="3")) == 1
    r = _attempt(tmp_path, "tests:a|b", "x = 1\n", MAXS="3")
    assert "no progress on T1" in r.stdout and _strikes(r) == 3
    assert "repair-stuck T1" in (tmp_path / "meas.log").read_text()


def test_same_failure_after_a_real_change_is_an_ordinary_retry(tmp_path):
    _attempt(tmp_path, "tests:a|b", "x = 1\n")
    (tmp_path / "state" / "T1.strikes").write_text("0\n")  # first strike only
    r = _attempt(tmp_path, "tests:a|b", "x = 2\n")
    assert "no progress" not in r.stdout and _strikes(r) == 1


def test_fewer_failing_tests_earns_another_attempt(tmp_path):
    _attempt(tmp_path, "tests:a|b|c", "x = 1\n")              # strike 1
    r = _attempt(tmp_path, "tests:a", "x = 2\n")              # strike 2, but progress
    assert "progress on T1" in r.stdout
    assert _strikes(r) == 1, "progress must hold the strike count below the cap"


def test_progress_extension_is_capped_per_brief(tmp_path):
    _attempt(tmp_path, "tests:a|b|c|d", "v1\n", SWBP_REPAIR_ATTEMPTS="2")
    r = _attempt(tmp_path, "tests:a|b|c", "v2\n", SWBP_REPAIR_ATTEMPTS="2")
    assert "progress" not in r.stdout and _strikes(r) == 2


def test_a_different_failure_is_not_progress(tmp_path):
    _attempt(tmp_path, "tests:a|b", "x = 1\n")
    r = _attempt(tmp_path, "tests:c", "x = 2\n")
    assert "progress" not in r.stdout and _strikes(r) == 2


def _verdict_with(tmp_path, records, tolerated=None):
    """Run test-verdict.py over records [(nodeid, outcome)], optionally with
    a D-215 skip-tolerated list."""
    import json as _json
    import os as _os
    tests = []
    for nodeid, outcome in records:
        phase = "skipped" if outcome == "skipped" else outcome
        tests.append({"nodeid": nodeid, "outcome": outcome,
                      "setup": {"outcome": phase if outcome == "skipped" else "passed"},
                      **({} if outcome == "skipped" else
                         {"call": {"outcome": phase}, "teardown": {"outcome": "passed"}})})
    counts = {o: sum(1 for _, x in records if x == o) for o in ("passed", "failed", "skipped")}
    rc = 1 if counts["failed"] else 0
    report = {"exitcode": rc, "summary": {"total": len(tests), **{k: v for k, v in counts.items() if v}},
              "collectors": [], "tests": tests}
    (tmp_path / ".cache").mkdir(exist_ok=True)
    (tmp_path / ".cache" / "test-report.json").write_text(_json.dumps(report))
    (tmp_path / "scripts/.approved").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts/.approved/test-nodeids").write_text("".join(n + "\n" for n, _ in records))
    env = dict(_os.environ)
    env.pop("SWBP_SKIP_TOLERATED_FILE", None)
    if tolerated is not None:
        (tmp_path / "tolerated").write_text("".join(n + "\n" for n in tolerated))
        env["SWBP_SKIP_TOLERATED_FILE"] = str(tmp_path / "tolerated")
    return subprocess.run(["python3", str(SCRIPTS / "test-verdict.py"), str(rc),
                           *[n for n, _ in records]],
                          cwd=tmp_path, capture_output=True, text=True, env=env)


SPEC = "tests/test_new.py::test_feature"
DEP = "tests/test_tree.py::test_render_tree_win32"


def test_a_dependent_tests_platform_skip_is_not_a_failure(tmp_path):
    """D-215, rich v1: a dependent legacy test skipped as 'Windows specific'
    on Linux blocked [success] — it can show no breakage either way."""
    r = _verdict_with(tmp_path, [(SPEC, "passed"), (DEP, "skipped")], tolerated=[DEP])
    assert r.returncode == 0, r.stdout


def test_a_mapped_tests_skip_still_fails(tmp_path):
    """Without the tolerated list (a spec-mapped test) a skip is no evidence."""
    r = _verdict_with(tmp_path, [(SPEC, "skipped")])
    assert r.returncode == 1 and SPEC in r.stdout
    r = _verdict_with(tmp_path, [(SPEC, "skipped"), (DEP, "skipped")], tolerated=[DEP])
    assert r.returncode == 1 and SPEC in r.stdout and DEP not in r.stdout.splitlines()[0]


def test_a_dependent_tests_failure_still_fails(tmp_path):
    r = _verdict_with(tmp_path, [(SPEC, "passed"), (DEP, "failed")], tolerated=[DEP])
    assert r.returncode == 1 and DEP in r.stdout


def test_skip_tolerance_is_scoped_to_the_dependent_verdict_call():
    src = (SCRIPTS / "orchestrate.sh").read_text()
    exports = [i for i, line in enumerate(src.splitlines())
               if "SWBP_SKIP_TOLERATED_FILE" in line and "export" in line]
    assert len(exports) == 1, "exactly one scoped export"
    lines = src.splitlines()
    window = "\n".join(lines[exports[0] - 3: exports[0] + 4])
    assert 'printf \'%s\\n\' ${DEP_IDS[@]+"${DEP_IDS[@]}"} > "${STATE_DIR:-.pipeline-state}/skip-tolerated"' in window
    assert "run_tests ${VERDICT_IDS" in window and "unset SWBP_SKIP_TOLERATED_FILE" in window


def test_failure_detail_follows_the_build_lane_and_a_nested_rootdir(tmp_path):
    """D-213: rich's code is in rich/, and its tests/pytest.ini makes pytest
    report frames relative to tests/ (`../rich/table.py`)."""
    import json as _json
    report = {
        "exitcode": 1, "summary": {"total": 1, "failed": 1}, "collectors": [],
        "tests": [{"nodeid": "tests/test_a.py::test_a", "outcome": "failed",
                   "setup": {"outcome": "passed"}, "teardown": {"outcome": "passed"},
                   "call": {"outcome": "failed",
                            "crash": {"message": "AssertionError: bad row"},
                            "traceback": [{"path": "test_a.py", "lineno": 4},
                                          {"path": "../rich/table.py", "lineno": 88},
                                          {"path": "../src/other.py", "lineno": 3}]}}],
    }
    (tmp_path / ".gate-paths").write_text("build=rich/\ntest=tests/\n")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "test-report.json").write_text(_json.dumps(report))
    (tmp_path / "scripts/.approved").mkdir(parents=True)
    (tmp_path / "scripts/.approved/test-nodeids").write_text("tests/test_a.py::test_a\n")
    r = subprocess.run(["python3", str(SCRIPTS / "test-verdict.py"), "1", "tests/"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert "[at rich/table.py:88]" in r.stdout, r.stdout
    assert "other.py" not in r.stdout and "test_a.py:4" not in r.stdout


def test_failure_detail_points_at_implementation_lines_not_test_code(tmp_path):
    import json as _json
    report = {
        "exitcode": 1, "summary": {"total": 1, "failed": 1}, "collectors": [],
        "tests": [{"nodeid": "tests/test_a.py::test_a", "outcome": "failed",
                   "setup": {"outcome": "passed"}, "teardown": {"outcome": "passed"},
                   "call": {"outcome": "failed",
                            "crash": {"message": "AssertionError: wrong status"},
                            "traceback": [{"path": "tests/test_a.py", "lineno": 4},
                                          {"path": "src/app.py", "lineno": 6}]}}],
    }
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "test-report.json").write_text(_json.dumps(report))
    (tmp_path / "scripts/.approved").mkdir(parents=True)
    (tmp_path / "scripts/.approved/test-nodeids").write_text("tests/test_a.py::test_a\n")
    r = subprocess.run(["python3", str(SCRIPTS / "test-verdict.py"), "1", "tests/"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 1
    assert "[at src/app.py:6]" in r.stdout, r.stdout
    assert "test_a.py:4" not in r.stdout, "test-file frames must not leak to the coder"

