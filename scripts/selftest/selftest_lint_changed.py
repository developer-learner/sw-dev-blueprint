"""D-74 diff-scoped lint (scripts/lint-changed.py).

The whole-file D-74 gate rejected a correct anchored edit whenever the edited
file carried a pre-existing ("legacy") lint finding on a line the coder never
touched — and under D-59 could not touch. These tests pin the fix: the gate
reports ONLY findings on lines the task changed relative to its baseline, while
still catching anything the coder newly introduces, always flagging syntax
errors, and failing closed on a real ruff error or an uncomputable diff.

Rule 6: this proves the helper's decision logic. That orchestrate.sh feeds it
the pre-task baseline (HEAD at strike 0) is proven by the source wiring, not here.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "lint-changed.py"

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None, reason="D-74 gate requires ruff; not installed here"
)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(repo, path, body):
    (repo / path).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _run(repo, path, baseline):
    return subprocess.run(
        ["python3", str(SCRIPT), path, baseline],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


def test_legacy_finding_grandfathered(tmp_path):
    """A pre-existing unused import survives an unrelated clean edit."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "import os\n\n\ndef a():\n    return 1\n")
    # Append a clean function; the legacy `import os` line is untouched.
    (repo / "m.py").write_text("import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n")
    r = _run(repo, "m.py", base)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == ""


def test_new_finding_on_changed_line_flagged(tmp_path):
    """A violation the edit introduces is reported."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "def a():\n    return 1\n")
    (repo / "m.py").write_text("import sys\n\n\ndef a():\n    return 1\n")  # new unused import
    r = _run(repo, "m.py", base)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "F401" in r.stdout
    assert "sys" in r.stdout


def test_legacy_kept_new_flagged_together(tmp_path):
    """Only the newly-introduced finding is reported; the legacy one is not."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "import os\n\n\ndef a():\n    return 1\n")
    # Keep the legacy `import os`; add a second unused import on a new line.
    (repo / "m.py").write_text("import os\nimport sys\n\n\ndef a():\n    return 1\n")
    r = _run(repo, "m.py", base)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "sys" in r.stdout
    assert "os" not in r.stdout  # legacy grandfathered


def test_new_file_whole_file_scope(tmp_path):
    """A file absent at baseline is entirely in scope (all of it is the coder's).

    Orchestrate commits the coder's file before this gate runs, so a created
    file is tracked here too — git diff then shows it wholly added.
    """
    repo = _repo(tmp_path)
    base = _commit(repo, "other.py", "x = 1\n")  # baseline has no m.py
    _commit(repo, "m.py", "import os\n\n\ndef a():\n    return 1\n")
    r = _run(repo, "m.py", base)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "os" in r.stdout


def test_none_baseline_falls_back_whole_file(tmp_path):
    """An unavailable baseline over-reports (fail-strict), never under-reports."""
    repo = _repo(tmp_path)
    _commit(repo, "m.py", "import os\n\n\ndef a():\n    return 1\n")
    r = _run(repo, "m.py", "NONE")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "os" in r.stdout


def test_syntax_error_always_reported(tmp_path):
    """E999 gates regardless of scope — an unparseable file cannot be graded."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "def a():\n    return 1\n")
    (repo / "m.py").write_text("def a(:\n    return 1\n")  # syntax error
    r = _run(repo, "m.py", base)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "invalid-syntax" in r.stdout  # ruff >= 0.9; older ruff emits E999


def test_clean_change_passes(tmp_path):
    """A clean edit on changed lines yields no findings."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "def a():\n    return 1\n")
    (repo / "m.py").write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    r = _run(repo, "m.py", base)
    assert r.returncode == 0, r.stdout + r.stderr


def test_unreadable_file_fails_closed(tmp_path):
    """A file ruff cannot read (E902) is always flagged, never a scope-filtered pass."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "x = 1\n")
    r = _run(repo, "does-not-exist.py", base)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "E902" in r.stdout


def test_ruff_crash_returns_2(tmp_path, monkeypatch):
    """A genuine ruff crash (rc not in {0,1}) fails closed as rc=2, not a silent pass."""
    repo = _repo(tmp_path)
    base = _commit(repo, "m.py", "x = 1\n")
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "ruff").write_text("#!/bin/sh\necho boom >&2\nexit 2\n")
    (shim / "ruff").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{__import__('os').environ['PATH']}")
    r = _run(repo, "m.py", base)
    assert r.returncode == 2, r.stdout + r.stderr
