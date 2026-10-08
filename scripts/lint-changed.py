#!/usr/bin/env python3
"""D-74 diff-scoped coder-output lint.

Runs the SAME `ruff check` the D-74 gate has always run on the one `.py` file a
coder task wrote — same rule set, same config resolution (a child project's ruff config
still governs; without one, the pinned core set — D-208) — but reports ONLY findings on lines
this task actually changed relative to a baseline ref. Pre-existing ("legacy")
findings on lines the coder did not touch are grandfathered, so an unrelated
lint debt in an edited file no longer burns a coder strike (the failure mode the
whole-file gate had: a correct anchored edit rejected for a violation elsewhere
in the file that the coder was never briefed to touch and, under D-59, could not
touch).

Scope is line-based, computed from `git diff <baseline_ref> -- <file>`:
  * the `+` (added/modified) line ranges in the NEW-file coordinate space, which
    is exactly the space ruff reports findings in, so the two align directly;
  * a NEW file (absent at baseline) diffs as entirely added, so the whole file is
    in scope — a created file is 100% the coder's work;
  * an empty / "NONE" baseline, or any failure to compute the diff, falls back to
    WHOLE-FILE scope. The fail-safe direction is stricter (over-report), never
    weaker: a gate that silently narrows to nothing is not a gate (Rule 6).

Syntax errors (ruff `E999`) are ALWAYS reported regardless of line scope: a file
that does not parse cannot run and its tests cannot even collect, so the
location ruff attributes the error to must never gate it out.

Usage:
    lint-changed.py <file> <baseline_ref>

Exit codes (consumed by orchestrate.sh's D-74 gate):
    0  no in-scope findings — the file's changed lines are clean
    1  one or more in-scope findings — a task failure; the findings print to
       stdout in ruff's `path:row:col: CODE message` form as retry evidence
    2  a real ruff/tooling error (ruff exited != {0,1}, or was unparseable) —
       the caller dies, preserving D-74's fail-closed-on-broken-tooling contract
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
import sys
from typing import Iterable

# `@@ -old(,oldcount)? +new(,newcount)? @@` — we want the NEW side only.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# Codes that gate regardless of which line ruff blames them on: syntax errors
# (a file that does not parse cannot run or collect tests — `E999` on older ruff,
# `invalid-syntax` on ruff >= 0.9) and I/O errors (`E902` — ruff could not read
# the file at all; failing closed beats a scope-filtered silent pass).
_ALWAYS_REPORT = {"E999", "invalid-syntax", "E902"}


def _changed_rows(file: str, baseline_ref: str) -> set[int] | None:
    """New-file line numbers changed since baseline_ref, or None for whole-file.

    None is the explicit "no reliable diff — lint everything" signal; an empty
    set is the distinct "diff succeeded and nothing changed" signal.
    """
    if not baseline_ref or baseline_ref == "NONE":
        return None
    try:
        proc = subprocess.run(
            ["git", "diff", "--unified=0", "--no-color", baseline_ref, "--", file],
            capture_output=True,
            text=True,
        )
    except OSError as exc:  # git missing / not a repo — fail strict.
        print(f"lint-changed: git diff failed ({exc}); linting whole file", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"lint-changed: git diff exited {proc.returncode} for {file} vs "
            f"{baseline_ref}; linting whole file",
            file=sys.stderr,
        )
        return None
    rows: set[int] = set()
    for line in proc.stdout.splitlines():
        m = _HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        if count == 0:
            # A pure deletion adds no new lines, but it CAN create a finding
            # at the seam (e.g. an import block re-sorted or a blank line
            # removed -> I001). Mark the rows either side of the deletion
            # point as touched; git reports `start` as the line before it.
            rows.update(r for r in (start, start + 1) if r > 0)
            continue
        for row in range(start, start + count):
            rows.add(row)
    return rows


# D-208: the canonical core rule set (D-106). Used ONLY when the project has
# no ruff config of its own — otherwise ruff's built-in defaults decide, and
# those moved from 59 rules (ruff 0.15) to 413 (ruff 0.16): the same file
# passed the gate on one machine and failed it on another.
CORE_RULES = ["--isolated", "--select", "E4,E7,E9,F"]


def rule_args(root: Path = Path(".")) -> list[str]:
    """[] when the project has its own ruff config (it governs), else the
    pinned core rule set. Shared by refreeze.sh's staged-test lint (D-67)."""
    if (root / "ruff.toml").is_file() or (root / ".ruff.toml").is_file():
        return []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and any(
            line.strip().startswith("[tool.ruff")
            for line in pyproject.read_text().splitlines()):
        return []
    return list(CORE_RULES)


def _ruff_findings(file: str) -> list[dict]:
    """Run the D-74 ruff check as JSON. Raises RuntimeError on a tooling error."""
    proc = subprocess.run(
        ["ruff", "check", "--no-cache", *rule_args(), "--output-format", "json", file],
        capture_output=True,
        text=True,
    )
    # ruff: 0 = clean, 1 = violations present, anything else = real error.
    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"ruff exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:400]}"
        )
    if not proc.stdout.strip():
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ruff JSON unparseable: {exc}") from None


def _in_scope(finding: dict, rows: set[int] | None) -> bool:
    if finding.get("code") in _ALWAYS_REPORT:
        return True
    if rows is None:  # whole-file scope
        return True
    # A finding is in scope when ANY row of its reported range was changed,
    # not only its first row: block-level rules such as I001 (import order)
    # anchor at the first line of the block, while the coder's change sits
    # lower inside it — start-row-only scoping silently dropped exactly those
    # (vortex v38/v43: an added import passed D-74 and failed CI's ruff).
    start = (finding.get("location") or {}).get("row")
    if not isinstance(start, int):
        return False
    end = (finding.get("end_location") or {}).get("row")
    if not isinstance(end, int) or end < start:
        end = start
    return any(r in rows for r in range(start, end + 1))


def _format(finding: dict) -> str:
    loc = finding.get("location") or {}
    return (
        f"{finding.get('filename', '?')}:{loc.get('row', '?')}:{loc.get('column', '?')}: "
        f"{finding.get('code', '?')} {finding.get('message', '')}"
    )


def filter_findings(findings: Iterable[dict], rows: set[int] | None) -> list[dict]:
    return [f for f in findings if _in_scope(f, rows)]


def main(argv: list[str]) -> int:
    if argv[1:] == ["--rule-args"]:
        print(" ".join(rule_args()))
        return 0
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: lint-changed.py <file> <baseline_ref>", file=sys.stderr)
        return 2
    file, baseline_ref = argv[1], argv[2]
    try:
        findings = _ruff_findings(file)
    except RuntimeError as exc:
        print(f"lint-changed: {exc}", file=sys.stderr)
        return 2
    rows = _changed_rows(file, baseline_ref)
    in_scope = filter_findings(findings, rows)
    for finding in in_scope:
        print(_format(finding))
    return 1 if in_scope else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
