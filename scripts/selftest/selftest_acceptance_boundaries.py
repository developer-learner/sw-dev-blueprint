"""Regression cases for the host/pytest and coder/filesystem boundaries.

Generated application code is never executed here. The real orchestrator
functions are exercised by the existing drivers with a stubbed model/sandbox.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
NODE = "tests/test_a.py::test_a"


def report_for(*nodes):
    return {
        "exitcode": 0,
        "summary": {"total": len(nodes), "passed": len(nodes)},
        "tests": [{"nodeid": n, "outcome": "passed",
                   **{p: {"outcome": "passed"} for p in ("setup", "call", "teardown")}}
                  for n in nodes],
        "collectors": [],
    }


def accept(work, report, *, runner=0, expected=(NODE,), selected=()):
    approved = work / "scripts/.approved"
    approved.mkdir(parents=True, exist_ok=True)
    (approved / "test-nodeids").write_text("\n".join(expected) + "\n")
    source = work / "injected-report.json"
    source.write_text(json.dumps(report))
    return subprocess.run(
        ["bash", str(SCRIPTS / "selftest/drive-runtime.sh"), "tests", str(work), *selected],
        capture_output=True, text=True,
        env={**os.environ, "SANDBOX_REPORT_SOURCE": str(source),
             "SANDBOX_STUB_RC": str(runner)},
    )


def test_cache_diagnostic_symlink_never_writes_host_target(tmp_path):
    (tmp_path / ".cache").mkdir()
    protected = tmp_path / "protected"
    protected.write_text("untouched\n")
    (tmp_path / ".cache/test-failures.txt").symlink_to("../protected")
    result = accept(tmp_path, report_for(NODE))
    assert protected.read_text() == "untouched\n"
    assert "FINAL_TESTS_RC=0" in result.stdout, (result.stdout, result.stderr)


def test_cache_directory_symlink_is_refused_before_cleanup(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "test-report.json"
    sentinel.write_text("untouched\n")
    (tmp_path / ".cache").symlink_to(outside, target_is_directory=True)
    result = accept(tmp_path, report_for(NODE))
    assert sentinel.read_text() == "untouched\n"
    assert result.returncode != 0 or "FINAL_TESTS_RC=0" not in result.stdout


def _copy_report(work, dest):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "test-verdict.py"), "copy", str(dest)],
        cwd=work, capture_output=True, text=True,
    )


def test_escalation_copy_refuses_symlinked_report(tmp_path):
    """The escalation bundle ships to the external web chat: a report path
    that is a symlink must be refused, not dereferenced (a read of a
    read-only mount would succeed and exfiltrate the target's bytes)."""
    (tmp_path / ".cache").mkdir()
    protected = tmp_path / "protected-secret"
    protected.write_text("top\nsecret\n")
    (tmp_path / ".cache/test-report.json").symlink_to(protected)
    dest = tmp_path / "bundle" / "test-report.json"
    result = _copy_report(tmp_path, dest)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert not dest.exists()
    assert protected.read_text() == "top\nsecret\n"


def test_escalation_copy_copies_regular_report(tmp_path):
    """A genuine (regular, unlinked) report is copied byte-identically so
    the bundle keeps its evidence."""
    (tmp_path / ".cache").mkdir()
    payload = json.dumps(report_for(NODE)).encode()
    (tmp_path / ".cache/test-report.json").write_bytes(payload)
    dest = tmp_path / "bundle" / "test-report.json"
    result = _copy_report(tmp_path, dest)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert dest.read_bytes() == payload


@pytest.mark.parametrize("case", ["runner", "exitcode", "empty", "count", "summary",
                                      "missing", "duplicate", "unexpected", "phase"])
def test_acceptance_rejects_inconsistent_or_incomplete_evidence(tmp_path, case):
    report = report_for(NODE)
    runner = 0
    expected = (NODE,)
    if case == "runner":
        runner = 1
    elif case == "exitcode":
        report["exitcode"] = 1
    elif case == "empty":
        report["tests"] = []
    elif case == "count":
        report["summary"]["total"] = 2
    elif case == "summary":
        report["summary"]["failed"] = 1
    elif case == "missing":
        expected = (NODE, "tests/test_a.py::test_b")
    elif case == "duplicate":
        report = report_for(NODE, NODE)
    elif case == "unexpected":
        report = report_for("tests/test_other.py::test_other")
    elif case == "phase":
        report["tests"][0]["teardown"]["outcome"] = "failed"
    result = accept(tmp_path, report, runner=runner, expected=expected)
    assert "FINAL_TESTS_RC=0" not in result.stdout, result.stdout


def test_targeted_acceptance_requires_only_selected_frozen_ids(tmp_path):
    result = accept(tmp_path, report_for(NODE), expected=(NODE, "tests/test_b.py::test_b"),
                    selected=(NODE,))
    assert "FINAL_TESTS_RC=0" in result.stdout, (result.stdout, result.stderr)


@pytest.mark.parametrize("command", ["prepare-redcheck", "redcheck"])
def test_redcheck_refuses_cache_directory_symlink(tmp_path, command):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "redcheck-report.json"
    sentinel.write_text(json.dumps(report_for(NODE)))
    before = sentinel.read_bytes()
    (tmp_path / ".cache").symlink_to(outside, target_is_directory=True)
    result = subprocess.run([sys.executable, str(SCRIPTS / "test-verdict.py"), command],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 3
    assert sentinel.read_bytes() == before
    assert not (tmp_path / ".pipeline-state/redcheck-already-green").exists()
