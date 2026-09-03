#!/usr/bin/env python3
"""D-74 diff-scoped coder-output lint.

Runs the SAME `ruff check` the D-74 gate has always run on the one `.py` file a
coder task wrote — same rule set, same config resolution (no `--select`, so a
child project's ruff config still governs) — but reports ONLY findings on lines
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
        # count == 0 is a pure deletion at this hunk: no new lines to lint.
        for row in range(start, start + count):
            rows.add(row)
    return rows


def _ruff_findings(file: str) -> list[dict]:
    """Run the D-74 ruff check as JSON. Raises RuntimeError on a tooling error."""
    proc = subprocess.run(
        ["ruff", "check", "--no-cache", "--output-format", "json", file],
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
    row = (finding.get("location") or {}).get("row")
    return isinstance(row, int) and row in rows


def _format(finding: dict) -> str:
    loc = finding.get("location") or {}
    return (
        f"{finding.get('filename', '?')}:{loc.get('row', '?')}:{loc.get('column', '?')}: "
        f"{finding.get('code', '?')} {finding.get('message', '')}"
    )


def filter_findings(findings: Iterable[dict], rows: set[int] | None) -> list[dict]:
    return [f for f in findings if _in_scope(f, rows)]


def main(argv: list[str]) -> int:
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
