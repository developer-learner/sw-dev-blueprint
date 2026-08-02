#!/usr/bin/env python3
"""Persist and safely restore task completions across successful runs.

The live crash checkpoint remains in gitignored .pipeline-state/. This small,
tracked cache records only successful task definitions and output hashes. A
record is reusable only when both still match byte-for-byte.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_LEDGER = Path(".pipeline-completions.json")
DEFAULT_PLAN = Path("tasks/plan.json")
DEFAULT_TASK_STATE = Path(".pipeline-state/tasks")
SCHEMA_VERSION = 1
MAX_SPECS = 50
SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class LedgerError(ValueError):
    """The ledger or its source state cannot be trusted."""


def task_fingerprint(task):
    return hashlib.sha256(
        json.dumps(task, sort_keys=True).encode()
    ).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_output_path(raw_path):
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise LedgerError(f"unsafe task output path: {raw_path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
    except ValueError as exc:
        raise LedgerError(
            f"task output escapes the repository: {raw_path}"
        ) from exc
    if not resolved.is_file():
        raise LedgerError(f"task output is not a file: {raw_path}")
    return resolved


def load_plan(plan_path):
    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read validated plan: {exc}") from exc
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise LedgerError("validated plan has no tasks")
    for task in tasks:
        task_id = task.get("id") if isinstance(task, dict) else None
        if not isinstance(task_id, str) or not SAFE_TASK_ID.fullmatch(task_id):
            raise LedgerError(f"unsafe or missing task id: {task_id!r}")
        if not isinstance(task.get("file"), str):
            raise LedgerError(f"task {task_id} has no output file")
    return tasks


def empty_ledger():
    return {"schema_version": SCHEMA_VERSION, "specs": {}}


def validate_record(task_id, record):
    if not isinstance(record, dict):
        raise LedgerError(f"task record {task_id} is not an object")
    for field in ("file", "fingerprint", "file_sha256"):
        if not isinstance(record.get(field), str) or not record[field]:
            raise LedgerError(f"task record {task_id} has invalid {field}")


def load_ledger(ledger_path, missing_ok):
    if not ledger_path.exists():
        if missing_ok:
            return empty_ledger()
        raise LedgerError(f"ledger not found: {ledger_path}")
    try:
        ledger = json.loads(ledger_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read ledger: {exc}") from exc
    if not isinstance(ledger, dict):
        raise LedgerError("ledger root is not an object")
    if ledger.get("schema_version") != SCHEMA_VERSION:
        raise LedgerError(
            f"unsupported ledger schema: {ledger.get('schema_version')!r}"
        )
    specs = ledger.get("specs")
    if not isinstance(specs, dict):
        raise LedgerError("ledger specs is not an object")
    for spec_version, run in specs.items():
        if (
            not isinstance(spec_version, str)
            or not spec_version.isdigit()
            or int(spec_version) < 1
            or str(int(spec_version)) != spec_version
        ):
            raise LedgerError(f"invalid ledger spec version: {spec_version!r}")
        records = run.get("tasks") if isinstance(run, dict) else None
        if not isinstance(records, dict):
            raise LedgerError(f"spec v{spec_version} tasks is not an object")
        for task_id, record in records.items():
            if not SAFE_TASK_ID.fullmatch(task_id):
                raise LedgerError(f"unsafe ledger task id: {task_id!r}")
            validate_record(task_id, record)
    return ledger


def atomic_write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def record(args):
    tasks = load_plan(args.plan)
    ledger = load_ledger(args.ledger, missing_ok=True)
    records = {}
    for task in tasks:
        task_id = task["id"]
        status_path = args.task_state / f"{task_id}.status"
        fingerprint_path = args.task_state / f"{task_id}.fp"
        status = status_path.read_text().strip() \
            if status_path.is_file() else ""
        if status != "done":
            raise LedgerError(
                f"task {task_id} is not done; refusing success record"
            )
        expected_fingerprint = task_fingerprint(task)
        saved_fingerprint = fingerprint_path.read_text().strip() \
            if fingerprint_path.is_file() else ""
        if saved_fingerprint != expected_fingerprint:
            raise LedgerError(
                f"task {task_id} fingerprint is missing or stale"
            )
        output = safe_output_path(task["file"])
        records[task_id] = {
            "file": task["file"],
            "file_sha256": file_sha256(output),
            "fingerprint": expected_fingerprint,
        }
    ledger["specs"][str(args.spec_version)] = {"tasks": records}
    newest = sorted(ledger["specs"], key=int, reverse=True)[:MAX_SPECS]
    ledger["specs"] = {
        version: ledger["specs"][version]
        for version in sorted(newest, key=int)
    }
    atomic_write_json(args.ledger, ledger)
    print(
        f"completion ledger: recorded {len(records)} task(s) "
        f"for spec v{args.spec_version}"
    )


def matching_record(task, ledger):
    task_id = task["id"]
    fingerprint = task_fingerprint(task)
    output = safe_output_path(task["file"])
    output_hash = file_sha256(output)
    for spec_version in sorted(ledger["specs"], key=int, reverse=True):
        record = ledger["specs"][spec_version]["tasks"].get(task_id)
        if record is None:
            continue
        if (
            record["file"] == task["file"]
            and record["fingerprint"] == fingerprint
            and record["file_sha256"] == output_hash
        ):
            return fingerprint
    return None


def restore(args):
    if args.task_state.exists() and any(args.task_state.iterdir()):
        print("completion ledger: live task state present — restore skipped")
        return
    if not args.ledger.exists():
        print("completion ledger: no successful history — restored 0 task(s)")
        return
    tasks = load_plan(args.plan)
    ledger = load_ledger(args.ledger, missing_ok=False)
    matches = []
    for task in tasks:
        try:
            fingerprint = matching_record(task, ledger)
        except LedgerError as exc:
            if str(exc).startswith("task output is not a file:"):
                continue
            raise
        if fingerprint is not None:
            matches.append((task["id"], fingerprint))
    args.task_state.mkdir(parents=True, exist_ok=True)
    for task_id, fingerprint in matches:
        (args.task_state / f"{task_id}.status").write_text("done\n")
        (args.task_state / f"{task_id}.fp").write_text(
            f"{fingerprint}\n"
        )
    print(f"completion ledger: restored {len(matches)} task(s)")


def latest(args):
    """Print the newest successfully recorded spec, or 0 when none exists.

    The orchestrator uses this after intentional success cleanup, when the
    gitignored runtime state no longer carries its prior spec version. Loading
    still validates the entire ledger so damaged history fails closed.
    """
    ledger = load_ledger(args.ledger, missing_ok=True)
    print(max((int(version) for version in ledger["specs"]), default=0))


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("record", "restore", "latest"))
    parser.add_argument("--spec-version", type=int)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument(
        "--task-state", type=Path, default=DEFAULT_TASK_STATE
    )
    args = parser.parse_args(argv)
    if args.action != "latest" and args.spec_version is None:
        parser.error("--spec-version is required for record and restore")
    if args.spec_version is not None and args.spec_version < 1:
        parser.error("--spec-version must be positive")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.action == "record":
            record(args)
        elif args.action == "restore":
            restore(args)
        else:
            latest(args)
    except (LedgerError, OSError) as exc:
        print(f"completion-ledger: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
