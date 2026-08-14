#!/usr/bin/env python3
"""contracts-delta.py — milestone-only contracts context (D-120).

contracts.json accumulates every milestone's routes, schemas, and errors.
The EM plans deltas against the current ERD-DELTA.md (authoritative, D-107);
it needs contract bodies for the files this milestone touches, not the full
accumulated load. Entries pin their owning file (schema "file" field, D-120):
this generator ships pinned entries whose file is in this milestone's exact
active inventory in full and carries every unpinned entry in full
(a missing pin is a conservative carry, never a silent drop). Pinned entries
outside the inventory are omitted entirely: this artifact is the in-scope
contract body, not an index of accumulated interfaces. Entry points are
self-pinning: "src.module:app" derives to src/module.py and is kept only when
that module is in the inventory.

While NO entry carries a file pin (the backfill is TPM-seat and pending), the
output is byte-identical to the input — the slice activates inertly the
moment pins land.

Usage: contracts-delta.py [path-to-contracts.json] > contracts-delta.json
SWBP_CONTRACT_FILES, when present, is the newline-delimited active inventory;
otherwise contracts.files is the backward-compatible inventory source.
Exit 0 with the slice; exit 1 when the contracts file is missing, unreadable,
or not the expected shape (the shell falls back to the full contracts file).
"""
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scripts/.approved/contracts.json")
if not path.is_file():
    sys.exit(1)
raw = path.read_text()
try:
    contracts = json.loads(raw)
except (OSError, json.JSONDecodeError):
    sys.exit(1)
if not isinstance(contracts, dict):
    sys.exit(1)

PINNED_KEYS = ("routes", "schemas", "errors", "ui")


def entry_pin(entry: object) -> str:
    return entry.get("file") if isinstance(entry, dict) else ""


def entry_point_file(entry_point: object) -> str:
    if not isinstance(entry_point, str) or not entry_point.startswith("src."):
        return ""
    module = entry_point.split(":", 1)[0]
    return module.replace(".", "/") + ".py"


any_pinned = any(
    entry_pin(e) for key in PINNED_KEYS for e in contracts.get(key, [])
)
if not any_pinned:
    sys.stdout.write(raw)
    sys.exit(0)

if "SWBP_CONTRACT_FILES" in os.environ:
    files = {
        line.strip() for line in os.environ["SWBP_CONTRACT_FILES"].splitlines()
        if line.strip()
    }
else:
    files = set(contracts.get("files", []))
sliced = dict(contracts)
for key in PINNED_KEYS:
    kept = []
    for entry in contracts.get(key, []):
        pin = entry_pin(entry)
        if not pin or pin in files:
            kept.append(entry)
    sliced[key] = kept

kept_points = []
for entry_point in contracts.get("entry_points", []):
    derived = entry_point_file(entry_point)
    if not derived or derived in files:
        kept_points.append(entry_point)
sliced["entry_points"] = kept_points

# Compact serialization (P1e / board finding 7 — context trimming): the slice
# is EM context, not a human artifact; compact separators cut ~17% of the
# block (16.2 KB -> 13.4 KB on testchat v103) with zero information loss.
# The pretty-vs-raw size dance is gone: compact is always <= pretty, so the
# slice-never-exceeds-source invariant (D-120) holds by construction.
sys.stdout.write(json.dumps(sliced, separators=(",", ":"), ensure_ascii=False) + "\n")
