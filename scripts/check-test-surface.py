#!/usr/bin/env python3
"""check-test-surface.py — INV-4: test-visible surface ⊆ ERD-locked surface.

Whatever the frozen tests observe is thereby locked, whether or not the ERD
meant to lock it. This gate keeps that de-facto lock aligned with the declared
one: tests may only import contract-listed entry points and only exercise
declared routes. A TPM test that reaches into internals fails HERE, at freeze
time, before it can silently shrink the EM's design space.

>>> CONFIDENCE FLAG (D-32): this is the LOWEST-CONFIDENCE mechanism in the
>>> gate set — a deliberately crude, grep-level static check, same spirit as
>>> INV-3. It catches the accident class (the author is a frontier model
>>> following instructions, not an adversary); it does not catch determined
>>> evasion (dynamic imports, computed paths). Tighten it from incidents,
>>> per the correction-log habit — do not pre-harden speculatively.

Checks:
  1. every `from src... import X` / `import src...` in tests/ resolves to an
     entry in contracts.entry_points ("module" allows the whole module;
     "module:symbol" allows exactly that symbol)
  2. every route-shaped string passed to an HTTP-client verb call
     (.get("/x"), .post(f"/y/{id}") ...) matches a declared route path
     template, segment-by-segment ({param} segments match anything)

Usage: check-test-surface.py [--tests-dir tests] [--contracts scripts/.approved/contracts.json]
Exit: 0 clean · 1 violations (listed on stderr) · 2 usage/input error
"""
import json
import re
import sys
from pathlib import Path

IMPORT_FROM = re.compile(r"^\s*from\s+(src[\w.]*)\s+import\s+(.+?)\s*(?:#.*)?$")
IMPORT_MOD = re.compile(r"^\s*import\s+(src[\w.]*)")
ROUTE_CALL = re.compile(
    r"\.\s*(?:get|post|put|delete|patch|head|options|request)\s*\(\s*f?[\"'](/[^\"']*)[\"']"
)


def parse_args(argv):
    tests_dir, contracts = "tests", "scripts/.approved/contracts.json"
    it = iter(argv)
    for a in it:
        if a == "--tests-dir":
            tests_dir = next(it, None)
        elif a == "--contracts":
            contracts = next(it, None)
        else:
            print(f"INV-4 usage error: unknown arg {a}", file=sys.stderr)
            sys.exit(2)
        if tests_dir is None or contracts is None:
            print("INV-4 usage error: missing value", file=sys.stderr)
            sys.exit(2)
    return Path(tests_dir), Path(contracts)


def allowed_imports(contracts):
    modules, symbols = set(), set()
    for ep in contracts.get("entry_points", []):
        if ":" in ep:
            symbols.add(tuple(ep.split(":", 1)))
        else:
            modules.add(ep)
    return modules, symbols


def route_templates(contracts):
    return [r["path"] for r in contracts.get("routes", []) if isinstance(r, dict) and "path" in r]


def path_matches(path, template):
    """Segment-wise match; {param} template segments match any one segment."""
    path = path.split("?", 1)[0].rstrip("/") or "/"
    template = template.rstrip("/") or "/"
    ps, ts = path.split("/"), template.split("/")
    if len(ps) != len(ts):
        return False
    for p, t in zip(ps, ts):
        if t.startswith("{") and t.endswith("}"):
            continue
        # an f-string placeholder in the test matches a {param} slot only,
        # which the branch above already handled — literal segments must equal
        if p.startswith("{") and p.endswith("}"):
            continue
        if p != t:
            return False
    return True


def main(argv):
    tests_dir, contracts_path = parse_args(argv)
    try:
        contracts = json.loads(contracts_path.read_text())
    except FileNotFoundError:
        print(f"INV-4 error: contracts not found: {contracts_path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"INV-4 error: contracts not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)
    if not tests_dir.is_dir():
        print(f"INV-4 error: tests dir not found: {tests_dir}", file=sys.stderr)
        sys.exit(2)

    modules, symbols = allowed_imports(contracts)
    templates = route_templates(contracts)
    violations = []

    for f in sorted(tests_dir.rglob("*.py")):
        for lineno, line in enumerate(f.read_text().splitlines(), 1):
            m = IMPORT_FROM.match(line)
            if m:
                mod, names = m.group(1), m.group(2)
                if mod not in modules:
                    for name in names.split(","):
                        name = name.strip().split(" as ")[0].strip()
                        if name and (mod, name) not in symbols:
                            violations.append(
                                f"{f}:{lineno}: imports `{mod}:{name}` — not in contracts.entry_points"
                            )
                continue
            m = IMPORT_MOD.match(line)
            if m and m.group(1) not in modules:
                violations.append(
                    f"{f}:{lineno}: imports module `{m.group(1)}` — not in contracts.entry_points"
                )
                continue
            for path in ROUTE_CALL.findall(line):
                if not any(path_matches(path, t) for t in templates):
                    violations.append(
                        f"{f}:{lineno}: exercises route `{path}` — matches no contracts.routes path"
                    )

    if violations:
        print("INV-4 GATE FAIL: test-visible surface exceeds the ERD-locked surface:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(
            "  -> either the TPM must lock these surfaces in contracts.json, or the "
            "tests must observe only through locked seams.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("INV-4 ok: test-visible surface is within the locked surface")


if __name__ == "__main__":
    main(sys.argv[1:])
