#!/usr/bin/env python3
"""Gate tiering + cost accounting: the retirement instrument (D-170).

Retiring a gate on silence is forbidden — silence cannot distinguish a dead
gate from a dormant one. This tool combines the three signals that can:

  1. teeth-proving   — the gate's mutation status
                       (proven / partial / unproven / pending / n/a)
  2. catch ledger    — in-the-wild catches recorded by refreeze.sh
  3. cost accounting — per-gate wall time from gate-cost.py

It assigns each gate a tier and writes a report. The report is evidence for
human review, never a build gate: tiering exits 0 on a successful report and
1 only when an input cannot be trusted (fail-closed).

Tiers
-----
  T1  core        proven teeth (all or some mutants killed), or at
                  least one in-the-wild catch. Keep; always run.
  T2  standard    hard gate with unproven teeth and no catches yet.
                  Keep; dormant, not dead — awaiting evidence.
  T3  review      soft/advisory gate, unproven teeth, zero catches.
                  Flagged for human review. This is NOT a retirement
                  decision (D-170) — it names the gate to examine.
  n/a             tools, orchestrators, manual tools — not tiered.

Usage:
    gate-tiering.py [--inventory PATH] [--cost PATH] [--ledger PATH]
                    [--out PATH]

    --inventory   default scripts/gate-inventory.tsv
    --cost        cost TSV from gate-cost.py (optional; cost shown if given)
    --ledger      catch ledger (default .catch-ledger.json)
    --out         write the report here (default: stdout)
"""

import argparse
import importlib.util
import sys
from pathlib import Path

# catch-ledger.py has a hyphen: load it from its path, not via `import`.
_CL_PATH = Path(__file__).resolve().parent / "catch-ledger.py"
_spec = importlib.util.spec_from_file_location("catch_ledger", _CL_PATH)
catch_ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catch_ledger)

DEFAULT_INVENTORY = Path("scripts/gate-inventory.tsv")
DEFAULT_LEDGER = Path(".catch-ledger.json")

TIERED_KINDS = {"hard", "soft", "advisory"}


def read_inventory(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise SystemExit(f"gate-tiering: inventory not found: {path}")
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        if cells and cells[0] == "gate":
            continue
        cells += [""] * (5 - len(cells))
        rows.append(cells[:5])
    return rows


def read_cost(path: Path | None) -> dict[str, str]:
    """gate -> probe_ms string (empty if unknown)."""
    if path is None or not path.is_file():
        return {}
    cost = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        cells = line.split("\t")
        if cells and cells[0] == "gate":
            continue
        if len(cells) >= 3:
            cost[cells[0]] = cells[2]
    return cost


def assign_tier(kind: str, mutation_status: str, catches: int) -> str:
    if kind not in TIERED_KINDS:
        return "n/a"
    # "partial" (some mutants killed) still demonstrates real teeth —
    # the survivor is an oracle gap to close, not proof the gate is dead.
    proven = mutation_status in ("proven", "partial")
    if kind == "hard":
        if proven or catches > 0:
            return "T1"
        return "T2"
    # soft / advisory
    if catches > 0:
        return "T1"
    if proven:
        return "T2"
    return "T3"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--cost", type=Path, default=None)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    # Fail-closed: a corrupt ledger must not produce a misleading report.
    try:
        ledger = catch_ledger.load_ledger(args.ledger)
    except catch_ledger.LedgerError as exc:
        print(f"gate-tiering: {exc}", file=sys.stderr)
        return 1

    rows = read_inventory(args.inventory)
    cost = read_cost(args.cost)

    lines = [
        "# Gate tiering report (D-170)",
        "",
        "Tiers are review evidence, not a build gate. T3 names a gate for",
        "human examination; it is not a retirement decision — silence alone",
        "cannot distinguish dead from dormant.",
        "",
        "| gate | kind | teeth | catches | cost_ms | tier |",
        "|------|------|-------|---------|---------|------|",
    ]
    counts = {"T1": 0, "T2": 0, "T3": 0, "n/a": 0}
    for gate, script, kind, mut, _cmd in rows:
        catches = len(ledger["gates"].get(gate, []))
        tier = assign_tier(kind, mut, catches)
        counts[tier] += 1
        cost_ms = cost.get(gate, "")
        lines.append(
            f"| {gate} | {kind} | {mut} | {catches} | {cost_ms} | {tier} |"
        )

    lines += [
        "",
        f"Totals: T1={counts['T1']}  T2={counts['T2']}  "
        f"T3={counts['T3']}  n/a={counts['n/a']}",
        "",
    ]

    text = "\n".join(lines)
    if args.out:
        args.out.write_text(text + "\n")
        print(f"gate-tiering: wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
