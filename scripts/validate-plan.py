#!/usr/bin/env python3
"""validate-plan.py — mechanical gate on the EM's task plan (D-26, D-28).

The plan (tasks/plan.json) is the EM's only channel of authority. Everything
checkable is checked here, so a bad decomposition fails at VALIDATION, not at
integration:

  - structural: schema shape, no unknown keys, no status field, id format
  - atomicity:  exactly one file per task, unique, under the build lane
  - coverage:   every file in the exact active milestone inventory has one task
  - oracle:     every frozen TPM test node-id that observably exercises this
                delta's inventory (module-level import of a task-owned module,
                or an AST-visible call to a route a task claims) is mapped to
                exactly one task; the rest are carried-forward regression
                tests, COMPUTED here — never EM-emitted (D-57) — whose
                acceptance point is the final full-suite run
  - contracts:  every referenced contract id exists in the frozen contracts
  - DAG:        dependencies exist, no self-deps, acyclic (Kahn)
  - routing:    a mapped test that exercises an HTTP route (AST-visible
                client.<method>("<path>") literal) must not be scheduled
                before the task claiming that route contract — the route
                must be claimed inside the task's dependency closure
  - freshness:  plan.erd_version == scripts/.approved/VERSION

Stdlib only (json/hashlib), matching the orchestrator's pre-flight contract.

Modes:
  validate-plan.py                          validate; exit 0/1
  validate-plan.py --topo                   validate; print task ids in topological order
  validate-plan.py --task ID --field F      print field F of task ID
                                            (F: file|brief|tests|contracts|smoke_check|fingerprint)
                                            smoke_check reads from contracts.json, not the plan
  validate-plan.py --affected DELTA.json [DELTA.json ...]
                                            print ids invalidated across re-freezes
                                            delta, including transitive dependents
  validate-plan.py --milestone-scope DELTA.json [DELTA.json ...]
                                            print the authoritative milestone
                                            node-id scope (sorted-unique, one per
                                            line): the SAME producer the subtree
                                            scope uses for map_nodeids, consumed
                                            by orchestrate's full-emission EM
                                            prompt (D-130). Raw changed_tests are
                                            file-granular; the frozen test_mapping
                                            pins which tests the milestone owns.
  validate-plan.py --active-inventory DELTA.json [DELTA.json ...]
                                            print the exact ordered active build
                                            inventory, including skipped freezes
                                            and a legitimate empty inventory.
  validate-plan.py --active-erd-context DELTA.json [DELTA.json ...]
                                            print a semantic compact view of every
                                            active freeze's immutable ERD
                                            instructions: current narrative plus
                                            deduplicated briefs, mappings, and DAG.
  validate-plan.py --synthesize-plan DELTA.json [DELTA.json ...]
                                            mechanical plan synthesis (B3-fast
                                            path): print the full plan JSON when
                                            the TPM's ERD-DELTA carries a verbatim
                                            coder brief for every inventory file,
                                            a DAG statement, and an ownership pin
                                            for every milestone node-id — one
                                            deterministic task per file, the EM
                                            never called. Exits 1 with the reasons
                                            when any piece is missing (unbriefed
                                            file, self/reference edges, unpinned
                                            scope id); the orchestrator then falls
                                            back to the EM full emission. The plan
                                            still faces the FULL validate() gate —
                                            this command is a producer, never an
                                            authority.
  validate-plan.py --diagnosis FILE         validate an EM diagnosis; print its verdict
  validate-plan.py --spec-preflight OLD NEW
                                                    D-78 freeze-time satisfiability: every
                                                    new/changed route and entry_point in NEW
                                                    (vs OLD, which may not exist yet) must be
                                                    implementable by NEW's contracts.files;
                                                    exit 0/1. Run by refreeze.sh BEFORE the
                                                    human approval prompt.
  validate-plan.py --subtree-scope PRIOR DELTA [DELTA...]
                                            print the delta re-plan scope (JSON)
                                            for a re-freeze: which prior tasks the
                                            delta(s) invalidate, which inventory
                                            files are new, which node-ids the EM
                                            must map, and whether the scope is
                                            trivially mechanically constructible
                                            (Cut 2: exactly one re-emit, no new
                                            files, no contract changes across any
                                            delta — the shell can build the
                                            subtree without an EM call). Loads
                                            PRIOR leniently (it validated against
                                            the PREVIOUS spec, not this one).
                                            Exits 1 with the reason whenever a
                                            subtree re-plan cannot soundly express
                                            the delta — the orchestrator then
                                            falls back to full emission.
  validate-plan.py --merge-subtree PRIOR SUBTREE SCOPE
                                            merge the EM's subtree reply over the
                                            carried-forward PRIOR plan and write
                                            tasks/plan.json ('-' as SUBTREE = the
                                            delta needed no EM tasks). The merged
                                            artifact then faces the FULL validate()
                                            gate unchanged — the D-64 bijection is
                                            a property of the validated artifact,
                                            not of who authored which part.
  validate-plan.py --construct-one-file PRIOR SCOPE [DELTA.json ...]
                                            Cut 2: print the mechanically-
                                            constructed subtree JSON for a
                                            trivial_construct scope — the prior
                                            task's contracts and depends_on
                                            carried through, tests updated to
                                            scope.map_nodeids, and any latest
                                            TPM verbatim brief preferred over
                                            the carried brief.
                                            Refuses (exit 1) if the scope is not
                                            trivial_construct. The output is fed
                                            to --merge-subtree exactly as an EM
                                            subtree reply would be.
  validate-plan.py --repair-closures [PLAN]
                                            best-effort closure auto-repair: add
                                            the depends_on edges the route /
                                            import / browser-D-64 closure checks
                                            would reject on — only when the add
                                            keeps the DAG acyclic — write the
                                            plan, print each edge. Exit 0 always;
                                            validate() runs after and is the
                                            authority. Monotone (edges only push
                                            tests later), so it can never make a
                                            bad plan pass. Run by orchestrate.sh
                                            before the gate.
"""
import ast
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

PLAN = Path("tasks/plan.json")
APPROVED = Path("scripts/.approved")
CONTRACTS = APPROVED / "contracts.json"
NODEIDS = APPROVED / "test-nodeids"
VERSION = APPROVED / "VERSION"

TASK_REQUIRED = {"id", "file", "depends_on", "brief", "contracts", "tests"}
TASK_ALLOWED = TASK_REQUIRED
MAX_BRIEF_CHARS = 2500
# D-89 (plan-gate half): threshold for the brief-overflow hint's ERD prose
# mass. Tuned against testchat history: v63's app.js section transcribed to a
# brief that fit the 2500-char plan-gate limit; v64's did not (12 behavioral
# items on one file → 2697-char brief). The freeze-time advisory was retired
# 2026-08-02 — only the plan-gate hint consumes this now, where the brief is
# actually rejected. Advisory only; the cap is the hard backstop.
ERD_MASS_ADVISORY_THRESHOLD = 2000
ERD_PATH = APPROVED / "ERD.md"
ERD_DELTA_PATH = APPROVED / "ERD-DELTA.md"

# D-133 (delta-only brief enforcement, 2026-08-11 audit item 4): an
# existing-file task's brief must describe only what THIS delta changes, never
# restate carried behavior the delta leaves untouched. em.md has said so in
# prose since v82, but prose is a suggestion, not a rule — and the mechanical
# synthesis lane (B3) copies the TPM's verbatim brief, which legitimately names
# carried symbols for context, so the check cannot simply forbid mentioning
# carried behavior. It must separate TPM-authorized context from EM-introduced
# restatement. The rule (enforced fail-closed in validate(), mirroring the D-89
# "name the source, suggest the fix" shape): for an EXISTING file whose plan
# brief DIVERGES from the TPM verbatim brief, flag any backticked code symbol
# the brief names that (a) is DEFINED in the current on-disk file — i.e.
# carried, pre-existing behavior — AND (b) appears NOWHERE in the ERD-DELTA the
# TPM authored. That symbol is behavior the delta does not change, restated.
#
# DECISIONS — the "do NOT fire / do NOT suggest" boundary (S6, 2026-08-08: an
# over-strict gate that halts every freeze is worse than none — this check
# fails OPEN unless every precondition for a sound verdict holds, and only then
# fails CLOSED with a named, bounded diagnosis):
#   * Verbatim TPM briefs are the authority. A plan brief equal (whitespace-
#     normalized) to the file's `_parse_brief_blocks` block is exempt outright,
#     so the synthesis path can NEVER be rejected by this gate (item-4
#     constraint). The symbol heuristic would already pass such a brief; the
#     explicit equality skip makes it an invariant, not an inference.
#   * No ERD-DELTA.md, or no verbatim brief block for the file → skip. Without
#     the TPM's authored delta there is no ground truth for "what the delta
#     changes"; firing blind is the S6 failure. The gate speaks only when it
#     has an authority to compare against.
#   * A new file (nothing on disk / no defined symbols) carries no behavior to
#     restate → skip. Grandfathering by construction: a symbol the delta
#     introduces is not yet defined in the file, so it can never be flagged;
#     only a symbol the file ALREADY defines can be.
#   * Only backticked identifiers that resolve to a symbol the file DEFINES
#     (def/class/function/const/let/var) fire — never prose, type names, or
#     un-backticked words. The offender list is capped (bounded diagnosis).
# The fix a fired diagnosis points to: drop the restated symbol from the brief;
# or, if the behavior genuinely changes, the TPM's ERD-DELTA must say so — that
# routes to the spec, not to an EM brief rewrite.
DELTA_ONLY_MAX_REPORT = 6
# A code identifier: the atoms we pull from a brief's backticks and match
# against a file's definitions.
_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Definition sites across the project's two source languages (Python, JS): the
# left-hand side of a def/class/function/const/let/var is a symbol the file
# OWNS. Anything a brief restates from this set is carried behavior.
_DEF_RES = (
    re.compile(r"\bdef\s+([A-Za-z_]\w*)"),
    re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
    re.compile(r"\bfunction\s+([A-Za-z_]\w*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_]\w*)\s*="),
)
VERDICTS = {"brief_wrong", "decomposition_wrong", "contract_or_test_wrong"}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
# Method-agnostic registration calls (Flask .route/.add_url_rule, FastAPI
# .add_api_route) — a path literal under one of these registers the route
# for ANY method.
ROUTE_REGISTRARS = {"route", "add_api_route", "add_url_rule", "websocket"}

# Carried-forward node-ids computed by the last validate() call (D-57).
# Informational — the final full-suite run covers them regardless.
AUTO_REGRESSION: list = []

# Browser node-ids the gate auto-placed at the DAG's final task (D-64).
# Filled by validate(); the default main() branch writes the corrected
# plan back to disk so every downstream reader sees the gate-owned mapping.
AUTO_PLACED: list = []


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


def seg_matches(t_seg, p_seg):
    """One path segment against one template segment: a {param} segment on
    either side matches anything; otherwise exact. Shared by the plan gate's
    route matcher (template vs concrete test literal) and the D-78 preflight
    (template vs registration-literal template)."""
    if t_seg.startswith("{") and t_seg.endswith("}"):
        return True
    if p_seg.startswith("{") and p_seg.endswith("}"):
        return True
    return t_seg == p_seg


def path_segs(path):
    return [s for s in path.strip("/").split("/") if s]


def contract_ids(contracts):
    ids = set(contracts.get("entry_points", []))
    for key in ("routes", "schemas", "errors", "externals", "ui"):
        for entry in contracts.get(key, []):
            if isinstance(entry, dict) and "id" in entry:
                ids.add(entry["id"])
    return ids


