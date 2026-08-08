#!/usr/bin/env python3
"""check-test-direction.py — S6: reverse-direction test lint.

The forward lints (check-spec-delta, check-test-surface) compare STAGED
tests against LIVE ACs. The v58 incident (correction log 2026-07-25) shipped
a contradiction in the OTHER direction: a carried-forward test monkeypatched
``httpx.get`` to return 200 for EVERY URL, so the other script model read as
loaded, AC-104's spawn-refusal never ran, and the test asserting ``Popen``
was called could not fail. Two checks:

  1. WHOLE-WORLD MOCK — a mock, in a test this delta touches, that answers
     every URL encodes "the whole world is ready" and silently couples
     unrelated subsystems. A URL-verb mock whose callable ignores its URL
     argument, or a bare Mock(), is rejected.
  2. CARRIED-FORWARD vs NEW ACs — an AC id this delta ADDS must not be
     cited by a carried-forward test: that test's assumptions predate the
     AC, so the delta either supersedes them (restage the test) or the AC
     is not actually new (fix the bookkeeping).

When run standalone, check 1 sweeps the whole given directory (audit
mode). When run from refreeze (with --staging/--repo-tests), check 1 is
scoped to the tests this delta touches — the tests that changed or are
removed (D-116's changed-test semantics), same seam as check 2. That is
deliberate: the legacy carried suite contains pre-existing whole-world
mocks (testchat: 9, see D-128 amend). A gate that halts every refreeze on
_old_ content freezes the pipeline over content the delta is not about.
The v58-class danger is a delta that *introduces* the coupling; a carried
mock that goes untouched by the delta is scanned only when the delta
changes it. Same incident class, right trigger.

> CONFIDENCE FLAG (D-32): check 1 is the lowest-confidence mechanism in the
> gate set — deliberate, crude static analysis in the same spirit as INV-4.
> It catches the accident class (a frontier-model author following
> instructions); it does not catch determined evasion (computed attributes,
> dynamic imports). Tighten it from incidents, do not pre-harden
> speculatively.

Usage:
  check-test-direction.py --tests-dir <DIR> [--staging <DIR> \
      --approved <DIR> --repo-tests <DIR>]
Exit: 0 clean · 1 violations (listed on stderr) · 2 usage/input error
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

URL_VERBS = {"get", "post", "stream", "request", "urlopen"}
HTTP_MARKERS = ("httpx", "requests", "urllib")
AC_ID = re.compile(r"\bAC-\d+\b")


def _is_http_module(node: ast.expr) -> bool:
    return any(m in ast.unparse(node) for m in HTTP_MARKERS)


def _name_ids(node: ast.AST | list[ast.AST]) -> set[str]:
    nodes = node if isinstance(node, list) else [node]
    return {
        n.id
        for chunk in nodes
        for n in ast.walk(chunk)
        if isinstance(n, ast.Name)
    }


def _url_blind(mock: ast.Lambda | ast.FunctionDef) -> str | None:
    """Why *mock* answers every URL, or None if it discriminates on its URL."""
    args = mock.args
    positional = [a.arg for a in args.posonlyargs + args.args]
    if not positional:
        label = "lambda" if isinstance(mock, ast.Lambda) else f"def {mock.name}"
        return f"{label} accepts no URL parameter — answers every URL"
    first = positional[0]
    if first not in _name_ids(mock.body):
        label = "lambda" if isinstance(mock, ast.Lambda) else f"def {mock.name}"
        return f"{label} never reads its URL parameter '{first}'"
    return None


def _mock_problem(mock: ast.expr, defs: dict[str, ast.FunctionDef]) -> str | None:
    """Describe a URL-blind mock site, or None if the mock looks scoped."""
    if isinstance(mock, ast.Call):
        func = mock.func
        is_mock = (
            (isinstance(func, ast.Name) and func.id in {"Mock", "MagicMock"})
            or (isinstance(func, ast.Attribute) and func.attr in {"Mock"})
        )
        if is_mock:
            return "bare Mock() — answers every URL"
        return None
    if isinstance(mock, ast.Lambda):
        return _url_blind(mock)
    if isinstance(mock, ast.Name):
        defined = defs.get(mock.id)
        if defined is not None:
            return _url_blind(defined)
    return None


def _mock_sites(tree: ast.AST) -> list[tuple[int, ast.expr]]:
    """Every (lineno, mock_expr) URL-verb mock install site in *tree*."""
    sites: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None
            )
            if name == "setattr" and len(node.args) >= 3:
                mod, verb, mock = node.args[0], node.args[1], node.args[2]
                if (
                    isinstance(verb, ast.Constant)
                    and isinstance(verb.value, str)
                    and verb.value in URL_VERBS
                    and _is_http_module(mod)
                ):
                    sites.append((node.lineno, mock))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Attribute)
                and target.attr in URL_VERBS
                and _is_http_module(target.value)
            ):
                sites.append((node.lineno, node.value))
    return sites


def whole_world_findings(
    test_dir: Path, allowed: set[str] | None = None
) -> list[str]:
    """Check 1: URL-verb mock sites whose callable ignores the URL.

    *allowed* restricts the scan to delta-touched tests (rel paths like
    tests/x.py); standalone runs pass None to sweep the entire directory.
    """
    findings: list[str] = []
    for py in sorted(test_dir.glob("*.py")):
        if allowed is not None and f"tests/{py.name}" not in allowed:
            continue
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        defs = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for lineno, mock in _mock_sites(tree):
            problem = _mock_problem(mock, defs)
            if problem:
                findings.append(f"{py}:{lineno}: {problem}")
    return findings


# --- check 2: carried-forward suite vs AC ids the delta ADDS -----------------


def _new_ac_ids(approved: Path, staging: Path) -> set[str]:
    added: set[str] = set()
    for rel in ("PRD.md", "ERD-DELTA.md"):
        p = staging / rel
        if p.is_file():
            added.update(AC_ID.findall(p.read_text()))
    known: set[str] = set()
    for rel in ("PRD.md", "ERD.md"):
        p = approved / rel
        if p.is_file():
            known.update(AC_ID.findall(p.read_text()))
    return added - known


def _changed_test_files(staging: Path, repo_tests: Path) -> set[str]:
    """Tests this delta stages as new or byte-changed (mirrors the freeze's
    CHANGED_TEST_FILES semantics: rel paths like tests/x.py, plus REMOVED)."""
    changed: set[str] = set()
    staged_tests = staging / "tests"
    if staged_tests.is_dir():
        for p in sorted(staged_tests.rglob("*")):
            if not p.is_file():
                continue
            target = repo_tests / p.name
            if not target.is_file() or target.read_bytes() != p.read_bytes():
                changed.add(f"tests/{p.name}")
    removed = staging / "REMOVED"
    if removed.is_file():
        for line in removed.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                changed.add(s)
    return changed


def _carried_citations(
    staging: Path, approved: Path, repo_tests: Path
) -> list[str]:
    """Carried tests that cite an AC this delta introduces."""
    new = _new_ac_ids(approved, staging)
    if not new:
        return []
    changed = _changed_test_files(staging, repo_tests)
    findings: list[str] = []
    for py in sorted(repo_tests.glob("*.py")):
        rel = f"tests/{py.name}"
        if rel in changed:
            continue
        hits = sorted(set(AC_ID.findall(py.read_text())) & new)
        if hits:
            findings.append(
                f"{py}: carried-forward test cites AC id(s) {', '.join(hits)} "
                "introduced by this delta — the test's assumptions predate the "
                "AC; restage the test with the delta or retire the 'new' claim"
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-dir", required=True)
    parser.add_argument("--staging")
    parser.add_argument("--approved")
    parser.add_argument("--repo-tests")
    args = parser.parse_args()

    test_dir = Path(args.tests_dir)
    if not test_dir.is_dir():
        print("--tests-dir must be a directory", file=sys.stderr)
        return 2

    allowed: set[str] | None = None
    if args.staging and args.repo_tests:
        allowed = _changed_test_files(Path(args.staging), Path(args.repo_tests))
    findings = whole_world_findings(test_dir, allowed)
    if args.staging and args.approved and args.repo_tests:
        findings += _carried_citations(
            Path(args.staging),
            Path(args.approved),
            Path(args.repo_tests),
        )
    for finding in findings:
        print(f"S6 {finding}", file=sys.stderr)
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())