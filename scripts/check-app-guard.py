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

Report-first (D-184 staging): prints findings and exits 0 unless --enforce,
or the app's `.swbp` says `guard=enforce`. The protected list lives HERE, in
the builder, so an app cannot edit its own guard away. Signature checks join
when the M2b provenance gate flips (check-provenance.py), not before.

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
    return git("rev-list", "--no-merges", "--reverse", spec).split()


def changed(sha: str) -> list[str]:
    return [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r",
                           "--root", sha).splitlines() if p]


def role(sha: str) -> str:
    out = git("log", "-1", "--format=%(trailers:key=Swbp-Role,valueonly)", sha)
    return out.strip().splitlines()[0].strip() if out.strip() else ""


def findings_for(sha: str) -> list[str]:
    paths = changed(sha)
    r = role(sha)
    out = []
    frozen = [p for p in paths if p.startswith(FREEZE_ONLY)]
    if frozen and r != "tpm":
        out.append(f"{sha[:12]} changed frozen surface without the freeze path "
                   f"(Swbp-Role: {r or 'none'}, need tpm): {', '.join(frozen)}")
    adapted = [p for p in paths if p in ADAPTATIONS]
    if adapted and r not in ROLES:
        out.append(f"{sha[:12]} changed pipeline adaptations outside the builder "
                   f"(no Swbp-Role; use `swbp commit`): {', '.join(adapted)}")
    return out


def enforced(flag: bool) -> bool:
    if flag:
        return True
    pin = Path(".swbp")
    return pin.is_file() and any(
        line.strip() == "guard=enforce" for line in pin.read_text().splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--range", help="A..B commit range")
    g.add_argument("--rev", help="check every commit reachable from REV")
    ap.add_argument("--enforce", action="store_true")
    a = ap.parse_args()
    spec = a.range or a.rev or "HEAD"
    found = [f for sha in commits(spec) for f in findings_for(sha)]
    mode = "enforce" if enforced(a.enforce) else "report"
    for f in found:
        print(f"swbp-guard: {f}")
    print(f"swbp-guard: {len(found)} finding(s) over {spec} [{mode}]")
    return 1 if found and mode == "enforce" else 0


if __name__ == "__main__":
    sys.exit(main())