def contract_file_pins(contracts):
    """{contract id: owning source path} from the D-120 file pins. Routes,
    schemas, errors and ui entries pin their owning file via their "file"
    field; entry_points self-pin through their module path (src.api.threads:app
    derives to src/api/threads.py)."""
    pins = {}
    for key in ("routes", "schemas", "errors", "externals", "ui"):
        for entry in contracts.get(key, []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("file"):
                pins[entry["id"]] = entry["file"]
    for ep in contracts.get("entry_points", []):
        if isinstance(ep, str) and ep.startswith("src."):
            pins[ep] = ep.split(":", 1)[0].replace(".", "/") + ".py"
    return pins


def active_delta_paths() -> list[Path]:
    """Return the current milestone's delta range (D-138)."""
    raw = os.environ.get("SWBP_ACTIVE_DELTA_FILES")
    if raw is not None:
        return [Path(line) for line in raw.splitlines() if line.strip()]
    if not VERSION.exists():
        return []
    try:
        frozen_v = int(VERSION.read_text().strip())
    except (OSError, ValueError):
        return []
    latest = APPROVED / f"DELTA-v{frozen_v}.json"
    return [latest] if latest.is_file() else []


def delta_changed_contract_ids(delta_paths: list[Path]) -> set[str]:
    """Union changed contract ids across only the active range (D-138)."""
    ids = set()
    for path in delta_paths:
        delta = load_json(path, "active milestone delta")
        changed = delta.get("changed_contract_ids", []) \
            if isinstance(delta, dict) else None
        if not isinstance(changed, list) or not all(
            isinstance(contract_id, str) for contract_id in changed
        ):
            fail([f"active milestone delta {path} has invalid "
                  "changed_contract_ids — expected an array of strings"])
        ids.update(changed)
    return ids


def active_inventory_files(
    delta_paths: list[Path], contracts: dict,
) -> list[str]:
    """Exact ordered build inventory for the active milestone (D-140).

    New freezes snapshot contracts.files in each DELTA.  A skipped-freeze
    milestone is the ordered union of those snapshots, including a genuinely
    empty snapshot.  If every delta predates the field, retain the historical
    contracts.files behavior.  During a mixed-format migration, legacy
    entries contribute only their explicit changed_files and changed-contract
    owners; accumulated standing inventory is never reintroduced.
    """
    deltas = [load_json(path, "active milestone delta") for path in delta_paths]
    if not deltas or not any("inventory_files" in d for d in deltas):
        return list(contracts.get("files", []))
    pins = contract_file_pins(contracts)
    ordered: list[str] = []
    for path, delta in zip(delta_paths, deltas):
        if "inventory_files" in delta:
            files = delta.get("inventory_files")
            if not isinstance(files, list) or not all(
                isinstance(item, str) for item in files
            ):
                fail([f"active milestone delta {path} has invalid "
                      "inventory_files — expected an array of strings"])
        else:
            files = list(delta.get("changed_files", []))
            files += [
                pins[contract_id]
                for contract_id in delta.get("changed_contract_ids", [])
                if contract_id in pins
            ]
        for file_path in files:
            if file_path not in ordered:
                ordered.append(file_path)
    return ordered


def _delta_version(path: Path) -> int | None:
    match = re.search(r"DELTA-v(\d+)\.json$", path.name)
    return int(match.group(1)) if match else None


def _git_erd_delta_at_freeze(delta_path: Path) -> str | None:
    """Recover a pre-D-140 instruction slice from its freeze commit."""
    try:
        try:
            git_path = delta_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            git_path = delta_path.as_posix()
        commit = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--diff-filter=A", "--",
             git_path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if not commit:
            return None
        return subprocess.run(
            ["git", "show", f"{commit}:{ERD_DELTA_PATH.as_posix()}"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def active_erd_delta_texts(
    delta_paths: list[Path],
) -> list[tuple[int | None, str]]:
    """Per-freeze instruction slices for the active range (D-140).

    Modern freezes carry immutable ERD-DELTA-vN.md files.  Historical Git
    freezes are recovered from the commit that introduced DELTA-vN.json.
    Synthetic/pre-Git legacy fixtures retain the old current-file fallback;
    a modern delta missing its immutable snapshot fails closed.
    """
    out: list[tuple[int | None, str]] = []
    legacy_fallback = False
    for delta_path in delta_paths:
        delta = load_json(delta_path, "active milestone delta")
        version = _delta_version(delta_path)
        versioned = APPROVED / f"ERD-DELTA-v{version}.md" \
            if version is not None else None
        if versioned is not None and versioned.is_file():
            out.append((version, versioned.read_text()))
            continue
        recovered = _git_erd_delta_at_freeze(delta_path)
        if recovered is not None:
            out.append((version, recovered))
            continue
        if "inventory_files" in delta:
            if not (
                delta.get("inventory_files")
                or delta.get("changed_contract_ids")
                or delta.get("changed_tests")
            ):
                continue
            fail([f"active milestone instruction snapshot missing for "
                  f"{delta_path}: expected {versioned}; cannot safely plan "
                  "a range after losing one freeze's ERD-DELTA"])
        legacy_fallback = True
    if legacy_fallback:
        if not ERD_DELTA_PATH.is_file():
            return out
        out.append((_delta_version(delta_paths[-1]), ERD_DELTA_PATH.read_text()))
    return out


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
    frozen_nodeids = [
        line.strip() for line in NODEIDS.read_text().splitlines() if line.strip()
    ]

    if not isinstance(plan, dict):
        fail(["plan must be a JSON object"])
    for key in list(plan):
        if key == "regression":
            errs.append(
                "plan carries a 'regression' key — the shell computes the "
                "carried-forward bucket itself; the EM never emits it (D-57)"
            )
        elif key not in ("version", "erd_version", "tasks"):
            errs.append(f"unknown top-level key: {key}")
    for key in ("version", "erd_version"):
        if not isinstance(plan.get(key), int) or plan.get(key, 0) < 1:
            errs.append(f"plan.{key} must be an integer >= 1")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        fail(errs + ["plan.tasks must be an array"])

    # freshness — a plan derived from a superseded ERD is stale
    if VERSION.exists():
        frozen_v = int(VERSION.read_text().strip())
        if isinstance(plan.get("erd_version"), int) and plan["erd_version"] != frozen_v:
            errs.append(
                f"plan is stale: erd_version={plan['erd_version']} but frozen "
                f"VERSION={frozen_v} — the EM must re-derive from the current ERD"
            )

    delta_paths = active_delta_paths()
    inventory = active_inventory_files(delta_paths, contracts)
    if not tasks:
        changed_contracts = delta_changed_contract_ids(delta_paths)
        runnable = set()
        mapping = contracts.get("test_mapping") or {}
        frozen_set = set(frozen_nodeids)
        for path in delta_paths:
            delta = load_json(path, "active milestone delta")
            runnable.update(milestone_scope_ids(
                mapping, delta.get("changed_files", []),
                delta.get("changed_tests", []),
                delta.get("changed_tests_granularity", "file"), frozen_set,
            ))
        if inventory or changed_contracts or runnable:
            fail(errs + [
                "plan.tasks may be empty only when the active milestone has "
                "no inventory files, changed contracts, or runnable changed "
                f"tests; found inventory={inventory}, "
                f"contracts={sorted(changed_contracts)}, "
                f"tests={sorted(runnable)}"
            ])
        if errs:
            fail(errs)
        AUTO_PLACED.clear()
        AUTO_REGRESSION.clear()
        return plan, []

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
        elif len(t["brief"]) > MAX_BRIEF_CHARS:
            # D-89: name the file's ERD prose mass if we can compute it —
            # the future TPM should see "the spec is oversized," not "the EM
            # wrote long," so a re-freeze routes to the spec rather than
            # another actor swap.
            hint = ""
            try:
                erd_text = ERD_PATH.read_text()
                mass = _erd_mass_per_file(erd_text, contracts.get("files", []))
                fm = mass.get(f)
                if fm is not None:
                    hint = (
                        f" (the ERD section for {f} is {fm} chars"
                        + (f", above the D-89 advisory threshold "
                           f"{ERD_MASS_ADVISORY_THRESHOLD}"
                           if fm > ERD_MASS_ADVISORY_THRESHOLD else "")
                        + ")"
                    )
            except OSError:
                pass
            errs.append(
                f"{where}: brief is {len(t['brief'])} chars (max {MAX_BRIEF_CHARS}) "
                f"— split the task or tighten the brief (Rule 8)"
                + hint
            )
        for key in ("depends_on", "contracts", "tests"):
            if not isinstance(t[key], list) or not all(isinstance(x, str) for x in t[key]):
                errs.append(f"{where}: {key} must be an array of strings")
        if isinstance(t.get("tests"), list) and not t["tests"]:
            smoke_checks = contracts.get("smoke_checks", {})
            if f not in smoke_checks:
                errs.append(
                    f"{where}: no mapped tests and no smoke_check in contracts for "
                    f"{f!r} — every task needs an acceptance signal"
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
    missing_tasks = sorted(set(inventory) - set(files))
    extra_files = sorted(set(files) - set(inventory))
    if missing_tasks:
        errs.append(f"ERD inventory files with no task: {missing_tasks}")
    if extra_files:
        errs.append(f"tasks target files not in the ERD inventory: {extra_files}")

    # D-65: no_edit_files must be inventory members — a no-edit declaration
    # for a file outside the inventory is a spec typo the freeze should have
    # caught; fail loudly here as the backstop.
    standing_inventory = set(contracts.get("files", []))
    stray_no_edit = sorted(
        set(contracts.get("no_edit_files", [])) - standing_inventory)
    if stray_no_edit:
        errs.append(
            f"contracts.no_edit_files entries not in the ERD inventory "
            f"(files): {stray_no_edit}"
        )

    # smoke_check executability — every value in contracts.smoke_checks must be
    # a real shell command, not prose. bash -n only checks syntax (prose is
    # syntactically valid), so we also verify the first token resolves to an
    # executable via `command -v`.
    for sc_file, sc_cmd in contracts.get("smoke_checks", {}).items():
        if sc_file not in standing_inventory:
            errs.append(
                f"smoke_checks key '{sc_file}' is not in contracts.files"
            )
        result = subprocess.run(
            ["bash", "-n", "-c", sc_cmd],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            errs.append(
                f"smoke_checks['{sc_file}'] is not valid shell syntax: "
                f"{sc_cmd!r} — bash -n says: {result.stderr.strip()}"
            )
        else:
            first_token = sc_cmd.split()[0] if sc_cmd.strip() else ""
            if first_token:
                # The token comes from TPM-authored contracts.smoke_checks —
                # untrusted text. It MUST NOT be interpolated into the shell
                # word (`command -v $tok` ran `$(...)`, backticks, and
                # `foo;payload` on the host at validation time). Pass it as a
                # positional arg so bash treats it as data, never syntax; `--`
                # guards a token that begins with '-'.
                cv = subprocess.run(
                    ["bash", "-c", 'command -v -- "$1"', "bash", first_token],
                    capture_output=True, text=True
                )
                if cv.returncode != 0:
                    errs.append(
                        f"smoke_checks['{sc_file}'] is not a valid shell command: "
                        f"first token '{first_token}' is not an executable "
                        f"(command -v fails). Value: {sc_cmd!r}"
                    )

    # contract references exist
    known = contract_ids(contracts)
    for t in tasks:
        bad = sorted(set(t["contracts"]) - known)
        if bad:
            errs.append(f"task {t['id']} references unknown contract id(s): {bad}")

    # Claim minimality (finding-2): a task claims only contracts THIS
    # milestone changed plus interfaces its file's work directly depends on
    # (cross-file pins and unpinned interfaces). Unchanged contracts pinned
    # to the task's OWN file are the ride-along pattern — testchat v99: a
    # GET-side 503-mapping task claimed route:PUT/route:DELETE and every
    # schema of its file, dragging unchanged behavior into the milestone's
    # acceptance and over-invalidating later freezes (one task re-ran 20
    # node-ids repeatedly). The TPM's changed_contract_ids declaration is the
    # authority: an id never declared changed in the active D-113 range cannot
    # be claimed by the task owning its file. Greenfield leaves the check inert.
    claim_delta_paths = active_delta_paths()
    changed_contracts = delta_changed_contract_ids(claim_delta_paths)
    if claim_delta_paths:
        pins = contract_file_pins(contracts)
        for t in tasks:
            ride = sorted(
                c for c in t["contracts"]
                if pins.get(c) == t["file"] and c not in changed_contracts
            )
            if ride:
                errs.append(
                    f"task {t['id']} claims contract(s) {ride} that are "
                    f"unchanged in the active milestone delta range and "
                    f"pinned to its own file "
                    f"{t['file']!r} — a task claims only contracts this "
                    f"milestone changed and interfaces it directly depends "
                    f"on; unchanged self-owned contracts must not ride "
                    f"(v99: GET-only milestone claiming PUT/DELETE). Trim "
                    f"these claims or the milestone's acceptance and "
                    f"invalidation both over-reach."
                )

    # oracle projection, part 1 — mapped node-ids must exist in the frozen
    # suite and be mapped at most once. Whether every node-id that NEEDS a
    # task has one is checked after the reachability machinery below, which
    # supplies the ownership signal (D-57: the carried-forward bucket is
    # computed, never EM-emitted — testchat M6 proved transcribing 58 ids
    # into JSON is the EM tier's dominant failure mode, and the split is
    # mechanically derivable).
    mapped = [n for t in tasks for n in t["tests"]]
    frozen_set = set(frozen_nodeids)
    unknown_map = sorted(set(mapped) - frozen_set)
    if unknown_map:
        errs.append(f"mapped test node-id(s) not in the frozen suite: {unknown_map}")

    # D-131 (2026-08-08): a node-id mapped to more than one task is
    # resolved gate-owned instead of halted — but ONLY after the pinned
    # relocation and the D-64 browser rule below have settled every
    # authority-driven placement, and after AUTO_PLACED is reset, so the
    # resolution observes the final plan and its notes survive to the
    # report. The EM tier repeatedly fails to honor prose placement rules
    # for backend tests (testchat v88: the storage-quarantine node was
    # placed on BOTH the storage task and the api/threads task twice in a
    # row, despite the ERD stating one owner). Same philosophy as D-64: a
    # deterministic placement rule is gate-owned, not EM-owned. The rule:
    # the node's acceptance point is the mapped task that runs LAST in the
    # DAG (its dependency closure covers the earlier claimants), matching
    # the freeze's own "any task downstream of the node's owner" view.
    # Pinned node-ids were already moved to their declared owner above;
    # a duplicate surviving the block below is a genuine error.

    if errs:
        fail(errs)

    order = toposort(tasks)
    if order is None:
        fail(["dependency cycle detected — the plan must be a DAG"])

    # DAG-brief consistency: a brief must not reference a file created by a
    # downstream task. If T3 depends on T4's output, T4 must be in T3's
    # depends_on — otherwise the brief has a forward dependency the DAG can't
    # satisfy. This is mechanically checkable and prevents the class of error
    # where the EM writes a brief that assumes a file exists but schedules its
    # creation after the task that needs it.
    task_by_file = {t["file"]: t["id"] for t in tasks}
    deps_of = {t["id"]: set(t["depends_on"]) for t in tasks}
    def ancestors(tid, cache={}):
        if tid in cache:
            return cache[tid]
        result = set(deps_of[tid])
        for d in list(result):
            result |= ancestors(d, cache)
        cache[tid] = result
        return result
    for t in tasks:
        for other_file, other_id in task_by_file.items():
            if other_id == t["id"]:
                continue
            if other_file in t["brief"] and other_id not in ancestors(t["id"]):
                errs.append(
                    f"task {t['id']} brief references '{other_file}' which is "
                    f"created by {other_id} — but {other_id} is not an ancestor "
                    f"of {t['id']} in the DAG. Either add it to depends_on or "
                    f"rewrite the brief to not assume that file exists."
                )

    # D-133: delta-only brief enforcement for EXISTING files. See the block
    # comment by DELTA_ONLY_MAX_REPORT for the rule and its fail-open/fail-closed
    # boundary. Fires only when the TPM's ERD-DELTA gives an authoritative delta
    # description to diverge from; grandfathers verbatim TPM briefs, new files,
    # and every symbol the TPM's own delta doc names.
    if ERD_DELTA_PATH.exists() or delta_paths:
        delta_text = (
            "\n\n".join(
                text for _, text in active_erd_delta_texts(delta_paths)
            )
            if delta_paths
            else ERD_DELTA_PATH.read_text()
        )
        if delta_text:
            tpm_briefs = _parse_brief_blocks(delta_text)  # {file: (tid, brief)}
            authorized = set(_SYMBOL_RE.findall(delta_text))
            for t in tasks:
                f = t["file"]
                if f not in tpm_briefs:
                    continue  # no TPM delta brief for this file → no authority
                if " ".join(t["brief"].split()) == " ".join(tpm_briefs[f][1].split()):
                    continue  # verbatim TPM brief → synthesis authority, exempt
                defined = _file_defined_symbols(f)
                if not defined:
                    continue  # new/unreadable file → no carried behavior
                offenders = sorted(
                    (_brief_backtick_symbols(t["brief"]) & defined) - authorized
                )
                if offenders:
                    shown = offenders[:DELTA_ONLY_MAX_REPORT]
                    more = len(offenders) - len(shown)
                    errs.append(
                        f"task {t['id']} brief restates carried behavior the "
                        f"delta does not change — {f} defines {shown}"
                        + (f" (+{more} more)" if more else "")
                        + ", which the frozen ERD-DELTA never names as changed "
                        "in this delta (D-133). An existing-file brief "
                        "describes ONLY the delta: drop the restated "
                        "symbol(s), or if that behavior really changes, the "
                        "TPM's ERD-DELTA must say so (route to the spec, not "
                        "an EM brief rewrite)."
                    )

    # Route reachability (testchat M5): a mapped test that exercises an HTTP
    # route can only pass once the task claiming that route contract has run.
    # AST-scan each mapped test for client.<method>("<literal path>") calls;
    # if the matched route is claimed by a task outside this task's dependency
    # closure, the mapping is wrong — the test is scheduled before the route
    # exists, and no coder attempt can ever make it pass. Fail-open on
    # detection: dynamic paths, request helpers, routes without a method
    # field, or routes no task claims do not fire.
    route_by_key = {}
    for r in contracts.get("routes", []):
        if isinstance(r, dict) and "id" in r and "method" in r and "path" in r:
            route_by_key[(r["method"].upper(), r["path"])] = r["id"]

    def match_route(method, path):
        rid = route_by_key.get((method, path))
        if rid:
            return rid
        p_segs = path.strip("/").split("/")
        for (m, template), rid in route_by_key.items():
            if m != method:
                continue
            t_segs = template.strip("/").split("/")
            if len(t_segs) == len(p_segs) and all(
                seg_matches(ts, ps) for ts, ps in zip(t_segs, p_segs)
            ):
                return rid
        return None

    claimers = {}  # route contract id -> task ids claiming it
    for t in tasks:
        for cid in t["contracts"]:
            claimers.setdefault(cid, set()).add(t["id"])

    ast_cache = {}

    def test_routes(nodeid):
        """Route contract ids exercised via client.<method>('<path>') literals."""
        parts = nodeid.split("::")
        path, func = parts[0], parts[-1].split("[")[0]
        if path not in ast_cache:
            try:
                ast_cache[path] = ast.parse(Path(path).read_text(), filename=path)
            except (OSError, SyntaxError):
                ast_cache[path] = None
        tree = ast_cache[path]
        if tree is None:
            return set()
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == func), None)
        if fn is None:
            return set()
        hit = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in HTTP_METHODS
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                rid = match_route(node.func.attr.upper(), node.args[0].value)
                if rid:
                    hit.add(rid)
        return hit

    if route_by_key:
        for t in tasks:
            closure = {t["id"]} | ancestors(t["id"])
            for nodeid in t["tests"]:
                for rid in sorted(test_routes(nodeid)):
                    owners = claimers.get(rid, set())
                    if owners and not owners & closure:
                        owner_str = "/".join(sorted(owners))
                        errs.append(
                            f"task {t['id']}: mapped test {nodeid} exercises "
                            f"{rid}, claimed by {owner_str} which is not in "
                            f"{t['id']}'s dependency closure — the test hits a "
                            f"route that does not exist yet at this point in "
                            f"the DAG. Map this test to {owner_str} or a task "
                            f"that depends on it."
                        )

    # Import reachability (same class as the route check, one artifact over):
    # pytest imports the whole test FILE at collection time, so a module-level
    # import of a module created by a downstream task fails EVERY test in the
    # file — collection error, before any test runs. Granularity is therefore
    # the file: every module a test file imports that maps onto an inventory
    # file must be owned by a task in the mapped task's dependency closure.
    # Fail-open: imports of modules outside the inventory (pre-existing code)
    # and dynamic imports are ignored.
    # Only genuine CREATES gate collection. A module that already exists at the
    # frozen baseline is importable no matter where its modifying task sits in
    # the DAG, so a test file importing it can never hit an ordering collection
    # error. Mapping a MODIFIED inventory file as "created by" its task is a
    # false positive: it forces every test importing two inventory modules into
    # one task's dependency closure — which spuriously halted M34's additive
    # two-file delta (its frozen test imports both src.services.models and
    # src.api.models). Restrict ownership to inventory files absent at baseline;
    # modifies impose no ordering constraint. (The route check above gets this
    # for free by keying only on explicitly-claimed route contracts.)
    module_owner = {}  # dotted module -> owning task id (creates only)
    for t in tasks:
        if t["file"].endswith(".py") and not Path(t["file"]).exists():
            module_owner[t["file"][:-3].replace("/", ".")] = t["id"]

    def file_imports(path):
        """Inventory-owned modules imported at module level of a test file."""
        if path not in ast_cache:
            try:
                ast_cache[path] = ast.parse(Path(path).read_text(), filename=path)
            except (OSError, SyntaxError):
                ast_cache[path] = None
        tree = ast_cache[path]
        if tree is None:
            return set()
        found = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in module_owner:
                        found.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in module_owner:
                    found.add(node.module)
                for a in node.names:
                    cand = f"{node.module}.{a.name}"
                    if cand in module_owner:
                        found.add(cand)
        return found

    for t in tasks:
        closure = {t["id"]} | ancestors(t["id"])
        for tf in sorted({n.split("::")[0] for n in t["tests"]}):
            for mod in sorted(file_imports(tf)):
                owner = module_owner[mod]
                if owner not in closure:
                    errs.append(
                        f"task {t['id']}: mapped test file {tf} imports {mod} "
                        f"at module level, created by {owner} which is not in "
                        f"{t['id']}'s dependency closure — pytest cannot even "
                        f"collect the file before {owner} runs. Map this "
                        f"file's tests to {owner} or later, or add {owner} to "
                        f"{t['id']}'s depends_on."
                    )

    # Placement from frozen data (M35 correction): a node-id pinned by
    # contracts.test_mapping is accepted at the task owning its pinned
    # file — the TPM's declared behavioral ownership is the authority,
    # not any heuristic. The EM maps node-ids "where natural"; the gate
    # moves each pinned node-id to its declared owner, so a mis-placement
    # can never mis-gate. Unpinned node-ids fall through to the D-64
    # browser rule below.
    mapping = contracts.get("test_mapping", {}) or {}
    if not isinstance(mapping, dict):
        fail(["contracts.test_mapping must be an object mapping node-ids "
              "to the file that behaviorally owns them"])
    AUTO_PLACED.clear()
    by_file = {t["file"]: t for t in tasks}
    if mapping:
        for t in tasks:
            moved = []
            for n in t["tests"]:
                owner_file = mapping.get(n)
                if not owner_file or owner_file == t["file"]:
                    continue
                owner = by_file.get(owner_file)
                if owner is None:
                    errs.append(
                        f"task {t['id']}: test {n} is pinned by "
                        f"contracts.test_mapping to {owner_file}, which no "
                        f"task in this plan owns"
                    )
                    continue
                moved.append(n)
            if not moved:
                continue
            t["tests"] = [n for n in t["tests"] if n not in moved]
            added = [n for n in moved if n not in owner["tests"]]
            owner["tests"] = sorted(owner["tests"] + added)
            AUTO_PLACED.append(
                f"{t['id']} -> {owner['id']} (pinned by test_mapping): "
                f"{', '.join(moved)}"
            )

    # D-64: browser tests observe the app through the DOM, not imports, so
    # the closure analysis above cannot see their dependencies — a Playwright
    # test can exercise ANY inventory file (markup, styling, and scripts all
    # shape what the browser renders). Its only safe acceptance point is a
    # task whose dependency closure contains the ENTIRE inventory, i.e. the
    # DAG's final task. testchat M15: the EM mapped a new browser test to the
    # markup task twice despite explicit ERD prose; M35: the EM repeated the
    # same mis-placement twice identically, and the closure repair could not
    # fix it (adding the edge would have closed a cycle). The placement is a
    # deterministic rule, so it is gate-owned: any browser node-id mapped to
    # a task with an incomplete closure is MOVED to the final task, not
    # rejected. The EM prompt no longer states the rule (M35 correction).
    # M35b: a node-id pinned by contracts.test_mapping is exempt — pinned
    # behavioral ownership is the authority, and this rule is only the
    # fallback for UNPINNED browser node-ids.
    def is_browser_test_file(path):
        if path not in ast_cache:
            try:
                ast_cache[path] = ast.parse(Path(path).read_text(), filename=path)
            except (OSError, SyntaxError):
                ast_cache[path] = None
        tree = ast_cache[path]
        if tree is None:
            return False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[0] == "playwright" for a in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "playwright":
                    return True
        return False

    all_task_ids = {t["id"] for t in tasks}
    finals = [t for t in tasks
              if ({t["id"]} | ancestors(t["id"])) == all_task_ids]
    final_task = finals[0] if len(finals) == 1 else None
    for t in tasks:
        closure = {t["id"]} | ancestors(t["id"])
        if closure == all_task_ids:
            continue
        browser_files = sorted(
            tf for tf in {n.split("::")[0] for n in t["tests"]}
            if is_browser_test_file(tf)
        )
        if not browser_files:
            continue
        if final_task is None:
            errs.append(
                f"task {t['id']}: browser test file(s) {browser_files} are "
                f"mapped here, but the DAG has no single final task — "
                f"auto-placement impossible (D-64); make the DAG converge or "
                f"map these tests to a task whose dependency closure "
                f"contains the entire inventory."
            )
            continue
        # A node-id pinned by contracts.test_mapping is exempt: its pinned
        # owner IS its acceptance point (the M35 authority), so the fallback
        # must never sweep it off that owner — otherwise the persisted plan
        # empties a task the acceptance gate then rejects on re-validation
        # (M35b: the v84 run committed exactly that emptied plan as "plan ok").
        moved = [n for n in t["tests"]
                 if n.split("::")[0] in browser_files and mapping.get(n) is None]
        if not moved:
            continue
        t["tests"] = [n for n in t["tests"] if n not in moved]
        final_task["tests"] = sorted(final_task["tests"] + moved)
        AUTO_PLACED.append(
            f"{t['id']} -> {final_task['id']}: {', '.join(browser_files)}"
        )

    # D-131 (2026-08-08): gate-owned resolution of duplicate node-ids.
    # Everything above had its chance to place node-ids authoritatively
    # (pinned relocation, browser rule). What remains multiply-mapped is a
    # pure EM mis-placement, and the DAG can VOTE: the node's acceptance
    # point is the mapped task that runs LAST in topological order, because
    # its dependency closure contains every earlier mapped task — so it is
    # the one mapped task after which the node is provably green. That is
    # the same "downstream is acceptable" view the freeze's own acceptance
    # gate uses, so the resolution can never reject a test the freeze
    # considers well-mapped. Pinned re-adds are exempt: mapping already
    # moved each padding node to its declared owner; a node pinned by
    # test_mapping can at most be duplicated by the D-64 sweep, and D-64
    # already skips mapped (pinned) node-ids, so anything over-mapped here
    # is UNPINNED by construction. Resolve by dropping the node from every
    # mapped task except the topologically-last one.
    remapped = [n for t in tasks for n in t["tests"]]
    still = sorted({n for n in remapped if remapped.count(n) > 1})
    if still:
        order = toposort(tasks)
        if order is None:
            errs.append(
                f"test node-id(s) mapped to more than one task: {still} — "
                "and the DAG has a cycle, so D-131 cannot order the "
                "claimants; resolve the duplicate by hand"
            )
        else:
            rank = {tid: i for i, tid in enumerate(order)}
            for t in tasks:
                keep, drop = [], []
                for n in t["tests"]:
                    if n not in still:
                        keep.append(n)
                        continue
                    owners = [tt["id"] for tt in tasks if n in tt["tests"]]
                    if t["id"] != max(owners, key=rank.get):
                        drop.append(n)
                    else:
                        keep.append(n)
                if drop:
                    t["tests"] = keep
                    AUTO_PLACED.append(
                        f"{t['id']} drops overmapped (D-131, kept on LAST "
                        f"mapped task): {', '.join(sorted(set(drop)))}"
                    )
            after = [n for t in tasks for n in t["tests"]]
            gone = sorted({n for n in after if after.count(n) > 1})
            if gone:
                errs.append(
                    f"test node-id(s) mapped to more than one task: {gone}"
                )

    # Non-vacuous acceptance (M35 correction): a task with no mapped test
    # and no smoke check is rejected — enforced at plan-gate level (see
    # the "needs an acceptance signal" check above). The complementary
    # half lives at freeze time: every smoke check must be RED on the
    # unchanged file (refreeze.sh), so a vacuous check can never satisfy
    # the invariant.

    # oracle projection, part 2 (D-57) — the carried-forward split, computed
    # from the same ownership signals the reachability gates already extract:
    # an unmapped frozen node-id whose test file imports a task-owned module,
    # or whose test body hits a route some task claims, belongs to THIS delta
    # and must be mapped — decomposition incomplete. Everything else is a
    # carried-forward regression test, auto-assigned; the final full-suite
    # run is its acceptance point. Fail-open by construction: a dynamic
    # import or built-up path hides the signal, which can only move a test
    # INTO regression — it still gates the run at the end, just not per-task.
    AUTO_REGRESSION.clear()
    for n in sorted(frozen_set - set(mapped)):
        tf = n.split("::")[0]
        owned = bool(file_imports(tf))
        if not owned:
            for rid in test_routes(n):
                if claimers.get(rid):
                    owned = True
                    break
        if owned:
            errs.append(
                f"frozen node-id {n} is mapped to no task, but its test "
                f"observably exercises this delta's inventory (module import "
                f"or claimed route) — decomposition incomplete: map it to "
                f"the task after which it should pass"
            )
        else:
            AUTO_REGRESSION.append(n)

    if errs:
        fail(errs)

    return plan, order


def registered_route_literals(src_root):
    """AST-visible route registrations under src_root, as (METHOD-or-None,
    path-literal, file). Catches decorator and call forms alike (both are
    ast.Call): <obj>.get("/x"), <obj>.route("/x", ...), add_api_route,
    add_url_rule. Registrations without a leading-slash string literal
    (mounts, prefix-only "" paths, computed paths) are invisible — callers
    must treat absence as 'no signal', never as proof of absence."""
    root = Path(src_root)
    if not root.is_dir():
        return []
    out = []
    for f in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(), filename=str(f))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.startswith("/")):
                attr = node.func.attr
                if attr in HTTP_METHODS:
                    out.append((attr.upper(), node.args[0].value, str(f)))
                elif attr in ROUTE_REGISTRARS:
                    out.append((None, node.args[0].value, str(f)))
    return out


def literal_registers(method, path, reg_method, literal):
    """Does a registration literal serve the frozen route (method, path)?
    Routers mount under prefixes (testchat: APIRouter(prefix='/api/v1') +
    @router.get('/models')), so the literal matches any segment-aligned
    SUFFIX of the full path template, with {param} segments wild on either
    side. '/' only matches '/' exactly."""
    if reg_method is not None and method and reg_method != method:
        return False
    l_segs = path_segs(literal)
    if not l_segs:
        return path.strip("/") == ""
    p_segs = path_segs(path)
    if len(l_segs) > len(p_segs):
        return False
    tail = p_segs[len(p_segs) - len(l_segs):]
    return all(seg_matches(ts, ls) for ts, ls in zip(tail, l_segs))


GREP_FAMILY = {"grep", "egrep", "rg", "ripgrep", "ack"}


def _grep_pattern(cmd):
    """If cmd is a single grep-family invocation, return (pattern, mode) where
    mode is 'fixed' for -F/fgrep and 'regex' otherwise. Return (None, None) for
    anything else — compound commands (|, ;, &&), non-grep tools, or grep
    invocations we cannot confidently parse (a shell substitution as the
    pattern, `-e` with no argument). Silent no-signal by design: this check
    only speaks about patterns it can read.
    """
    try:
        toks = shlex.split(cmd, posix=True)
    except ValueError:
        return None, None
    if not toks:
        return None, None
    # Bail on anything that isn't a single simple command. shlex.split does not
    # split on shell operators; a literal `|`/`;`/`&&`/`||` token means the
    # command has more than one clause and we can't reason about the pattern.
    if any(t in ("|", ";", "&&", "||", "&") for t in toks):
        return None, None
    i = 0
    # `git grep …` — accept the same flag surface.
    if toks[0] == "git" and len(toks) > 1 and toks[1] == "grep":
        i = 2
        head = "grep"
    elif toks[0] == "fgrep":
        return None, "fixed"  # legacy alias; treat as fixed-string, no signal
    elif toks[0] in GREP_FAMILY:
        head = toks[0]
        i = 1
    else:
        return None, None
    mode = "regex"
    if head == "grep":
        mode = "basic"
    # Walk flags. `-e PATTERN` explicitly names the pattern; otherwise the
    # first non-flag argument is the pattern.
    while i < len(toks):
        t = toks[i]
        if t == "--":
            i += 1
            if i < len(toks):
                return toks[i], mode
            return None, None
        if t in ("-e", "--regexp"):
            if i + 1 < len(toks):
                return toks[i + 1], mode
            return None, None
        if t.startswith("--"):
            # Long options with =value are self-contained; without =, we don't
            # know if the next token is a value or the pattern. Conservative:
            # if it's a known value-taking option, skip its argument.
            if "=" not in t and t in ("--file", "--regexp", "--include",
                                       "--exclude", "--exclude-dir"):
                i += 2
                continue
            i += 1
            continue
        if t.startswith("-") and len(t) > 1:
            if "F" in t[1:]:
                mode = "fixed"
            if "E" in t[1:] or "P" in t[1:]:
                mode = "regex"
            i += 1
            continue
        return t, mode
    return None, None


_BRIGHT_QUOTES = ('"', "'")


def _quote_brittle(pattern):
    """Return the literal quote character in `pattern` that makes it
    quote-brittle, or None if the pattern is safe.

    Safe forms:
      - no literal quote characters at all
      - every literal quote appears inside a bracket expression `[...]` that
        contains BOTH `'` and `"` (so either quote in source matches)

    Brittle forms (any is enough to flag):
      - a literal quote outside any bracket expression
      - a bracket expression containing only one quote type
    """
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            # backslash-escape: the escaped char is literal, so a `\"` counts
            # as a literal quote just as a bare `"` would.
            nxt = pattern[i + 1]
            if nxt in _BRIGHT_QUOTES:
                return nxt
            i += 2
            continue
        if c == "[":
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            # A `]` as the first character of a bracket expression is literal.
            if j < n and pattern[j] == "]":
                j += 1
            has_dq = has_sq = False
            end = None
            while j < n:
                if pattern[j] == "\\" and j + 1 < n:
                    if pattern[j + 1] == '"':
                        has_dq = True
                    elif pattern[j + 1] == "'":
                        has_sq = True
                    j += 2
                    continue
                if pattern[j] == "]":
                    end = j
                    break
                if pattern[j] == '"':
                    has_dq = True
                elif pattern[j] == "'":
                    has_sq = True
                j += 1
            if end is None:
                # Unterminated bracket: treat the rest as ordinary chars and
                # let any bare quote fail via the outer branch.
                i += 1
                continue
            if (has_dq or has_sq) and not (has_dq and has_sq):
                return '"' if has_dq else "'"
            i = end + 1
            continue
        if c in _BRIGHT_QUOTES:
            return c
        i += 1
    return None


def _quote_agnostic_rewrite(pattern):
    """Rewrite `pattern` so every literal `'`/`"` becomes a `['\"]` char class.
    Purely advisory — printed in the failure to save the TPM a moment of
    guessing at the fix. Preserves backslash escaping so the caller can drop
    the string straight into their command."""
    out = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            if nxt in _BRIGHT_QUOTES:
                out.append("['\\\"]")
                i += 2
                continue
            out.append(c)
            out.append(nxt)
            i += 2
            continue
        if c in _BRIGHT_QUOTES:
            out.append("['\\\"]")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _erd_mass_per_file(erd_text, inventory):
    """Return {file: char_count} — the ERD prose mass attributed to each
    inventory file. Heuristic: for each file, find its first "section-start"
    mention (at line start, optionally after a bullet/heading marker,
    optionally wrapped in backticks/bold), then the section extends from that
    position to the next file's section-start (or end of text). Files with no
    section-start mention yield no entry (no signal, no advisory).

    The ERD is prose, not a schema; this is an approximation whose only job
    is to name the file whose section is heaviest at freeze time so the same
    signal doesn't have to travel through two EM plan calls (testchat M31 v64:
    12 behavioral items concentrated on src/static/app.js, brief overshot
    MAX_BRIEF_CHARS by 197 chars, ~10 min to discover post-plan)."""
    positions = {}
    for f in inventory:
        if not isinstance(f, str):
            continue
        # Line-anchored: filename must sit near the start of a line, with
        # optional list/heading markers and optional bold/backtick wrapping.
        # A mid-sentence mention doesn't open a section.
        pat = re.compile(
            r"(?:\A|\n)[ \t]*"
            r"(?:[-*+][ \t]+|\d+\.[ \t]+|#+[ \t]+|\|[ \t]*)?"
            r"(?:\*\*[ \t]*)?"
            r"[`'\"]?"
            + re.escape(f)
            + r"[`'\"]?"
        )
        m = pat.search(erd_text)
        if m:
            positions[f] = m.start()
    if not positions:
        return {}
    # A `#`-heading closes the current file's section — otherwise the last
    # file in an "As-built architecture" list absorbs the whole "Behavior
    # locked" section that follows and every file after, dominating the mass
    # measurement of the file that actually has the most prose.
    heading_positions = [m.start() for m in
                         re.finditer(r"\n#{1,6}[ \t]+", erd_text)]
    order = sorted(positions.items(), key=lambda kv: kv[1])
    mass = {}
    for i, (f, start) in enumerate(order):
        next_file = order[i + 1][1] if i + 1 < len(order) else len(erd_text)
        next_heading = next((h for h in heading_positions if h > start),
                            len(erd_text))
        mass[f] = min(next_file, next_heading) - start
    return mass


def spec_preflight(old_path, new_path):
    """D-78: freeze-time satisfiability. The plan gate's exact plan↔inventory
    bijection means a task may only target contracts.files members — so a
    new contract whose implementing file is outside the inventory is
    unimplementable by ANY EM, and every plan will be rejected. That is
    provable from the spec alone; prove it here, before a human approves the
    freeze (testchat v51/M28: ~75 minutes and two EM swaps downstream of a
    2-second check).

    Fail-closed on the provable classes, fail-open where the spec carries no
    signal (a brand-new route family names no natural implementing file)."""
    old = {}
    if Path(old_path).is_file():
        old = load_json(Path(old_path), "current frozen contracts")
    new = load_json(Path(new_path), "staged contracts")
    files = set(new.get("files", []))
    editable = files - set(new.get("no_edit_files", []))
    editable_py = {f for f in editable if f.endswith(".py")}
    errs = []
    checked = 0

    # D-86: changed_files is the TPM's scope declaration and reaches the coder
    # through --affected. An entry outside the inventory can never map to a
    # task (the plan gate's bijection is over files), so it would silently
    # declare nothing; an entry that is also no_edit is self-contradictory.
    declared = new.get("changed_files", [])
    if not isinstance(declared, list):
        errs.append("changed_files must be an array of inventory file paths")
        declared = []
    for f in declared:
        checked += 1
        if f not in files:
            errs.append(
                f"changed_files names '{f}', which is not in contracts.files — "
                f"no task can target it, so declaring it scopes nothing"
            )
        elif f not in editable:
            errs.append(
                f"changed_files names '{f}', which is also in no_edit_files — "
                f"declare it in one or the other, not both"
            )

    # entry_points: the implementing file is derivable exactly — the module
    # path. New module → must be buildable (in files) or already on disk.
    # New :symbol on an on-disk module outside the inventory → same v51
    # class, one artifact smaller: no task may add the symbol.
    old_eps = set(old.get("entry_points", []))
    for ep in new.get("entry_points", []):
        if not isinstance(ep, str) or ep in old_eps:
            continue
        checked += 1
        module, _, symbol = ep.partition(":")
        mod_file = module.replace(".", "/") + ".py"
        if mod_file in files:
            continue
        p = Path(mod_file)
        if not p.is_file():
            errs.append(
                f"entry_point '{ep}': implementing file {mod_file} is neither "
                f"in contracts.files nor on disk — no task may create it"
            )
            continue
        if symbol:
            try:
                tree = ast.parse(p.read_text(), filename=mod_file)
            except SyntaxError:
                continue  # unparseable existing module: no signal
            names = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    names.update(t.id for t in node.targets
                                 if isinstance(t, ast.Name))
                elif isinstance(node, ast.AnnAssign) and isinstance(
                        node.target, ast.Name):
                    names.add(node.target.id)
            if symbol not in names:
                errs.append(
                    f"entry_point '{ep}': symbol '{symbol}' does not exist in "
                    f"{mod_file}, which is not in contracts.files — no task "
                    f"may add it"
                )

    # routes: a route's implementing file is not named by the spec, but the
    # source tree carries the signal. Already registered → satisfiable.
    # Not registered → this delta must build it, and its natural home is
    # where its path-siblings are registered (v51: /api/v1/models/catalog
    # belongs beside GET /api/v1/models in src/api/models.py) — that file
    # must be an editable inventory member.
    def route_entries(c):
        return {r["id"]: r for r in c.get("routes", [])
                if isinstance(r, dict) and r.get("id")
                and isinstance(r.get("path"), str)}

    old_routes = route_entries(old)
    new_routes = route_entries(new)
    changed = [
        r for rid, r in sorted(new_routes.items())
        if rid not in old_routes
        or json.dumps(old_routes[rid], sort_keys=True)
        != json.dumps(r, sort_keys=True)
    ]
    if changed:
        regs = registered_route_literals(build_dir())

        def implementers(route):
            method = (route.get("method") or "").upper()
            return sorted({f for m, lit, f in regs
                           if literal_registers(method, route["path"], m, lit)})

        # Sibling evidence comes from every route we can LOCATE in source —
        # old and new alike. Restricting it to old routes would blind the
        # old={} audit form (D-79 runs the preflight with no old contracts):
        # v51's sibling, GET /api/v1/models, is in the new contracts too.
        located = {}
        for rid, r in {**old_routes, **new_routes}.items():
            impl = implementers(r)
            if impl:
                located[rid] = (path_segs(r["path"]), impl)
        for r in changed:
            checked += 1
            rid, path = r["id"], r["path"]
            if rid in located:
                continue  # already registered somewhere; satisfiable
            segs = path_segs(path)
            sibling_files = []
            for k in range(len(segs) - 1, 0, -1):
                sibs = sorted({
                    f
                    for osegs, ofiles in located.values()
                    for f in ofiles
                    if osegs[:k] == segs[:k]
                })
                if sibs:
                    sibling_files = sibs
                    break
            if sibling_files:
                if not set(sibling_files) & editable:
                    errs.append(
                        f"route '{rid}' ({path}) is new and registered "
                        f"nowhere; its path-siblings live in "
                        f"{', '.join(sibling_files)}, none of which is an "
                        f"editable contracts.files member — no task can "
                        f"implement it (the v51/M28 class). Add the "
                        f"implementing file to contracts.files."
                    )
            elif not editable_py:
                errs.append(
                    f"route '{rid}' ({path}) is new, registered nowhere, and "
                    f"contracts.files has no editable .py file that could "
                    f"register it"
                )
            # else: new route family with editable .py present — the spec
            # names no natural implementing file; no signal, fail open.

    # D-87: static-asset reachability. entry_points and routes are reached by
    # import and registration, both proved above. A stylesheet/script/template
    # is reached only by a textual reference from another file — and nothing
    # checks it, so a new asset whose only possible host is uneditable gets
    # written correctly and never loaded: the task goes green, the ACs fail,
    # and no error names the cause (testchat M31 v62 — src/static/current-chat.css,
    # linkable only from index.html, which was frozen out of the delta).
    # Same shape as the route check: reference found → satisfiable; no
    # reference and every same-suffix host uneditable → provably dead; no
    # host at all → no signal, fail open.
    old_files = set(old.get("files", []))
    new_assets = [f for f in new.get("files", [])
                  if isinstance(f, str) and f not in old_files
                  and not f.endswith(".py") and not Path(f).is_file()]
    if new_assets:
        corpus = {}
        root = Path(build_dir())
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if not p.is_file():
                    continue
                try:
                    corpus[str(p)] = p.read_text(errors="ignore")
                except OSError:
                    continue
        for f in new_assets:
            checked += 1
            base = Path(f).name
            suffix = Path(f).suffix
            if any(base in text for p, text in corpus.items() if p != f):
                continue  # something already references it
            if not suffix:
                continue  # no suffix, no sibling signal
            pat = re.compile(r"[\w./-]+" + re.escape(suffix) + r"(?![\w])")
            hosts = sorted({p for p, text in corpus.items()
                            if p != f and pat.search(text)})
            if hosts and not set(hosts) & editable:
                errs.append(
                    f"file '{f}' is new and referenced nowhere; the file(s) "
                    f"that reference {suffix} assets ({', '.join(hosts)}) are "
                    f"not editable contracts.files members — no task can wire "
                    f"it in, so it would be written and never loaded (the "
                    f"M31 class). Add the referencing file to contracts.files, "
                    f"or fold this content into a file already in scope."
                )
            # else: no host references this asset type — no signal, fail open.

    # D-88: quote-brittle smoke_checks. A spec-authored grep pattern that
    # names a literal `"` or `'` in the matched source rejects a
    # semantically-equivalent implementation using the other quote character —
    # the failure mode is a spec oracle failing a correct file, which the
    # ladder cannot recover from below the TPM (testchat M31 v61:
    # `grep -q '[data-active="true"]' …` failed a CSS that wrote
    # `[data-active='true']`; 4 coder strikes + 2 EM diagnosis calls + an
    # escalation halt, all against a file that satisfied the spec).
    # Only checked for smoke_checks that are new or changed vs `old` — a
    # carried-forward entry has already earned its way through a freeze.
    old_sc = old.get("smoke_checks", {}) if isinstance(
        old.get("smoke_checks"), dict) else {}
    for sc_file, sc_cmd in sorted(new.get("smoke_checks", {}).items()):
        if not isinstance(sc_cmd, str):
            continue
        if old_sc.get(sc_file) == sc_cmd:
            continue  # unchanged
        pattern, mode = _grep_pattern(sc_cmd)
        if pattern is None:
            continue  # not a grep-family invocation we can reason about
        if mode == "fixed":
            # -F/fgrep: char classes don't apply. Any literal quote is
            # brittle by construction; the fix is to switch to -E.
            if any(q in pattern for q in _BRIGHT_QUOTES):
                checked += 1
                errs.append(
                    f"smoke_checks['{sc_file}'] uses fixed-string matching "
                    f"(-F) on a pattern containing a literal quote, which "
                    f"rejects a semantically-equivalent implementation using "
                    f"the other quote character (the M31 v61 class). Switch "
                    f"to `grep -qE` and use a `['\\\"]` character class."
                )
            continue
        checked += 1
        offender = _quote_brittle(pattern)
        if offender is not None:
            rewrite = _quote_agnostic_rewrite(pattern)
            errs.append(
                f"smoke_checks['{sc_file}'] pattern contains a literal "
                f"{offender!r} that would reject an implementation using the "
                f"other quote character (the M31 v61 class: "
                f"`[data-active=\"true\"]` vs `[data-active='true']` is "
                f"semantically identical in HTML/CSS but byte-different, and "
                f"grep sees only bytes). Rewrite the quote(s) as a `['\\\"]` "
                f"character class, e.g. `{rewrite}`. If -E is not already set, "
                f"add it (`grep -qE`)."
            )

    if errs:
        for e in errs:
            print(f"SPEC PREFLIGHT FAIL (D-78): {e}", file=sys.stderr)
        sys.exit(1)
    print(f"spec preflight ok (D-78): {checked} new/changed contract(s) "
          f"implementable by the inventory")


def _id_family(node_id):
    """The stable family of a test node-id: module-prefix + bare test name,
    with any parametrization suffix stripped. Node-ids legitimately flip
    between `module::name[chromium]` and `module::name` (D-116/D-124); the
    family is the form the slice matches on, so the milestone intersection
    cannot be falsified by a presentation shape in either direction."""
    module, sep, name = node_id.rpartition("::")
    return (module + "::" + name.split("[", 1)[0]) if sep else node_id


def milestone_scope_ids(mapping, changed_files, changed_tests,
                        granularity="file", current_ids=None):
    """The authoritative milestone node-id set for ONE delta: which of its
    changed_tests the milestone actually owns. Raw legacy deltas carry
    changed_tests at FILE granularity — orchestrate-testchat v87: a
    2-comment-line diff in tests/test_ui.py staged 58 node-ids, of which only
    the 6 the TPM pinned were the milestone's; the other 52 were relabeled
    leftovers (D-116 class) that leaked into the EM scope and the
    invalidation set (audit 2026-08-08).

    Rule for legacy file-granular deltas: a changed test belongs to the
    milestone iff its family is among the pinned mapping keys (family-matched,
    so the slice survives either id shape), plus any pinned id whose owner
    FILE the delta staged — the D-124 completeness repair, preserved. When
    the mapping carries no pins, the slice is inert and the raw set rides.

    Rule for function-granular deltas (changed_tests_granularity ==
    "function"): the mapping NEVER trims. The producer already recorded
    precisely which test functions changed, and an unpinned NEW or MODIFIED
    test must never be silently discarded — testchat v99: the AC-161 oracle
    `test_quarantine_rename_failure_is_unavailable` rode no test_mapping pin,
    so the file-granular slice emptied its task's tests list and the default
    D-112 verdict could pass without ever running it. The mapping's only
    remaining role here is the D-124 completeness repair: a pinned id whose
    owner file the delta staged rides even if the producer dropped it.
    """
    current = set(current_ids) if current_ids is not None else None
    scope = {n for n in changed_tests if current is None or n in current}
    if mapping:
        pinned = {_id_family(k) for k in mapping}
        if granularity != "function":
            scope = {n for n in scope if _id_family(n) in pinned}
        scope |= {n for n, owner in mapping.items()
                  if owner in set(changed_files)
                  and (current is None or n in current)}
    return sorted(scope)


def _hit_task_ids(tasks, delta, test_slice=None):
    """Task ids a delta invalidates: direct hits (a mapped test changed, a
    referenced contract changed, or the task's file is in the declared
    changed_files) plus transitive dependents.

    `test_slice`, when given, is the run's authoritative
    milestone_scope_ids for this delta — callers pass it when consuming
    the raw changed_tests directly would invalidate tasks the milestone
    never touched (the v87 58-id leak)."""
    changed_tests = set(test_slice
                        if test_slice is not None
                        else delta.get("changed_tests", []))
    changed_contracts = set(delta.get("changed_contract_ids", []))
    changed_files = set(delta.get("changed_files", []))
    by_id = {t["id"]: t for t in tasks}
    hit = {
        tid
        for tid, t in by_id.items()
        if set(t["tests"]) & changed_tests
        or set(t["contracts"]) & changed_contracts
        or t["file"] in changed_files
    }
    # transitive dependents are invalidated too
    grew = True
    while grew:
        grew = False
        for tid, t in by_id.items():
            if tid not in hit and set(t["depends_on"]) & hit:
                hit.add(tid)
                grew = True
    return hit


def cmd_affected(delta_paths):
    plan, _ = validate()
    contracts = load_json(CONTRACTS, "frozen contracts")
    mapping = contracts.get("test_mapping") or {}
    current_ids = {
        line.strip() for line in NODEIDS.read_text().splitlines()
        if line.strip()
    }
    hit = set()
    for delta_path in delta_paths:
        delta = load_json(Path(delta_path), "delta")
        # D-130: same authoritative milestone slice as the subtree scope —
        # relabeled leftover ids (D-116) must not reset tasks the milestone
        # did not touch, or a completed M33-class task re-runs on churn.
        slice_ids = milestone_scope_ids(
            mapping, delta.get("changed_files", []),
            delta.get("changed_tests", []),
            delta.get("changed_tests_granularity", "file"), current_ids)
        invalidation_ids = set(slice_ids) | set(delta.get("retired_tests", []))
        if "retired_tests" not in delta:
            invalidation_ids |= set(delta.get("changed_tests", [])) - current_ids
        hit.update(_hit_task_ids(
            plan["tasks"], delta, sorted(invalidation_ids)))
    for tid in sorted(hit):
        print(tid)


def cmd_milestone_scope(delta_paths):
    """Print the authoritative milestone node-id scope (one per line,
    sorted-unique) for a set of active deltas: the SAME producer the
    subtree scope uses for map_nodeids, so the full-emission EM prompt
    and the subtree re-plan can never disagree on what the milestone
    is (D-130). Raw deltas' changed_tests are file-granular; this is the
    tiny-diff/big-file trim (58 -> 6 for orchestrate-testchat v87)."""
    contracts = load_json(CONTRACTS, "frozen contracts")
    mapping = contracts.get("test_mapping") or {}
    current_ids = ({
        line.strip() for line in NODEIDS.read_text().splitlines()
        if line.strip()
    } if NODEIDS.exists() else None)
    ids = []
    for p in delta_paths:
        d = load_json(Path(p), f"delta {p}")
        ids += milestone_scope_ids(mapping, d.get("changed_files", []),
                                   d.get("changed_tests", []),
                                   d.get("changed_tests_granularity", "file"),
                                   current_ids)
    print("\n".join(sorted(set(ids))))


def cmd_active_erd_context(delta_paths):
    """Emit the compact, complete active ERD instruction packet (D-166)."""
    paths = [Path(path) for path in delta_paths]
    contracts = load_json(CONTRACTS, "frozen contracts")
    if not active_inventory_files(paths, contracts):
        print("(active milestone has no behavioral build inventory)")
        return
    print(compact_active_erd_context(active_erd_delta_texts(paths)))


def cmd_active_inventory(delta_paths):
    """Print the exact active build inventory, one file per line."""
    contracts = load_json(CONTRACTS, "frozen contracts")
    print("\n".join(active_inventory_files(
        [Path(path) for path in delta_paths], contracts)))


_BRIEF_RE = re.compile(r"^###\s+(T\d+)\s*[—-]\s*(\S+?)\s*(?:\s*\([^)]*\))?\s*$")
_MAP_PIN_RE = re.compile(r"`([^`]+)`\s*->\s*`([^`]+)`")


def _parse_brief_blocks(text):
    """{file: (task_id, brief)} from the TPM's "## Coder briefs (verbatim)"
    section. A block opens with `### T<n> — <file> (<label>)` and runs to the
    next heading or end of document; the body is kept verbatim (trimmed of
    leading/trailing blank lines) — the TPM's exact wording is the coder's
    brief, no EM paraphrase in the mechanical lane."""
    out = {}
    m = re.search(r"^##\s+Coder briefs \(verbatim\)\s*$", text, re.M)
    if not m:
        return out
    section = text[m.end():]
    lines = section.splitlines(keepends=True)
    heads = [(i, line) for i, line in enumerate(lines)
             if re.match(r"^#{2,3}\s", line)]
    for k, (ln, line) in enumerate(heads):
        hm = _BRIEF_RE.match(line)
        if not hm:
            continue
        start = sum(len(line) for line in lines[:ln + 1])
        end = sum(len(line) for line in lines[:heads[k + 1][0]]) \
            if k + 1 < len(heads) else len(section)
        body = section[start:end].strip()
        if not body:
            continue
        out[hm.group(2)] = (hm.group(1), body)
    return out


def _brief_backtick_symbols(brief):
    """Identifier tokens a brief names inside backticks — the symbols it claims
    to describe. Only backticked spans count: un-backticked prose ("keep the
    retry loop running") never contributes, so D-133 fires on symbol
    references, not on English about behavior."""
    syms = set()
    for span in re.findall(r"`([^`]+)`", brief):
        syms.update(_SYMBOL_RE.findall(span))
    return syms


def _file_defined_symbols(path):
    """The symbols the current on-disk file DEFINES (def/class/function/
    const/let/var). None when the file is absent or unreadable — a new file
    the delta creates has nothing to restate, so D-133 skips it. A brief
    symbol in this set is carried, pre-existing behavior."""
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    out = set()
    for rx in _DEF_RES:
        out.update(rx.findall(text))
    return out


def _parse_delta_dag(text, brief_files):
    """Dependency edges from the delta's DAG prose, in two forms:
      - "`<file> depends on <file>`" statements
      - "Task order: T1 (label) -> T2 (label) -> ..." chains
    Returns {file: [dep, ...]}. Files must resolve to brief blocks (only
    inventory files are tasks); unresolvable references are returned as
    (extra) refusals the caller reports."""
    edges = {}
    for a, b in re.findall(r"`([^`]+)`\s+depends on\s+`([^`]+)`", text):
        edges.setdefault(a, []).append(b)
    for chain in re.finditer(
            r"Task order:\s*((?:T\d+[^->]*->\s*)+T\d+[^->]*)", text):
        steps = [s.strip() for s in chain.group(1).split("->")]
        ids = [re.match(r"T\d+", s).group(0) for s in steps if re.match(r"T\d+", s)]
        by_id = {tid: f for f, (tid, _) in brief_files.items()}
        for prev, cur in zip(ids, ids[1:]):
            if cur in by_id and prev in by_id:
                edges.setdefault(by_id[cur], []).append(by_id[prev])
    return edges


def _parse_mapping_pins(text):
    """{node-id: file} from the TPM's "## Test-to-file mapping" section —
    the delta-side pin table the frozen contracts.json test_mapping cannot
    yet hold (a NEW test added by this delta is frozen only after the
    freeze; its ownership pin lives here first)."""
    m = re.search(r"^##\s+Test-to-file mapping\s*$", text, re.M)
    if not m:
        return {}
    return dict(_MAP_PIN_RE.findall(text[m.end():]))


_TOP_SECTION_RE = re.compile(r"^##\s+([^\n]+?)\s*$", re.M)
_MAPPING_ROW_RE = re.compile(
    r"(?m)^[ \t]*(?:[*-]\s*)?`[^`\n]+`[ \t]*(?:\n[ \t]*)?"
    r"->[ \t]*`[^`\n]+`[ \t]*(?:\n|$)"
)
_DAG_EDGE_LINE_RE = re.compile(
    r"(?m)^.*`[^`\n]+`\s+depends on\s+`[^`\n]+`.*(?:\n|$)"
)
_TASK_ORDER_LINE_RE = re.compile(r"(?m)^.*Task order:.*(?:\n|$)")
_HISTORICAL_SPEC_HEADINGS = {
    "Changed acceptance criteria",
    "Superseded acceptance criteria",
}


def _top_sections(text):
    """Return preamble plus ordered top-level Markdown sections."""
    matches = list(_TOP_SECTION_RE.finditer(text))
    if not matches:
        return text.strip(), []
    preamble = text[:matches[0].start()].strip()
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1).strip(), text[match.end():end].strip()))
    return preamble, sections


