#!/usr/bin/env python3
"""validate-plan.py — mechanical gate on the EM's task plan (D-26, D-28).

The plan (tasks/plan.json) is the EM's only channel of authority. Everything
checkable is checked here, so a bad decomposition fails at VALIDATION, not at
integration:

  - structural: schema shape, no unknown keys, no status field, id format
  - atomicity:  exactly one file per task, unique, under the build lane
  - coverage:   every file in the frozen ERD inventory has exactly one task
  - oracle:     every frozen TPM test node-id mapped to exactly one task
  - contracts:  every referenced contract id exists in the frozen contracts
  - DAG:        dependencies exist, no self-deps, acyclic (Kahn)
  - freshness:  plan.erd_version == scripts/.approved/VERSION

Stdlib only (json/hashlib), matching the orchestrator's pre-flight contract.

Modes:
  validate-plan.py                          validate; exit 0/1
  validate-plan.py --topo                   validate; print task ids in topological order
  validate-plan.py --task ID --field F      print field F of task ID
                                            (F: file|brief|tests|contracts|smoke_check|fingerprint)
  validate-plan.py --affected DELTA.json    print ids of tasks invalidated by a re-freeze
                                            delta, including transitive dependents
  validate-plan.py --diagnosis FILE         validate an EM diagnosis; print its verdict
"""
import hashlib
import json
import sys
from pathlib import Path

PLAN = Path("tasks/plan.json")
APPROVED = Path("scripts/.approved")
CONTRACTS = APPROVED / "contracts.json"
NODEIDS = APPROVED / "test-nodeids"
VERSION = APPROVED / "VERSION"

TASK_REQUIRED = {"id", "file", "depends_on", "brief", "contracts", "tests"}
TASK_ALLOWED = TASK_REQUIRED | {"smoke_check"}
VERDICTS = {"brief_wrong", "decomposition_wrong", "contract_or_test_wrong"}


def fail(msgs):
    for m in msgs:
        print(f"PLAN GATE FAIL: {m}", file=sys.stderr)
    sys.exit(1)


def load_json(path, what):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        fail([f"{what} not found: {path}"])
    except json.JSONDecodeError as e:
        fail([f"{what} is not valid JSON: {e}"])


def build_dir():
    d = "src/"
    try:
        for line in Path(".gate-paths").read_text().splitlines():
            if line.startswith("build="):
                raw = line.split("=", 1)[1].strip()
                raw = raw[2:] if raw.startswith("./") else raw
                d = raw.rstrip("/") + "/"
    except FileNotFoundError:
        pass
    return d


def contract_ids(contracts):
    ids = set(contracts.get("entry_points", []))
    for key in ("routes", "schemas", "errors"):
        for entry in contracts.get(key, []):
            if isinstance(entry, dict) and "id" in entry:
                ids.add(entry["id"])
    return ids


def toposort(tasks):
    """Kahn's algorithm. Returns ordered id list, or None on a cycle."""
    ids = [t["id"] for t in tasks]
    deps = {t["id"]: set(t["depends_on"]) for t in tasks}
    order = []
    ready = sorted(i for i in ids if not deps[i])
    while ready:
        n = ready.pop(0)
        order.append(n)
        newly = []
        for i in ids:
            if n in deps[i]:
                deps[i].discard(n)
                if not deps[i] and i not in order and i not in ready:
                    newly.append(i)
        ready.extend(sorted(newly))
    return order if len(order) == len(ids) else None


def fingerprint(task):
    return hashlib.sha256(
        json.dumps(task, sort_keys=True).encode()
    ).hexdigest()


