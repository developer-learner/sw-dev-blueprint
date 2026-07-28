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


def contracts_changed(staging: Path, approved: Path) -> tuple[bool, list[str]]:
    incoming_path = staging / "contracts.json"
    if not incoming_path.is_file():
        return False, []
    incoming = load_json(incoming_path)
    current = load_json(approved / "contracts.json")
    changed_files = [
        value for value in incoming.get("changed_files", [])
        if isinstance(value, str) and value
    ]
    for value in (incoming, current):
        value.pop("erd_version", None)
        value.pop("changed_files", None)
    return incoming != current or bool(changed_files), changed_files


def new_ac_ids(staging: Path, approved: Path, repo: Path) -> set[str]:
    added: set[str] = set()
    incoming_prd = staging / "PRD.md"
    if incoming_prd.is_file():
        added |= ac_ids(incoming_prd) - ac_ids(approved / "PRD.md")
    for incoming in staged_test_files(staging):
        relative = incoming.relative_to(staging)
        added |= ac_ids(incoming) - ac_ids(repo / relative)
    return added


def validate(staging: Path, approved: Path, repo: Path, current_version: int) -> str:
    if current_version == 0:
        return "initial"

    contract_delta, changed_files = contracts_changed(staging, approved)
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
    if errors:
        raise ValueError("; ".join(errors))
    return "behavioral"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--approved", required=True, type=Path)
    parser.add_argument("--repo", default=Path("."), type=Path)
    parser.add_argument("--current-version", required=True, type=int)
    args = parser.parse_args()
    try:
        print(validate(args.staging, args.approved, args.repo, args.current_version))
    except ValueError as exc:
        print(f"SPEC DELTA FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
