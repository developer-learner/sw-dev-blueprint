#!/usr/bin/env python3
"""check-prd-additive.py — PRD additive-only guard (D-136).

The PRD is the standing product record. A milestone may ADD product context
and acceptance criteria to it, but it may not silently drop what came before:
the product capsule (the introduction paragraph tpm-pack.sh ships as milestone
context) must survive unchanged, and no historical acceptance-criterion id may
disappear. Superseding a criterion is a real operation — it goes through the
ERD-DELTA (D-107), which records the supersession while the PRD keeps the
historical id. A criterion that simply vanishes from a staged PRD is a
fail-closed error: the loss is either an accident or an unrecorded supersession,
and both are caught here before the freeze.

This runs only when a PRD is staged over an existing one (v>1). The capsule
extraction mirrors tpm-pack.sh's product_capsule/first_paragraph so the text
this guard protects is exactly the text the milestone context ships.

Usage: check-prd-additive.py <standing-PRD.md> <staged-PRD.md>
Exit 0 when the staged PRD is additive; exit 1 naming the removed capsule or
AC ids.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AC_ID = re.compile(r"\bAC-(\d+)\b")


def first_paragraph(lines: list[str], start: int) -> str:
    """Read one Markdown paragraph after a heading (mirrors tpm-pack.sh)."""
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
    """Select the PRD's product-introduction paragraph (mirrors tpm-pack.sh)."""
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


def check(standing: str, staged: str) -> list[str]:
    errors: list[str] = []
    capsule = product_capsule(standing)
    if capsule and capsule not in normalize(staged):
        errors.append(
            "the standing product capsule text was removed or altered — a "
            "staged PRD must carry it unchanged (additive-only)")
    standing_acs = {f"AC-{m.group(1)}" for m in AC_ID.finditer(standing)}
    staged_acs = {f"AC-{m.group(1)}" for m in AC_ID.finditer(staged)}
    removed = sorted(standing_acs - staged_acs, key=lambda a: int(a.split("-")[1]))
    if removed:
        errors.append(
            "historical acceptance criteria removed: "
            f"{', '.join(removed)} — supersessions go through ERD-DELTA.md; "
            "the PRD stays additive")
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
