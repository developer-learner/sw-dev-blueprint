#!/usr/bin/env python3
"""
feature-summary — a per-milestone digest of what the pipeline actually did.

Reads what orchestrate.sh, refreeze.sh, and the shell already write:
  - .pipeline-state/logs/timings.tsv         (per-phase wall clock)
  - .em-archive/*/meta.txt                    (EM call outcome + gate result)
  - .pipeline-state/escalations/*/BATCH.md    (TPM shuttles)
  - .pipeline-state/tasks/T*.status           (final task disposition)
  - git log                                   (refreezes = human approvals)

No new files are written by the pipeline itself; this script only reads.
Invoke from the child project root; scope defaults to "since the last refreeze
commit", which is the natural feature boundary.

Print a small text digest to stdout. Never modifies anything.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def sh(*a: str) -> str:
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


def since_last_refreeze() -> tuple[str, int]:
    """Return (spec-version-string, unix-epoch-of-refreeze). '' + 0 if none."""
    line = sh("git", "log", "--grep=^\\[refreeze v", "-1", "--format=%at %s")
    if not line:
        return "", 0
    epoch, _, subject = line.partition(" ")
    m = re.search(r"\[refreeze v(\d+)\]", subject)
    return (m.group(1) if m else ""), int(epoch or 0)


def read_timings(path: Path, since_epoch: int) -> list[tuple[str, int, str]]:
    """Return [(HH:MM:SS, elapsed_seconds_at_row, label)] for THIS run only."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        hms, elapsed, label = parts
        # keep only rows since the last "run start" (this run's boundary)
        if label.startswith("run start"):
            rows = []
        try:
            rows.append((hms, int(elapsed.rstrip("s")), label))
        except ValueError:
            pass
    return rows


def bucket_timings(rows: list[tuple[str, int, str]]) -> dict[str, int]:
    """Attribute elapsed deltas between rows to a coarse bucket."""
    buckets = Counter()
    if not rows:
        return dict(buckets)
    prev_elapsed = 0
    prev_label = "start"
    for _, elapsed, label in rows:
        dt = max(0, elapsed - prev_elapsed)
        if "em-call" in prev_label and "plan" in prev_label:
            buckets["planning"] += dt
        elif "em-call" in prev_label and "diagnosis" in prev_label:
            buckets["diagnosis"] += dt
        elif "coder" in prev_label:
            buckets["coding"] += dt
        elif "tests" in prev_label:
            buckets["tests"] += dt
        elif "pre-flight" in prev_label:
            buckets["preflight"] += dt
        else:
            buckets["other"] += dt
        prev_elapsed = elapsed
        prev_label = label
    return dict(buckets)


def em_calls(archive: Path, since_epoch: int) -> Counter:
    """Count EM calls in this feature by kind and outcome."""
    c = Counter()
    if not archive.is_dir():
        return c
    for d in sorted(archive.iterdir()):
        if not d.is_dir() or d.stat().st_mtime < since_epoch:
            continue
        kind = d.name.rsplit("_", 1)[-1]
        meta = (d / "meta.txt")
        outcome = "ok"
        if meta.is_file():
            for line in meta.read_text().splitlines():
                if line.startswith("plan_gate="):
                    outcome = line.split("=", 1)[1]
                elif line.startswith("verdict="):
                    outcome = line.split("=", 1)[1]
                elif line.startswith("outcome=") and outcome == "ok":
                    outcome = line.split("=", 1)[1]
        c[f"{kind}:{outcome}"] += 1
    return c


def task_states(state_dir: Path) -> Counter:
    c = Counter()
    if not (state_dir / "tasks").is_dir():
        return c
    for f in (state_dir / "tasks").glob("T*.status"):
        c[f.read_text().strip() or "pending"] += 1
    return c


def escalations(state_dir: Path) -> list[str]:
    esc = state_dir / "escalations"
    if not esc.is_dir():
        return []
    out = []
    for d in sorted(esc.iterdir()):
        b = d / "BATCH.md"
        if b.is_file():
            first = next((ln for ln in b.read_text().splitlines() if ln.strip()), "")
            out.append(f"{d.name}: {first[:80]}")
    return out


def commits_since(since_epoch: int) -> list[str]:
    if not since_epoch:
        return []
    out = sh("git", "log", f"--since=@{since_epoch}", "--reverse", "--format=%h %s")
    return [ln for ln in out.splitlines() if ln]


def main() -> int:
    state = Path(".pipeline-state")
    archive = Path(".em-archive")
    timings_path = state / "logs" / "timings.tsv"

    spec, since_epoch = since_last_refreeze()
    since_iso = datetime.fromtimestamp(since_epoch, timezone.utc).isoformat() if since_epoch else "(none)"

    rows = read_timings(timings_path, since_epoch)
    buckets = bucket_timings(rows)
    ems = em_calls(archive, since_epoch)
    tasks = task_states(state)
    escs = escalations(state)
    commits = commits_since(since_epoch)

    total = rows[-1][1] if rows else 0
    productive = buckets.get("coding", 0) + buckets.get("tests", 0)
    overhead = total - productive

    print(f"feature: v{spec or '?'}  (since refreeze @ {since_iso})")
    print(f"wall clock: {total}s  productive: {productive}s  overhead: {overhead}s")
    print()
    print("time by bucket:")
    for k in ("preflight", "planning", "coding", "tests", "diagnosis", "other"):
        v = buckets.get(k, 0)
        if v:
            print(f"  {k:10s} {v:5d}s  ({100*v/max(total,1):4.1f}%)")
    print()
    if ems:
        print("EM calls (kind:outcome):")
        for k, v in sorted(ems.items()):
            print(f"  {k:40s} x{v}")
    print()
    print(f"tasks: {dict(tasks)}")
    if escs:
        print("escalations:")
        for e in escs:
            print(f"  {e}")
    print(f"commits in feature: {len(commits)}")
    for c in commits:
        print(f"  {c}")
    print()
    print("human touches (proxy): refreeze commits since last summary + escalations")
    refreezes = sum(1 for c in commits if "[refreeze v" in c)
    print(f"  refreezes: {refreezes}   escalations: {len(escs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
