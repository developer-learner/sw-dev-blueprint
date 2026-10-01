"""Regression cases for the host/pytest and coder/filesystem boundaries.

Generated application code is never executed here. The real orchestrator
functions are exercised by the existing drivers with a stubbed model/sandbox.
"""

import json
import importlib.util
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


def plan_for(work, target):
    approved = work / "scripts/.approved"
    approved.mkdir(parents=True)
    (approved / "VERSION").write_text("1\n")
    (approved / "test-nodeids").write_text(NODE + "\n")
    (approved / "contracts.json").write_text(json.dumps({"files": [target], "entry_points": []}))
    (work / "tasks").mkdir()
    (work / "tasks/plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 1,
        "tasks": [{"id": "T1", "file": target, "brief": "implement value",
                   "depends_on": [], "contracts": [], "tests": [NODE]}],
    }))


@pytest.mark.parametrize("target", ["src/../tests/x.py", "src/./x.py", "src//x.py"])
def test_plan_rejects_noncanonical_inventory_paths(tmp_path, target):
    plan_for(tmp_path, target)
    result = subprocess.run([sys.executable, str(SCRIPTS / "validate-plan.py")],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize("ancestor", [False, True])
def test_plan_rejects_source_symlinks(tmp_path, ancestor):
    target = "src/nested/a.py" if ancestor else "src/a.py"
    (tmp_path / "src").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.py").write_text("old\n")
    (tmp_path / ("src/nested" if ancestor else target)).symlink_to(
        outside if ancestor else outside / "a.py", target_is_directory=ancestor)
    plan_for(tmp_path, target)
    result = subprocess.run([sys.executable, str(SCRIPTS / "validate-plan.py")],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout


def test_applier_refuses_symlink_even_without_plan_gate(tmp_path):
    (tmp_path / "src").mkdir()
    outside = tmp_path / "protected"
    outside.write_text("old\n")
    (tmp_path / "src/a.py").symlink_to(outside)
    reply = tmp_path / "reply"
    reply.write_text("<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n")
    result = subprocess.run([sys.executable, str(SCRIPTS / "apply-edit-blocks.py"),
                             "src/a.py", str(reply)], cwd=tmp_path,
                            capture_output=True, text=True)
    assert outside.read_text() == "old\n"
    assert result.returncode != 0


def test_coder_create_cannot_write_through_parent_symlink(tmp_path):
    (tmp_path / "src").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "src/link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "replies").mkdir()
    (tmp_path / "replies/1").write_text(
        "=== FILE: src/link/new.py ===\nvalue = 1\n=== END FILE ===\n")
    result = subprocess.run(["bash", str(SCRIPTS / "selftest/drive-coder.sh"),
                             str(tmp_path), "T1", "src/link/new.py", "0"],
                            capture_output=True, text=True)
    assert not (outside / "new.py").exists(), (result.stdout, result.stderr)
    assert result.returncode != 0 or "RC=0" not in result.stdout


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


def source_helper():
    spec = importlib.util.spec_from_file_location("source_paths", SCRIPTS / "source_paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_write_rechecks_parent_after_initial_validation(tmp_path, monkeypatch):
    helper = source_helper()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    validate = helper.validate_source_path

    def plant_link(path):
        validate(path)
        (tmp_path / "src/nested").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(helper, "validate_source_path", plant_link)
    with pytest.raises((OSError, ValueError)):
        helper.write_source("src/nested/new.py", "value = 1\n")
    assert list(outside.iterdir()) == []


def test_source_write_does_not_modify_hardlink_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("old\n")
    outside.chmod(0o755)
    os.link(outside, tmp_path / "src/a.py")
    source_helper().write_source("src/a.py", "new\n")
    assert outside.read_text() == "old\n"
    assert (tmp_path / "src/a.py").read_text() == "new\n"
    assert (tmp_path / "src/a.py").stat().st_mode & 0o777 == 0o755


def test_source_write_creates_nested_custom_lane(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gate-paths").write_text("build=./lib/app/\n")
    source_helper().write_source("lib/app/nested/a.py", "value = 1\n")
    assert (tmp_path / "lib/app/nested/a.py").read_text() == "value = 1\n"
    assert not list(tmp_path.rglob(".swbp-write-*"))