def compact_active_erd_context(erd_texts):
    """Semantically compact model-facing active-freeze instructions (D-166).

    Versioned ERD deltas remain immutable and plan synthesis still consumes
    every raw slice.  This renderer changes only the model-facing view:
    historical preambles, changed-file inventories, and assumptions are audit
    narrative already superseded by the current capsule and active JSON
    inventory. Historical AC changes remain versioned; repeated coder briefs,
    ownership pins, and DAG edges are emitted once in first-seen order. Unique
    incremental execution instructions remain byte-for-byte present. A
    one-freeze milestone keeps its original body.
    """
    texts = list(erd_texts)
    if not texts:
        return "(active milestone has no ERD instructions)"
    if len(texts) == 1:
        version, body = texts[0]
        label = f"v{version}" if version is not None else "unversioned"
        return f"## Active freeze instructions — {label}\n{body.rstrip()}"

    retained_sections = []
    seen_sections = set()
    brief_rows = []
    seen_briefs = set()
    mapping_rows = []
    seen_mappings = set()
    dag_edges = []
    seen_edges = set()
    residual_rows = []
    seen_residuals = set()
    latest_preamble = ""

    for index, (version, body) in enumerate(texts):
        label = f"v{version}" if version is not None else "unversioned"
        is_latest = index == len(texts) - 1
        preamble, sections = _top_sections(body)
        latest_preamble = preamble

        for file_path, (task_id, brief) in _parse_brief_blocks(body).items():
            key = (file_path, brief)
            if key not in seen_briefs:
                seen_briefs.add(key)
                brief_rows.append((label, task_id, file_path, brief))

        for node_id, file_path in _parse_mapping_pins(body).items():
            key = (node_id, file_path)
            if key not in seen_mappings:
                seen_mappings.add(key)
                mapping_rows.append(key)

        local_briefs = _parse_brief_blocks(body)
        for file_path, dependencies in _parse_delta_dag(body, local_briefs).items():
            for dependency in dependencies:
                key = (file_path, dependency)
                if key not in seen_edges:
                    seen_edges.add(key)
                    dag_edges.append(key)

        for heading, section_body in sections:
            if heading == "Coder briefs (verbatim)":
                continue
            if heading == "Test-to-file mapping":
                residual = _MAPPING_ROW_RE.sub("", section_body).strip()
                if is_latest and residual and residual not in seen_residuals:
                    seen_residuals.add(residual)
                    residual_rows.append((label, heading, residual))
                continue
            if "DAG" in heading:
                residual = _DAG_EDGE_LINE_RE.sub("", section_body)
                residual = _TASK_ORDER_LINE_RE.sub("", residual).strip()
                if is_latest and residual and residual not in seen_residuals:
                    seen_residuals.add(residual)
                    residual_rows.append((label, heading, residual))
                continue
            if not is_latest and heading not in _HISTORICAL_SPEC_HEADINGS:
                continue
            key = (heading, section_body)
            if key not in seen_sections:
                seen_sections.add(key)
                retained_sections.append((label, heading, section_body))

    first_version = texts[0][0]
    last_version = texts[-1][0]
    first_label = f"v{first_version}" if first_version is not None else "unversioned"
    last_label = f"v{last_version}" if last_version is not None else "unversioned"
    out = [f"## Active freeze instructions — compacted {first_label}..{last_label}"]
    if latest_preamble:
        out.extend(["", f"<!-- latest freeze preamble: {last_label} -->", latest_preamble])
    for label, heading, section_body in retained_sections + residual_rows:
        out.extend(["", f"<!-- active freeze section: {label} -->", f"## {heading}"])
        if section_body:
            out.extend(["", section_body])
    if mapping_rows:
        out.extend(["", "## Test-to-file mapping (active, deduplicated)", ""])
        out.extend(f"* `{node_id}` -> `{file_path}`" for node_id, file_path in mapping_rows)
    if dag_edges:
        out.extend(["", "## Task DAG (active, deduplicated)", ""])
        out.extend(f"`{file_path}` depends on `{dependency}`"
                   for file_path, dependency in dag_edges)
    if brief_rows:
        out.extend(["", "## Coder briefs (active, deduplicated)"])
        for label, task_id, file_path, brief in brief_rows:
            out.extend(["", f"### {label}/{task_id} — {file_path}", "", brief])

    compact = "\n".join(out).rstrip() + "\n"
    raw = "\n\n".join(
        f"## Active freeze instructions — "
        f"{f'v{version}' if version is not None else 'unversioned'}\n{body.rstrip()}"
        for version, body in texts
    ) + "\n"
    return compact if len(compact.encode()) <= len(raw.encode()) else raw.rstrip()


