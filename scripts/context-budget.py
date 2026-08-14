#!/usr/bin/env python3
"""Byte budgets and no-expansion checks for model context (D-145).

Absolute budgets are regression warnings: a safe full-artifact fallback may
legitimately exceed one and must remain available.  Relative slice checks are
fail-closed: a generated slice larger than its source is not a trim and the
caller must use its existing loud fallback instead.

Usage:
  context-budget.py warn <surface> <file> [<file> ...]
  context-budget.py warn-bytes <surface> <nonnegative-byte-count>
  context-budget.py slice <surface> <slice-file> <source-file> [<source-file> ...]
"""

import sys
from pathlib import Path


SURFACE_BUDGETS: dict[str, int] = {
    "tpm-stage1": 88_000,
    "standing-summary": 8_192,
    "interface-index": 16_384,
    "em-context": 65_536,
    "escalation-shared": 32_768,
}


def file_bytes(paths: list[Path]) -> int:
    """Return the exact byte total of existing context files (D-145)."""
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError as exc:
            raise ValueError(f"cannot read context file {path}: {exc}") from exc
    return total


def warn_if_over(surface: str, size: int) -> None:
    """Warn when a named surface exceeds its pinned D-145 byte budget."""
    if surface not in SURFACE_BUDGETS:
        raise ValueError(f"unknown budget surface {surface!r}")
    limit = SURFACE_BUDGETS[surface]
    if size > limit:
        sys.stderr.write(
            f"context-budget: WARNING {surface} is {size} bytes "
            f"(budget {limit}; over by {size - limit})\n"
        )


def check_slice(surface: str, slice_path: Path, sources: list[Path]) -> int:
    """Reject context expansion and warn on a named surface when applicable."""
    slice_size = file_bytes([slice_path])
    source_size = file_bytes(sources)
    if slice_size > source_size:
        sys.stderr.write(
            f"context-budget: ERROR {surface} slice is {slice_size} bytes, "
            f"larger than its {source_size}-byte source\n"
        )
        return 1
    if surface in SURFACE_BUDGETS:
        warn_if_over(surface, slice_size)
    return 0


def parse_nonnegative_bytes(raw: str) -> int:
    """Parse an exact byte count without accepting signs or decimals."""
    if not raw.isdigit():
        raise ValueError(f"byte count must be a nonnegative integer, got {raw!r}")
    return int(raw)


def main(argv: list[str]) -> int:
    """Run one D-145 warning or slice-invariant check."""
    if len(argv) < 3:
        sys.stderr.write(__doc__.split("Usage:\n", 1)[1])
        return 2
    command, surface, *args = argv[1:]
    try:
        if command == "warn" and args:
            warn_if_over(surface, file_bytes([Path(arg) for arg in args]))
            return 0
        if command == "warn-bytes" and len(args) == 1:
            warn_if_over(surface, parse_nonnegative_bytes(args[0]))
            return 0
        if command == "slice" and len(args) >= 2:
            return check_slice(
                surface,
                Path(args[0]),
                [Path(arg) for arg in args[1:]],
            )
    except ValueError as exc:
        sys.stderr.write(f"context-budget: {exc}\n")
        return 2
    sys.stderr.write(f"context-budget: invalid arguments: {' '.join(argv[1:])}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
