#!/usr/bin/env python3
"""D-168 / D-186 plane-snapshot mechanism tests: pinned ref = authority,
immutable snapshot = execution.

Since stage F (D-218) the only entry is the builder (`scripts/swbp`): it
resolves the app's `.swbp` pin, materializes the snapshot, refuses a
mid-milestone plane change and execs the snapshot's script. The swbp tests
below drive the REAL launcher against synthetic builder repos; orchestrate's
own guard is pinned to refuse any direct (non-snapshot) launch.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCHESTRATE = HERE.parent / "orchestrate.sh"
SANDBOX_RUN = HERE.parent / "sandbox-run.sh"
REPO = HERE.parents[1]






def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)
















def test_direct_orchestrate_launch_is_refused(tmp_path):
    """Stage F (D-218): the hosted/linked-child entry is gone. A launch that
    does not come from a swbp snapshot stops at the guard, before any work."""
    app = tmp_path / "app"
    app.mkdir()
    _git(app, "init", "-q", "-b", "main")
    (app / ".template-version").write_text("repo=x/y\nref=" + "a" * 40 + "\n")
    env = {k: v for k, v in os.environ.items() if k != "SWBP_PLANE_SNAPSHOT"}
    r = subprocess.run(["bash", str(ORCHESTRATE)], cwd=app, capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode != 0
    assert "orchestrate runs only through the builder" in r.stderr, r.stderr
    assert not (app / ".pipeline-state").exists(), "the guard must stop before any mutation"


def test_snapshot_launch_passes_the_guard(tmp_path):
    """Under SWBP_PLANE_SNAPSHOT the guard resolves PLANE_DIR and returns."""
    src = ORCHESTRATE.read_text()
    guard = src[src.index("_plane_self() {"):src.index("plane_entry_guard \"$@\"")]
    script = ('die() { echo "FAIL: $*" >&2; exit 1; }\nPLANE_DIR=""\n' + guard
              + 'plane_entry_guard\necho "PLANE_DIR=$PLANE_DIR"\n')
    f = tmp_path / "guard.sh"
    f.write_text(script)
    env = dict(os.environ, SWBP_PLANE_SNAPSHOT="/some/snapshot")
    r = subprocess.run(["bash", str(f)], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"PLANE_DIR={tmp_path.resolve().parent}", r.stdout


def test_snapshot_sandbox_mounts_the_child_repo(tmp_path):
    """A helper reached through the plane must still sandbox the child tree.

    A fake Podman records the final run arguments, so this crosses the real
    sandbox-run.sh repository-selection path without requiring a VM/container.
    """
    child = tmp_path / "sandbox-child"
    child.mkdir()
    (child / "Containerfile").write_text("FROM scratch\n")
    (child / "requirements.txt").write_text("")
    _git(child, "init", "-q", "-b", "main")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    podman_log = tmp_path / "podman-run.args"
    podman = fake_bin / "podman"
    podman.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = info ]; then exit 0; fi\n"
        "if [ \"$1\" = image ] && [ \"$2\" = exists ]; then exit 0; fi\n"
        "printf '%s\\n' \"$@\" > \"$PODMAN_LOG\"\n"
    )
    podman.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["PODMAN_LOG"] = str(podman_log)
    result = subprocess.run(
        ["bash", str(SANDBOX_RUN), "--", "true"],
        cwd=child,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    args = podman_log.read_text().splitlines()
    child_mount = f"{child.resolve()}:/work:ro,Z"
    plane_mount = f"{REPO.resolve()}:/work:ro,Z"
    assert child_mount in args
    assert plane_mount not in args






# ---------------------------------------------------------------------------
# D-186 stage A — two roots: plane files from the plane, app files from cwd.
#
# The central builder runs against an app that carries no plane. Stage A makes
# every entry script resolve its own helpers (tools, prompts, schemas, settings)
# from the plane root — where the script really lives, symlinks walked — and
# only app artifacts (spec, tests, tasks, state) from the working directory.
#
# Behavioral proof: an app whose ONLY plane file is the entry-script symlink
# still runs. Before stage A, tpm-view.sh died opening the app's
# scripts/spec_artifacts.py. The static guard keeps a cwd-relative plane call
# from creeping back into the converted scripts.
# ---------------------------------------------------------------------------

PLANE = Path(__file__).resolve().parents[2]
SPEC = PLANE / "examples" / "minimal-spec"

CONVERTED = [
    "scripts/orchestrate.sh",
    "scripts/refreeze.sh",
    "scripts/tpm-pack.sh",
    "scripts/tpm-agent.sh",
    "scripts/tpm-view.sh",
    "scripts/em-bench.sh",
]

# A plane path used as a command/argument without going through $PLANE_DIR.
CWD_PLANE_CALL = re.compile(
    r"(?:(?:python3|bash|source)\s+|^\s*|&&\s+|\|\s+|timeout\s+\S+\s+)"
    r"scripts/[\w.-]+\.(?:py|sh)\b"
    r"|(?<![\w/}])\.opencode/prompts/"
    r"|(?<![\w/}])scripts/schemas/"
)


def _plane_less_app(tmp_path: Path) -> Path:
    app = tmp_path / "app"
    approved = app / "scripts" / ".approved"
    approved.mkdir(parents=True)
    for name in ("PRD.md", "ERD.md", "contracts.json"):
        shutil.copy(SPEC / name, approved / name)
    shutil.copytree(SPEC / "tests", app / "tests",
                    ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    (app / "scripts" / "tpm-view.sh").symlink_to(PLANE / "scripts" / "tpm-view.sh")
    return app


def test_entry_script_runs_in_an_app_that_carries_no_plane(tmp_path):
    app = _plane_less_app(tmp_path)
    r = subprocess.run(
        ["bash", "scripts/tpm-view.sh"], cwd=app, capture_output=True, text=True
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    view = app / ".tpm" / "view"
    assert (view / "contracts.json").is_file()
    assert (view / "tests").is_dir()
    # the app itself gained no plane files
    assert sorted(p.name for p in (app / "scripts").iterdir()) == [
        ".approved",
        "tpm-view.sh",
    ]


def test_converted_scripts_make_no_cwd_relative_plane_calls():
    offenders = []
    for rel in CONVERTED:
        for n, line in enumerate((PLANE / rel).read_text().splitlines(), 1):
            code = line.strip()
            if not code or code.startswith("#"):
                continue
            if re.search(r"\b(echo|die|printf|emit)\b", code):
                continue  # messages and bundle labels name paths, they don't read them
            if CWD_PLANE_CALL.search(line):
                offenders.append(f"{rel}:{n}: {code}")
    assert not offenders, "\n".join(offenders)


# ---------------------------------------------------------------------------
# D-186 stage B — `scripts/swbp <cmd> --app <path>`: the builder runs against
# an app from a snapshot of the pinned builder ref; the app gains nothing.
# A throwaway builder repo is committed twice: an OLD ref without swbp and a
# NEW ref with it, so the launcher's ref-age refusal is exercised for real.
# ---------------------------------------------------------------------------


def _builder_repo(tmp_path: Path) -> tuple[Path, str, str]:
    builder = tmp_path / "builder"
    files = subprocess.run(
        ["git", "-C", str(PLANE), "ls-files", "-co", "--exclude-standard", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    for rel in filter(None, files):
        src = PLANE / rel
        if src.is_file() and not src.is_symlink():
            dst = builder / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    swbp = builder / "scripts" / "swbp"
    held = swbp.read_bytes()
    swbp.unlink()

    def commit(msg: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", str(builder), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(builder), "-c", "core.hooksPath=/dev/null",
                        "commit", "-qm", msg], check=True, env=env)
        return subprocess.run(["git", "-C", str(builder), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

    subprocess.run(["git", "init", "-q", str(builder)], check=True)
    old = commit("old")
    swbp.write_bytes(held)
    swbp.chmod(0o755)
    new = commit("new")
    return builder, old, new


def _swbp_app(tmp_path: Path, ref: str) -> Path:
    app = tmp_path / "swbp-app"
    approved = app / "scripts" / ".approved"
    approved.mkdir(parents=True)
    for name in ("PRD.md", "ERD.md", "contracts.json"):
        shutil.copy(SPEC / name, approved / name)
    shutil.copytree(SPEC / "tests", app / "tests",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (app / ".swbp").write_text(f"ref={ref}\n")
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    return app


def _run_swbp(builder: Path, tmp_path: Path, *args: str):
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    return subprocess.run([str(builder / "scripts" / "swbp"), *args],
                          capture_output=True, text=True, env=env)


def test_swbp_runs_a_builder_step_against_a_plane_less_app(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (app / ".tpm" / "view" / "contracts.json").is_file()
    # nothing of the plane landed in the app
    assert sorted(p.name for p in (app / "scripts").iterdir()) == [".approved"]
    # hooks come from the pinned snapshot, via untracked config: D-201 points
    # hooksPath at shims inside the app's .git that forward to the snapshot
    hp = subprocess.run(["git", "-C", str(app), "config", "core.hooksPath"],
                        capture_output=True, text=True).stdout.strip()
    assert Path(hp) == (app / ".git" / "swbp-hooks").resolve()
    snap_hook = tmp_path / "cache" / "swbp-plane" / new / ".githooks" / "pre-commit"
    assert snap_hook.is_file()
    assert f"target='{snap_hook}'" in Path(hp, "pre-commit").read_text()


def test_swbp_refuses_a_ref_that_predates_it(tmp_path):
    builder, old, _new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, old)
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app))
    assert r.returncode != 0
    assert "predates swbp" in r.stderr
    assert not (app / ".tpm").exists()


def test_swbp_refuses_unknown_command_and_non_repo_app(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    r = _run_swbp(builder, tmp_path, "rm", "--app", str(app))
    assert r.returncode != 0 and "unknown command" in r.stderr
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(plain))
    assert r.returncode != 0 and "root of a git repository" in r.stderr


def test_swbp_refuses_mid_milestone_plane_change(tmp_path):
    builder, old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    state = app / ".pipeline-state"
    (state / "tasks").mkdir(parents=True)
    (state / "tasks" / "T1").write_text("pending\n")
    (state / "plane-sha").write_text(old + "\n")
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app))
    assert r.returncode != 0
    assert "mid-milestone plane adoption forbidden" in r.stderr


def _frozen(app: Path) -> None:
    approved = app / "scripts" / ".approved"
    (approved / "VERSION").write_text("1\n")
    rows = []
    for f in sorted([*approved.glob("*.md"), *approved.glob("*.json"),
                     *(app / "tests").glob("*.py")]):
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        rows.append(f"{digest}  {f.relative_to(app)}")
    (approved / "frozen-manifest").write_text("\n".join(rows) + "\n")


def test_phase_gate_app_mode_skips_hosted_plane_but_keeps_frozen_spec(tmp_path):
    app = _swbp_app(tmp_path, "0" * 40)
    _frozen(app)
    gate = str(PLANE / "scripts" / "phase-gate.sh")
    r = subprocess.run(["bash", gate, "manifest", "HEAD"], cwd=app,
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    # the frozen spec is still fail-closed in app mode
    with open(app / "tests" / "api_tests.py", "a") as fh:
        fh.write("# tampered\n")
    r = subprocess.run(["bash", gate, "manifest", "HEAD"], cwd=app,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "tampered" in r.stdout
    # without the .swbp marker the hosted-plane checks still apply
    (app / ".swbp").unlink()
    _frozen(app)
    r = subprocess.run(["bash", gate, "manifest", "HEAD"], cwd=app,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "manifest missing" in r.stdout


# ---------------------------------------------------------------------------
# D-186 stage C — the app guard (check-app-guard.py), `swbp commit`, and the
# pre-push hook's app mode. Report-first: findings print, exit 0, unless
# --enforce or `.swbp` says guard=enforce.
# ---------------------------------------------------------------------------

GUARD = PLANE / "scripts" / "check-app-guard.py"
ZERO_SHA = "0" * 40
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _commit(app: Path, path: str, text: str, role: str = "") -> str:
    f = app / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    env = {**os.environ, **IDENT}
    msg = ["-m", f"edit {path}"] + (["-m", f"Swbp-Role: {role}"] if role else [])
    subprocess.run(["git", "-C", str(app), "add", path], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-q", *msg], check=True, env=env)
    return subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _guard(app: Path, *args: str):
    return subprocess.run([sys.executable, str(GUARD), *args], cwd=app,
                          capture_output=True, text=True)


def _guard_app(tmp_path: Path) -> tuple[Path, str]:
    app = tmp_path / "guard-app"
    app.mkdir()
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    base = _commit(app, ".swbp", "ref=" + "0" * 40 + "\n", role="human")
    return app, base


def test_guard_accepts_builder_commits_and_flags_hand_edits(tmp_path):
    app, base = _guard_app(tmp_path)
    _commit(app, "tests/test_a.py", "def test_a(): pass\n", role="tpm")
    _commit(app, "CLAUDE.md", "notes\n", role="human")
    _commit(app, "src/app.py", "x = 1\n")  # product code: not guarded
    clean = _guard(app, "--rev", f"{base}..HEAD")
    assert clean.returncode == 0 and "0 finding(s)" in clean.stdout, clean.stdout

    hand_test = _commit(app, "tests/test_a.py", "def test_a(): assert 1\n")
    coder_spec = _commit(app, "scripts/.approved/ERD.md", "x\n", role="coder")
    hand_cfg = _commit(app, ".github/workflows/ci.yml", "on: push\n")
    r = _guard(app, "--rev", f"{base}..HEAD")
    assert r.returncode == 0, "report-first must not fail"
    assert "3 finding(s)" in r.stdout, r.stdout
    for sha in (hand_test, coder_spec, hand_cfg):
        assert sha[:12] in r.stdout

    assert _guard(app, "--rev", f"{base}..HEAD", "--enforce").returncode == 1
    (app / ".swbp").write_text("ref=" + "0" * 40 + "\nguard=enforce\n")
    assert _guard(app, "--rev", f"{base}..HEAD").returncode == 1


def _git(app: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(["git", "-C", str(app), *args], check=True,
                          capture_output=True, text=True,
                          env={**os.environ, **IDENT}, input=input).stdout.strip()


def test_guard_merge_carrying_brokered_changes_is_clean(tmp_path):
    # D-192: a (role-less) merge that merely carries brokered branch changes
    # is authorized by the origin commits — no finding.
    app, base = _guard_app(tmp_path)
    branch = _git(app, "symbolic-ref", "--short", "HEAD")
    _commit(app, "tests/test_a.py", "def test_a(): pass\n", role="tpm")
    subprocess.run(["git", "-C", str(app), "checkout", "-qb", "side"], check=True)
    _commit(app, "tests/test_b.py", "def test_b(): pass\n", role="tpm")
    subprocess.run(["git", "-C", str(app), "checkout", "-q", branch], check=True)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "merge", "-q", "--no-ff", "side", "-m", "merge side"],
                   check=True, env={**os.environ, **IDENT})
    r = _guard(app, "--range", f"{base}..HEAD")
    assert r.returncode == 0 and "0 finding(s)" in r.stdout, r.stdout


def test_guard_flags_merge_introduced_changes(tmp_path):
    # D-192: the merge commit's introduced diff (first-parent) is inspected.
    # Here the merge carries a hand edit to a frozen test that NO commit
    # contains — a conflict-resolution-style introduction the old
    # --no-merges guard never saw.
    app, base = _guard_app(tmp_path)
    branch = _git(app, "symbolic-ref", "--short", "HEAD")
    main1 = _commit(app, "tests/test_b.py", "def test_b(): pass\n", role="tpm")
    subprocess.run(["git", "-C", str(app), "checkout", "-qb", "side"], check=True)
    _commit(app, "tests/test_c.py", "def test_c(): pass\n", role="tpm")
    side_head = _git(app, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(app), "checkout", "-q", branch], check=True)
    # hand-built merge: main1's tree + side's brokered test_c + a hand edit
    # to tests/test_a.py that exists in no commit
    _git(app, "read-tree", main1)
    _git(app, "update-index", "--add", "--cacheinfo",
         f"100644,{_git(app, 'rev-parse', 'side:tests/test_c.py')},tests/test_c.py")
    blob = _git(app, "hash-object", "-w", "--stdin",
                input="def test_a(): assert False  # hand edit in the merge\n")
    _git(app, "update-index", "--add", "--cacheinfo", f"100644,{blob},tests/test_a.py")
    tree = _git(app, "write-tree")
    merge = _git(app, "commit-tree", tree, "-p", main1, "-p", side_head,
                 "-m", "merge side")
    _git(app, "update-ref", f"refs/heads/{branch}", merge)
    r = _guard(app, "--range", f"{base}..HEAD")
    assert r.returncode == 0, "report-first must not fail"
    assert "1 finding(s)" in r.stdout, r.stdout
    assert merge[:12] in r.stdout and "tests/test_a.py" in r.stdout, r.stdout
    assert _guard(app, "--range", f"{base}..HEAD", "--enforce").returncode == 1


def test_guard_catches_test_edit_with_a_regenerated_frozen_manifest(tmp_path):
    """Security plan item 5: an edit that weakens a frozen test AND rewrites
    scripts/.approved/frozen-manifest to match passes every hash check — so
    the guard must judge by path and role, and must stay in enforce mode
    even when the same commit drops guard=enforce."""
    app = tmp_path / "guard-app"
    app.mkdir()
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    base = _commit(app, ".swbp", "ref=" + "0" * 40 + "\nguard=enforce\n", role="human")
    _commit(app, "tests/test_a.py", "def test_a(): assert 2 + 2 == 4\n", role="tpm")
    _commit(app, "scripts/.approved/frozen-manifest", "aaa  tests/test_a.py\n", role="tpm")
    pinned = subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    (app / "tests/test_a.py").write_text("def test_a(): assert True\n")
    (app / "scripts/.approved/frozen-manifest").write_text("bbb  tests/test_a.py\n")
    (app / ".swbp").write_text("ref=" + "0" * 40 + "\n")
    env = {**os.environ, **IDENT}
    subprocess.run(["git", "-C", str(app), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "tidy"], check=True, env=env)
    r = _guard(app, "--range", f"{pinned}..HEAD")
    assert r.returncode == 1, r.stdout
    assert "[enforce]" in r.stdout, r.stdout
    assert "scripts/.approved/frozen-manifest" in r.stdout and "tests/test_a.py" in r.stdout
    assert base


def test_guard_enforcement_ratchets_against_downgrades(tmp_path):
    # D-192: once any commit in the range had guard=enforce, the whole range
    # is checked in enforce mode — a hand downgrade of the guard cannot
    # demote the check that would catch it.
    app = tmp_path / "guard-app"
    app.mkdir()
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    base = _commit(app, ".swbp", "ref=" + "0" * 40 + "\nguard=enforce\n",
                   role="human")
    _commit(app, ".swbp", "ref=" + "0" * 40 + "\n")  # hand downgrade
    r = _guard(app, "--range", f"{base}..HEAD")
    assert "1 finding(s)" in r.stdout, r.stdout
    assert "[enforce]" in r.stdout, r.stdout
    assert r.returncode == 1, "a hand downgrade must not demote the check"

    # the authorized path: a brokered commit may lower the mode
    app2 = tmp_path / "guard-app2"
    app2.mkdir()
    subprocess.run(["git", "init", "-q", str(app2)], check=True)
    base2 = _commit(app2, ".swbp", "ref=" + "0" * 40 + "\nguard=enforce\n",
                    role="human")
    _commit(app2, ".swbp", "ref=" + "0" * 40 + "\n", role="human")
    r2 = _guard(app2, "--range", f"{base2}..HEAD")
    assert "0 finding(s)" in r2.stdout and r2.returncode == 0, r2.stdout


def test_swbp_commit_goes_through_the_broker(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    env = {**os.environ, **IDENT, "HOME": str(tmp_path / "home"),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    subprocess.run(["git", "-C", str(app), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "seed"], check=True, env=env)
    base = subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    (app / "CLAUDE.md").write_text("app notes\n")
    r = subprocess.run([str(builder / "scripts" / "swbp"), "commit", "--app", str(app),
                        "--", "docs: app notes", "CLAUDE.md"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    body = subprocess.run(["git", "-C", str(app), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert "Swbp-Role: human" in body and f"Swbp-Plane: {new}" in body, body
    g = _guard(app, "--rev", f"{base}..HEAD", "--enforce")
    assert g.returncode == 0, g.stdout


def _push_line(sha: str, remote_sha: str = ZERO_SHA) -> str:
    return f"refs/heads/main {sha} refs/heads/main {remote_sha}\n"



def test_pre_push_app_mode_runs_app_checks_not_the_plane_suite(tmp_path):
    app = _swbp_app(tmp_path, "0" * 40)
    _frozen(app)
    env = {**os.environ, **IDENT}
    subprocess.run(["git", "-C", str(app), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "seed", "-m", "Swbp-Role: tpm"], check=True, env=env)
    head = subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    hook = str(PLANE / ".githooks" / "pre-push")
    ok = subprocess.run(["bash", hook, "origin", "url"], cwd=app, input=_push_line(head),
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    assert "app checks green" in ok.stderr
    assert "control-plane suite" not in ok.stderr

    # a hand edit to a frozen test: the frozen-spec check refuses the push
    bad = _commit(app, "tests/api_tests.py", "# tampered\n")
    r = subprocess.run(["bash", hook, "origin", "url"], cwd=app,
                       input=_push_line(bad, head), capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "REFUSED" in r.stderr and "tampered" in r.stderr


def test_pre_push_app_mode_uses_the_apps_venv_tools(tmp_path):
    app = _swbp_app(tmp_path, "0" * 40)
    _frozen(app)
    (app / "src").mkdir()
    (app / "src" / "m.py").write_text("x = 1\n")
    env = {**os.environ, **IDENT}
    subprocess.run(["git", "-C", str(app), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "seed", "-m", "Swbp-Role: tpm"], check=True, env=env)
    head = subprocess.run(["git", "-C", str(app), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    # a venv mypy that fails: the hook must find it and refuse
    venv = app / ".venv" / "bin"
    venv.mkdir(parents=True)
    fake = venv / "mypy"
    fake.write_text("#!/bin/sh\necho venv-mypy-ran >&2\nexit 1\n")
    fake.chmod(0o755)
    r = subprocess.run(["bash", str(PLANE / ".githooks" / "pre-push"), "origin", "url"],
                       cwd=app, input=_push_line(head), capture_output=True, text=True, env=env)
    assert "venv-mypy-ran" in r.stderr, r.stderr
    assert r.returncode != 0


def test_new_project_targeted_is_born_without_a_plane(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    env = {**os.environ, **IDENT, "HOME": str(tmp_path / "home"),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    r = subprocess.run([str(builder / "scripts" / "new-project.sh"), "--targeted", "demo",
                        "--from", str(builder), "--skip-bootstrap"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    app = tmp_path / "demo"
    assert (app / ".swbp").read_text().splitlines()[1] == f"ref={new}"
    # no plane: no scripts, no manifests, no link/pin files, no tracked hooks
    tracked = subprocess.run(["git", "-C", str(app), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.split()
    assert not [t for t in tracked if t.startswith(("scripts/", ".githooks/", ".opencode/"))
                and not t.startswith("scripts/.approved/")], tracked
    for gone in (".template-version", ".template-link", "BLUEPRINT.md"):
        assert gone not in tracked
    assert {".github/workflows/ci.yml", ".github/workflows/swbp-guard.yml"} <= set(tracked)
    assert os.readlink(app / "AGENTS.md") == "CLAUDE.md"
    assert "builder-targeted app" in (app / "CLAUDE.md").read_text()
    body = subprocess.run(["git", "-C", str(app), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert "Swbp-Role: human" in body, body
    assert _guard(app, "--rev", "HEAD", "--enforce").returncode == 0
    gate = subprocess.run(["bash", str(PLANE / "scripts" / "phase-gate.sh"), "manifest",
                           "HEAD"], cwd=app, capture_output=True, text=True)
    assert gate.returncode == 0, gate.stdout


def test_swbp_in_a_worktree_leaves_the_main_checkouts_hooks_alone(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    main = _swbp_app(tmp_path, new)
    env = {**os.environ, **IDENT, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    subprocess.run(["git", "-C", str(main), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(main), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "seed"], check=True, env=env)
    subprocess.run(["git", "-C", str(main), "config", "core.hooksPath", ".githooks"],
                   check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "side", str(wt)],
                   check=True, env=env)
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(wt))
    assert r.returncode == 0, (r.stdout, r.stderr)

    def hp(repo):
        return subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath"],
                              capture_output=True, text=True).stdout.strip()

    assert hp(main) == ".githooks"
    wt_gitdir = subprocess.run(["git", "-C", str(wt), "rev-parse", "--absolute-git-dir"],
                               capture_output=True, text=True, check=True).stdout.strip()
    assert hp(wt) == f"{wt_gitdir}/swbp-hooks"
    assert f"swbp-plane/{new}/.githooks/pre-commit'" in Path(hp(wt), "pre-commit").read_text()

# --- D-201: snapshot publication is atomic; hooks survive a purged cache ---

def _populate_unstamped(root: Path, builder: Path, sha: str) -> None:
    """Model ANOTHER launcher mid-publication: a complete extraction that is
    not stamped yet, plus a marker the test can watch for deletion."""
    root.mkdir(parents=True)
    arch = subprocess.run(["git", "-C", str(builder), "archive", sha],
                          capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(root)], input=arch, check=True)
    (root / "IN-PROGRESS-BY-OTHER").write_text("x")


def _stamp_later(root: Path, delay: float) -> subprocess.Popen:
    return subprocess.Popen(
        ["sh", "-c", f'sleep {delay}; : > "{root}/.swbp-plane-stamped"'])


def test_swbp_never_deletes_a_snapshot_another_launcher_is_publishing(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    root = tmp_path / "cache" / "swbp-plane" / new
    _populate_unstamped(root, builder, new)
    other = _stamp_later(root, 1.5)
    r = _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app))
    other.wait()
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (root / "IN-PROGRESS-BY-OTHER").exists(), \
        "an unstamped snapshot another launcher was publishing was deleted"
    assert (root / ".swbp-plane-stamped").exists()


def test_swbp_replaces_a_stale_unstamped_leftover(tmp_path):
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    root = tmp_path / "cache" / "swbp-plane" / new
    root.mkdir(parents=True)
    (root / "half-written").write_text("crash leftover")
    env_wait = {"SWBP_PLANE_PUBLISH_WAIT": "1"}
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache"), **env_wait}
    r = subprocess.run([str(builder / "scripts" / "swbp"), "tpm-view", "--app", str(app)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (root / ".swbp-plane-stamped").exists()
    assert (root / "scripts" / "swbp").is_file()
    assert not (root / "half-written").exists()




def test_swbp_hooks_refuse_when_the_snapshot_is_purged(tmp_path):
    """git silently runs NO hooks when core.hooksPath points at a missing
    directory. After a cache purge, a commit must be refused, not ungated;
    the next swbp entry restores gating."""
    builder, _old, new = _builder_repo(tmp_path)
    app = _swbp_app(tmp_path, new)
    env = {**os.environ, **IDENT}
    subprocess.run(["git", "-C", str(app), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(app), "-c", "core.hooksPath=/dev/null",
                    "commit", "-qm", "seed"], check=True, env=env)
    assert _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app)).returncode == 0
    shutil.rmtree(tmp_path / "cache" / "swbp-plane" / new)
    (app / "notes.md").write_text("hand edit\n")
    subprocess.run(["git", "-C", str(app), "add", "notes.md"], check=True, env=env)
    r = subprocess.run(["git", "-C", str(app), "commit", "-qm", "ungated?"],
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0, "commit went through with the plane snapshot purged"
    assert "snapshot missing" in r.stderr, r.stderr
    assert _run_swbp(builder, tmp_path, "tpm-view", "--app", str(app)).returncode == 0
    r = subprocess.run(["git", "-C", str(app), "commit", "-qm", "gated again"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