def cmd_synthesize_plan(delta_paths):
    """Mechanical plan synthesis (B3): when the TPM's ERD-DELTA carries the
    complete decomposition — a verbatim coder brief for EVERY inventory file,
    a DAG statement, and a test-to-file pin for every milestone node-id — the
    plan is fully determined and no EM call is needed. This command prints
    that plan JSON to stdout; ensure_plan then runs the full validate() gate
    over it and the gate (not this command) is the authority. On any missing
    piece it refuses (exit 1, reasons on stderr) and the orchestrator falls
    back to the EM full emission with the reasons as context — the EM is
    exception-only in the mechanical lane.

    Ownership rules (all gate-checked afterwards by validate()):
      - one task per contracts.files entry; brief = TPM verbatim block
      - tests = milestone_scope_ids(node-ids whose owner file is this task's:
        frozen test_mapping ∪ ERD-DELTA Test-to-file mapping) — plus, per
        D-124's v99 fix, a NEW test pinned in the delta's mapping section
        rides even when the legacy file-granular slice dropped it
      - contracts = changed_contract_ids pinned to this task's file
        (D-120 pins / entry-point self-pins); ride-along claims are never
        synthesized
      - depends_on = the delta's DAG prose (`A` depends on `B` statements and
        Task-order chains), resolved to brief-file tasks
    """
    paths = [Path(p) for p in delta_paths]
    deltas = [load_json(path, f"delta {path}") for path in paths]
    contracts = load_json(CONTRACTS, "frozen contracts")
    files = active_inventory_files(paths, contracts)
    current_ids = ({
        line.strip() for line in NODEIDS.read_text().splitlines()
        if line.strip()
    } if NODEIDS.exists() else None)
    if not files:
        scope = set()
        for delta in deltas:
            scope.update(milestone_scope_ids(
                contracts.get("test_mapping") or {},
                delta.get("changed_files", []),
                delta.get("changed_tests", []),
                delta.get("changed_tests_granularity", "file"), current_ids,
            ))
        changed_contracts = {
            contract_id for delta in deltas
            for contract_id in delta.get("changed_contract_ids", [])
        }
        if scope or changed_contracts:
            fail(["--synthesize-plan: empty active inventory conflicts with "
                  f"runnable tests {sorted(scope)} or changed contracts "
                  f"{sorted(changed_contracts)}"])
        frozen_v = int(VERSION.read_text().strip()) if VERSION.exists() else 1
        print(json.dumps({
            "version": 1, "erd_version": frozen_v, "tasks": [],
        }, indent=2))
        return
    erd_texts = active_erd_delta_texts(paths)
    briefs = {}
    for _, body in erd_texts:
        for file_path, (task_id, brief) in _parse_brief_blocks(body).items():
            if file_path in briefs:
                prior_id, prior_brief = briefs[file_path]
                briefs[file_path] = (
                    prior_id,
                    f"{prior_brief.rstrip()}\n\n{brief.lstrip()}",
                )
            else:
                briefs[file_path] = (task_id, brief)
    missing = [f for f in files if f not in briefs]
    if missing:
        fail(["--synthesize-plan: no verbatim coder brief for "
              f"{len(missing)} inventory file(s): {sorted(missing)} — TPM "
              "briefs for every file are the mechanical-lane precondition; "
              "the EM must emit the full plan"])
    ids = [briefs[f][0] for f in files]
    if len(set(ids)) != len(ids):
        ids = [f"T{i}" for i in range(1, len(files) + 1)]
    task_ids = {f: ids[i] for i, f in enumerate(files)}

    edges = {}
    for _, body in erd_texts:
        local_briefs = _parse_brief_blocks(body)
        for file_path, deps_for_file in _parse_delta_dag(
            body, local_briefs,
        ).items():
            edges.setdefault(file_path, []).extend(deps_for_file)
    unknown = sorted(set(edges) - set(files))
    if unknown:
        fail(["--synthesize-plan: DAG prose references non-inventory file(s) "
              f"{unknown} — no task can own their dependency edges"])
    targets = {d for deps in edges.values() for d in deps}
    unknown_t = sorted(targets - set(files))
    if unknown_t:
        fail(["--synthesize-plan: DAG prose depends on non-inventory file(s) "
              f"{unknown_t} — no task can claim those dependency edges"])
    if len(files) > 1 and not edges:
        fail(["--synthesize-plan: no DAG statement in ERD-DELTA (no "
              "`<file> depends on <file>` line and no Task-order chain) — "
              "dependencies are semantic, never assumed empty; the EM must "
              "emit the full plan"])
    deps = {f: sorted({task_ids[d] for d in edges.get(f, [])}) for f in files}
    for f in files:
        if task_ids[f] in deps[f]:
            fail([f"--synthesize-plan: self-dependency in DAG prose for {f}"])

    scope = []
    for d in deltas:
        scope += milestone_scope_ids(
            contracts.get("test_mapping") or {},
            d.get("changed_files", []),
            d.get("changed_tests", []),
            d.get("changed_tests_granularity", "file"), current_ids)
    pins = dict(contracts.get("test_mapping") or {})
    for _, body in erd_texts:
        pins.update(_parse_mapping_pins(body))
    unpinned = sorted(set(scope) - set(pins))
    if unpinned:
        fail(["--synthesize-plan: milestone node-id(s) with no ownership pin "
              f"in test_mapping or the delta's Test-to-file mapping: "
              f"{unpinned} — the EM must place them"])

    changed_contracts = set()
    for d in deltas:
        changed_contracts |= set(d.get("changed_contract_ids", []))
    cpins = contract_file_pins(contracts)

    tasks = []
    for f in files:
        tasks.append({
            "id": task_ids[f],
            "file": f,
            "depends_on": deps[f],
            "brief": briefs[f][1],
            "contracts": sorted(c for c in changed_contracts
                                if cpins.get(c) == f),
            "tests": sorted(n for n, owner in pins.items()
                            if owner == f and n in set(scope)),
        })
    frozen_v = 1
    if VERSION.exists():
        try:
            frozen_v = int(VERSION.read_text().strip())
        except ValueError:
            pass
    print(json.dumps({
        "version": 1,
        "erd_version": frozen_v,
        "tasks": tasks,
    }, indent=2))


