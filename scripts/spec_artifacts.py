#!/usr/bin/env python3
"""Shared path policy for TPM shuttle and refreeze staging artifacts."""

from __future__ import annotations

import re
import sys
from pathlib import Path


DOCUMENT_PATHS = ("PRD.md", "ERD.md", "ERD-DELTA.md", "contracts.json")
EXACT_PATHS = frozenset((*DOCUMENT_PATHS, "REMOVED"))
DISPLAY_PATHS = (*DOCUMENT_PATHS, "REMOVED", "tests/<...>", "captures/<...>")
TEST_PATH = re.compile(r"tests/[A-Za-z0-9_./-]+")
CAPTURE_PATH = re.compile(r"captures/[A-Za-z0-9_./-]+")


def allowed_description() -> str:
    return ", ".join(DISPLAY_PATHS)


def is_allowed(path: str) -> bool:
    """Return whether *path* is an allowed repo-relative staging artifact."""
    parts = path.split("/")
    if (not path or path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)):
        return False
    if path in EXACT_PATHS:
        return True
    return bool(TEST_PATH.fullmatch(path) or CAPTURE_PATH.fullmatch(path))


def invalid_under(root: Path) -> list[str]:
    """List every non-directory entry under *root* that violates the policy."""
    invalid = []
    for candidate in root.rglob("*"):
        if candidate.is_file() or candidate.is_symlink():
            relative = candidate.relative_to(root).as_posix()
            if not is_allowed(relative):
                invalid.append(relative)
    return sorted(invalid)


def main(argv: list[str]) -> int:
    if argv == ["describe"]:
        print(allowed_description())
        return 0
    if argv == ["documents"]:
        print("\n".join(DOCUMENT_PATHS))
        return 0
    if len(argv) == 2 and argv[0] == "invalid-under":
        root = Path(argv[1])
        if not root.is_dir():
            print(f"spec-artifacts: staging dir not found: {root}", file=sys.stderr)
            return 2
        print("\n".join(invalid_under(root)))
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        invalid = [path for path in argv[1:] if not is_allowed(path)]
        for path in invalid:
            print(f"disallowed path: {path!r}", file=sys.stderr)
        return 1 if invalid else 0
    print(
        "usage: spec_artifacts.py "
        "<describe|documents|invalid-under DIR|check PATH...>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
