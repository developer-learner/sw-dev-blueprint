"""Publication gate (.githooks/pre-push) — A2 / D-168 follow-up.

D-168 shipped a green *release* claim while the full control-plane selftest
suite was red. CI runs that suite only after a push and only once a remote
exists; the pre-push hook makes publication fail-closed instead.

These tests drive the hook directly with a fake suite command inside a throw-
away git repo, so they never depend on the live suite's state. Rule 6: the
gate's decision logic is proven here; that it runs the REAL suite on a real
release push is proven by the default command the hook ships with (asserted in
test_default_suite_command_is_the_ci_command).
"""

import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"
ZERO = "0" * 40


def _run(tmp_path, stdin, suite_cmd, protected_ref="refs/heads/main"):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    env = dict(os.environ)
    env["SWBP_RELEASE_SUITE_CMD"] = suite_cmd
    env["SWBP_RELEASE_PROTECTED_REF"] = protected_ref
    return subprocess.run(
        ["bash", str(HOOK), "origin", "file:///tmp/remote.git"],
        cwd=tmp_path, input=stdin, env=env,
        capture_output=True, text=True,
    )


def test_hook_exists_and_is_executable():
    assert HOOK.is_file(), "release-gate pre-push hook is missing"
    assert os.access(HOOK, os.X_OK), "pre-push hook must be executable"


def test_default_suite_command_is_the_ci_command():
    # The gate must run the SAME suite CI runs; if these drift, a green push
    # can pass a weaker local suite than CI enforces.
    text = HOOK.read_text()
    assert "pytest scripts/selftest/selftest_*.py -q" in text


def test_push_to_main_with_green_suite_allows(tmp_path):
    r = _run(tmp_path, "refs/heads/main aaa refs/heads/main bbb\n", suite_cmd="true")
    assert r.returncode == 0, r.stderr


def test_push_to_main_with_red_suite_blocks(tmp_path):
    r = _run(tmp_path, "refs/heads/main aaa refs/heads/main bbb\n", suite_cmd="false")
    assert r.returncode != 0, "a red suite must block publication"
    assert "REFUSED" in r.stderr


def test_non_main_push_does_not_run_the_suite(tmp_path):
    sentinel = tmp_path / "suite_ran"
    r = _run(
        tmp_path,
        "refs/heads/feature aaa refs/heads/feature bbb\n",
        suite_cmd=f"touch {sentinel}; false",
    )
    assert r.returncode == 0, "a non-release push must pass without gating"
    assert not sentinel.exists(), "the suite must not run for a non-release push"


def test_unrunnable_suite_fails_closed(tmp_path):
    r = _run(
        tmp_path,
        "refs/heads/main aaa refs/heads/main bbb\n",
        suite_cmd="swbp-nonexistent-suite-binary-xyz",
    )
    assert r.returncode != 0, "a suite that cannot run must fail closed (block)"


def test_branch_deletion_is_not_gated(tmp_path):
    sentinel = tmp_path / "suite_ran"
    r = _run(
        tmp_path,
        f"(delete) {ZERO} refs/heads/main ccc\n",
        suite_cmd=f"touch {sentinel}; false",
    )
    assert r.returncode == 0, "a branch deletion publishes nothing to verify"
    assert not sentinel.exists()


def test_mixed_push_gates_when_any_ref_targets_main(tmp_path):
    # A push updating both a feature ref and main must still gate on main.
    r = _run(
        tmp_path,
        "refs/heads/feature aaa refs/heads/feature bbb\n"
        "refs/heads/main ccc refs/heads/main ddd\n",
        suite_cmd="false",
    )
    assert r.returncode != 0, "any ref advancing main triggers the gate"
    assert "REFUSED" in r.stderr