def _load_plan_lenient(path, what="prior plan"):
    """Structural load of a plan that validated against a PREVIOUS spec —
    the full validate() would rightly reject it as stale, but the subtree
    machinery only needs its task graph to be well-formed."""
    plan = load_json(Path(path), what)
    if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list) \
            or not plan["tasks"]:
        fail([f"{what}: not a plan-shaped object (non-empty tasks array required)"])
    errs = []
    for i, t in enumerate(plan["tasks"]):
        if not isinstance(t, dict):
            errs.append(f"{what}: tasks[{i}] is not an object")
            continue
        missing = TASK_REQUIRED - set(t)
        if missing:
            extra = sorted(set(t) - TASK_REQUIRED)
            errs.append(
                f"{what}: tasks[{i}] missing required key(s) {sorted(missing)}"
                + (f"; has unexpected {extra} (task keys are exactly "
                   f"{sorted(TASK_REQUIRED)})" if extra else ""))
            continue
        if not isinstance(t["id"], str) or not isinstance(t["file"], str):
            errs.append(f"{what}: tasks[{i}]: id and file must be strings")
        for key in ("depends_on", "contracts", "tests"):
            if not isinstance(t[key], list) \
                    or not all(isinstance(x, str) for x in t[key]):
                errs.append(f"{what}: task {t.get('id')}: {key} must be an "
                            f"array of strings")
    if errs:
        fail(errs)
    return plan


