#!/usr/bin/env python3
"""Validate the current-milestone ERD delta before a re-freeze."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


AC_ID = re.compile(r"\bAC-\d+\b")
REQUIRED_SECTIONS = (
    "## Changed acceptance criteria",
    "## Superseded acceptance criteria",
    "## Changed files",
    "## Test-to-file mapping",
)
# D-122: contract families the DELTA-vN walk records (refreeze.sh's
# DELTA_CONTRACTS heredoc: entry_points plus routes/schemas/errors/ui)
# versus the top-level keys it cannot see. A change in the invisible set
# with no other visible scope is lost to the orchestrator's subtree reset
# entirely.
ID_FAMILIES = ("entry_points", "routes", "schemas", "errors", "ui")
INVISIBLE_CONTRACT_KEYS = ("files", "test_mapping", "smoke_checks", "no_edit_files")
# The v82 incident marker: the ERD-DELTA marks a frozen test UPDATED while
# the freeze stages no bytes for its file, so DELTA-vN records no test
# change and the milestone's claim is bookkeeping-invisible. Case-sensitive
# by design: mapping sections carry the "(UPDATED)" marker; historical
# prose ("was updated at v80") describes a prior freeze, not this one.
UPDATED_MARK = re.compile(r"\btest_[a-z0-9_]+")


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def ac_ids(path: Path) -> set[str]:
    return set(AC_ID.findall(path.read_text())) if path.is_file() else set()


def staged_test_files(staging: Path) -> list[Path]:
    tests = staging / "tests"
    return sorted(path for path in tests.rglob("*") if path.is_file()) \
        if tests.is_dir() else []


def removed_tests(staging: Path) -> list[str]:
    path = staging / "REMOVED"
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def contracts_changed(contracts_path: Path, approved: Path) -> tuple[bool, list[str]]:
    if not contracts_path.is_file():
        return False, []
    incoming = load_json(contracts_path)
    current = load_json(approved / "contracts.json")
    changed_files = [
        value for value in incoming.get("changed_files", [])
        if isinstance(value, str) and value
    ]
    for value in (incoming, current):
        value.pop("erd_version", None)
        value.pop("changed_files", None)
    return incoming != current or bool(changed_files), changed_files


def staged_changed_test_files(staging: Path, repo: Path) -> set[str]:
    changed: set[str] = set()
    for path in staged_test_files(staging):
        rel = str(path.relative_to(staging))
        if not (repo / rel).is_file() or not (repo / rel).read_bytes() == path.read_bytes():
            changed.add(rel)
    changed.update(removed_tests(staging))
    return changed


def delta_completeness(staging: Path, approved: Path, repo: Path,
                       contracts_path: Path) -> list[str]:
    """D-122: fail a freeze whose changes the DELTA-vN bookkeeping cannot see.

    The DELTA-vN file is the orchestrator's only scope source (subtree reset,
    verdict scope, red-check): it records the ID_FAMILIES contract entries
    plus staged test byte-changes, and nothing else. A freeze that changes
    only the INVISIBLE_CONTRACT_KEYS, or that claims a test update in
    ERD-DELTA.md without staging its bytes, would bookkeep as an empty or
    partial delta — the v82 class.

    D-136: contracts_path is the MERGED contracts (refreeze's staged-merge
    result), never the raw partial — comparing a partial against the full
    standing would read every id-array the delta omits as "changed" and defeat
    the invisible-change detection below.
    """
    errors: list[str] = []
    incoming = load_json(contracts_path)
    current = load_json(approved / "contracts.json")
    if incoming:
        invisible_changed = [
            key for key in INVISIBLE_CONTRACT_KEYS
            if incoming.get(key) != current.get(key)
        ]
        if invisible_changed:
            visible = bool(incoming.get("changed_files")) or bool(
                staged_changed_test_files(staging, repo)
            ) or any(
                incoming.get(key) != current.get(key) for key in ID_FAMILIES
            )
            if not visible:
                errors.append(
                    "contracts change is invisible to the DELTA-vN "
                    "bookkeeping (D-122): " + ", ".join(invisible_changed)
                    + " differ from the frozen spec, but the freeze declares "
                    "no changed_files, stages no test byte-change, and changes "
                    "no contract entry — the orchestrator could never see this "
                    "freeze; declare the changed files or stage the tests that "
                    "pin the behavior"
                )

    delta_path = staging / "ERD-DELTA.md"
    nodeids_path = approved / "test-nodeids"
    if delta_path.is_file() and nodeids_path.is_file():
        by_file: dict[str, set[str]] = {}
        for line in nodeids_path.read_text().splitlines():
            node_id = line.strip()
            if node_id:
                by_file.setdefault(node_id.rsplit("::", 1)[0], set()).add(node_id)
        claimed: set[str] = set()
        for line in delta_path.read_text().splitlines():
            if "UPDATED" not in line:
                continue
            for token in UPDATED_MARK.findall(line):
                claimed.update(
                    file
                    for file, ids in by_file.items()
                    if any(
                        node_id.rsplit("::", 1)[1].split("[", 1)[0] == token
                        for node_id in ids
                    )
                )
        unstaged = sorted(claimed - staged_changed_test_files(staging, repo))
        if unstaged:
            errors.append(
                "ERD-DELTA.md marks test(s) as UPDATED whose files this "
                "freeze does not stage as changed (D-122): "
                + ", ".join(unstaged)
                + " — the DELTA-vN bookkeeping would record no test change "
                "for the claimed update; stage the updated test bytes or "
                "drop the claim"
            )
    return errors


def new_ac_ids(staging: Path, approved: Path, repo: Path) -> set[str]:
    added: set[str] = set()
    incoming_prd = staging / "PRD.md"
    if incoming_prd.is_file():
        added |= ac_ids(incoming_prd) - ac_ids(approved / "PRD.md")
    for incoming in staged_test_files(staging):
        relative = incoming.relative_to(staging)
        added |= ac_ids(incoming) - ac_ids(repo / relative)
    return added


def validate(staging: Path, approved: Path, repo: Path, current_version: int,
             contracts_path: Path | None = None) -> str:
    if current_version == 0:
        return "initial"

    # D-136: validate the MERGED contracts (refreeze passes --contracts); a
    # standalone call defaults to the staged file for backward compatibility.
    if contracts_path is None:
        contracts_path = staging / "contracts.json"
    contract_delta, changed_files = contracts_changed(contracts_path, approved)
    introduced_acs = new_ac_ids(staging, approved, repo)
    behavior_delta = bool(
        staged_test_files(staging)
        or removed_tests(staging)
        or contract_delta
        or introduced_acs
    )
    delta_path = staging / "ERD-DELTA.md"
    if not behavior_delta and not delta_path.is_file():
        return "nonbehavioral"
    if not delta_path.is_file():
        raise ValueError(
            "a behavioral re-freeze must stage ERD-DELTA.md; tests, test "
            "removals, or substantive contracts changed"
        )

    text = delta_path.read_text()
    missing_sections = [section for section in REQUIRED_SECTIONS if section not in text]
    missing_acs = sorted(introduced_acs - set(AC_ID.findall(text)))
    missing_files = sorted(path for path in changed_files if path not in text)
    errors: list[str] = []
    if contract_delta:
        incoming = load_json(contracts_path)
        mapping = incoming.get("test_mapping", {})
        if not isinstance(mapping, dict):
            errors.append("contracts.test_mapping must be an object")
        else:
            nodeids_path = approved / "test-nodeids"
            nodeids = {
                line.strip()
                for line in nodeids_path.read_text().splitlines()
                if line.strip()
            } if nodeids_path.is_file() else set()
            files = set(incoming.get("files", []))
            for node_id, pinned in sorted(mapping.items()):
                if node_id not in nodeids:
                    errors.append(
                        f"contracts.test_mapping pins unknown node-id "
                        f"{node_id} — every key must be a frozen node-id "
                        f"in test-nodeids"
                    )
                if pinned not in files:
                    errors.append(
                        f"contracts.test_mapping pins {node_id} to "
                        f"{pinned}, which is not in contracts.files"
                    )
        current = load_json(approved / "contracts.json")
        for key in ("routes", "schemas", "errors"):
            incoming_entries = {
                e.get("id"): e for e in incoming.get(key, [])
                if isinstance(e, dict) and e.get("id")
            }
            current_entries = {
                e.get("id"): e for e in current.get(key, [])
                if isinstance(e, dict) and e.get("id")
            }
            for entry_id, entry in sorted(incoming_entries.items()):
                if entry == current_entries.get(entry_id):
                    continue  # carried unchanged — exempt
                if not re.fullmatch(r"src/.*\.py", entry.get("file", "")):
                    errors.append(
                        f"contracts.{key}[{entry_id}] is new or changed but "
                        f"carries no file pin — add \"file\": \"<owning "
                        f"src/...py path>\" (D-120)"
                    )
    if missing_sections:
        errors.append("missing required section(s): " + ", ".join(missing_sections))
    if missing_acs:
        errors.append(
            "new acceptance criteria absent from ERD-DELTA.md: "
            + ", ".join(missing_acs)
        )
    if missing_files:
        errors.append(
            "contracts.changed_files absent from ERD-DELTA.md: "
            + ", ".join(missing_files)
        )
    errors += delta_completeness(staging, approved, repo, contracts_path)
    if errors:
        raise ValueError("; ".join(errors))
    return "behavioral"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--approved", required=True, type=Path)
    parser.add_argument("--repo", default=Path("."), type=Path)
    parser.add_argument("--current-version", required=True, type=int)
    parser.add_argument("--contracts", type=Path, default=None,
                        help="D-136: the MERGED contracts to validate "
                             "(refreeze passes the staged-merge result); "
                             "defaults to <staging>/contracts.json")
    args = parser.parse_args()
    try:
        print(validate(args.staging, args.approved, args.repo,
                       args.current_version, args.contracts))
    except ValueError as exc:
        print(f"SPEC DELTA FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
