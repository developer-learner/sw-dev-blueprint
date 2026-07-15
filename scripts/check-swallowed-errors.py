#!/usr/bin/env python3
"""check-swallowed-errors.py <file> [<file>...] — D-68 swallowed-error gate.

Rejects silent error swallows in coder output: an error path that discards
the failure with no code and no stated reason. Found by external audit of
testchat: a fire-and-forget persist PUT ended in `.catch(function () {})`,
so a failed save of the user's data was indistinguishable from a successful
one. No gate anywhere looked.

The rule is deliberately narrow — swallowing is sometimes right (best-effort
cleanup), so a swallow carrying a justification comment passes. What fails
is the SILENT swallow:

  Python: an `except` handler whose body is exactly `pass`, with no comment
          anywhere on the handler's lines.
  JS:     an empty `.catch()` callback or empty `catch` block — `{}` with
          nothing inside (a comment inside the braces makes it non-empty
          and is exactly the fix for an intentional swallow).

Exit 0: clean (or file type not covered). Exit 1: findings on stdout, one
per line, `path:line: message` — orchestrate feeds them into the retry brief.
"""

import ast
import re
import sys


def check_python(path: str, source: str) -> list[str]:
    findings = []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []  # not this gate's job; the ast-parse/refreeze gates own syntax
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            span = lines[node.lineno - 1 : node.body[0].lineno]
            if not any("#" in ln for ln in span):
                findings.append(
                    f"{path}:{node.lineno}: except-block swallows the error with a bare "
                    f"'pass' and no justification comment — handle the failure, or state "
                    f"why ignoring it is safe in a comment inside the handler"
                )
    return findings


# An empty catch callback: .catch(function (e) {}), .catch((e) => {}),
# .catch(e => {}) — or an empty catch block: catch {} / catch (e) {}.
# `\{\s*\}` only matches truly empty braces, so a comment inside passes.
_JS_EMPTY_CATCH_CALLBACK = re.compile(
    r"\.catch\(\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)\s*\{\s*\}\s*\)"
)
_JS_EMPTY_CATCH_BLOCK = re.compile(r"(?<![.\w$])catch\s*(?:\([^)]*\))?\s*\{\s*\}")


def check_js(path: str, source: str) -> list[str]:
    findings = []
    for pattern, what in (
        (_JS_EMPTY_CATCH_CALLBACK, "empty .catch() callback"),
        (_JS_EMPTY_CATCH_BLOCK, "empty catch block"),
    ):
        for m in pattern.finditer(source):
            line = source.count("\n", 0, m.start()) + 1
            findings.append(
                f"{path}:{line}: {what} swallows the error silently — surface the "
                f"failure, or put a justification comment inside the braces if "
                f"ignoring it is deliberate"
            )
    return sorted(findings, key=lambda f: int(f.split(":")[1]))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: check-swallowed-errors.py <file> [<file>...]", file=sys.stderr)
        return 2
    findings = []
    for path in argv[1:]:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue  # a missing target is the atomicity gate's finding, not ours
        if path.endswith(".py"):
            findings.extend(check_python(path, source))
        elif path.endswith((".js", ".mjs", ".ts", ".jsx", ".tsx")):
            findings.extend(check_js(path, source))
    for f in findings:
        print(f)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
