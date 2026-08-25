#!/usr/bin/env python3
"""Track in-the-wild gate catches: a gate that rejected a real delta is
evidence of utility (D-170).

The ledger is the witness that tiering + cost accounting reads — the
retirement instrument that replaces retire-on-silence, because silence
alone cannot distinguish a dead gate from a dormant one.

A "catch" is recorded by the live path (refreeze.sh) when a hard gate
rejects a staged delta. Selftest fixture failures are teeth-proving, not
catches: they invoke the gate scripts directly and never run through
refreeze.sh, so they never reach this ledger. The two measurements stay
separate on purpose.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULT_LEDGER = Path(".catch-ledger.json")
SCHEMA_VERSION = 1
MAX_EVENTS_PER_GATE = 50


class LedgerError(ValueError):
    """The catch ledger cannot be trusted or updated safely."""


def empty_ledger():
    return {"schema_version": SCHEMA_VERSION, "gates": {}}


def validate_gate(gate):
    if not isinstance(gate, str) or not gate.strip():
        raise LedgerError("gate must be a non-empty string")
    if any(char in gate for char in ("\n", "\r", "\t")):
        raise LedgerError("gate contains a control character")


def load_ledger(path, missing_ok=True):
    if not path.exists():
        if missing_ok:
            return empty_ledger()
        raise LedgerError(f"ledger not found: {path}")
    try:
        ledger = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read ledger: {exc}") from exc
    if not isinstance(ledger, dict):
        raise LedgerError("ledger root is not an object")
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(
            f"unsupported ledger schema: {ledger.get('schema_version')!r}"
        )
    gates = ledger.get("gates")
    if not isinstance(gates, dict):
        raise LedgerError("ledger gates is not an object")
    for gate, events in gates.items():
        validate_gate(gate)
        if not isinstance(events, list):
            raise LedgerError(f"events for {gate} are not an array")
        seen = set()
        for event in events:
            if not isinstance(event, dict):
                raise LedgerError(f"event for {gate} is not an object")
            spec_version = event.get("spec_version")
            if (
                not isinstance(spec_version, int)
                or isinstance(spec_version, bool)
                or spec_version < 1
            ):
                raise LedgerError(f"invalid spec version for {gate}")
            if spec_version in seen:
                raise LedgerError(
                    f"duplicate spec v{spec_version} event for {gate}"
                )
            seen.add(spec_version)
    return ledger


def atomic_write(path, ledger):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            json.dump(ledger, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def record(args):
    validate_gate(args.gate)
    ledger = load_ledger(args.ledger)
    events = ledger["gates"].setdefault(args.gate, [])
    events[:] = [
        event for event in events
        if event["spec_version"] != args.spec_version
    ]
    events.append({"spec_version": args.spec_version})
    events.sort(key=lambda event: event["spec_version"])
    del events[:-MAX_EVENTS_PER_GATE]
    atomic_write(args.ledger, ledger)
    print(f"catch ledger: {args.gate} has {len(events)} catch(es)")


def count(args):
    validate_gate(args.gate)
    ledger = load_ledger(args.ledger)
    print(len(ledger["gates"].get(args.gate, [])))


def report(args):
    ledger = load_ledger(args.ledger)
    gates = ledger["gates"]
    if not gates:
        print("catch ledger: no catches recorded")
        return
    for gate in sorted(gates):
        events = gates[gate]
        latest = max(event["spec_version"] for event in events)
        print(f"{gate}\tcatches={len(events)}\tlatest_spec_v{latest}")


def parse_args(argv):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    count_parser = subparsers.add_parser("count")
    count_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    count_parser.add_argument("--gate", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    record_parser.add_argument("--gate", required=True)
    record_parser.add_argument("--spec-version", type=int, required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    args = parser.parse_args(argv)
    if getattr(args, "spec_version", 1) < 1:
        parser.error("--spec-version must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        {"record": record, "count": count, "report": report}[args.action](args)
    except LedgerError as exc:
        print(f"catch-ledger: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
