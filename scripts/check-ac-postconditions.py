#!/usr/bin/env python3
"""S5 lint: state-changing ACs must carry post-condition clauses.

The M29 defect class: ACs specifying mechanisms (``terminate the process``)
without observable postconditions (``such that the health endpoint returns
503``) produce tests that cannot fail.  Any staged PRD or ERD-DELTA carrying
a state-changing AC without a ``such that`` clause is rejected at refreeze.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AC_ID = re.compile(r"\bAC-(\d+)\b")
HEADING = re.compile(r"^##\s", re.MULTILINE)

STATE_VERBS = re.compile(
    r"\b(spawn|terminate|kill|unload|evict|delete|release|clear|cancel)\b",
    re.IGNORECASE,
)
POST_CONDITION = re.compile(r"\bsuch that\b", re.IGNORECASE)


def extract_acs(text: str) -> list[tuple[str, str]]:
    """Return (ac_id, ac_text) for each unique AC definition in *text*."""
    matches = list(AC_ID.finditer(text))
    if not matches:
        return []
    seen: set[str] = set()
    acs: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        ac_id = f"AC-{m.group(1)}"
        if ac_id in seen:
            continue
        seen.add(ac_id)
        start = m.start()
        end = len(text)
        if i + 1 < len(matches):
            end = min(end, matches[i + 1].start())
        h = HEADING.search(text, m.end())
        if h:
            end = min(end, h.start())
        acs.append((ac_id, text[start:end].strip()))
    return acs


def check_file(path: Path) -> list[str]:
    """Return error messages for ACs violating the S5 post-condition rule."""
    if not path.is_file():
        return []
    text = path.read_text()
    errors: list[str] = []
    for ac_id, ac_text in extract_acs(text):
        verbs = STATE_VERBS.findall(ac_text)
        if verbs and not POST_CONDITION.search(ac_text):
            unique = sorted(set(v.lower() for v in verbs))
            errors.append(
                f"{ac_id}: state-changing verb ({', '.join(unique)}) "
                f"without 'such that' post-condition clause"
            )
    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check-ac-postconditions.py <file>...", file=sys.stderr)
        return 2
    all_errors: list[str] = []
    for arg in sys.argv[1:]:
        path = Path(arg)
        for error in check_file(path):
            all_errors.append(f"{path}: {error}")
    for error in all_errors:
        print(error, file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
