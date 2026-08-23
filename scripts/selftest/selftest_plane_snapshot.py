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

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORCHESTRATE = HERE.parent / "orchestrate.sh"
SANDBOX_RUN = HERE.parent / "sandbox-run.sh"
REPO = HERE.parents[1]


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
    (child / "scripts").mkdir(parents=True)
    (child / "scripts" / "orchestrate.sh").symlink_to(ORCHESTRATE)
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
    (child / "scripts").mkdir(parents=True)
    (child / "scripts" / "orchestrate.sh").symlink_to(ORCHESTRATE)
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
