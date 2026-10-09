"""D-214: the first freeze of an adopted app, and pytest node-ids.

1. Rolling back a failed FIRST freeze: HEAD has tests/ (the app's own suite)
   but no scripts/.approved/. The rollback restored both lanes from HEAD in
   one `git restore`, whose unmatched scripts/.approved/ pathspec failed the
   whole call — a false "rollback restore failed" warning, and the tests/
   lane was never restored (rich-adoption v1, 2026-10-08). The real
   on_refreeze_exit() is extracted from refreeze.sh and run.
2. Every pipeline pytest call pins --rootdir=. so node-ids are repo-relative
   even when the app keeps a pytest config below the root (rich's
   tests/pytest.ini made them `test_x.py::t`, so no mapped id ever matched).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def git(root: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def adopted(tmp_path):
    """An adopted app before its first freeze: tracked legacy tests, no lane."""
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_legacy.py").write_text("def test_old(): pass\n")
    # Every pipeline app ignores the staging dir (template .gitignore); that
    # is what keeps `git clean` off it on rollback.
    (tmp_path / ".gitignore").write_text("scripts/.approved/incoming/\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "adopt")
    return tmp_path


def apply_and_fail(root: Path, staged: bool = True) -> subprocess.CompletedProcess:
    """Simulate an applied-then-failed first freeze: new staged lane files, a
    modified legacy test, the staging dir present; then run the real
    on_refreeze_exit with rc=1. staged=False is the rich v1 case: the
    smoke red-check died before anything was `git add`ed."""
    approved = root / "scripts" / ".approved"
    (approved / "incoming").mkdir(parents=True)
    (approved / "incoming" / "PRD.md").write_text("staged\n")
    (approved / "VERSION").write_text("1\n")
    (approved / "contracts.json").write_text("{}\n")
    (root / "tests" / "test_new.py").write_text("def test_new(): pass\n")
    (root / "tests" / "test_legacy.py").write_text("def test_old(): assert 0\n")
    if staged:
        git(root, "add", "-f", "scripts/.approved/VERSION", "tests/test_new.py")
    src = (SCRIPTS / "refreeze.sh").read_text()
    fn = re.search(r"^on_refreeze_exit\(\) \{.*?^\}", src, re.S | re.M).group(0)
    script = f"PREVIEW=$(mktemp -d); REFREEZE_APPLIED=1\n{fn}\n(exit 1); on_refreeze_exit\n"
    return subprocess.run(["bash", "-c", script], cwd=root, capture_output=True, text=True)


@pytest.mark.parametrize("staged", [False, True])
def test_failed_first_freeze_rolls_back_cleanly_without_a_false_warning(adopted, staged):
    r = apply_and_fail(adopted, staged)
    assert "WARNING" not in r.stderr, r.stderr
    approved = adopted / "scripts" / ".approved"
    assert not (approved / "VERSION").exists() and not (approved / "contracts.json").exists()
    assert not (adopted / "tests" / "test_new.py").exists()
    assert (adopted / "tests" / "test_legacy.py").read_text() == "def test_old(): pass\n"
    assert (approved / "incoming" / "PRD.md").is_file(), "staging must survive for retry"
    assert git(adopted, "status", "--porcelain", "--untracked-files=no") == ""


def test_rollback_never_unstages_a_lane_head_tracks(adopted):
    """The tracked tests/ lane is restored, not removed from the index."""
    apply_and_fail(adopted)
    assert "tests/test_legacy.py" in git(adopted, "ls-files", "tests/")


def test_every_pipeline_pytest_call_pins_a_repo_relative_rootdir():
    calls = []
    for name in ("refreeze.sh", "orchestrate.sh"):
        for line in (SCRIPTS / name).read_text().splitlines():
            if "sandbox-run.sh" in line and "-- pytest" in line:
                calls.append((name, line.strip()))
    assert len(calls) >= 4, calls
    missing = [c for c in calls if "--rootdir=." not in c[1]]
    assert not missing, missing


def test_rootdir_pin_makes_node_ids_repo_relative_under_a_nested_config(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "tests" / "pytest.ini").write_text("[pytest]\njunit_family=legacy\n")
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(): pass\n")
    def collect(*extra: str) -> str:
        return subprocess.run([sys.executable, "-m", "pytest", "tests/", *extra,
                               "--collect-only", "-q", "-p", "no:cacheprovider"],
                              cwd=tmp_path, capture_output=True, text=True).stdout
    assert "\ntest_x.py::test_a" in "\n" + collect()           # the defect
    assert "tests/test_x.py::test_a" in collect("--rootdir=.")  # the fix


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
