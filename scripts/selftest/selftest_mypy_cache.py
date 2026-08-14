"""D-142 green-only mypy fingerprint-cache pins."""

import json
import os
import subprocess
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent
ORCHESTRATE = SCRIPTS / "orchestrate.sh"

SANDBOX_STUB = """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SANDBOX_ARG_LOG"
case " $* " in
  *" -- mypy "*) exit "${SANDBOX_MYPY_RC:-0}" ;;
esac
cp "$SANDBOX_REPORT_SOURCE" .cache/test-report.json
exit 0
"""

DRIVER = """set -euo pipefail
cd "__WORK__"
STATE_DIR=.pipeline-state
ACTIVE_DELTA_FILES=("delta.json")
mark() { :; }
die() { echo "FAIL: $*" >&2; exit 1; }
eval "$(sed -n '/^run_tests() {/,/^}/p' "__ORCHESTRATE__")"
run_tests "tests/test_a.py::test_a"
__BETWEEN__
run_tests __SECOND_ARGS__
echo "FINAL_TESTS_RC=$TESTS_RC"
echo "FINAL_FAILING=$FAILING"
"""


def _run_twice(
    tmp_path: Path,
    *,
    between: str = ":",
    mypy_rc: int = 0,
    second_args: str = '"tests/test_a.py::test_a"',
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the extracted acceptance funnel twice over one pipeline state."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".cache").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "def value() -> int:\n    return 1\n"
    )
    (tmp_path / "src" / "dependency.py").write_text(
        "def dependency() -> int:\n    return 1\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[tool.mypy]\npython_version = '3.12'\n"
    )
    (tmp_path / "delta.json").write_text(json.dumps({
        "changed_files": ["src/a.py"],
    }))
    report = tmp_path / "pass-report.json"
    report.write_text(json.dumps({
        "summary": {"total": 1, "passed": 1},
        "tests": [{
            "nodeid": "tests/test_a.py::test_a",
            "outcome": "passed",
        }],
        "collectors": [],
    }))
    sandbox = tmp_path / "scripts" / "sandbox-run.sh"
    sandbox.write_text(SANDBOX_STUB)
    sandbox.chmod(0o755)
    arg_log = tmp_path / "sandbox-calls.log"
    driver = (
        DRIVER
        .replace("__WORK__", str(tmp_path))
        .replace("__ORCHESTRATE__", str(ORCHESTRATE))
        .replace("__BETWEEN__", between)
        .replace("__SECOND_ARGS__", second_args)
    )
    result = subprocess.run(
        ["bash", "-c", driver],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SANDBOX_ARG_LOG": str(arg_log),
            "SANDBOX_MYPY_RC": str(mypy_rc),
            "SANDBOX_REPORT_SOURCE": str(report),
        },
    )
    calls = arg_log.read_text().splitlines() if arg_log.exists() else []
    return result, calls


def _mypy_calls(calls: list[str]) -> list[str]:
    return [call for call in calls if " -- mypy " in f" {call} "]


def _pytest_calls(calls: list[str]) -> list[str]:
    return [call for call in calls if " pytest " in f" {call} "]


def test_mypy_green_is_reused_for_identical_typing_state(tmp_path: Path):
    result, calls = _run_twice(tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "FINAL_TESTS_RC=0" in result.stdout
    assert len(_mypy_calls(calls)) == 1, calls
    assert len(_pytest_calls(calls)) == 2, calls
    assert len(list((tmp_path / ".pipeline-state" / "mypy-green").iterdir())) == 1


def test_mypy_green_invalidates_after_python_source_change(tmp_path: Path):
    result, calls = _run_twice(
        tmp_path,
        between="printf '\\n# source changed\\n' >> src/dependency.py",
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(_mypy_calls(calls)) == 2, calls
    assert len(_pytest_calls(calls)) == 2, calls


def test_mypy_green_invalidates_after_typing_config_change(tmp_path: Path):
    result, calls = _run_twice(
        tmp_path,
        between="printf '\\nwarn_unused_ignores = true\\n' >> pyproject.toml",
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(_mypy_calls(calls)) == 2, calls


def test_mypy_green_is_specific_to_target_set(tmp_path: Path):
    result, calls = _run_twice(tmp_path, second_args="")
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(_mypy_calls(calls)) == 2, calls
    assert "src/a.py" in _mypy_calls(calls)[0]
    assert _mypy_calls(calls)[1].endswith("src/")


def test_mypy_failure_is_never_cached(tmp_path: Path):
    result, calls = _run_twice(tmp_path, mypy_rc=1)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "FINAL_TESTS_RC=1" in result.stdout
    assert "FINAL_FAILING=mypy:src/a.py" in result.stdout
    assert len(_mypy_calls(calls)) == 2, calls
    assert _pytest_calls(calls) == []
    assert not (tmp_path / ".pipeline-state" / "mypy-green").exists()