def validate():
    errs = []
    plan = load_json(PLAN, "plan")
    contracts = load_json(CONTRACTS, "frozen contracts")
    if not NODEIDS.exists():
        fail(["frozen test-nodeids missing — run scripts/refreeze.sh first"])
    frozen_nodeids = [l.strip() for l in NODEIDS.read_text().splitlines() if l.strip()]

    if not isinstance(plan, dict):
        fail(["plan must be a JSON object"])
    for key in list(plan):
        if key not in ("version", "erd_version", "tasks"):
            errs.append(f"unknown top-level key: {key}")
    for key in ("version", "erd_version"):
        if not isinstance(plan.get(key), int) or plan.get(key, 0) < 1:
            errs.append(f"plan.{key} must be an integer >= 1")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        fail(errs + ["plan.tasks must be a non-empty array"])

    # freshness — a plan derived from a superseded ERD is stale
    if VERSION.exists():
        frozen_v = int(VERSION.read_text().strip())
        if isinstance(plan.get("erd_version"), int) and plan["erd_version"] != frozen_v:
            errs.append(
                f"plan is stale: erd_version={plan['erd_version']} but frozen "
                f"VERSION={frozen_v} — the EM must re-derive from the current ERD"
            )

    lane = build_dir()
    ids, files = [], []
    for i, t in enumerate(tasks):
        where = f"tasks[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{where} is not an object")
            continue
        if "status" in t or "state" in t or "done" in t:
            errs.append(
                f"{where} carries a status field — the orchestrator owns all "
                "state; the EM never marks anything done (D-26)"
            )
        missing = TASK_REQUIRED - set(t)
        if missing:
            errs.append(f"{where} missing keys: {sorted(missing)}")
            continue
        unknown = set(t) - TASK_ALLOWED
        if unknown:
            errs.append(f"{where} unknown keys: {sorted(unknown)}")
        tid = t["id"]
        where = f"task {tid}"
        if not isinstance(tid, str) or not tid.startswith("T") or not tid[1:].isdigit():
            errs.append(f"{where}: id must match ^T[0-9]+$")
        ids.append(tid)
        f = t["file"]
        if not isinstance(f, str) or not f.startswith(lane):
            errs.append(f"{where}: file must be a path under the build lane {lane!r}: {f!r}")
        files.append(f)
        if not isinstance(t["brief"], str) or not t["brief"].strip():
            errs.append(f"{where}: brief must be a non-empty string")
        for key in ("depends_on", "contracts", "tests"):
            if not isinstance(t[key], list) or not all(isinstance(x, str) for x in t[key]):
                errs.append(f"{where}: {key} must be an array of strings")
        if "smoke_check" in t and (
            not isinstance(t["smoke_check"], str) or not t["smoke_check"].strip()
        ):
            errs.append(f"{where}: smoke_check, when present, must be a non-empty string")
        if isinstance(t.get("tests"), list) and not t["tests"] and not t.get("smoke_check"):
            errs.append(
                f"{where}: no mapped tests and no smoke_check — every task needs "
                "an acceptance signal, even a non-oracular one"
            )

    if errs:
        fail(errs)

    # uniqueness — one task per file, one file per task
    for coll, what in ((ids, "task id"), (files, "task file")):
        dupes = sorted({x for x in coll if coll.count(x) > 1})
        if dupes:
            errs.append(f"duplicate {what}(s): {dupes} — one file per task, one task per file")

    id_set = set(ids)
    for t in tasks:
        for d in t["depends_on"]:
            if d == t["id"]:
                errs.append(f"task {t['id']} depends on itself")
            elif d not in id_set:
                errs.append(f"task {t['id']} depends on unknown task {d}")

    # ERD inventory coverage — exact bijection with contracts.files
    inventory = contracts.get("files", [])
    missing_tasks = sorted(set(inventory) - set(files))
    extra_files = sorted(set(files) - set(inventory))
    if missing_tasks:
        errs.append(f"ERD inventory files with no task: {missing_tasks}")
    if extra_files:
        errs.append(f"tasks target files not in the ERD inventory: {extra_files}")

    # contract references exist
    known = contract_ids(contracts)
    for t in tasks:
        bad = sorted(set(t["contracts"]) - known)
        if bad:
            errs.append(f"task {t['id']} references unknown contract id(s): {bad}")

    # oracle projection — every frozen node-id mapped to EXACTLY one task
    mapped = [n for t in tasks for n in t["tests"]]
    frozen_set = set(frozen_nodeids)
    unknown_map = sorted(set(mapped) - frozen_set)
    if unknown_map:
        errs.append(f"mapped test node-id(s) not in the frozen suite: {unknown_map}")
    unmapped = sorted(frozen_set - set(mapped))
    if unmapped:
        errs.append(
            f"frozen test node-id(s) mapped to no task (decomposition incomplete): {unmapped}"
        )
    overmapped = sorted({n for n in mapped if mapped.count(n) > 1})
    if overmapped:
        errs.append(f"test node-id(s) mapped to more than one task: {overmapped}")

    if errs:
        fail(errs)

    order = toposort(tasks)
    if order is None:
        fail(["dependency cycle detected — the plan must be a DAG"])
    return plan, order


