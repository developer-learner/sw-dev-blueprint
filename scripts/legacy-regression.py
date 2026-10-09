#!/usr/bin/env python3
"""legacy-regression.py — existing-suite regression evidence (D-212).

An adopted project (D-165, e.g. rich-adoption) keeps its pre-existing test
suite as a hash-pinned snapshot, `legacy-pin.json` ({"files": {path: sha256},
optional "known_failing": [nodeid, ...]}), looked up at
scripts/.approved/legacy-pin.json, then at the project root. That suite is
NOT an oracle and never gates acceptance (D-165): it was written with the
implementation in view, so a green run proves little. A RED run is still
evidence — a previously passing test of existing behavior now fails — and a
milestone should not be able to break existing behavior silently.

    legacy-regression.py targets                 # pinned test files to run
    legacy-regression.py report --report R --pytest-rc N --spec V --out F

`targets` prints the pinned test files that still exist, one per line
(nothing, exit 0, when the project has no pin). `report` reads the pytest
json-report the shell produced in the sandbox and writes the record F:
counts, `regressions` (failing or erroring nodeids not in known_failing),
`changed_files` (pinned files whose bytes differ from the pin or are gone),
and `run_problem` when the suite could not run. It prints one summary line.
Report-only: it always exits 0 on a readable input; nothing reads its output
as a verdict. metrics-report.py counts the regressions into metrics.tsv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PIN_PATHS = (Path("scripts/.approved/legacy-pin.json"), Path("legacy-pin.json"))


def load_pin(root: Path) -> dict | None:
    for rel in PIN_PATHS:
        p = root / rel
        if p.is_file():
            data = json.loads(p.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
                raise SystemExit(f"legacy-regression: {rel} has no 'files' map")
            return data
    return None


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def targets(root: Path) -> list[str]:
    pin = load_pin(root)
    if pin is None:
        return []
    return sorted(p for p in pin["files"] if is_test_file(p) and (root / p).is_file())


CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def changed_files(root: Path, pin: dict) -> list[str]:
    """Pinned files whose bytes differ or are gone. Tool caches a snapshot
    may have swept in (rich's pin holds tests/.pytest_cache/) are not tests."""
    changed = []
    for rel, digest in sorted(pin["files"].items()):
        if CACHE_DIRS & set(rel.split("/")):
            continue
        p = root / rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            changed.append(rel)
    return changed


def build_record(root: Path, report: Path, pytest_rc: int, spec: str) -> dict:
    pin = load_pin(root)
    if pin is None:
        raise SystemExit("legacy-regression: no legacy pin in this project")
    known = set(pin.get("known_failing") or [])
    rec: dict = {"spec_version": spec, "pytest_rc": pytest_rc,
                 "passed": 0, "failed": 0, "skipped": 0, "errors": 0,
                 "regressions": [], "known_failing_seen": [],
                 "changed_files": changed_files(root, pin), "run_problem": ""}
    try:
        data = json.loads(report.read_text())
        tests = data["tests"]
    except (OSError, ValueError, KeyError, TypeError):
        rec["run_problem"] = f"no readable pytest report (pytest exit {pytest_rc})"
        return rec
    failing = set()
    for t in tests:
        outcome = t.get("outcome", "")
        if outcome in ("passed", "xfailed"):
            rec["passed"] += 1
        elif outcome == "skipped":
            rec["skipped"] += 1
        else:
            rec["errors" if outcome == "error" else "failed"] += 1
            failing.add(t.get("nodeid", "?"))
    for c in data.get("collectors") or []:
        if c.get("outcome") == "failed":
            rec["errors"] += 1
            failing.add(c.get("nodeid") or "?")
    rec["regressions"] = sorted(failing - known)
    rec["known_failing_seen"] = sorted(failing & known)
    if not tests and not failing:
        rec["run_problem"] = f"pytest collected no tests (exit {pytest_rc})"
    return rec


def summary(rec: dict) -> str:
    if rec["run_problem"]:
        head = f"Existing tests: NOT RUN — {rec['run_problem']}"
    elif rec["regressions"]:
        shown = ", ".join(rec["regressions"][:5])
        more = f" (+{len(rec['regressions']) - 5} more)" if len(rec["regressions"]) > 5 else ""
        head = (f"Existing tests: {len(rec['regressions'])} REGRESSION(S) — "
                f"{shown}{more}; {rec['passed']} passed, {rec['skipped']} skipped")
    else:
        head = (f"Existing tests: no regressions — {rec['passed']} passed, "
                f"{rec['skipped']} skipped, {len(rec['known_failing_seen'])} known failing")
    if rec["changed_files"]:
        head += f"; {len(rec['changed_files'])} pinned test file(s) changed since adoption"
    return head


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="existing-suite regression evidence (D-212)")
    ap.add_argument("--root", type=Path, default=Path.cwd())
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("targets")
    rp = sub.add_parser("report")
    rp.add_argument("--report", required=True, type=Path)
    rp.add_argument("--pytest-rc", type=int, default=0)
    rp.add_argument("--spec", required=True)
    rp.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "targets":
        for t in targets(a.root):
            print(t)
        return 0
    rec = build_record(a.root, a.report, a.pytest_rc, a.spec)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(rec, indent=2) + "\n")
    print(summary(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
