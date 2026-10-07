#!/usr/bin/env python3
"""vm_land.py — land a VM run's commits into a host project (D-205).

The dev VM never writes host project files. A run works on its own clone in
the VM; when it is done, the host pulls back ONE git bundle holding only the
run's new commits and this script decides whether they may land.

    vm_land.py --repo HOST --bundle FILE --base SHA --branch BR --run RUN_ID

`--base` and `--branch` come from the HOST's own run record, never from the
VM. The bundle is untrusted input. Nothing in the host checkout changes until
every check below has passed:

  1. the bundle verifies against the host repo and carries exactly one ref;
  2. its commits are fetched into a quarantine ref (refs/swbp-vm/<run>) —
     objects only, no branch or working-tree change;
  3. the run's tip descends from the snapshot base, with no merge commits;
  4. no commit adds or changes a symlink or a submodule entry, a path with
     an empty, '.', '..' or '.git' component (any case), or a path the host's
     ignore rules exclude (a committed .env would otherwise land);
  5. the host branch still points at the snapshot base (no newer host
     commits), and no file the run touched has uncommitted host edits.

Only then does the branch move: a fast-forward merge when the host checkout
is on that branch, otherwise a compare-and-swap ref update that leaves the
working tree alone. The quarantine ref is always removed.

Exit: 0 landed (or nothing to land) · 1 rejected, host unchanged · 2 usage.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
SHA = re.compile(r"[0-9a-f]{40}")
FORBIDDEN_MODES = {"120000": "symlink", "160000": "submodule"}
MAX_BUNDLE_BYTES = 512 * 1024 * 1024


class Rejected(Exception):
    pass


def git(repo: Path, *args: str, input: bytes | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], input=input,
                          capture_output=True, check=check)


def out(repo: Path, *args: str) -> str:
    return git(repo, *args).stdout.decode().strip()


def path_problem(path: str) -> str | None:
    """Why a committed path may not land, or None."""
    if not path or path.startswith("/") or "\\" in path:
        return "not a plain relative path"
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return "empty, '.' or '..' component"
        if part.lower() == ".git":
            return "'.git' component"
    return None


def changed_entries(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(new_mode, path) for every entry the commit adds or modifies."""
    raw = git(repo, "diff-tree", "-r", "--no-commit-id", "--raw", "-z",
              "--root", commit).stdout.decode("utf-8", "surrogateescape")
    fields = raw.split("\0")
    entries = []
    i = 0
    while i < len(fields) - 1:
        meta, path = fields[i], fields[i + 1]
        i += 2
        if not meta.startswith(":"):
            raise Rejected(f"unparseable diff-tree output for {commit[:12]}")
        _old_mode, new_mode, _old, _new, status = meta[1:].split(" ")
        if status.startswith("D"):
            continue
        entries.append((new_mode, path))
    return entries


def ignored(repo: Path, paths: list[str]) -> list[str]:
    if not paths:
        return []
    r = git(repo, "check-ignore", "--no-index", "-z", "--stdin",
            input="\0".join(paths).encode() + b"\0", check=False)
    if r.returncode not in (0, 1):
        raise Rejected("could not evaluate the host's ignore rules")
    return [p for p in r.stdout.decode().split("\0") if p]


def validate(repo: Path, base: str, tip: str) -> list[str]:
    if git(repo, "merge-base", "--is-ancestor", base, tip,
           check=False).returncode != 0:
        raise Rejected("the run's history does not extend the snapshot base")
    if out(repo, "rev-list", "--min-parents=2", f"{base}..{tip}"):
        raise Rejected("the run contains merge commits; land linear history only")
    touched: set[str] = set()
    for commit in out(repo, "rev-list", "--reverse", f"{base}..{tip}").split():
        for mode, path in changed_entries(repo, commit):
            if mode in FORBIDDEN_MODES:
                raise Rejected(f"{commit[:12]} adds a {FORBIDDEN_MODES[mode]}: {path}")
            problem = path_problem(path)
            if problem:
                raise Rejected(f"{commit[:12]} has an unsafe path ({problem}): {path!r}")
            touched.add(path)
    bad = ignored(repo, sorted(touched))
    if bad:
        raise Rejected(f"the run commits paths the host ignores: {bad}")
    deleted = out(repo, "diff", "--name-only", "--diff-filter=D", base, tip).split("\n")
    return sorted(touched | {p for p in deleted if p})


def land(repo: Path, bundle: Path, base: str, branch: str, run: str) -> str:
    if not bundle.is_file() or bundle.is_symlink():
        raise Rejected("bundle is not a regular file")
    if bundle.stat().st_size > MAX_BUNDLE_BYTES:
        raise Rejected("bundle exceeds 512 MiB")
    if git(repo, "bundle", "verify", "-q", str(bundle), check=False).returncode != 0:
        raise Rejected("bundle does not verify against the host repository")
    heads = out(repo, "bundle", "list-heads", str(bundle)).splitlines()
    if len(heads) != 1 or not heads[0].endswith(" refs/heads/swbp-run"):
        raise Rejected(f"bundle must carry exactly refs/heads/swbp-run, got {heads}")
    quarantine = f"refs/swbp-vm/{run}"
    git(repo, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
        str(bundle), f"+refs/heads/swbp-run:{quarantine}")
    try:
        tip = out(repo, "rev-parse", "--verify", quarantine)
        if tip == base:
            return "nothing to land"
        touched = validate(repo, base, tip)
        current = out(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
        if current != base:
            raise Rejected(f"host branch {branch} moved since the snapshot "
                           f"({base[:12]} -> {current[:12]}); start a new run")
        on_branch = git(repo, "symbolic-ref", "--quiet", "HEAD",
                        check=False).stdout.decode().strip() == f"refs/heads/{branch}"
        if on_branch:
            dirty = git(repo, "status", "--porcelain", "-z", "--untracked-files=all",
                        "--", *touched).stdout
            if dirty:
                names = [e[3:] for e in dirty.decode().split("\0") if len(e) > 3]
                raise Rejected(f"host has uncommitted edits to files the run changed: {names}")
            r = git(repo, "merge", "--ff-only", "--quiet", tip, check=False)
            if r.returncode != 0:
                raise Rejected("fast-forward refused: " + r.stderr.decode().strip())
        else:
            r = git(repo, "update-ref", "-m", f"swbp-vm land {run}",
                    f"refs/heads/{branch}", tip, base, check=False)
            if r.returncode != 0:
                raise Rejected("branch moved during landing; nothing changed")
        return f"landed {len(out(repo, 'rev-list', f'{base}..{tip}').split())} commit(s) on {branch} at {tip[:12]}"
    finally:
        git(repo, "update-ref", "-d", quarantine, check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="land a VM run's commits (D-205)")
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--bundle", required=True, type=Path)
    ap.add_argument("--base", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    if not SHA.fullmatch(a.base) or not RUN_ID.fullmatch(a.run) \
            or path_problem(a.branch) or a.branch.startswith("-"):
        print("vm-land: invalid --base, --run or --branch", file=sys.stderr)
        return 2
    try:
        print("vm-land: " + land(a.repo.resolve(), a.bundle, a.base, a.branch, a.run))
        return 0
    except Rejected as exc:
        print(f"vm-land: REJECTED — {exc}. Host checkout unchanged.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"vm-land: REJECTED — git failed: {exc.stderr.decode().strip()}. "
              "Host checkout unchanged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