def cmd_affected(delta_path):
    plan, _ = validate()
    delta = load_json(Path(delta_path), "delta")
    changed_tests = set(delta.get("changed_tests", []))
    changed_contracts = set(delta.get("changed_contract_ids", []))
    changed_files = set(delta.get("changed_files", []))
    tasks = {t["id"]: t for t in plan["tasks"]}
    hit = {
        tid
        for tid, t in tasks.items()
        if set(t["tests"]) & changed_tests
        or set(t["contracts"]) & changed_contracts
        or t["file"] in changed_files
    }
    # transitive dependents are invalidated too
    grew = True
    while grew:
        grew = False
        for tid, t in tasks.items():
            if tid not in hit and set(t["depends_on"]) & hit:
                hit.add(tid)
                grew = True
    for tid in sorted(hit):
        print(tid)


def cmd_diagnosis(path):
    d = load_json(Path(path), "diagnosis")
    errs = []
    if not isinstance(d, dict):
        fail(["diagnosis must be a JSON object"])
    unknown = set(d) - {"task_id", "verdict", "reason", "revised_brief"}
    if unknown:
        errs.append(f"diagnosis unknown keys: {sorted(unknown)}")
    for key in ("task_id", "verdict", "reason"):
        if not isinstance(d.get(key), str) or not d.get(key, "").strip():
            errs.append(f"diagnosis.{key} must be a non-empty string")
    if d.get("verdict") not in VERDICTS:
        errs.append(f"diagnosis.verdict must be one of {sorted(VERDICTS)}")
    if d.get("verdict") == "brief_wrong" and not str(d.get("revised_brief", "")).strip():
        errs.append("verdict brief_wrong requires a non-empty revised_brief")
    if errs:
        fail(errs)
    print(d["verdict"])


def main(argv):
    if not argv:
        validate()
        print("plan ok")
        return
    if argv[0] == "--topo":
        _, order = validate()
        print("\n".join(order))
        return
    if argv[0] == "--task" and len(argv) == 4 and argv[2] == "--field":
        plan, _ = validate()
        tid, field = argv[1], argv[3]
        task = next((t for t in plan["tasks"] if t["id"] == tid), None)
        if task is None:
            fail([f"no such task: {tid}"])
        if field == "fingerprint":
            print(fingerprint(task))
        elif field in ("tests", "contracts", "depends_on"):
            print("\n".join(task[field]))
        elif field in ("file", "brief"):
            print(task[field])
        elif field == "smoke_check":
            print(task.get("smoke_check", ""))
        else:
            fail([f"unknown field: {field}"])
        return
    if argv[0] == "--affected" and len(argv) == 2:
        cmd_affected(argv[1])
        return
    if argv[0] == "--diagnosis" and len(argv) == 2:
        cmd_diagnosis(argv[1])
        return
    fail([f"usage error: {' '.join(argv)} (see module docstring)"])


if __name__ == "__main__":
    main(sys.argv[1:])
