"""D-205: copy-in / copy-out between host projects and the dev VM.

These drive the real scripts/vm-sync and scripts/vm_land.py. The "VM" is a
local directory (SWBP_VM_FAKE_HOME), so everything the VM side does — clone,
commit, bundle — is real git, and the host side is exactly what runs against
the Lima VM. The live round-trip through limactl is checked separately.

Acceptance (from the review that commissioned this):
  - each run gets an isolated snapshot;
  - only the run's commits return, never the workspace;
  - symlinks, submodules, path escapes, ignored files and conflicts with
    newer host edits are rejected;
  - a rejected or interrupted run leaves the host untouched.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
VM_SYNC = SCRIPTS / "vm-sync"
sys.path.insert(0, str(SCRIPTS))
from vm_land import path_problem  # noqa: E402

IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=check,
                          env={**os.environ, **IDENT}).stdout.strip()


def commit_file(repo: Path, rel: str, text: str, msg: str = "change") -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(repo, "add", "-f", rel)
    git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def env(tmp_path: Path):
    host = tmp_path / "proj"
    host.mkdir()
    git(host, "init", "-q", "-b", "main")
    (host / ".gitignore").write_text(".env\n")
    commit_file(host, "app.py", "x = 1\n", "seed")
    vm = tmp_path / "vm"
    vm.mkdir()
    e = {**os.environ, **IDENT, "SWBP_VM_FAKE_HOME": str(vm)}
    return host, vm, e


def vm_sync(e: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(VM_SYNC), *args], capture_output=True,
                          text=True, env=e)


def start(host: Path, e: dict, *extra: str) -> tuple[str, Path]:
    r = vm_sync(e, "start", str(host), *extra)
    assert r.returncode == 0, (r.stdout, r.stderr)
    run = r.stdout.strip().splitlines()[-1]
    ws = Path(e["SWBP_VM_FAKE_HOME"]) / "swbp-runs" / host.name / run / "ws"
    assert (ws / ".git").is_dir()
    return run, ws


def host_state(host: Path) -> str:
    """A fingerprint of everything the host could lose: refs and file bytes."""
    h = hashlib.sha256()
    h.update(git(host, "for-each-ref", "--format=%(refname) %(objectname)").encode())
    for p in sorted(host.rglob("*")):
        if ".git" in p.relative_to(host).parts or not p.is_file():
            continue
        h.update(str(p.relative_to(host)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def test_round_trip_lands_only_the_runs_commits(env):
    host, _vm, e = env
    base = git(host, "rev-parse", "HEAD")
    run, ws = start(host, e)
    tip = commit_file(ws, "app.py", "x = 2\n", "vm work")
    (ws / "scratch.log").write_text("workspace junk that must not return\n")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert git(host, "rev-parse", "HEAD") == tip
    assert git(host, "rev-parse", "HEAD~1") == base
    assert (host / "app.py").read_text() == "x = 2\n"
    assert not (host / "scratch.log").exists()
    assert git(host, "for-each-ref", "refs/swbp-vm") == ""
    assert "landed" in vm_sync(e, "list", str(host)).stdout


def test_each_run_is_its_own_snapshot(env):
    host, _vm, e = env
    run1, ws1 = start(host, e)
    commit_file(ws1, "app.py", "x = 'run1'\n")
    run2, ws2 = start(host, e)
    assert run1 != run2 and ws1 != ws2
    assert (ws2 / "app.py").read_text() == "x = 1\n"


def test_uncommitted_and_ignored_host_files_stay_on_the_host(env):
    host, _vm, e = env
    (host / ".env").write_text("SECRET=1\n")
    (host / "draft.py").write_text("wip\n")
    _run, ws = start(host, e)
    assert not (ws / ".env").exists()
    assert not (ws / "draft.py").exists()


def test_copy_file_goes_in_but_never_comes_back(env):
    host, _vm, e = env
    (host / ".env").write_text("SECRET=1\n")
    run, ws = start(host, e, "--copy-file", ".env")
    assert (ws / ".env").read_text() == "SECRET=1\n"
    (ws / ".env").write_text("SECRET=changed-in-vm\n")
    commit_file(ws, "app.py", "x = 3\n")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (host / ".env").read_text() == "SECRET=1\n"


def test_nothing_to_land_is_a_clean_noop(env):
    host, _vm, e = env
    before = host_state(host)
    run, _ws = start(host, e)
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0 and "nothing to land" in r.stdout
    assert host_state(host) == before


def _rejected(host: Path, e: dict, run: str, before: str, needle: str):
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert needle in r.stderr, r.stderr
    assert host_state(host) == before, "a rejected landing changed the host"
    assert git(host, "for-each-ref", "refs/swbp-vm") == "", "quarantine ref left behind"


def test_symlink_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    (ws / "link").symlink_to("/etc/passwd")
    git(ws, "add", "link")
    git(ws, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "symlink")
    _rejected(host, e, run, host_state(host), "symlink")


def test_submodule_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    sha = git(ws, "rev-parse", "HEAD")
    git(ws, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/sub")
    git(ws, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "gitlink")
    _rejected(host, e, run, host_state(host), "submodule")


def test_ignored_file_committed_in_the_vm_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    commit_file(ws, ".env", "SECRET=leaked\n", "commits a secret")
    _rejected(host, e, run, host_state(host), "ignores")


def test_merge_commit_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    git(ws, "checkout", "-q", "-b", "side")
    commit_file(ws, "side.py", "s = 1\n")
    git(ws, "checkout", "-q", "swbp-run")
    commit_file(ws, "main.py", "m = 1\n")
    git(ws, "-c", "core.hooksPath=/dev/null", "merge", "-q", "--no-ff", "-m", "merge", "side")
    _rejected(host, e, run, host_state(host), "merge commits")


def test_history_that_does_not_extend_the_snapshot_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    git(ws, "checkout", "-q", "--orphan", "rewritten")
    commit_file(ws, "app.py", "x = 'forged'\n", "unrelated root")
    git(ws, "branch", "-f", "swbp-run", "rewritten")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode != 0
    assert (host / "app.py").read_text() == "x = 1\n"


def test_crafted_dot_git_path_is_rejected(env):
    """Porcelain git refuses '.git' paths, but plumbing (mktree/commit-tree)
    does not — and on a case-insensitive host disk `x/.GIT/config` checks out
    as a nested repository config. The landing gate must refuse it."""
    host, _vm, e = env
    run, ws = start(host, e)

    def plumb(*args: str, stdin: str = "") -> str:
        return subprocess.run(["git", "-C", str(ws), *args], input=stdin,
                              capture_output=True, text=True, check=True,
                              env={**os.environ, **IDENT}).stdout.strip()

    blob = plumb("hash-object", "-w", "--stdin", stdin="[core]\n\thooksPath = /tmp\n")
    inner = plumb("mktree", stdin=f"100644 blob {blob}\tconfig\n")
    mid = plumb("mktree", stdin=f"040000 tree {inner}\t.GIT\n")
    base_tree = plumb("rev-parse", "HEAD^{tree}")
    entries = plumb("ls-tree", base_tree) + f"\n040000 tree {mid}\tx\n"
    top = plumb("mktree", stdin=entries)
    commit = plumb("commit-tree", top, "-p", "HEAD", "-m", "crafted")
    git(ws, "update-ref", "refs/heads/swbp-run", commit)
    _rejected(host, e, run, host_state(host), "'.git' component")


def test_unrelated_history_is_rejected_even_without_a_fast_forward(env):
    """With the host checkout on another branch, landing is a ref update, not
    a fast-forward merge — so the ancestry check alone must stop a run whose
    history does not extend the snapshot."""
    host, _vm, e = env
    run, ws = start(host, e)
    git(ws, "checkout", "-q", "--orphan", "rewritten")
    commit_file(ws, "app.py", "x = 'forged'\n", "unrelated root")
    git(ws, "branch", "-f", "swbp-run", "rewritten")
    git(host, "checkout", "-q", "-b", "elsewhere")
    before_main = git(host, "rev-parse", "main")
    _rejected(host, e, run, host_state(host), "does not extend the snapshot")
    assert git(host, "rev-parse", "main") == before_main


def test_host_branch_moved_since_snapshot_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    commit_file(ws, "app.py", "x = 'vm'\n")
    commit_file(host, "other.py", "o = 1\n", "newer host work")
    _rejected(host, e, run, host_state(host), "moved since the snapshot")


def test_uncommitted_host_edit_to_a_touched_file_is_rejected(env):
    host, _vm, e = env
    run, ws = start(host, e)
    commit_file(ws, "app.py", "x = 'vm'\n")
    (host / "app.py").write_text("x = 'my unsaved host edit'\n")
    _rejected(host, e, run, host_state(host), "uncommitted edits")
    assert (host / "app.py").read_text() == "x = 'my unsaved host edit'\n"


def test_host_on_another_branch_gets_a_ref_update_only(env):
    host, _vm, e = env
    run, ws = start(host, e)
    tip = commit_file(ws, "app.py", "x = 'vm'\n")
    git(host, "checkout", "-q", "-b", "elsewhere")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert git(host, "rev-parse", "main") == tip
    assert (host / "app.py").read_text() == "x = 1\n", "working tree must not change"


def test_interrupted_run_leaves_the_host_untouched(env):
    host, vm, e = env
    before = host_state(host)
    run, ws = start(host, e)
    commit_file(ws, "app.py", "x = 'half done'\n")
    # The VM disappears mid-run (here: its disk is gone before landing).
    import shutil
    shutil.rmtree(vm / "swbp-runs")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode != 0
    assert host_state(host) == before
    assert git(host, "for-each-ref", "refs/swbp-vm") == ""


def test_land_trusts_the_host_record_not_the_vm(env):
    host, _vm, e = env
    first = git(host, "rev-parse", "HEAD")
    commit_file(host, "app.py", "x = 'host v2'\n", "host moves before the run")
    run, ws = start(host, e)
    # The VM rewrites its own meta to claim an older base; land must ignore it.
    meta = ws.parent / "meta"
    meta.write_text(meta.read_text().replace(git(host, "rev-parse", "HEAD"), first))
    tip = commit_file(ws, "app.py", "x = 'vm'\n")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert git(host, "rev-parse", "HEAD") == tip


def test_discard_removes_the_vm_clone_and_blocks_landing(env):
    host, _vm, e = env
    run, ws = start(host, e)
    r = vm_sync(e, "discard", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not ws.exists()
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode != 0 and "discarded" in r.stderr


@pytest.mark.parametrize("path,ok", [
    ("src/app.py", True), ("a/b/c.txt", True),
    ("../escape", False), ("/abs", False), ("a//b", False), ("a/./b", False),
    (".git/hooks/post-merge", False), ("sub/.GIT/config", False),
    ("x/.Git", False), ("a\\b", False), ("", False),
])
def test_path_policy(path, ok):
    assert (path_problem(path) is None) is ok


# --- D-207: run telemetry comes home (catch ledger + metrics), nothing else ---

def _ignore_telemetry(host: Path) -> None:
    (host / ".gitignore").write_text(".env\n.catch-ledger.json\n.measurement/\n")
    git(host, "add", ".gitignore")
    git(host, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "ignore telemetry")


def _vm_telemetry(ws: Path, ledger: str | None, metrics: str | None) -> None:
    if ledger is not None:
        (ws / ".catch-ledger.json").write_text(ledger)
    if metrics is not None:
        (ws / ".measurement").mkdir(exist_ok=True)
        (ws / ".measurement" / "metrics.tsv").write_text(metrics)


LEDGER = '{"schema_version": 1, "gates": {"test-verdict": [{"spec_version": 4}]}}'
METRICS = "milestone\tfeature\nabc123\tv4\n"


def test_land_brings_home_the_runs_telemetry(env):
    host, _vm, e = env
    _ignore_telemetry(host)
    run, ws = start(host, e)
    commit_file(ws, "app.py", "x = 2\n")
    _vm_telemetry(ws, LEDGER, METRICS)
    (ws / "unlisted.log").write_text("never returns\n")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert json.loads((host / ".catch-ledger.json").read_text())["gates"] == \
        {"test-verdict": [{"spec_version": 4}]}
    assert (host / ".measurement" / "metrics.tsv").read_text() == METRICS
    assert not (host / "unlisted.log").exists()


def test_discarded_run_still_brings_home_its_catches(env):
    """Gates catch the local model mostly in runs that fail — those runs are
    discarded, and their evidence must not go with them."""
    host, _vm, e = env
    _ignore_telemetry(host)
    run, ws = start(host, e)
    _vm_telemetry(ws, LEDGER, None)
    r = vm_sync(e, "discard", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "test-verdict" in (host / ".catch-ledger.json").read_text()


def test_telemetry_is_merged_not_overwritten(env):
    host, _vm, e = env
    _ignore_telemetry(host)
    (host / ".catch-ledger.json").write_text(
        '{"schema_version": 1, "gates": {"mypy": [{"spec_version": 2}]}}')
    (host / ".measurement").mkdir()
    (host / ".measurement" / "metrics.tsv").write_text("milestone\tfeature\nold999\tv2\n")
    run, ws = start(host, e)
    _vm_telemetry(ws, LEDGER, METRICS)
    vm_sync(e, "discard", str(host), run)
    gates = json.loads((host / ".catch-ledger.json").read_text())["gates"]
    assert set(gates) == {"mypy", "test-verdict"}
    assert (host / ".measurement" / "metrics.tsv").read_text() == \
        "milestone\tfeature\nold999\tv2\nabc123\tv4\n"


def test_metrics_with_appended_columns_merge_into_an_older_host_table(env):
    """D-211 appends metrics columns. A host table with the older header gets
    the new header and its old rows padded; a different table is refused."""
    host, _vm, e = env
    _ignore_telemetry(host)
    (host / ".measurement").mkdir()
    (host / ".measurement" / "metrics.tsv").write_text("milestone\tfeature\nold999\tv2\n")
    run, ws = start(host, e)
    _vm_telemetry(ws, None, "milestone\tfeature\thuman_edits\nabc123\tv4\t1\n")
    vm_sync(e, "discard", str(host), run)
    assert (host / ".measurement" / "metrics.tsv").read_text() == \
        "milestone\tfeature\thuman_edits\nold999\tv2\t\nabc123\tv4\t1\n"
    run, ws = start(host, e)
    _vm_telemetry(ws, None, "other\ttable\nx\ty\n")
    r = vm_sync(e, "discard", str(host), run)
    assert "header differs" in r.stderr
    assert "abc123" in (host / ".measurement" / "metrics.tsv").read_text()


def test_bad_telemetry_warns_and_never_blocks_landing(env):
    host, _vm, e = env
    _ignore_telemetry(host)
    run, ws = start(host, e)
    tip = commit_file(ws, "app.py", "x = 2\n")
    _vm_telemetry(ws, '{"schema_version": 1, "gates": {"x": [{"spec_version": 0}]}}',
                  "other\theader\nrow\tvalue\n")
    r = vm_sync(e, "land", str(host), run)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert git(host, "rev-parse", "HEAD") == tip
    assert "catch ledger was rejected" in r.stderr
    assert not (host / ".catch-ledger.json").exists()


def test_telemetry_the_project_does_not_ignore_is_not_written(env):
    host, _vm, e = env  # fixture .gitignore covers only .env
    run, ws = start(host, e)
    _vm_telemetry(ws, LEDGER, METRICS)
    r = vm_sync(e, "discard", str(host), run)
    assert "not in proj's .gitignore" in r.stderr, r.stderr
    assert not (host / ".catch-ledger.json").exists()
    assert not (host / ".measurement").exists()