def cmd_subtree_scope(prior_path, delta_paths):
    """What must a delta re-plan cover? Computed against the prior plan and
    the CURRENT frozen spec. Prints a scope JSON for the orchestrator.
    Refuses (exit 1, reason on stderr) whenever a subtree re-plan cannot
    soundly express the delta; the caller falls back to full emission."""
    prior = _load_plan_lenient(prior_path)
    contracts = load_json(CONTRACTS, "frozen contracts")
    if not NODEIDS.exists():
        fail(["frozen test-nodeids missing — run scripts/refreeze.sh first"])
    current_ids = {
        line.strip() for line in NODEIDS.read_text().splitlines() if line.strip()
    }
    inventory = active_inventory_files([Path(p) for p in delta_paths], contracts)
    tasks = prior["tasks"]
    prior_files = {t["file"] for t in tasks}
    removed = sorted(prior_files - set(inventory))
    if removed:
        fail([f"subtree scope refused: file(s) left the inventory: {removed} "
              f"— carried briefs and dependencies may assume them; re-plan "
              f"in full"])
    deltas = [load_json(Path(p), f"delta {p}") for p in delta_paths]
    mapping = contracts.get("test_mapping") or {}
    hit = set()
    changed_tests = set()
    contract_changed = False
    for d in deltas:
        # D-130: the delta's authoritative milestone slice (mapping ∩
        # changed tests, family-matched) drives BOTH what invalidates and
        # what the EM maps. Raw changed_tests are file-granular: a tiny
        # diff in a big test file stages every node-id it contains, but
        # only the pinned test-level set is this milestone's work — the
        # rest (relabeled leftovers, D-116) must neither re-plan carried
        # tasks nor enter map_ids (audit 2026-08-08: v87 staged 6 real +
        # 52 relabeled; the run re-emitted and re-mapped all 58).
        slice_ids = milestone_scope_ids(
            mapping, d.get("changed_files", []), d.get("changed_tests", []),
            d.get("changed_tests_granularity", "file"), current_ids)
        invalidation_ids = set(slice_ids) | set(d.get("retired_tests", []))
        if "retired_tests" not in d:
            invalidation_ids |= set(d.get("changed_tests", [])) - current_ids
        hit |= _hit_task_ids(tasks, d, sorted(invalidation_ids))
        changed_tests |= set(slice_ids)
        if d.get("changed_contract_ids"):
            contract_changed = True
    reemit = [{"file": t["file"], "keep_id": t["id"]}
              for t in tasks if t["id"] in hit]
    new_files = sorted(set(inventory) - prior_files)
    # Node-ids the EM must (re)map: the deltas' still-current changed tests,
    # plus everything previously mapped to a task being re-emitted. Any
    # changed id that was previously mapped belongs to a hit task by
    # construction (the mapping intersection is what made the task hit), so
    # nothing here is still mapped on a carried task — no overmap possible.
    map_ids = sorted(
        (changed_tests & current_ids)
        | {n for t in tasks if t["id"] in hit for n in t["tests"]
           if n in current_ids}
    )
    if map_ids and not (reemit or new_files):
        fail(["subtree scope refused: the delta changes mapped/new tests but "
              "re-plans no file — the mappings would have to land on carried "
              "tasks, which a subtree reply cannot express; re-plan in full"])
    carried = [{"id": t["id"], "file": t["file"], "depends_on": t["depends_on"]}
               for t in tasks if t["id"] not in hit]
    # Cut 2: mechanical-construction eligibility. When the delta re-plans
    # exactly ONE existing file with no contract changes across any delta in
    # the range, no judgment survives for the EM to add — the file's carried
    # brief and contracts still describe what it does, and the D-59 edit-mode
    # coder receives its current content anyway. The shell can build the
    # subtree from the prior task + the delta's new node-ids; if the new
    # tests demand behavior the carried brief doesn't cover, mapped tests
    # go red and the escalation ladder summons the EM at its consult rung
    # (D-70) — exactly where its judgment is real. New files stay EM-only
    # (contract selection is a semantic call the shell can't make).
    trivial_construct = (
        len(reemit) == 1
        and not new_files
        and not contract_changed
    )
    print(json.dumps({
        "prior_version": prior.get("version", 1),
        "reemit": reemit,
        "new_files": new_files,
        "map_nodeids": map_ids,
        "carried": carried,
        "em_needed": bool(reemit or new_files),
        "trivial_construct": trivial_construct,
    }, indent=2))


