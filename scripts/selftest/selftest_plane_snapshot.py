#!/usr/bin/env python3
"""D-168 plane-snapshot mechanism tests: pinned ref = authority, immutable
snapshot = execution, drift alarm = telemetry.

The mechanism scenarios drive the REAL `plane_entry_guard` extracted from
orchestrate.sh between its D-168 BEGIN/END markers (the same anti-drift
extraction pattern drive-plan.sh uses for ensure_plan). A synthetic two-commit
"blueprint" repo stands in for the plane. A separate whole-entrypoint test
executes the REAL orchestrate.sh prelude and guard from a child symlink, proving
the dry-run re-exec boundary exits before any post-guard preflight or work.

Scope honesty (Rule 6): these pins prove the MECHANISM — materialization,
content-addressed reuse, authority surviving blueprint advancement, drift
telemetry, mid-milestone adoption stop, cache-eviction rebuild. The full
two-task paused-run hazard is composed from these parts; an end-to-end drive
under a live LLM is out of scope here and covered by the run machinery
itself (drive-coder exercises orchestrate's execution path separately).
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCHESTRATE = HERE.parent / "orchestrate.sh"
SANDBOX_RUN = HERE.parent / "sandbox-run.sh"
REPO = HERE.parents[1]


def _install_copied_entrypoint(child: Path) -> None:
    """Model a normal update-template child, which owns copied plane files."""
    scripts = child / "scripts"
    scripts.mkdir(parents=True)
    installed = scripts / "orchestrate.sh"
    shutil.copy2(ORCHESTRATE, installed)
    digest = hashlib.sha256(installed.read_bytes()).hexdigest()
    (scripts / ".manifest-template").write_text(
        f"{digest}  scripts/orchestrate.sh\n"
    )


def _extract_guard_source():
    """Pull everything from 'set -euo pipefail' through the END marker so the
    extracted snippet carries die() expectations of the real file. die is
    stubbed to raise SystemExit(78) with the message on stderr."""
    text = ORCHESTRATE.read_text()
    begin = text.index("# --- D-168: pinned-plane immutable snapshot")
    end = text.index("# --- D-168 END")
    body = text[begin:end]
    # Strip the script's own embedded call so the harness controls exactly
    # one guarded invocation, after its stubs exist.
    body = body.replace('\nplane_entry_guard "$@"\n', "\n")
    body = body.replace('"${BASH_SOURCE[0]}"', '"$PLANE_SELF"')
    return ("set -euo pipefail\n"
            'die() { echo "$*" >&2; exit 78; }\n'
            "meas() { :; }\n"
            'PLANE_SELF="scripts/orchestrate.sh"\n'
            + body)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


class FakePlane:
    """A git repo standing in for sw-dev-blueprint, with a helper payload that
    changes across commits so tests can prove WHICH version executed."""

    def __init__(self, root: Path):
        self.root = root
        (root / "scripts").mkdir(parents=True)
        (root / ".githooks").mkdir()
        self.write_helper("v1")
        # The entry-point itself, committed, so git archive carries it.
        (root / "scripts" / "orchestrate.sh").write_text(
            "#!/usr/bin/env bash\n# stub entry point\n")
        _git(root, "init", "-q", "-b", "main")
        _git(root, "add", "-A")
        _git(root, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", "c1")

    def write_helper(self, body: str):
        (self.root / "scripts" / "helper.txt").write_text(body)
        (self.root / "scripts" / "context-budget.py").write_text(
            f'print("{body}")\n')

    def commit(self, msg: str):
        _git(self.root, "add", "-A")
        _git(self.root, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-qm", msg)

    @property
    def head(self) -> str:
        return subprocess.run(["git", "-C", str(self.root), "rev-parse",
                               "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()


def make_child(tmp: Path, pin: str, plane_root: Path) -> Path:
    child = tmp / "child"
    (child / "scripts").mkdir(parents=True)
    # The child reaches the plane the way real ones do: a live symlink into it.
    (child / "scripts" / "orchestrate.sh").symlink_to(
        plane_root / "scripts" / "orchestrate.sh")
    (child / ".template-version").write_text(
        f"repo=fake/plane\nref={pin}\n")
    _git(child, "init", "-q", "-b", "main")
    _git(child, "add", "-A")
    _git(child, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "birth")
    return child


def run_guard(child: Path, extra_env=None):
    env = dict(os.environ)
    env.pop("SWBP_PLANE_SNAPSHOT", None)
    env["SWBP_PLANE_DRYRUN"] = "1"
    env["XDG_CACHE_HOME"] = str(child / "_cache")
    env.update(extra_env or {})
    harness = child / "_harness.sh"
    harness.write_text(
        "set -euo pipefail\n"
        + _extract_guard_source().replace(
            "${BASH_SOURCE[0]}", '"scripts/orchestrate.sh"')
        + "\nplane_entry_guard \"$@\"\n"
    )
    return subprocess.run(["bash", "_harness.sh", "--full-suite"],
                          cwd=child, capture_output=True, text=True,
                          env=env)


def main() -> int:
    failures = []
    checks = 0

    def check(name, cond, detail=""):
        nonlocal checks
        checks += 1
        if not cond:
            failures.append(f"{name}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plane = FakePlane(tmp / "plane")
        c1 = plane.head
        child = make_child(tmp, c1, plane.root)

        # 1. First launch: materializes the PIN, not HEAD, and re-execs from
        #    the snapshot path.
        r = run_guard(child)
        check("first-run rc", r.returncode == 0, r.stderr)
        check("dryrun names snapshot", "DRYRUN exec:" in r.stdout, r.stdout)
        snap_marker = f"SWBP_PLANE_SHA={c1}"
        check("snapshot sha is pin", snap_marker in r.stdout, r.stdout)

        # 2. Advance the blueprint past the pin (the vortex hazard), then
        #    relaunch: authority still the recorded pin; movement logged.
        plane.write_helper("v2")
        plane.commit("c2")
        c2 = plane.head
        check("plane advanced", c2 != c1)
        r2 = run_guard(child)
        check("authority sticks to pin", f"SWBP_PLANE_SHA={c1}" in r2.stdout,
              r2.stdout)
        drift = child / ".measurement" / "plane-drift.log"
        check("drift telemetry written", drift.exists())
        if drift.exists():
            line = drift.read_text()
            check("drift names both shas", c1 in line and c2 in line, line)

        # 3. Snapshot is content-addressed and reused, never rebuilt over.
        stamp = child / "_cache" / "swbp-plane" / c1 / ".swbp-plane-stamped"
        check("stamped snapshot exists", stamp.exists(), str(stamp))

        # 4. Mid-milestone adoption forbidden: a milestone is IN PROGRESS
        #    (task state present), state recorded c1, restamp to c2 -> hard
        #    stop even though c2 now exists in the plane repo.
        (child / ".pipeline-state" / "tasks").mkdir(parents=True, exist_ok=True)
        (child / ".pipeline-state" / "tasks" / "T1").write_text("in-progress")
        (child / ".template-version").write_text(f"repo=fake/plane\nref={c2}\n")
        r3 = run_guard(child)
        check("adoption blocked rc", r3.returncode == 78, r3.stderr)
        check("adoption blocked msg", "mid-milestone plane adoption forbidden"
              in r3.stderr, r3.stderr)

        # 4b. After the milestone completes (no task state), the SAME stale
        #     record must be ADOPTED, not blocked — D-168 live-fire fix
        #     (2026-08-23): a stale plane-sha otherwise wedges the first run
        #     after every adoption.
        import shutil as _sh
        _sh.rmtree(child / ".pipeline-state" / "tasks")
        r3b = run_guard(child)
        check("stale-record adoption allowed rc", r3b.returncode == 0, r3b.stderr)
        check("adopts the new pin", f"SWBP_PLANE_SHA={c2}" in r3b.stdout, r3b.stdout)

        # 5. Unknown pin fails closed with an actionable message.
        bad = tmp / "child2"
        bad.mkdir()
        (bad / "scripts").mkdir()
        (bad / ".template-version").write_text("repo=fake/plane\nref=" +
                                               "0" * 40 + "\n")
        (bad / "scripts" / "orchestrate.sh").symlink_to(
            plane.root / "scripts" / "orchestrate.sh")
        _git(bad, "init", "-q", "-b", "main")
        r4 = run_guard(bad)
        check("unknown pin blocked", r4.returncode == 78, r4.stderr)
        check("unknown pin msg", "not present in" in r4.stderr, r4.stderr)

        # 6. Cache eviction rebuilds identical snapshot from the SAME sha.
        import shutil
        shutil.rmtree(child / "_cache" / "swbp-plane" / c1)
        r5 = run_guard(child)  # still pinned c2 now; force pin back first
        (child / ".template-version").write_text(f"repo=fake/plane\nref={c1}\n")
        r5 = run_guard(child)
        check("rebuild after evict rc", r5.returncode == 0, r5.stderr)
        check("rebuild same sha", f"SWBP_PLANE_SHA={c1}" in r5.stdout,
              r5.stdout)
        check("restamped", stamp.exists())

    print(f"{checks - len(failures)}/{checks} passed")
    for f in failures:
        print(f"FAIL {f}")
    return 1 if failures else 0


def test_plane_snapshot_authority_immutability_drift_and_resume():
    """Pytest entry (CI collects this module): runs every mechanism scenario
    in main(). Kept as one composite so the synthetic plane/child fixtures
    build once; individual failure names surface through main()'s report."""
    assert main() == 0


