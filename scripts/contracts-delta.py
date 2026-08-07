#!/usr/bin/env python3
"""contracts-delta.py — the EM's contracts context, the milestone slice (D-120).

contracts.json accumulates every milestone's routes, schemas, and errors.
The EM plans deltas against the current ERD-DELTA.md (authoritative, D-107);
it needs contract bodies for the files this milestone touches, not the full
accumulated load. Entries pin their owning file (schema "file" field, D-120):
this generator ships pinned entries whose file is in this milestone's
contracts.files inventory in full, carries every unpinned entry in full (a
missing pin is a conservative carry, never a silent drop), and reduces
pinned entries outside the inventory to a one-line index (id + shape + pin)
under `out_of_scope` — the EM still sees that the interface exists, so it
plans against the ERD-delta's integration instructions instead of guessing.
entry_points are self-pinning: "src.module:app" derives to src/module.py,
kept when that module is in the inventory and indexed when it is not.

While NO entry carries a file pin (the backfill is TPM-seat and pending), the
output is byte-identical to the input — the slice activates inertly the
moment pins land.

Usage: contracts-delta.py [path-to-contracts.json] > contracts-delta.json
Exit 0 with the slice; exit 1 when the contracts file is missing, unreadable,
or not the expected shape (the shell falls back to the full contracts file).
"""
import json
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


def entry_pin(entry):
    return entry.get("file") if isinstance(entry, dict) else ""


def entry_point_file(entry_point):
    if not isinstance(entry_point, str) or not entry_point.startswith("src."):
        return ""
    module = entry_point.split(":", 1)[0]
    return module.replace(".", "/") + ".py"


def one_line(key, entry):
    entry_id = entry.get("id", "")
    if key == "routes":
        shape = f"{entry.get('method', '?')} {entry.get('path', '?')}"
    elif key == "schemas":
        fields = entry.get("fields") or []
        names = [f.get("id") if isinstance(f, dict) else str(f) for f in fields]
        shape = ("fields: " + ", ".join(names)) if names else ""
    elif key == "ui":
        shape = f"testid {entry.get('testid')}" if entry.get("testid") else ""
    else:
        shape = entry.get("shape") or ""
    pin = entry.get("file")
    if shape:
        return f"{entry_id} — {shape}; pinned {pin} (outside this milestone)"
    return f"{entry_id}; pinned {pin} (outside this milestone)"


any_pinned = any(
    entry_pin(e) for key in PINNED_KEYS for e in contracts.get(key, [])
)
if not any_pinned:
    sys.stdout.write(raw)
    sys.exit(0)

files = set(contracts.get("files", []))
out_of_scope: list[str] = []
sliced = dict(contracts)
for key in PINNED_KEYS:
    kept = []
    for entry in contracts.get(key, []):
        pin = entry_pin(entry)
        if not pin or pin in files:
            kept.append(entry)
        else:
            out_of_scope.append(one_line(key, entry))
    sliced[key] = kept

kept_points = []
for entry_point in contracts.get("entry_points", []):
    derived = entry_point_file(entry_point)
    if not derived or derived in files:
        kept_points.append(entry_point)
    else:
        out_of_scope.append(
            f"{entry_point} — module outside this milestone (import path exists)")
sliced["entry_points"] = kept_points
if out_of_scope:
    sliced["out_of_scope"] = out_of_scope

sys.stdout.write(json.dumps(sliced, indent=2) + "\n")
