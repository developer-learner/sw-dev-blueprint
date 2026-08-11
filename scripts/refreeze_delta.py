#!/usr/bin/env python3
"""Compute and write a freeze's DELTA-v{n}.json (D-31 affected-subtree reset).

Extracted from refreeze.sh's inline heredoc so the delta computation has a real
producer test (correction-log meta-rule: adapters need a real producer test).
refreeze.sh invokes `main()` from the repo root with the previous freeze's
node-ids, changed/removed test files, and changed contract ids already written
to .pipeline-state/. The pure `compute_changed_tests` below is what the D-116
guard lives in and what the selftest pins directly.

changed_tests granularity (finding-1 fix): the delta records changed tests at
FUNCTION level, not file level. refreeze.sh snapshots each staged test file's
pre-apply source under .pipeline-state/old-tests/; the new source is the
applied tree. A test is changed iff its function's source bytes changed (or it
is newly added); a content-bearing change OUTSIDE every test function
(fixtures, helpers, imports, module constants) can alter test meaning without
any test body changing, so it conservatively falls back to file-level scope —
an over-run, never an under-run that could green a milestone without running
the affected test. Comment-only and whitespace-only changes are noise (the
v87 two-comment-line class, D-116): they cannot change meaning and never
widen the delta. DELTA files written by this producer carry
"changed_tests_granularity": "function"; consumers slice function-granular
deltas without trimming (an unpinned new test must never be silently
discarded — testchat v99: the AC-161 oracle rode no test_mapping pin, so the
file-granular slice emptied its task and the default verdict could pass
without running it).
"""
from __future__ import annotations

import ast
import difflib
import json
import re
import sys
from pathlib import Path


def family_of(node_id: str) -> str:
    """The stable family of a test node-id: module-prefix + bare test name,
    parametrization stripped. Matches validate-plan.py's _id_family."""
    module, sep, tail = node_id.rpartition("::")
    return module + "::" + tail.split("[", 1)[0] if sep else node_id


def _filtered_lines(src: str) -> list[tuple[int, str]]:
    """(original_lineno, line) pairs for every line that can carry meaning:
    non-blank, non-comment. Comment/whitespace-only changes are the D-116
    noise class and must never widen the delta, wherever they sit."""
    return [
        (i, line)
        for i, line in enumerate(src.splitlines(keepends=True), 1)
        if line.strip() and not line.strip().startswith("#")
    ]


def _test_spans(tree):
    """{node-id family suffix: (start_lineno, end_lineno)} for every test
    function (def test_* and Test* class methods), including decorators."""
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name.startswith("test"):
            start = min((d.lineno for d in node.decorator_list),
                        default=node.lineno)
            spans[f"::{node.name}"] = (start, node.end_lineno)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and m.name.startswith("test"):
                    start = min((d.lineno for d in m.decorator_list),
                                default=m.lineno)
                    spans[f"::{node.name}::{m.name}"] = (start, m.end_lineno)
    return spans


def _slice_lines(src: str, start: int, end: int) -> list[str]:
    return [
        ln for ln in src.splitlines(keepends=True)[start - 1:end]
        if ln.strip() and not ln.strip().startswith("#")
    ]


def function_changes(
    file_path: str,
    old_src: str,
    new_src: str,
) -> tuple[set[str], bool]:
    """Function-level diff of one test file.

    Returns (families, infra):
    - families: node-id families whose test-function source bytes changed or
      that are newly added (comment/whitespace-only deltas ignored).
    - infra: True when a content-bearing line outside every test-function
      span changed (imports, fixtures, helpers, module constants) — test
      MEANING can change there without any test body changing, so the caller
      falls back to file-level scope for this file.
    A file that cannot be parsed (SyntaxError) or diffed is conservative
    infra: full file-level scope, never a silent under-scope.
    """
    old_lines = _filtered_lines(old_src)
    new_lines = _filtered_lines(new_src)
    if [ln for _, ln in old_lines] == [ln for _, ln in new_lines]:
        return set(), False
    try:
        old_tree = ast.parse(old_src, filename=file_path)
        new_tree = ast.parse(new_src, filename=file_path)
    except SyntaxError:
        return set(), True
    old_spans = _test_spans(old_tree)
    new_spans = _test_spans(new_tree)
    families: set[str] = set()
    for suffix in sorted(set(old_spans) | set(new_spans)):
        if suffix not in old_spans:
            families.add(file_path + suffix)          # newly added test
        elif suffix in new_spans:
            o_start, o_end = old_spans[suffix]
            n_start, n_end = new_spans[suffix]
            if _slice_lines(old_src, o_start, o_end) \
                    != _slice_lines(new_src, n_start, n_end):
                families.add(file_path + suffix)      # source bytes changed
        # else: removed test — the removed node-id term below covers it
    infra = False
    matcher = difflib.SequenceMatcher(
        None, [ln for _, ln in old_lines], [ln for _, ln in new_lines])
    old_bounds = list(old_spans.values())
    new_bounds = list(new_spans.values())
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if any(
            not any(a <= old_lines[i][0] <= b for a, b in old_bounds)
            for i in range(i1, i2)
        ):
            infra = True
        if any(
            not any(a <= new_lines[j][0] <= b for a, b in new_bounds)
            for j in range(j1, j2)
        ):
            infra = True
    return families, infra


