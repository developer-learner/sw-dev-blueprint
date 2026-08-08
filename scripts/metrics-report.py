#!/usr/bin/env python3
"""
metrics-report — the metrics layer (D-126): per-milestone aggregate over the
data the pipeline already writes.

Reads:
  - .pipeline-state/logs/timings.tsv      per-phase wall clock
  - .pipeline-state/logs/run-exit.log     run outcomes (exit 0 = success)
  - .em-archive/*/meta.txt                EM call outcome + gate result
  - .pipeline-flakes.json                 idempotent per-spec flake history (D-111)

Appends one TSV row per milestone to .pipeline-state/logs/metrics.tsv
(idempotent: a milestone+feature already recorded is skipped). With
--evidence it prints the same numbers WITHOUT writing anything — the
measured-evidence block a D-115 retirement entry must cite.

A report, never a gate: nothing in the completion path reads this file.
State dirs are gitignored, so the metrics file has no manifest impact.
Invoke from the project root (or pass --root).

The milestone boundary mirrors feature-summary's: the last `[refreeze vN]`
commit at-or-before the milestone ref. On an empty substrate everything
counts zero and the row still records — a milestone with no data is itself
measured.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

COLS = [
    "milestone", "date", "feature", "gate_hours", "selftest_count",
    "selftest_s", "em_calls", "em_waste", "flakes", "success_runs",
    "retry_runs",
]
METRICS_REL = Path(".pipeline-state") / "logs" / "metrics.tsv"
RE_REFREEZE_EPOCH = re.compile(r"^\[refreeze v(\d+)\]")
RE_FEATURE = re.compile(r"\[(?:success\] spec|refreeze) v(\d+)")


def sh(root: Path, *a: str) -> str:
    return subprocess.run(
        a, cwd=root, capture_output=True, text=True
    ).stdout.strip()


def refreeze_epoch(root: Path, milestone: str) -> int:
    """Unix epoch of the last [refreeze vN] commit at-or-before milestone."""
    out = sh(
        root, "git", "log", milestone, "--grep=^\\[refreeze v", "-1",
        "--format=%at",
    )
    return int(out) if out else 0


def resolve_milestone(root: Path, milestone: str) -> tuple[str, str, str]:
    """Return (short-ref, commit-date-iso, feature-version)."""
    short = sh(root, "git", "rev-parse", "--short", milestone)
    date = sh(root, "git", "log", "-1", "--format=%ad", "--date=short", milestone)
    subject = sh(root, "git", "log", "-1", "--format=%s", milestone)
    m = RE_FEATURE.search(subject)
    return short, date or "", m.group(1) if m else ""


def read_timings(path: Path) -> list[tuple[int, str]]:
    """Return [(elapsed_seconds, label)] for THIS run only (last run start)."""
    if not path.is_file():
        return []
    rows: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        hms, elapsed, label = parts
        if label.startswith("run start"):
            rows = []
        try:
            rows.append((int(elapsed.rstrip("s")), label))
        except ValueError:
            pass
    return rows


def em_outcomes(archive: Path, since_epoch: int) -> tuple[int, int]:
    """(em_calls, em_waste) — archived EM calls at-or-after the boundary."""
    if not archive.is_dir():
        return 0, 0
    calls = waste = 0
    for d in sorted(archive.iterdir()):
        if not d.is_dir() or d.stat().st_mtime < since_epoch:
            continue
        meta = d / "meta.txt"
        if not meta.is_file():
            continue
        calls += 1
        outcome = "ok"
        for line in meta.read_text().splitlines():
            if line.startswith("plan_gate="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("verdict="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("outcome=") and outcome == "ok":
                outcome = line.split("=", 1)[1]
        if outcome not in ("ok", "accepted", "valid"):
            waste += 1
    return calls, waste


def flake_count(path: Path, feature: str) -> int:
    """Events with spec_version == feature across all nodes (D-111 ledger).

    This is a milestone-wide query the per-nodeid ledger CLI does not offer,
    so the file is read directly with the same schema expectations. A
    malformed or absent ledger counts zero; an unparseable feature counts
    zero (the evidence block says so).
    """
    if not feature or not path.is_file():
        return 0
    try:
        ledger = json.loads(path.read_text())
        nodes = ledger.get("nodes")
        if not isinstance(nodes, dict):
            return 0
        target = int(feature)
    except (ValueError, OSError, json.JSONDecodeError):
        return 0
    count = 0
    for events in nodes.values():
        if not isinstance(events, list):
            continue
        count += sum(
            1 for e in events
            if isinstance(e, dict) and e.get("spec_version") == target
        )
    return count


def run_outcomes(path: Path, since_epoch: int) -> tuple[int, int]:
    """(success_runs, retry_runs) from run-exit.log rows at-or-after boundary."""
    if not path.is_file():
        return 0, 0
    success = retries = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        try:
            ts = datetime.fromisoformat(parts[0].replace("Z", "+00:00")).timestamp()
        except (ValueError, IndexError):
            continue
        if ts < since_epoch:
            continue
        m = re.search(r"exit=(\d+)", line)
        if m and int(m.group(1)) == 0:
            success += 1
        elif m:
            retries += 1
    return success, retries


def compute(root: Path, milestone: str) -> dict[str, str]:
    state = root / ".pipeline-state"
    archive = root / ".em-archive"
    since = refreeze_epoch(root, milestone)
    short, date, feature = resolve_milestone(root, milestone)

    timings = read_timings(state / "logs" / "timings.tsv")
    gate_hours = 0.0
    selftest_count = 0
    selftest_s = 0
    prev = 0
    for elapsed, label in timings:
        dt = max(0, elapsed - prev)
        prev = elapsed
        gate_hours = elapsed / 3600.0
        if "tests" in label or "pytest" in label:
            selftest_count += 1
            selftest_s += dt
    em_calls, em_waste = em_outcomes(archive, since)
    success, retries = run_outcomes(
        state / "logs" / "run-exit.log", since
    )

    return {
        "milestone": short,
        "date": date,
        "feature": f"v{feature}" if feature else "",
        "gate_hours": f"{gate_hours:.2f}",
        "selftest_count": str(selftest_count),
        "selftest_s": str(selftest_s),
        "em_calls": str(em_calls),
        "em_waste": str(em_waste),
        "flakes": str(flake_count(root / ".pipeline-flakes.json", feature)),
        "success_runs": str(success),
        "retry_runs": str(retries),
    }


def evidence_block(row: dict[str, str]) -> str:
    return (
        f"metrics evidence — milestone {row['milestone']}, feature "
        f"{row['feature'] or '(none)'}, {row['date'] or '(no date)'}\n"
        f"  gate_hours={row['gate_hours']}  "
        f"selftest_count={row['selftest_count']}  "
        f"selftest_s={row['selftest_s']}\n"
        f"  em_calls={row['em_calls']}  em_waste={row['em_waste']}  "
        f"flakes={row['flakes']}\n"
        f"  success_runs={row['success_runs']}  "
        f"retry_runs={row['retry_runs']}\n"
    )


def append_row(path: Path, row: dict[str, str]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        for line in path.read_text().splitlines():
            fields = line.split("\t")
            if len(fields) == len(COLS) and fields[0] == row["milestone"] \
                    and fields[2] == row["feature"]:
                return False
        lines = path.read_text().splitlines()
    else:
        lines = []
    if not lines:
        lines = ["\t".join(COLS)]
    lines.append("\t".join(row[c] for c in COLS))
    path.write_text("\n".join(lines) + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--milestone", default="HEAD",
        help="git ref of the milestone to measure (default HEAD)",
    )
    parser.add_argument(
        "--evidence", action="store_true",
        help="print the measured-evidence block without writing metrics.tsv",
    )
    args = parser.parse_args(argv)

    row = compute(args.root, args.milestone)
    if args.evidence:
        print(evidence_block(row))
        return 0

    out = args.root / METRICS_REL
    if append_row(out, row):
        print(f"metrics.tsv: recorded {row['milestone']} "
              f"(feature {row['feature'] or '(none)'})")
    else:
        print(f"metrics.tsv: milestone {row['milestone']} feature "
              f"{row['feature'] or '(none)'} already recorded — skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
