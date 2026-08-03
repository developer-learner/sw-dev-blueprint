#!/usr/bin/env python3
"""Compute and write a freeze's DELTA-v{n}.json (D-31 affected-subtree reset).

Extracted from refreeze.sh's inline heredoc so the delta computation has a real
producer test (correction-log meta-rule: adapters need a real producer test).
refreeze.sh invokes `main()` from the repo root with the previous freeze's
node-ids, changed/removed test files, and changed contract ids already written
to .pipeline-state/. The pure `compute_changed_tests` below is what the D-116
guard lives in and what the selftest pins directly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def compute_changed_tests(
    old_nodeids: set[str],
    new_nodeids: set[str],
    changed_files: set[str],
    removed_files: set[str],
) -> list[str]:
    """The delta's changed_tests: retired/relocated node-ids plus every node-id
    living in a file this delta actually staged.

    D-116: a node-id in (old - new) is a *real* removal only when its source FILE
    actually changed in this delta — a staged byte-different edit (changed_files)
    or a REMOVED retirement (removed_files). When the file is byte-identical and
    still present, an id that "disappeared" did so only because collection
    relabeled it: pytest's parametrized `name[chromium]` expands with sandbox
    collect success, static AST emits the bare `name` when it does not, so the
    frozen set flips shape between freezes with no spec change. Counting that
    flip re-runs finished, green work off a phantom delta (testchat v77: 60
    relabeled node-ids in a byte-identical suite reset three already-done tasks).
    Scope the removed term to files this delta actually touched; the
    changed-files term is already file-scoped and unaffected.
    """
    delta_scope_files = changed_files | removed_files
    removed = {
        n for n in (old_nodeids - new_nodeids)
        if n.split("::")[0] in delta_scope_files
    }
    in_changed_files = {n for n in new_nodeids if n.split("::")[0] in changed_files}
    return sorted(removed | in_changed_files)


def _lines(p: str) -> list[str]:
    return [line for line in Path(p).read_text().splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    new_v, nodeids_path = int(argv[1]), argv[2]
    contracts_staged = argv[3] == "1"

    old_nodeids = set(_lines(".pipeline-state/refreeze-old-nodeids"))
    new_nodeids = set(_lines(nodeids_path))
    changed_files = set(_lines(".pipeline-state/refreeze-changed-files"))
    removed_files = set(_lines(".pipeline-state/refreeze-removed-files"))
    changed_tests = compute_changed_tests(
        old_nodeids, new_nodeids, changed_files, removed_files
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
