#!/usr/bin/env python3
"""check-app-guard.py — D-186 stage C: builder-only changes to an app's
protected surface.

A builder-targeted app (marked by `.swbp`) carries no plane and no tracked
hooks, so nothing inside it stops a hand edit to its tests, frozen spec, or
pipeline adaptations. This guard reads the app's history and reports every
commit that changed that surface without coming through the builder's
provenance broker (D-174 `Swbp-Role:` trailer):

  tests/, scripts/.approved/   -> only the freeze path: Swbp-Role: tpm
  pipeline adaptations         -> any broker commit (`swbp commit` for people)

D-192 (security plan item 5): merge commits are INSPECTED, not skipped —
a merge is the point where changes enter the branch, and its introduced
diff (against the first parent) can carry conflict-resolution edits that
live in no other commit. A merge's introduced paths are authorized by its
own broker role OR by any commit in a merged line that touched the path
with the required role (the change was brokered at its origin). And the
enforcement mode is a RATCHET: if the `--enforce` flag is set, the current
`.swbp` says `guard=enforce`, or ANY commit in the range had
`guard=enforce`, the whole range is checked in enforce mode — a hand
downgrade of the guard cannot demote the check that would catch it. Only
a brokered commit may lower the mode, and it stays in the trail.

Report-first (D-184 staging): prints findings and exits 0 unless --enforce,
or the app's `.swbp` says `guard=enforce` (or the ratchet above trips). The
protected list lives HERE, in the builder, so an app cannot edit its own
guard away. Signature checks join when the M2b provenance gate flips
(check-provenance.py), not before — until then the Swbp-Role trailer is
self-asserted, and the guard's enforcement claim is bounded by that.

Usage (cwd = app root):
  check-app-guard.py [--range A..B | --rev REV] [--enforce]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

FREEZE_ONLY = ("tests/", "scripts/.approved/")
ADAPTATIONS = frozenset({
    ".swbp",
    ".gate-paths",
    "opencode.json",
    "Containerfile",
    ".dockerignore",
    ".github/workflows/ci.yml",
    ".github/workflows/container-build.yml",
    ".github/workflows/swbp-guard.yml",
    "CLAUDE.md",
    "AGENTS.md",
    "CONVENTIONS.md",
})
ROLES = {"em", "coder", "tpm", "pipeline", "human"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def commits(spec: str) -> list[str]:
    # D-192: merges INCLUDED — a merge is the point where changes enter the
    # branch, and its introduced diff can carry edits that live in no other
    # commit (conflict resolutions). --no-merges was the hole.
    return git("rev-list", "--reverse", spec).split()


def introduced(sha: str) -> list[str]:
    """Paths this commit introduced: against its FIRST parent (full tree at
    root). For a merge that is what the merge brought into the mainline —
    including resolution edits absent from every parent. (The old
    `diff-tree --root` combined diff shows only files differing from ALL
    parents — a resolution edit to a file both sides touched would vanish.)
    """
    parents = git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    if not parents:
        return [p for p in git("diff-tree", "--no-commit-id", "--name-only",
                               "-r", "--root", sha).splitlines() if p]
    return [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r",
                           parents[0], sha).splitlines() if p]


def changed(sha: str) -> list[str]:
    return [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r",
                           "--root", sha).splitlines() if p]


def role(sha: str) -> str:
    out = git("log", "-1", "--format=%(trailers:key=Swbp-Role,valueonly)", sha)
    return out.strip().splitlines()[0].strip() if out.strip() else ""


def _line_authorizes(sha: str, paths: list[str], roles: set[str]) -> bool:
    """For a merge: True when every path in `paths` was touched by some
    commit in a merged line (reachable from a non-first parent, not from
    the first) with a role in `roles` — the change was brokered at its
    origin, and the merge merely carried it. Path-level granularity is the
    stated limit: a resolution edit to a file a brokered commit also
    touched inherits that commit's authority."""
    parents = git("rev-list", "--parents", "-n", "1", sha).split()[1:]
    if len(parents) < 2:
        return False
    for p in paths:
        ok = False
        for i in range(1, len(parents)):
            for c in git("rev-list", f"{parents[0]}..{parents[i]}").split():
                if p in changed(c) and role(c) in roles:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            return False
    return True


def findings_for(sha: str) -> list[str]:
    paths = introduced(sha)
    r = role(sha)
    out = []
    frozen = [p for p in paths if p.startswith(FREEZE_ONLY)]
    if frozen and r != "tpm" and not _line_authorizes(sha, frozen, {"tpm"}):
        out.append(f"{sha[:12]} changed frozen surface without the freeze path "
                   f"(Swbp-Role: {r or 'none'}, need tpm): {', '.join(frozen)}")
    adapted = [p for p in paths if p in ADAPTATIONS]
    if adapted and r not in ROLES and not _line_authorizes(sha, adapted, ROLES):
        out.append(f"{sha[:12]} changed pipeline adaptations outside the builder "
                   f"(no Swbp-Role; use `swbp commit`): {', '.join(adapted)}")
    return out


def _pin_enforces() -> bool:
    pin = Path(".swbp")
    return pin.is_file() and any(
        line.strip() == "guard=enforce" for line in pin.read_text().splitlines())


def enforced(flag: bool, spec: str) -> bool:
    """D-192 ratchet: enforce when the flag says so, the CURRENT .swbp says
    so, the state in force at the range's start says so, or ANY commit in
    the range had guard=enforce (checked via the commits that touched
    .swbp). Once a range was enforced, a hand downgrade inside it cannot
    demote the check that would catch it; only a brokered commit may lower
    the mode, and it stays in the trail."""
    if flag or _pin_enforces():
        return True
    for boundary in _boundaries(spec):
        if _pin_at(boundary):
            return True
    for sha in git("log", "--format=%H", spec, "--", ".swbp").split():
        if _pin_at(sha):
            return True
    return False


def _boundaries(spec: str) -> list[str]:
    """The commit whose tree is the state in force just before `spec`: for
    `A..B` that is A (its pin counts even though A is outside the range);
    for a bare rev (reachable history) there is no before."""
    if spec.count("..") == 1:
        left = spec.split("..", 1)[0]
        if left:
            return [left]
    return []


def _pin_at(sha: str) -> bool:
    out = subprocess.run(["git", "show", f"{sha}:.swbp"], capture_output=True,
                         text=True)
    return (out.returncode == 0
            and any(line.strip() == "guard=enforce"
                    for line in out.stdout.splitlines()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--range", help="A..B commit range")
    g.add_argument("--rev", help="check every commit reachable from REV")
    ap.add_argument("--enforce", action="store_true")
    a = ap.parse_args()
    spec = a.range or a.rev or "HEAD"
    shas = commits(spec)
    found = [f for sha in shas for f in findings_for(sha)]
    mode = "enforce" if enforced(a.enforce, spec) else "report"
    for f in found:
        print(f"swbp-guard: {f}")
    print(f"swbp-guard: {len(found)} finding(s) over {spec} [{mode}]")
    return 1 if found and mode == "enforce" else 0


if __name__ == "__main__":
    sys.exit(main())