def compute_changed_tests(
    old_nodeids: set[str],
    new_nodeids: set[str],
    changed_files: set[str],
    removed_files: set[str],
    old_sources: dict[str, str] | None = None,
    new_sources: dict[str, str] | None = None,
) -> list[str]:
    """The delta's changed_tests: retired/relocated node-ids plus every
    node-id whose test function this delta actually changed.

    D-116: a node-id in (old - new) is a *real* removal only when its source
    FILE actually changed in this delta — a staged byte-different edit
    (changed_files) or a REMOVED retirement (removed_files). When the file is
    byte-identical and still present, an id that "disappeared" did so only
    because collection relabeled it: pytest's parametrized `name[chromium]`
    expands with sandbox collect success, static AST emits the bare `name`
    when it does not, so the frozen set flips shape between freezes with no
    spec change. Counting that flip re-runs finished, green work off a phantom
    delta (testchat v77: 60 relabeled node-ids in a byte-identical suite reset
    three already-done tasks). Scope the removed term to files this delta
    actually touched.

    Changed-files term (finding-1 fix): when the pre/post-apply sources are
    supplied, the surviving-id term is FUNCTION-granular — only node-ids whose
    family function_changes marks changed, plus every node-id of a file whose
    infra-level lines changed (conservative file-level fallback). Without
    sources the term falls back to file granularity (the legacy shape; the
    snapshot lives in refreeze.sh and is always supplied in production).
    """
    delta_scope_files = changed_files | removed_files
    removed = {
        n for n in (old_nodeids - new_nodeids)
        if n.split("::")[0] in delta_scope_files
    }
    if old_sources is not None and new_sources is not None:
        infra_files: set[str] = set()
        changed_families: set[str] = set()
        for f in sorted(changed_files):
            if f not in old_sources or f not in new_sources:
                infra_files.add(f)
                continue
            fams, infra = function_changes(
                f, old_sources[f], new_sources[f])
            changed_families |= fams
            if infra:
                infra_files.add(f)
        in_changed_files = {
            n for n in new_nodeids
            if n.split("::")[0] in changed_files
            and (n.split("::")[0] in infra_files
                 or family_of(n) in changed_families)
        }
    else:
        in_changed_files = {
            n for n in new_nodeids if n.split("::")[0] in changed_files
        }
    return sorted(removed | in_changed_files)


def _erd_pins(text: str) -> dict[str, str]:
    """Node-id -> owner-file rows from ERD-DELTA.md's '## Test-to-file mapping'
    section: `* ``node-id`` bullets whose next non-blank line carries
    `-> ``file`` (the two-line row shape testchat's v99 delta uses). Rows
    that name no backticked file are not pins: a mapping line without an
    owner resolves nothing."""
    pins: dict[str, str] = {}
    lines = text.splitlines()
    in_section = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            in_section = line.strip() == "## Test-to-file mapping"
            continue
        if not in_section or not line.lstrip().startswith("*"):
            continue
        ids = re.findall(r"`([^`]+)`", line)
        if not ids:
            continue
        node_id = ids[0].strip()
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines):
            continue
        m = re.search(r"->\s*`([^`]+)`", lines[j])
        if m and m.group(1).strip():
            pins[node_id] = m.group(1).strip()
    return pins


def pin_gate_violations(
    changed_files: list[str],
    old_sources: dict[str, str],
    new_sources: dict[str, str],
    test_mapping: dict[str, str],
    erd_delta: str,
) -> list[str]:
    """Item 1 freeze-time gate: every test function this delta ADDS or
    MODIFIES (the function-granular changed term) must carry an explicit
    owning-file pin in contracts.test_mapping or the ERD-DELTA '## Test-to-file
    mapping' section, at freeze time. A pin matches at FAMILY granularity
    (parametrization stripped), so a bare family is satisfied by a
    `name[chromium]` pin and vice versa.

    The testchat v99 hole: the AC-161 oracle was a genuinely new test riding
    no pin — the file-granular milestone slice emptied its task and the
    default verdict could pass without running it. Grandfathered by design
    (S6/D-128 lesson): infra-level file fallbacks and carried tests are NOT
    gated — requiring a pin for every test in a 50-test file whose fixture
    changed would halt the pipeline. Only functions whose own bytes changed
    must pin. Returns the sorted list of unpinned families; empty = green.
    """
    pins = {family_of(k): v for k, v in (test_mapping or {}).items() if v}
    pins.update({family_of(k): v for k, v in _erd_pins(erd_delta or "").items()})
    unpinned: set[str] = set()
    for f in changed_files:
        new_src = new_sources.get(f)
        if new_src is None:
            continue                     # removed file: no living tests to gate
        fams, _ = function_changes(f, old_sources.get(f, ""), new_src)
        unpinned |= {fam for fam in fams if fam not in pins}
    return sorted(unpinned)


