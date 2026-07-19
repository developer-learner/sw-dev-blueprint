#!/usr/bin/env python3
"""validate-plan.py — mechanical gate on the EM's task plan (D-26, D-28).

The plan (tasks/plan.json) is the EM's only channel of authority. Everything
checkable is checked here, so a bad decomposition fails at VALIDATION, not at
integration:

  - structural: schema shape, no unknown keys, no status field, id format
  - atomicity:  exactly one file per task, unique, under the build lane
  - coverage:   every file in the frozen ERD inventory has exactly one task
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
  validate-plan.py --affected DELTA.json    print ids of tasks invalidated by a re-freeze
                                            delta, including transitive dependents
  validate-plan.py --diagnosis FILE         validate an EM diagnosis; print its verdict
  validate-plan.py --spec-preflight OLD NEW
                                            D-78 freeze-time satisfiability: every
                                            new/changed route and entry_point in NEW
                                            (vs OLD, which may not exist yet) must be
                                            implementable by NEW's contracts.files;
                                            exit 0/1. Run by refreeze.sh BEFORE the
                                            human approval prompt.
"""
import ast
import hashlib
import json
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
VERDICTS = {"brief_wrong", "decomposition_wrong", "contract_or_test_wrong"}
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
# Method-agnostic registration calls (Flask .route/.add_url_rule, FastAPI
# .add_api_route) — a path literal under one of these registers the route
# for ANY method.
ROUTE_REGISTRARS = {"route", "add_api_route", "add_url_rule", "websocket"}

# Carried-forward node-ids computed by the last validate() call (D-57).
# Informational — the final full-suite run covers them regardless.
AUTO_REGRESSION: list = []


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
        elif len(t["brief"]) > MAX_BRIEF_CHARS:
            errs.append(
                f"{where}: brief is {len(t['brief'])} chars (max {MAX_BRIEF_CHARS}) "
                f"— split the task or tighten the brief (Rule 8)"
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
    inventory = contracts.get("files", [])
    missing_tasks = sorted(set(inventory) - set(files))
    extra_files = sorted(set(files) - set(inventory))
    if missing_tasks:
        errs.append(f"ERD inventory files with no task: {missing_tasks}")
    if extra_files:
        errs.append(f"tasks target files not in the ERD inventory: {extra_files}")

    # D-65: no_edit_files must be inventory members — a no-edit declaration
    # for a file outside the inventory is a spec typo the freeze should have
    # caught; fail loudly here as the backstop.
    stray_no_edit = sorted(set(contracts.get("no_edit_files", [])) - set(inventory))
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
        if sc_file not in inventory:
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
    overmapped = sorted({n for n in mapped if mapped.count(n) > 1})
    if overmapped:
        errs.append(f"test node-id(s) mapped to more than one task: {overmapped}")

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
    module_owner = {}  # dotted module -> owning task id
    for t in tasks:
        if t["file"].endswith(".py"):
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

    # D-64: browser tests observe the app through the DOM, not imports, so
    # the closure analysis above cannot see their dependencies — a Playwright
    # test can exercise ANY inventory file (markup, styling, and scripts all
    # shape what the browser renders). Its only safe acceptance point is a
    # task whose dependency closure contains the ENTIRE inventory, i.e. the
    # DAG's final task. testchat M15: the EM mapped a new browser test to the
    # markup task twice despite explicit ERD prose; the test structurally
    # could not pass before the styling task ran — a false task failure.
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
    for t in tasks:
        closure = {t["id"]} | ancestors(t["id"])
        if closure == all_task_ids:
            continue
        browser_files = sorted(
            tf for tf in {n.split("::")[0] for n in t["tests"]}
            if is_browser_test_file(tf)
        )
        if browser_files:
            missing = sorted(all_task_ids - closure)
            errs.append(
                f"task {t['id']}: browser test file(s) {browser_files} are "
                f"mapped here, but task(s) {missing} are not in {t['id']}'s "
                f"dependency closure — a browser test observes the rendered "
                f"page, which any inventory file can shape, so it can only "
                f"be accepted at a task downstream of the whole inventory. "
                f"Map these tests to the DAG's final task."
            )

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

    if errs:
        for e in errs:
            print(f"SPEC PREFLIGHT FAIL (D-78): {e}", file=sys.stderr)
        sys.exit(1)
    print(f"spec preflight ok (D-78): {checked} new/changed contract(s) "
          f"implementable by the inventory")


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


def main(argv):
    if not argv:
        validate()
        print("plan ok")
        if AUTO_REGRESSION:
            print(
                f"validate-plan: {len(AUTO_REGRESSION)} carried-forward "
                f"node-id(s) auto-assigned to regression (final full-suite "
                f"acceptance, D-57)", file=sys.stderr,
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
    if argv[0] == "--affected" and len(argv) == 2:
        cmd_affected(argv[1])
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