def cmd_construct_one_file(prior_path, scope_path, delta_paths=()):
    """Cut 2 mechanical constructor. Reads the prior plan + subtree scope and
    prints a subtree JSON with exactly one task. Contracts and dependencies
    carry from the prior task; tests update to scope.map_nodeids. When the
    active delta range supplies a TPM-authored verbatim brief for this file,
    the latest one is authoritative and replaces the carried brief. Refuses
    non-trivial scopes so the eligibility check lives with the scope logic
    (single source of truth)."""
    scope = load_json(Path(scope_path), "subtree scope")
    if not scope.get("trivial_construct"):
        fail(["scope is not trivial_construct — mechanical construction "
              "refused; the EM subtree emission path applies"])
    if not VERSION.exists():
        fail(["frozen VERSION missing — run scripts/refreeze.sh first"])
    frozen_v = int(VERSION.read_text().strip())
    prior = _load_plan_lenient(prior_path)
    r = scope["reemit"][0]
    prior_task = next((t for t in prior["tasks"] if t["id"] == r["keep_id"]),
                      None)
    if prior_task is None:
        fail([f"scope.reemit references keep_id {r['keep_id']} which is not "
              f"in the prior plan"])
    brief = prior_task["brief"]
    if delta_paths:
        for _, body in active_erd_delta_texts(
            [Path(delta_path) for delta_path in delta_paths],
        ):
            delta_brief = _parse_brief_blocks(body).get(r["file"])
            if delta_brief is not None:
                brief = delta_brief[1]
    task = {
        "id": r["keep_id"],
        "file": r["file"],
        "depends_on": prior_task["depends_on"],
        "brief": brief,
        "contracts": prior_task["contracts"],
        "tests": scope["map_nodeids"],
    }
    print(json.dumps({
        "version": 1,               # --merge-subtree renumbers
        "erd_version": frozen_v,    # --merge-subtree overwrites
        "tasks": [task],
    }))