def _plane_ref(repo):
    """A commit that EXISTS in the blueprint plane repo.

    In the template repo `.template-version` is UNSTAMPED, so HEAD is itself a
    real blueprint commit. In an adopted child, HEAD is a CHILD commit absent
    from the plane; the valid plane ref is the one the child is pinned to (its
    stamped `.template-version`). Using HEAD unconditionally made this test
    blueprint-only — green in the template, red in every child that adopted it.
    """
    tv = repo / ".template-version"
    if tv.is_file():
        for line in tv.read_text().splitlines():
            if line.startswith("ref="):
                ref = line.split("=", 1)[1].strip()
                if ref and ref != "UNSTAMPED":
                    return ref
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_whole_entrypoint_dryrun_stops_at_reexec_boundary(tmp_path):
    """Invoke the real entrypoint, not an extracted guard.

    The child intentionally lacks every ordinary orchestrator prerequisite.
    A zero exit therefore proves the prelude defined the guard dependencies,
    the guard reached the dry-run re-exec boundary, and `exit 0` prevented the
    post-guard preflight from running. The state assertion also proves no
    later pipeline checkpoint was written.
    """
    pin = _plane_ref(REPO)
    child = tmp_path / "whole-entry-child"
    _install_copied_entrypoint(child)
    (child / ".template-version").write_text(
        f"repo=developer-learner/sw-dev-blueprint\nref={pin}\n"
    )
    _git(child, "init", "-q", "-b", "main")

    env = dict(os.environ)
    env.pop("SWBP_PLANE_SNAPSHOT", None)
    env["SWBP_PLANE_DRYRUN"] = "1"
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        ["bash", "scripts/orchestrate.sh", "--full-suite"],
        cwd=child,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    snapshot = tmp_path / "cache" / "swbp-plane" / pin
    expected = (
        f"DRYRUN exec: SWBP_PLANE_SNAPSHOT={snapshot} "
        f"SWBP_PLANE_SHA={pin} bash {snapshot}/scripts/orchestrate.sh "
        "--full-suite"
    )
    assert result.stdout.strip() == expected
    assert (child / ".pipeline-state" / "plane-sha").read_text().strip() == pin
    assert sorted(p.name for p in (child / ".pipeline-state").iterdir()) == [
        "plane-sha"
    ]
    assert "=== Pre-flight ===" not in result.stdout
    assert not (child / ".measurement" / "plane-drift.log").exists(), \
        "a child commit is not blueprint drift telemetry"


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


