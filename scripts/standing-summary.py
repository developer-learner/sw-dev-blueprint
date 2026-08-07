#!/usr/bin/env python3
"""standing-summary.py — the EM's standing context, minimal (D-116).

The standing ERD's "As-built architecture" sections accumulate every
milestone's implementation detail. The EM plans deltas against the current
ERD-DELTA.md (authoritative, D-107); the standing doc's only standing value
is its rules (invariants, file inventory, oracle mapping, risk notes) and a
file-level map of who owns what. This generator replaces the accumulated
architecture prose with that file map, so the EM prompt carries the
milestone slice plus a small standing map instead of the full standing ERD.

Usage: standing-summary.py [path-to-ERD.md] > standing-summary.md
Exit 0 with the summary; exit 1 when the ERD is missing or unreadable.
"""
import re
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scripts/.approved/ERD.md")
if not path.is_file():
    sys.exit(1)
text = path.read_text()


def file_map(section):
    lines = []
    for m in re.finditer(r"^\* \*\*`([^`]+)`\*\*\s*—\s*(.*)$", section, re.M):
        name = m.group(1)
        desc = re.sub(r"\s+", " ", m.group(2)).strip()
        if len(desc) > 140:
            desc = desc[:140].rstrip() + "..."
        lines.append(f"- `{name}` — {desc}")
    return lines


out = []
for section in re.split(r"\n(?=## )", text):
    if section.startswith("## As-built architecture"):
        files = file_map(section)
        title = section.splitlines()[0]
        out.append(f"{title} (file map)")
        out.extend(files or ["(no file bullets)"])
    else:
        out.append(section.rstrip())

sys.stdout.write("\n\n".join(out).rstrip() + "\n")
