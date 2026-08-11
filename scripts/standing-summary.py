#!/usr/bin/env python3
"""Generate standing rules plus a compact file-interface map (D-116).

The current ERD-DELTA.md is the milestone authority (D-107). The standing
ERD contributes only durable rule sections and a map of file interfaces;
oracle inventories, smoke tours, risk registers, and accumulated prose do
not belong in milestone context. File descriptions use the complete first
paragraph of each file bullet before applying the 140-character cap.

Usage: standing-summary.py [path-to-ERD.md] > standing-summary.md
Exit 0 with the summary; exit 1 when the ERD is missing, unreadable, or the
generated slice would exceed its source (the caller falls back loudly).
"""
import re
import sys
from pathlib import Path


FILE_BULLET = re.compile(r"^[*-] \*\*`([^`]+)`\*\*\s*[—-]\s*(.*)$")
RULE_HEADING = re.compile(r"\b(invariant|rule|constraint)s?\b", re.I)


def section_heading(section: str) -> str:
    """Return the first Markdown heading in a section (D-116)."""
    return section.splitlines()[0].strip() if section.splitlines() else ""


def is_rule_section(section: str) -> bool:
    """Recognize durable rule sections without retaining every appendix (D-116)."""
    return bool(RULE_HEADING.search(section_heading(section)))


def truncate_description(description: str, limit: int = 140) -> str:
    """Cap an interface summary at a word boundary (D-116)."""
    normalized = re.sub(r"\s+", " ", description).strip()
    if len(normalized) <= limit:
        return normalized
    prefix = normalized[: limit - 3].rstrip()
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip(" ,;:") + "..."


def file_map(sections: list[str]) -> list[str]:
    """Summarize each architecture file bullet's first paragraph (D-116)."""
    mapped: list[str] = []
    seen: set[str] = set()
    for section in sections:
        if "architecture" not in section_heading(section).lower():
            continue
        lines = section.splitlines()
        index = 0
        while index < len(lines):
            match = FILE_BULLET.match(lines[index])
            if not match:
                index += 1
                continue
            name, opening = match.groups()
            paragraph = [opening]
            index += 1
            while index < len(lines):
                continuation = lines[index]
                if not continuation.strip() or FILE_BULLET.match(continuation):
                    break
                if continuation.startswith("## "):
                    break
                paragraph.append(continuation.strip())
                index += 1
            if name not in seen:
                description = truncate_description(" ".join(paragraph))
                mapped.append(f"- `{name}` — {description}")
                seen.add(name)
    return mapped


def summarize(text: str) -> str:
    """Build the rules-and-file-map standing slice (D-116)."""
    sections = re.split(r"\n(?=## )", text)
    title = sections[0].split("\n## ", 1)[0].strip()
    rules = [section.rstrip() for section in sections if is_rule_section(section)]
    mapped = file_map(sections)

    output = [title] if title else ["# Standing ERD summary"]
    output.extend(rules)
    output.append("## File map")
    output.extend(mapped or ["(no architecture file bullets)"])
    return "\n\n".join(output).rstrip() + "\n"


def main() -> int:
    """Read the standing ERD and emit its D-116 milestone context."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "scripts/.approved/ERD.md"
    )
    if not path.is_file():
        return 1
    try:
        text = path.read_text()
    except OSError:
        return 1
    summary = summarize(text)
    if len(summary.encode()) > len(text.encode()):
        return 1
    sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
