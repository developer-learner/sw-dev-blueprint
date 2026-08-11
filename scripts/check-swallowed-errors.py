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

Scope (audit 2026-08-11 item 2): the gate examined the ENTIRE edited file, so
a pre-existing swallow the coder never touched could block a task whose change
lands elsewhere. Findings are now scoped to the delta's changed region — the
lines the coder actually changed. The change region is derived, per file, in
this order:

  1. an explicit `--changed-lines <path>=<ranges>` (e.g. `m.py=3,10-14`);
  2. otherwise `git diff <base> -- <path>` (base defaults to HEAD, comparing
     the committed baseline to the working-tree file the coder just wrote);
  3. otherwise — a NEW/untracked file, a non-repo, or any git failure — the
     WHOLE file, which only ever reports MORE. A finding that lands in a
     changed region is never weakened; only findings wholly outside the
     coder's change are dropped. `--no-scope` forces whole-file for every
     target.

Exit 0: clean (or file type not covered). Exit 1: findings on stdout, one
per line, `path:line: message` — orchestrate feeds them into the retry brief.
"""

import ast
import re
import subprocess
import sys


def check_python(path: str, source: str) -> list[tuple[set[int], str]]:
    """(covered-line-set, message) per finding. The line set is the handler's
    span (header line through the `pass`), so a swallow counts as "in the
    changed region" when the coder touched ANY of its lines, not only the
    `except` header."""
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
                covered = set(range(node.lineno, node.body[0].lineno + 1))
                findings.append((
                    covered,
                    f"{path}:{node.lineno}: except-block swallows the error with a bare "
                    f"'pass' and no justification comment — handle the failure, or state "
                    f"why ignoring it is safe in a comment inside the handler"
                ))
    return findings


# An empty catch callback: .catch(function (e) {}), .catch((e) => {}),
# .catch(e => {}) — or an empty catch block: catch {} / catch (e) {}.
# `\{\s*\}` only matches truly empty braces, so a comment inside passes.
_JS_EMPTY_CATCH_CALLBACK = re.compile(
    r"\.catch\(\s*(?:function\s*\([^)]*\)|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)\s*\{\s*\}\s*\)"
)
_JS_EMPTY_CATCH_BLOCK = re.compile(r"(?<![.\w$])catch\s*(?:\([^)]*\))?\s*\{\s*\}")


def check_js(path: str, source: str) -> list[tuple[set[int], str]]:
    findings = []
    for pattern, what in (
        (_JS_EMPTY_CATCH_CALLBACK, "empty .catch() callback"),
        (_JS_EMPTY_CATCH_BLOCK, "empty catch block"),
    ):
        for m in pattern.finditer(source):
            start = source.count("\n", 0, m.start()) + 1
            end = source.count("\n", 0, m.end()) + 1
            findings.append((
                set(range(start, end + 1)),
                f"{path}:{start}: {what} swallows the error silently — surface the "
                f"failure, or put a justification comment inside the braces if "
                f"ignoring it is deliberate"
            ))
    return sorted(findings, key=lambda f: int(f[1].split(":")[1]))


def _parse_ranges(spec: str) -> set[int]:
    """`3,10-14` -> {3,10,11,12,13,14}."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def _git_changed_lines(path: str, base: str):
    """Set of working-tree line numbers of `path` that differ from `base`, or
    None when no tracked baseline is available (new/untracked file, not a git
    repo, or any git failure) — the caller then reports on the whole file. None
    is the safe answer: it can only report MORE, never weaken a finding."""
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", path],
            capture_output=True, text=True,
        )
        if tracked.returncode != 0:
            return None  # untracked / outside repo / not a repo -> whole file
        diff = subprocess.run(
            ["git", "diff", "--unified=0", "--no-color", base, "--", path],
            capture_output=True, text=True,
        )
    except OSError:
        return None  # git absent -> whole file
    if diff.returncode != 0:
        return None  # bad base / other git error -> whole file
    changed: set[int] = set()
    for line in diff.stdout.splitlines():
        if not line.startswith("@@"):
            continue
        m = re.search(r"\+(\d+)(?:,(\d+))?", line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        changed.update(range(start, start + count))  # count 0 (deletion) -> none
    return changed


def main(argv: list[str]) -> int:
    base = "HEAD"
    no_scope = False
    explicit: dict[str, set[int]] = {}
    targets: list[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--no-scope":
            no_scope = True
        elif a == "--base":
            i += 1
            if i >= len(argv):
                print("usage: --base requires a git ref", file=sys.stderr)
                return 2
            base = argv[i]
        elif a == "--changed-lines":
            i += 1
            if i >= len(argv) or "=" not in argv[i]:
                print("usage: --changed-lines <path>=<ranges>", file=sys.stderr)
                return 2
            p, spec = argv[i].split("=", 1)
            explicit[p] = _parse_ranges(spec)
        else:
            targets.append(a)
        i += 1
    if not targets:
        print("usage: check-swallowed-errors.py [--no-scope] [--base REF] "
              "[--changed-lines <path>=<ranges>] <file> [<file>...]",
              file=sys.stderr)
        return 2
    out: list[str] = []
    for path in targets:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError:
            continue  # a missing target is the atomicity gate's finding, not ours
        if path.endswith(".py"):
            raw = check_python(path, source)
        elif path.endswith((".js", ".mjs", ".ts", ".jsx", ".tsx")):
            raw = check_js(path, source)
        else:
            continue
        if no_scope:
            changed = None
        elif path in explicit:
            changed = explicit[path]
        else:
            changed = _git_changed_lines(path, base)
        for covered, msg in raw:
            if changed is None or (covered & changed):
                out.append(msg)
    for f in out:
        print(f)
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
