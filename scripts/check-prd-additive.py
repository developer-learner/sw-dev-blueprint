#!/usr/bin/env python3
"""check-prd-additive.py — PRD additive-only guard (D-136).

The PRD is the standing product record. A milestone may ADD product context
and acceptance criteria to it, but it may not silently alter or drop what came
before: the product capsule (the identifying introduction paragraph) must
survive unchanged, and every historical acceptance-criterion block must remain
present, unique, contiguous, and textually unchanged after whitespace
normalization (D-148). Superseding a criterion is a real operation — it goes
through the ERD-DELTA (D-107), which records the supersession while the PRD
keeps the historical block.

This runs only when a PRD is staged over an existing one (v>1). The capsule
extraction identifies the durable product introduction independently of the
chat packer, which now ships the complete PRD (D-147 amended).

Usage: check-prd-additive.py <standing-PRD.md> <staged-PRD.md>
Exit 0 when the staged PRD is additive; exit 1 naming the removed capsule or
the missing, duplicated, or altered AC blocks.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AC_START = re.compile(
    r"^\s*(?:[-*+]\s+|#{1,6}\s+)(?:\*\*)?AC-(\d+)"
    r"(?::)?(?:\*\*)?\s*:?.*$",
    re.I,
)
HEADING = re.compile(r"^\s*#{1,6}\s+")


def first_paragraph(lines: list[str], start: int) -> str:
    """Read one Markdown paragraph after a product heading."""
    paragraph: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        if not line.strip():
            if paragraph:
                break
            continue
        paragraph.append(line.strip())
    return re.sub(r"\s+", " ", " ".join(paragraph)).strip()


def product_capsule(prd: str) -> str:
    """Select the PRD's product-introduction paragraph."""
    lines = prd.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+(what\b|product\b|overview\b)", line, re.I):
            return first_paragraph(lines, index + 1)
    for index, line in enumerate(lines):
        if line.startswith("#") or not line.strip():
            continue
        paragraph = first_paragraph(lines, index)
        if paragraph:
            return paragraph
    return ""


def normalize(text: str) -> str:
    """Collapse whitespace so capsule containment ignores reflow."""
    return re.sub(r"\s+", " ", text).strip()


def acceptance_blocks(prd: str) -> dict[str, list[str]]:
    """Return normalized Markdown AC blocks grouped by id (D-148)."""
    lines = prd.splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = AC_START.match(line)
        if match:
            starts.append((index, f"AC-{int(match.group(1))}"))

    blocks: dict[str, list[str]] = {}
    for position, (start, ac_id) in enumerate(starts):
        next_start = starts[position + 1][0] if position + 1 < len(starts) \
            else len(lines)
        end = next_start
        for index in range(start + 1, next_start):
            if HEADING.match(lines[index]):
                end = index
                break
        blocks.setdefault(ac_id, []).append(normalize("\n".join(lines[start:end])))
    return blocks


def check(standing: str, staged: str) -> list[str]:
    errors: list[str] = []
    capsule = product_capsule(standing)
    if capsule and capsule not in normalize(staged):
        errors.append(
            "the standing product capsule text was removed or altered — a "
            "staged PRD must carry it unchanged (additive-only)")
    standing_acs = acceptance_blocks(standing)
    staged_acs = acceptance_blocks(staged)
    removed = sorted(standing_acs.keys() - staged_acs.keys(),
                     key=lambda a: int(a.split("-")[1]))
    if removed:
        errors.append(
            "historical acceptance criteria removed: "
            f"{', '.join(removed)} — supersessions go through ERD-DELTA.md; "
            "the PRD stays additive")
    duplicated = sorted(
        (ac_id for ac_id, blocks in staged_acs.items() if len(blocks) != 1),
        key=lambda a: int(a.split("-")[1]),
    )
    if duplicated:
        errors.append(
            "acceptance criteria duplicated: "
            f"{', '.join(duplicated)} — every AC id must have one contiguous block")
    altered = sorted(
        (ac_id for ac_id in standing_acs.keys() & staged_acs.keys()
         if len(standing_acs[ac_id]) != 1
         or len(staged_acs[ac_id]) != 1
         or standing_acs[ac_id][0] != staged_acs[ac_id][0]),
        key=lambda a: int(a.split("-")[1]),
    )
    if altered:
        errors.append(
            "historical acceptance criteria altered or split: "
            f"{', '.join(altered)} — historical AC blocks are immutable; "
            "supersessions go through ERD-DELTA.md")
    return errors


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check-prd-additive.py <standing-PRD.md> <staged-PRD.md>",
              file=sys.stderr)
        return 2
    try:
        standing = Path(sys.argv[1]).read_text()
        staged = Path(sys.argv[2]).read_text()
    except OSError as exc:
        sys.exit(f"REFREEZE FAIL (D-136 PRD additive guard): cannot read PRD: {exc}")
    errors = check(standing, staged)
    if errors:
        sys.exit("REFREEZE FAIL (D-136 PRD additive guard): " + "; ".join(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
