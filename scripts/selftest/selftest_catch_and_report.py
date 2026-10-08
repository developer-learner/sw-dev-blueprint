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
PLANE_DIR="$REPO"; FROZEN_V=7; MAX_TASK_STRIKES=2
TASK_STATE=state; mkdir -p "$TASK_STATE"
counter()     { [ -f "$TASK_STATE/$1.$2" ] && cat "$TASK_STATE/$1.$2" || echo 0; }
set_counter() { printf '%s\n' "$3" > "$TASK_STATE/$1.$2"; }
eval "$(extract record_catch)"
eval "$(extract fail_attempt)"
CODER_SPEC_REPORT="$SPEC"
fail_attempt T1 "some evidence" "$GATE"
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
