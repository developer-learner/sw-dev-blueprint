#!/usr/bin/env python3
"""Per-gate wall-time probe: measure how much each gate costs to run.

Reads the gate inventory (scripts/gate-inventory.tsv) and, for every row
carrying a probe command, runs that command a fixed number of times against
the current repo and records the median wall time. The cost table is the
input tiering + cost accounting reads: a gate that eats most of the pipeline
clock is a candidate for a cheaper tier, all else equal.

Probe commands must be read-only and safe to run against the live repo.
Gates with no probe command (fixture-only, side-effecting, or manual) are
reported as not-probed rather than guessed at.

Usage:
    gate-cost.py [--inventory PATH] [--runs N] [--out PATH]

    --inventory   default scripts/gate-inventory.tsv
    --runs        probe repetitions per gate (default 3); median is kept
    --out         write the cost TSV here (default: stdout)
"""

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_INVENTORY = Path("scripts/gate-inventory.tsv")


def read_inventory(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise SystemExit(f"gate-cost: inventory not found: {path}")
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        if cells and cells[0] == "gate":
            continue  # header
        # pad to 5 columns
        cells += [""] * (5 - len(cells))
        rows.append(cells[:5])
    return rows


def probe(cmd: str, runs: int, root: Path) -> tuple[float, bool]:
    """Run cmd `runs` times; return (median_ms, ok). ok=False if any run
    exited non-zero (a probe must be green to be a valid cost sample)."""
    samples = []
    ok = True
    for _ in range(runs):
        t0 = time.monotonic()
        proc = subprocess.run(
            cmd, shell=True, cwd=root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        dt = (time.monotonic() - t0) * 1000.0
        if proc.returncode != 0:
            ok = False
        samples.append(dt)
    return (statistics.median(samples), ok)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.runs < 1:
        ap.error("--runs must be >= 1")

    root = Path.cwd()
    rows = read_inventory(args.inventory)

    out_lines = ["gate\tscript\tprobe_ms\truns\tprobe_ok"]
    for gate, script, kind, mut, cmd in rows:
        if not cmd:
            out_lines.append(f"{gate}\t{script}\t\t{args.runs}\tnot-probed")
            continue
        median_ms, ok = probe(cmd, args.runs, root)
        status = "ok" if ok else "fail"
        out_lines.append(
            f"{gate}\t{script}\t{median_ms:.0f}\t{args.runs}\t{status}"
        )

    text = "\n".join(out_lines) + "\n"
    if args.out:
        args.out.write_text(text)
        print(f"gate-cost: wrote {args.out} ({len(rows)} gates)", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