def _lines(p: str) -> list[str]:
    return [line for line in Path(p).read_text().splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "pin-gate":
        return cmd_pin_gate(argv[2:])
    new_v, nodeids_path = int(argv[1]), argv[2]
    contracts_staged = argv[3] == "1"

    old_nodeids = set(_lines(".pipeline-state/refreeze-old-nodeids"))
    new_nodeids = set(_lines(nodeids_path))
    changed_files = set(_lines(".pipeline-state/refreeze-changed-files"))
    removed_files = set(_lines(".pipeline-state/refreeze-removed-files"))
    old_root = Path(".pipeline-state/old-tests")
    old_sources = {}
    new_sources = {}
    for f in changed_files:
        old_p = old_root / f
        if old_p.is_file():
            old_sources[f] = old_p.read_text()
        new_p = Path(f)
        if new_p.is_file():
            new_sources[f] = new_p.read_text()
    changed_tests = compute_changed_tests(
        old_nodeids, new_nodeids, changed_files, removed_files,
        old_sources, new_sources,
    )

    # D-86: the TPM's own scope declaration. Until D-86 this was hardcoded [],
    # so the coder's editable set was reachable only through the EM's test
    # mapping — scope, a containment boundary, set implicitly by the mid tier.
    # validate-plan.py's preflight has already proved every entry is an editable
    # inventory member, so copy it through verbatim.
    declared_files: list[str] = []
    if contracts_staged:
        contracts = json.load(open("scripts/.approved/contracts.json"))
        declared_files = [f for f in contracts.get("changed_files", []) if f]

    delta = {
        "changed_contract_ids": _lines(".pipeline-state/refreeze-changed-contracts"),
        "changed_tests": changed_tests,
        "changed_tests_granularity": "function",
        "changed_files": declared_files,
    }
    with open(f"scripts/.approved/DELTA-v{new_v}.json", "w") as f:
        json.dump(delta, f, indent=2)
    if not (delta["changed_contract_ids"] or changed_tests or declared_files):
        print("  WARNING (D-86): this delta scopes NOTHING — no changed tests, no "
              "changed contract ids, no declared changed_files. With the inverted "
              "no-edit default every existing file is untouchable, so a run will "
              "invoke the coder for nothing and report normally. If a milestone is "
              "unbuilt, declare its files in contracts.changed_files and re-freeze.")
    return 0


def cmd_pin_gate(argv: list[str]) -> int:
    """Pre-apply freezer gate (item 1): staged change files' new/modified test
    functions must carry owning-file pins. Runs from the repo root with
    --old-root . (current tree = pre-apply sources) and --new-root <staging>
    (the incoming files); pin sources are the staged contracts.json and
    ERD-DELTA.md. Exits 0 when every changed test function is pinned."""
    import argparse
    ap = argparse.ArgumentParser(
        prog="refreeze_delta.py pin-gate", description=__doc__)
    ap.add_argument("--old-root", required=True)
    ap.add_argument("--new-root", required=True)
    ap.add_argument("--test-mapping")
    ap.add_argument("--erd-delta")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    old_sources: dict[str, str] = {}
    new_sources: dict[str, str] = {}
    for f in args.files:
        old_p = Path(args.old_root) / f
        if old_p.is_file():
            old_sources[f] = old_p.read_text()
        new_p = Path(args.new_root) / f
        if new_p.is_file():
            new_sources[f] = new_p.read_text()
    test_mapping: dict[str, str] = {}
    if args.test_mapping and Path(args.test_mapping).is_file():
        c = json.load(open(args.test_mapping))
        mapping = c.get("test_mapping", {})
        if isinstance(mapping, dict):
            test_mapping = mapping
    erd = ""
    if args.erd_delta and Path(args.erd_delta).is_file():
        erd = Path(args.erd_delta).read_text()
    bad = pin_gate_violations(
        args.files, old_sources, new_sources, test_mapping, erd)
    if bad:
        print(f"PIN GATE FAIL: {len(bad)} changed test function(s) carry no "
              "owning-file pin:", file=sys.stderr)
        for fam in bad:
            print(f"  {fam}", file=sys.stderr)
        print("  -> name each one's owner file in contracts.test_mapping or the",
              file=sys.stderr)
        print("     ERD-DELTA.md '## Test-to-file mapping' section, and restage.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
