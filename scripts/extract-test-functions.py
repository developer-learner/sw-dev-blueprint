#!/usr/bin/env python3
"""extract-test-functions.py — extract named test functions from a test file.

Given a test file and one or more pytest node-ids, outputs only the source of
the matching functions plus any module-level helpers they call.  Designed to
replace full-file paste in consult_em() (D-116 context minimalism).

Usage:
  extract-test-functions.py <test_file> <node_id> [<node_id> ...]

Node-ids follow pytest convention:
  tests/test_ui.py::test_ctrl_enter_sends[chromium]
Only the function name is used (path prefix and parametrize suffix stripped).

Exit: 0 with extracted source on stdout · 1 on error or no matches.
"""
import ast
import re
import sys
from pathlib import Path


def function_names_from_nodeids(nodeids: list[str]) -> set[str]:
    names: set[str] = set()
    for nid in nodeids:
        part = nid.rsplit("::", 1)[-1] if "::" in nid else nid
        part = re.sub(r"\[.*\]$", "", part)
        if part:
            names.add(part)
    return names


def collect_helpers(tree: ast.Module, target_funcs: list[ast.FunctionDef]) -> list[ast.FunctionDef]:
    all_top = {
        n.name: n for n in ast.iter_child_nodes(tree) if isinstance(n, ast.FunctionDef)
    }
    called: set[str] = set()
    for func in target_funcs:
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
    helpers = []
    for name in sorted(called):
        if name in all_top and all_top[name] not in target_funcs:
            helpers.append(all_top[name])
    return helpers


def extract_source(lines: list[str], node: ast.FunctionDef) -> str:
    start = node.lineno - 1
    end = node.end_lineno  # 1-indexed inclusive → exclusive slice index
    comment_line = start - 1
    if comment_line >= 0 and lines[comment_line].lstrip().startswith("#"):
        start = comment_line
    return "".join(lines[start:end])


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: extract-test-functions.py <test_file> <node_id> ...", file=sys.stderr)
        return 1

    test_file = Path(sys.argv[1])
    if not test_file.is_file():
        print(f"File not found: {test_file}", file=sys.stderr)
        return 1

    source = test_file.read_text()
    lines = source.splitlines(keepends=True)

    try:
        tree = ast.parse(source, filename=str(test_file))
    except SyntaxError as e:
        print(f"Syntax error in {test_file}: {e}", file=sys.stderr)
        return 1

    wanted = function_names_from_nodeids(sys.argv[2:])
    all_top_funcs = [n for n in ast.iter_child_nodes(tree) if isinstance(n, ast.FunctionDef)]
    targets = [f for f in all_top_funcs if f.name in wanted]

    if not targets:
        print(f"No matching functions for: {', '.join(sorted(wanted))}", file=sys.stderr)
        return 1

    helpers = collect_helpers(tree, targets)

    parts: list[str] = []
    for h in helpers:
        parts.append(extract_source(lines, h))
    for t in sorted(targets, key=lambda f: f.lineno):
        parts.append(extract_source(lines, t))

    print("\n\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
