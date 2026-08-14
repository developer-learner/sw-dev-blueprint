#!/usr/bin/env python3
"""
metrics-report — the metrics layer (D-126): per-milestone aggregate over the
data the pipeline already writes — read ONLY from artifacts that survive the
success teardown's `rm -rf .pipeline-state` (orchestrate.sh:1953). D-108's
lesson, applied: the row must be recomputable after the milestone, from what
outlives it.

Durable sources (all survive teardown):
  - .measurement/counters            per-run exit rows: rc, phase, task,
                                     spec, elapsed (Phase 5 instrumentation)
  - .measurement/timings-<TS>.tsv    per-run timings copies
  - .em-archive/*/meta.txt           EM call outcome + gate result (spec-tagged)
  - .pipeline-flakes.json            committed per-spec flake history (D-111)
  - git history                      milestone ref, date, feature version

Appends one TSV row per milestone to .measurement/metrics.tsv (idempotent: a
milestone+feature already recorded is skipped). With --evidence it prints the
same numbers WITHOUT writing anything — the measured-evidence block a D-115
retirement entry must cite. A report, never a gate: nothing in the completion
path reads the output, and a write can never fail a run (wired with `|| true`
in orchestrate.sh). Invoke from the project root (or pass --root).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

COLS = [
    "milestone", "date", "feature", "gate_hours", "selftest_count",
    "selftest_s", "em_calls", "em_waste", "flakes", "success_runs",
    "retry_runs",
]
METRICS_REL = Path(".measurement") / "metrics.tsv"
RE_FEATURE = re.compile(r"\[(?:success\] spec|refreeze) v(\d+)")
RE_RC = re.compile(r"rc=(\d+)")
RE_SPEC = re.compile(r"spec=(\d+)")
RE_ELAPSED = re.compile(r"elapsed=(\d+)s")


def sh(root: Path, *a: str) -> str:
    return subprocess.run(
        a, cwd=root, capture_output=True, text=True
    ).stdout.strip()


def resolve_milestone(
    root: Path, milestone: str, feature_override: str
) -> tuple[str, str, str]:
    """Return (short-ref, commit-date-iso, feature-version)."""
    short = sh(root, "git", "rev-parse", "--short", milestone)
    date = sh(root, "git", "log", "-1", "--format=%ad", "--date=short", milestone)
    subject = sh(root, "git", "log", "-1", "--format=%s", milestone)
    m = RE_FEATURE.search(subject)
    feature = feature_override or (m.group(1) if m else "")
    return short, date or "", feature


def counter_runs(path: Path, spec: int | None) -> list[dict[str, str]]:
    """Exit rows in .measurement/counters, filtered to one spec."""
    if not path.is_file():
        return []
    runs = []
    for line in path.read_text().splitlines():
        if "exit rc=" not in line:
            continue
        rc = RE_RC.search(line)
        elapsed = RE_ELAPSED.search(line)
        if not rc or not elapsed:
            continue
        m_spec = RE_SPEC.search(line)
        if spec is not None and (not m_spec or int(m_spec.group(1)) != spec):
            continue
        runs.append({"rc": rc.group(1), "elapsed": elapsed.group(1)})
    return runs


def newest_timings_copy(meas_dir: Path) -> Path | None:
    """The most recent .measurement/timings-<TS>.tsv, by timestamp sort."""
    if not meas_dir.is_dir():
        return None
    copies = sorted(meas_dir.glob("timings-*.tsv"))
    return copies[-1] if copies else None


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


def selftest_stats(path: Path | None) -> tuple[int, int]:
    """(selftest_count, selftest_s) from the newest timings copy."""
    if path is None:
        return 0, 0
    count = 0
    seconds = 0
    prev = 0
    for elapsed, label in read_timings(path):
        dt = max(0, elapsed - prev)
        prev = elapsed
        if "tests" in label or "pytest" in label:
            count += 1
            seconds += dt
    return count, seconds


def em_outcomes(archive: Path, spec: int | None) -> tuple[int, int]:
    """(em_calls, em_waste) — EM calls whose meta tags this spec version."""
    if not archive.is_dir():
        return 0, 0
    calls = waste = 0
    for d in sorted(archive.iterdir()):
        if not d.is_dir():
            continue
        meta = d / "meta.txt"
        if not meta.is_file():
            continue
        entry_spec = None
        outcome = "ok"
        for line in meta.read_text().splitlines():
            if line.startswith("spec_version="):
                entry_spec = line.split("=", 1)[1].strip()
            elif line.startswith("plan_gate="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("verdict="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("outcome=") and outcome == "ok":
                outcome = line.split("=", 1)[1]
        if spec is not None and entry_spec != str(spec):
            continue
        calls += 1
        if outcome not in ("ok", "accepted", "valid"):
            waste += 1
    return calls, waste


def flake_count(path: Path, feature: str) -> int:
    """Events with spec_version == feature across all nodes (D-111 ledger)."""
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


def compute(root: Path, milestone: str, feature_override: str) -> dict[str, str]:
    meas_dir = root / ".measurement"
    archive = root / ".em-archive"
    short, date, feature = resolve_milestone(root, milestone, feature_override)
    # The orchestrator's success path passes `--feature v$FROZEN_V` (with the
    # "v" prefix, e.g. v99) and RE_FEATURE captures the bare digits from the
    # subject — normalize to the integer form once so the spec filter, flake
    # count, and the v-prefixed row all agree. Before this, int("v99") raised
    # and the caller's `|| true` swallowed it: no .measurement/metrics.tsv row.
    feature = re.sub(r"^[vV]", "", feature.strip())
    spec = int(feature) if feature else None

    runs = counter_runs(meas_dir / "counters", spec)
    gate_hours = sum(int(r["elapsed"]) for r in runs) / 3600.0
    success = sum(1 for r in runs if r["rc"] == "0")
    retries = len(runs) - success

    selftest_count, selftest_s = selftest_stats(newest_timings_copy(meas_dir))
    em_calls, em_waste = em_outcomes(archive, spec)

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
        "--feature", default="",
        help="explicit spec version (e.g. v84); overrides subject parsing",
    )
    parser.add_argument(
        "--evidence", action="store_true",
        help="print the measured-evidence block without writing metrics.tsv",
    )
    args = parser.parse_args(argv)

    row = compute(args.root, args.milestone, args.feature)
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
