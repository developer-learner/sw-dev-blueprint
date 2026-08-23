"""Publication gate (.githooks/pre-push) — A2 / D-168 follow-up.

D-168 shipped a green *release* claim while the full control-plane selftest
suite was red. CI runs that suite only after a push and only once a remote
exists; the pre-push hook makes publication fail-closed instead.

The hook must verify the COMMIT BEING PUSHED, not the working tree — a red SHA
can be pushed while the checkout sits green (`git push origin other:main`).
These tests build a fixture repo with a red commit and a green commit, drive
the hook with a fake, tree-sensitive suite command, and prove the DECISION is
governed by the pushed SHA. Rule 6: the gate's logic is proven here; that it
runs the REAL suite on a real release push is proven by the default command
the hook ships with (test_default_suite_command_is_the_ci_command).
"""

import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "pre-push"
ZERO = "0" * 40

# Green iff the checked-out tree's `verdict` file says "pass". This makes the
# suite result depend on WHICH tree the hook runs it in.
VERDICT_SUITE = 'test "$(cat verdict)" = pass'


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _commit(repo, verdict):
    (repo / "verdict").write_text(verdict)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", verdict)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _fixture(tmp_path):
    """A repo whose HEAD/working tree is GREEN, with an earlier RED commit."""
    _git(tmp_path, "init", "-q")
    red = _commit(tmp_path, "fail")
    green = _commit(tmp_path, "pass")   # HEAD and working tree are green
    return red, green


def _run(repo, stdin, suite_cmd, protected_ref="refs/heads/main"):
    env = dict(os.environ)
    env["SWBP_RELEASE_SUITE_CMD"] = suite_cmd
    env["SWBP_RELEASE_PROTECTED_REF"] = protected_ref
    return subprocess.run(
        ["bash", str(HOOK), "origin", "file:///tmp/remote.git"],
        cwd=repo, input=stdin, env=env, capture_output=True, text=True,
    )


def _line(sha, remote="refs/heads/main"):
    return f"refs/heads/x {sha} {remote} 0\n"


def test_hook_exists_and_is_executable():
    assert HOOK.is_file(), "release-gate pre-push hook is missing"
    assert os.access(HOOK, os.X_OK), "pre-push hook must be executable"


def test_default_suite_command_is_the_ci_command():
    # The gate must run the SAME suite CI runs; if these drift, a green push
    # can pass a weaker local suite than CI enforces.
    assert "pytest scripts/selftest/selftest_*.py -q" in HOOK.read_text()


def test_push_green_commit_allows(tmp_path):
    _red, green = _fixture(tmp_path)
    r = _run(tmp_path, _line(green), suite_cmd=VERDICT_SUITE)
    assert r.returncode == 0, r.stderr


def test_push_red_commit_blocks_even_though_worktree_is_green(tmp_path):
    # THE bypass: working tree/HEAD is green, but the pushed SHA is red.
    red, _green = _fixture(tmp_path)
    r = _run(tmp_path, _line(red), suite_cmd=VERDICT_SUITE)
    assert r.returncode != 0, "the RED pushed commit must block, not the green tree"
    assert "REFUSED" in r.stderr
    assert red[:12] in r.stderr, "the message should name the commit under test"


def test_suite_result_governs_regardless_of_tree(tmp_path):
    _red, green = _fixture(tmp_path)
    assert _run(tmp_path, _line(green), suite_cmd="true").returncode == 0
    assert _run(tmp_path, _line(green), suite_cmd="false").returncode != 0


def test_non_main_push_does_not_run_the_suite(tmp_path):
    _red, green = _fixture(tmp_path)
    sentinel = tmp_path / "suite_ran"
    r = _run(
        tmp_path, _line(green, remote="refs/heads/feature"),
        suite_cmd=f"touch {sentinel}; false",
    )
    assert r.returncode == 0, "a non-release push must pass without gating"
    assert not sentinel.exists(), "the suite must not run for a non-release push"


def test_unrunnable_suite_fails_closed(tmp_path):
    _red, green = _fixture(tmp_path)
    r = _run(tmp_path, _line(green), suite_cmd="swbp-nonexistent-suite-binary-xyz")
    assert r.returncode != 0, "a suite that cannot run must fail closed (block)"


def test_uncheckoutable_sha_fails_closed(tmp_path):
    _fixture(tmp_path)
    r = _run(tmp_path, _line("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"), suite_cmd="true")
    assert r.returncode != 0, "a SHA that cannot be checked out must fail closed"


def test_branch_deletion_is_not_gated(tmp_path):
    _fixture(tmp_path)
    sentinel = tmp_path / "suite_ran"
    r = _run(tmp_path, f"(delete) {ZERO} refs/heads/main 0\n", suite_cmd=f"touch {sentinel}; false")
    assert r.returncode == 0, "a branch deletion publishes nothing to verify"
    assert not sentinel.exists()


def test_mixed_push_gates_on_the_main_ref(tmp_path):
    _red, green = _fixture(tmp_path)
    stdin = _line(green, remote="refs/heads/feature") + _line(green)
    r = _run(tmp_path, stdin, suite_cmd="false")
    assert r.returncode != 0, "any ref advancing main triggers the gate"
    assert "REFUSED" in r.stderr