def cmd_merge_subtree(prior_path, subtree_path, scope_path):
    """Merge the EM's subtree reply over the carried-forward prior plan and
    write tasks/plan.json. '-' as SUBTREE means the delta needed no EM
    tasks (docs-only / test-removal-only re-freeze): carried tasks merge
    mechanically with zero EM involvement.

    Id discipline is REJECTED, never repaired: a task for a re-planned file
    must carry that file's prior id (carried depends_on references stay
    valid by construction), and a new-file task id must collide with
    nothing. Silent renumbering would make depends_on references ambiguous
    — a wrong id is validator feedback for the EM's revision, not something
    to guess around. The merged artifact then faces the FULL validate()
    gate, unchanged."""
    prior = _load_plan_lenient(prior_path)
    scope = load_json(Path(scope_path), "subtree scope")
    if not VERSION.exists():
        fail(["frozen VERSION missing — run scripts/refreeze.sh first"])
    frozen_v = int(VERSION.read_text().strip())
    current_ids = set()
    if NODEIDS.exists():
        current_ids = {
            line.strip() for line in NODEIDS.read_text().splitlines()
            if line.strip()
        }
    keep_id = {r["file"]: r["keep_id"] for r in scope.get("reemit", [])}
    allowed = set(keep_id) | set(scope.get("new_files", []))
    hit_ids = set(keep_id.values())
    carried = [t for t in prior["tasks"] if t["id"] not in hit_ids]
    carried_ids = {t["id"] for t in carried}

    sub_tasks = []
    if subtree_path == "-":
        if allowed:
            fail([f"empty subtree ('-') but the scope requires tasks for: "
                  f"{sorted(allowed)}"])
    else:
        sub = load_json(Path(subtree_path), "subtree reply")
        if not isinstance(sub, dict) or not isinstance(sub.get("tasks"), list):
            fail(["subtree reply: a tasks array is required"])
        sub_tasks = sub["tasks"]
        errs = []
        for i, t in enumerate(sub_tasks):
            if not isinstance(t, dict):
                errs.append(f"subtree reply: tasks[{i}] is not an object")
            elif TASK_REQUIRED - set(t):
                missing = sorted(TASK_REQUIRED - set(t))
                extra = sorted(set(t) - TASK_REQUIRED)
                errs.append(
                    f"subtree reply: tasks[{i}] missing required key(s) {missing}"
                    + (f"; has unexpected {extra} (task keys are exactly "
                       f"{sorted(TASK_REQUIRED)})" if extra else ""))
        if errs:
            fail(errs)
        sub_files = [t["file"] for t in sub_tasks]
        dupes = sorted({f for f in sub_files if sub_files.count(f) > 1})
        if dupes:
            fail([f"subtree reply plans the same file twice: {dupes}"])
        over = sorted(set(sub_files) - allowed)
        if over:
            fail([f"subtree reply plans file(s) outside the delta scope: "
                  f"{over} — emit tasks ONLY for: {sorted(allowed)}"])
        missing = sorted(allowed - set(sub_files))
        if missing:
            fail([f"subtree reply is missing task(s) for: {missing}"])
        errs = []
        used = set(carried_ids)
        for t in sub_tasks:
            if t["file"] in keep_id:
                if t["id"] != keep_id[t["file"]]:
                    errs.append(
                        f"subtree reply: the task for {t['file']} must keep "
                        f"the carried plan's id {keep_id[t['file']]}, got "
                        f"{t['id']} — carried tasks reference that id")
            elif t["id"] in used:
                errs.append(
                    f"subtree reply: new-file task id {t['id']} collides "
                    f"with a carried task id — use a fresh T-id")
            used.add(t["id"])
        if errs:
            fail(errs)

    all_ids = carried_ids | {t["id"] for t in sub_tasks}
    for t in carried:
        # Stale mappings cannot survive on carried tasks by construction
        # (a removed id was mapped -> its task was hit -> re-emitted), but
        # the delta files are computed by refreeze.sh — filter defensively
        # rather than trust a second tool's invariant.
        t["tests"] = [n for n in t["tests"] if n in current_ids]
        t["depends_on"] = [d for d in t["depends_on"] if d in all_ids]
    merged = {
        "version": int(prior.get("version", 1)) + 1,
        "erd_version": frozen_v,
        "tasks": carried + sub_tasks,
    }
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(merged, indent=2) + "\n")
    print(f"merged: {len(carried)} carried + {len(sub_tasks)} subtree "
          f"task(s) -> {PLAN} (erd_version {frozen_v}, "
          f"version {merged['version']})")


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
    rb = d.get("revised_brief", "")
    if isinstance(rb, str) and len(rb) > MAX_BRIEF_CHARS:
        errs.append(
            f"diagnosis.revised_brief is {len(rb)} chars (max {MAX_BRIEF_CHARS}) "
            f"— Rule 8 applies to revised briefs too; a revised brief must not "
            f"reintroduce the overload the plan gate rejects"
        )
    if errs:
        fail(errs)
    print(d["verdict"])


# ---------------------------------------------------------------------------
# Closure auto-repair (D-64 browser / import / route). Best-effort PRE-PASS,
# run by orchestrate.sh BEFORE the validate() gate. Only ADDS depends_on edges
# (monotone: tests schedule later, never earlier) and only when the addition
# keeps the DAG acyclic; a would-be cycle is reverted and left for validate()
# to reject — identical to no repair. validate() runs UNCHANGED after this and
# is the authority: a bug here can never make a bad plan pass, only fail to
# repair. Detection mirrors validate()'s route/import/browser closure checks.
# ---------------------------------------------------------------------------
def _closure_needs(tasks, contracts):
    """[(task_id, frozenset(owner_ids the task's closure must gain))] for every
    mapped test whose route/import/browser closure is unsatisfied. Mirrors the
    validate() closure checks (route ~L497, import ~L562, browser D-64 ~L603)."""
    deps_of = {t["id"]: set(t.get("depends_on", [])) for t in tasks}

    def ancestors(tid):
        out, stack = set(), list(deps_of.get(tid, ()))
        while stack:
            d = stack.pop()
            if d in out:
                continue
            out.add(d)
            stack.extend(deps_of.get(d, ()))
        return out

    all_ids = {t["id"] for t in tasks}
    cache = {}

    def tree(path):
        if path not in cache:
            try:
                cache[path] = ast.parse(Path(path).read_text(), filename=path)
            except (OSError, SyntaxError):
                cache[path] = None
        return cache[path]

    route_by_key = {}
    for r in contracts.get("routes", []):
        if isinstance(r, dict) and {"id", "method", "path"} <= set(r):
            route_by_key[(r["method"].upper(), r["path"])] = r["id"]

    def match_route(method, path):
        rid = route_by_key.get((method, path))
        if rid:
            return rid
        p = path.strip("/").split("/")
        for (m, tmpl), rid in route_by_key.items():
            if m != method:
                continue
            ts = tmpl.strip("/").split("/")
            if len(ts) == len(p) and all(
                a == b or (a[:1] == "{" and a[-1:] == "}")
                for a, b in zip(ts, p)
            ):
                return rid
        return None

    claimers = {}
    for t in tasks:
        for cid in t.get("contracts", []):
            claimers.setdefault(cid, set()).add(t["id"])

    def test_routes(nodeid):
        p = nodeid.split("::")[0]
        func = nodeid.split("::")[-1].split("[")[0]
        tr = tree(p)
        if tr is None:
            return set()
        fn = next((n for n in ast.walk(tr)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == func), None)
        if fn is None:
            return set()
        hit = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in HTTP_METHODS
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                rid = match_route(node.func.attr.upper(), node.args[0].value)
                if rid:
                    hit.add(rid)
        return hit

    module_owner = {}
    for t in tasks:
        if t["file"].endswith(".py") and not Path(t["file"]).exists():
            module_owner[t["file"][:-3].replace("/", ".")] = t["id"]

    def file_imports(tf):
        tr = tree(tf)
        if tr is None:
            return set()
        found = set()
        for node in tr.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in module_owner:
                        found.add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in module_owner:
                    found.add(node.module)
                for a in node.names:
                    cand = f"{node.module}.{a.name}"
                    if cand in module_owner:
                        found.add(cand)
        return found

    def is_browser(tf):
        tr = tree(tf)
        if tr is None:
            return False
        for node in ast.walk(tr):
            if isinstance(node, ast.Import) and any(
                    a.name.split(".")[0] == "playwright" for a in node.names):
                return True
            if (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.split(".")[0] == "playwright"):
                return True
        return False

    needs = []
    for t in tasks:
        closure = {t["id"]} | ancestors(t["id"])
        test_files = {n.split("::")[0] for n in t.get("tests", [])}
        for nodeid in t.get("tests", []):
            for rid in test_routes(nodeid):
                owners = claimers.get(rid, set())
                if owners and not (owners & closure):
                    needs.append((t["id"], frozenset(owners)))
        for tf in test_files:
            for mod in file_imports(tf):
                owner = module_owner[mod]
                if owner not in closure:
                    needs.append((t["id"], frozenset({owner})))
        if closure != all_ids and any(is_browser(tf) for tf in test_files):
            needs.append((t["id"], frozenset(all_ids - closure)))
    return needs


def _repair_apply(tasks, needs_fn):
    """Add depends_on edges to satisfy needs_fn(tasks), skipping any addition
    that would create a cycle (toposort None). Fixpoint, bounded by task count.
    Returns [(task_id, [added_ids])]. Pure w.r.t. detection — unit-tested with a
    synthetic needs_fn."""
    by_id = {t["id"]: t for t in tasks}
    repairs = []
    for _ in range(len(tasks) + 1):
        progressed = False
        for tid, owners in needs_fn(tasks):
            task = by_id.get(tid)
            if task is None:
                continue
            add = {o for o in owners if o != tid and o in by_id} \
                - set(task["depends_on"])
            if not add:
                continue
            saved = list(task["depends_on"])
            task["depends_on"] = sorted(set(task["depends_on"]) | add)
            if toposort(tasks) is None:
                task["depends_on"] = saved          # would cycle — leave for validate()
            else:
                repairs.append((tid, sorted(add)))
                progressed = True
        if not progressed:
            break
    return repairs


def cmd_repair_closures(plan_path=None):
    """Best-effort closure auto-repair. Adds the depends_on edges the
    route/import/browser closure checks would otherwise reject on (when
    acyclic), writes the repaired plan, and prints each edge added. Exit 0
    always — validate() is the authority and runs after."""
    p = Path(plan_path) if plan_path else PLAN
    try:
        plan = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not all(
            isinstance(t, dict) and "id" in t and "file" in t
            and isinstance(t.get("depends_on"), list) for t in tasks):
        return
    contracts = load_json(CONTRACTS, "frozen contracts")
    repairs = _repair_apply(tasks, lambda ts: _closure_needs(ts, contracts))
    if repairs:
        p.write_text(json.dumps(plan, indent=2) + "\n")
        for tid, add in repairs:
            print(f"closure-repair: {tid} depends_on += {add}")


def cmd_repair_contracts(plan_path=None):
    """Best-effort contract-id repair. Drops any task contracts entry that is
    not a registered id in contracts.json (monotone: removal only), writes
    the repaired plan, and prints each id dropped. Exit 0 always — validate()
    is the authority and runs after."""
    p = Path(plan_path) if plan_path else PLAN
    try:
        plan = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not all(
            isinstance(t, dict) and "id" in t
            and isinstance(t.get("contracts"), list) for t in tasks):
        return
    contracts = load_json(CONTRACTS, "frozen contracts")
    known = contract_ids(contracts)
    drops = []
    for t in tasks:
        keep = [c for c in t["contracts"] if c in known]
        if len(keep) != len(t["contracts"]):
            drops.append((t["id"], sorted(set(t["contracts"]) - known)))
            t["contracts"] = keep
    if drops:
        p.write_text(json.dumps(plan, indent=2) + "\n")
        for tid, dropped in drops:
            print(f"contract-repair: {tid} dropped {dropped}")


def main(argv):
    if not argv:
        plan, _ = validate()
        print("plan ok")
        if AUTO_REGRESSION:
            print(
                f"validate-plan: {len(AUTO_REGRESSION)} carried-forward "
                f"node-id(s) auto-assigned to regression (final full-suite "
                f"acceptance, D-57)", file=sys.stderr,
            )
        if AUTO_PLACED:
            PLAN.write_text(json.dumps(plan, indent=2) + "\n")
            print(
                "validate-plan: gate-owned placement (test_mapping/D-64/"
                f"D-131) — node-ids moved to their acceptance task: "
                f"{'; '.join(AUTO_PLACED)}",
                file=sys.stderr,
            )
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
            c = load_json(CONTRACTS, "frozen contracts")
            print(c.get("smoke_checks", {}).get(task["file"], ""))
        else:
            fail([f"unknown field: {field}"])
        return
    if argv[0] == "--affected" and len(argv) >= 2:
        cmd_affected(argv[1:])
        return
    if argv[0] == "--milestone-scope" and len(argv) >= 2:
        cmd_milestone_scope(argv[1:])
        return
    if argv[0] == "--active-erd-context" and len(argv) >= 2:
        cmd_active_erd_context(argv[1:])
        return
    if argv[0] == "--active-inventory" and len(argv) >= 2:
        cmd_active_inventory(argv[1:])
        return
    if argv[0] == "--synthesize-plan" and len(argv) >= 2:
        cmd_synthesize_plan(argv[1:])
        return
    if argv[0] == "--subtree-scope" and len(argv) >= 3:
        cmd_subtree_scope(argv[1], argv[2:])
        return
    if argv[0] == "--merge-subtree" and len(argv) == 4:
        cmd_merge_subtree(argv[1], argv[2], argv[3])
        return
    if argv[0] == "--construct-one-file" and len(argv) >= 3:
        cmd_construct_one_file(argv[1], argv[2], argv[3:])
        return
    if argv[0] == "--repair-closures" and len(argv) <= 2:
        cmd_repair_closures(argv[1] if len(argv) == 2 else None)
        return
    if argv[0] == "--repair-contracts" and len(argv) <= 2:
        cmd_repair_contracts(argv[1] if len(argv) == 2 else None)
        return
    if argv[0] == "--diagnosis" and len(argv) == 2:
        cmd_diagnosis(argv[1])
        return
    if argv[0] == "--spec-preflight" and len(argv) == 3:
        spec_preflight(argv[1], argv[2])
        return
    fail([f"usage error: {' '.join(argv)} (see module docstring)"])


if __name__ == "__main__":
    main(sys.argv[1:])