def test_whole_entrypoint_nondryrun_crosses_reexec_into_preflight(tmp_path):
    """The REAL (non-DRYRUN) re-exec must pass its OWN pre-flight.

    The DRYRUN test above stops at the boundary; this one crosses it. The plane
    re-exec points core.hooksPath at the snapshot's ABSOLUTE .githooks, so the
    pre-flight hooksPath check must accept that path. D-168 live-fire
    (2026-08-23): the re-exec failed its own next check because the gate only
    accepted the literal ".githooks", and no test caught it — every DRYRUN test
    exits before the re-exec. The bare child fails LATER (no frozen spec /
    manifest), but it must get PAST the hooksPath gate, reaching pre-flight and
    never dying with "core.hooksPath is not".
    """
    pin = _plane_ref(REPO)
    child = tmp_path / "nondryrun-child"
    _install_copied_entrypoint(child)
    (child / ".template-version").write_text(
        f"repo=developer-learner/sw-dev-blueprint\nref={pin}\n"
    )
    _git(child, "init", "-q", "-b", "main")
    _git(child, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init")
    _git(child, "config", "core.hooksPath", ".githooks")

    env = dict(os.environ)
    env.pop("SWBP_PLANE_SNAPSHOT", None)
    env.pop("SWBP_PLANE_DRYRUN", None)   # the REAL path, not the boundary preview
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        ["bash", "scripts/orchestrate.sh"],
        cwd=child, capture_output=True, text=True, env=env,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, "the bare child has no frozen spec; it must fail later"
    assert "=== Pre-flight ===" in combined, "the re-exec must reach pre-flight"
    assert "core.hooksPath is not" not in combined, \
        "the re-exec's hooksPath check must accept the snapshot's absolute .githooks"
    assert "not a git repository" not in combined, \
        "the run must operate on the CHILD tree (a git repo), not the snapshot dir"


if __name__ == "__main__":
    sys.exit(main())


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
    # hooks come from the pinned snapshot, via untracked config
    hp = subprocess.run(["git", "-C", str(app), "config", "core.hooksPath"],
                        capture_output=True, text=True).stdout.strip()
    assert hp == str(tmp_path / "cache" / "swbp-plane" / new / ".githooks")
    assert Path(hp, "pre-commit").is_file()


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
    assert hp(wt).endswith(f"swbp-plane/{new}/.githooks")
