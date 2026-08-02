#!/usr/bin/env python3
"""Track accepted D-77 flake occurrences across successful spec versions."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULT_LEDGER = Path(".pipeline-flakes.json")
SCHEMA_VERSION = 1
MAX_EVENTS_PER_NODE = 50


class LedgerError(ValueError):
    """The flake ledger cannot be trusted or updated safely."""


def empty_ledger():
    return {"schema_version": SCHEMA_VERSION, "nodes": {}}


def validate_nodeid(nodeid):
    if not isinstance(nodeid, str) or not nodeid.strip():
        raise LedgerError("nodeid must be a non-empty string")
    if any(char in nodeid for char in ("\n", "\r", "\t")):
        raise LedgerError("nodeid contains a control character")


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
    nodes = ledger.get("nodes")
    if not isinstance(nodes, dict):
        raise LedgerError("ledger nodes is not an object")
    for nodeid, events in nodes.items():
        validate_nodeid(nodeid)
        if not isinstance(events, list):
            raise LedgerError(f"events for {nodeid} are not an array")
        seen = set()
        for event in events:
            if not isinstance(event, dict):
                raise LedgerError(f"event for {nodeid} is not an object")
            spec_version = event.get("spec_version")
            isolation_passes = event.get("isolation_passes")
            if (
                not isinstance(spec_version, int)
                or isinstance(spec_version, bool)
                or spec_version < 1
            ):
                raise LedgerError(f"invalid spec version for {nodeid}")
            if spec_version in seen:
                raise LedgerError(
                    f"duplicate spec v{spec_version} event for {nodeid}"
                )
            seen.add(spec_version)
            if isolation_passes not in (1, 2):
                raise LedgerError(f"invalid isolation passes for {nodeid}")
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
    validate_nodeid(args.nodeid)
    ledger = load_ledger(args.ledger)
    events = ledger["nodes"].setdefault(args.nodeid, [])
    new_event = {
        "isolation_passes": args.isolation_passes,
        "spec_version": args.spec_version,
    }
    events[:] = [
        event for event in events
        if event["spec_version"] != args.spec_version
    ]
    events.append(new_event)
    events.sort(key=lambda event: event["spec_version"])
    del events[:-MAX_EVENTS_PER_NODE]
    atomic_write(args.ledger, ledger)
    print(f"flake ledger: {args.nodeid} has {len(events)} occurrence(s)")


def count(args):
    validate_nodeid(args.nodeid)
    ledger = load_ledger(args.ledger)
    print(len(ledger["nodes"].get(args.nodeid, [])))


def projected_count(args):
    validate_nodeid(args.nodeid)
    ledger = load_ledger(args.ledger)
    existing_versions = {
        event["spec_version"]
        for event in ledger["nodes"].get(args.nodeid, [])
    }
    existing_versions.add(args.spec_version)
    print(len(existing_versions))


def parse_args(argv):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    count_parser = subparsers.add_parser("count")
    count_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    count_parser.add_argument("--nodeid", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    record_parser.add_argument("--spec-version", type=int, required=True)
    record_parser.add_argument("--nodeid", required=True)
    record_parser.add_argument(
        "--isolation-passes", type=int, choices=(1, 2), required=True
    )

    projected_count_parser = subparsers.add_parser("projected-count")
    projected_count_parser.add_argument(
        "--ledger", type=Path, default=DEFAULT_LEDGER
    )
    projected_count_parser.add_argument("--nodeid", required=True)
    projected_count_parser.add_argument(
        "--spec-version", type=int, required=True
    )

    args = parser.parse_args(argv)
    if getattr(args, "spec_version", 1) < 1:
        parser.error("--spec-version must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.action == "record":
            record(args)
        elif args.action == "projected-count":
            projected_count(args)
        else:
            count(args)
    except (LedgerError, OSError) as exc:
        print(f"flake-ledger: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
