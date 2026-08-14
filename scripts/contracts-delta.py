#!/usr/bin/env python3
"""contracts-delta.py — milestone-only contracts context (D-120) and the TPM
two-stage intake index (D-141).

Body mode (default): contracts.json accumulates every milestone's routes,
schemas, and errors. The EM plans deltas against the current ERD-DELTA.md
(authoritative, D-107); it needs contract bodies for the files this milestone
touches, not the full accumulated load. Entries pin their owning file (schema
"file" field, D-120): this generator ships pinned entries whose file is in
this milestone's exact active inventory in full and carries every unpinned
entry in full (a missing pin is a conservative carry, never a silent drop).
Pinned entries outside the inventory are omitted entirely: this artifact is
the in-scope contract body, not an index of accumulated interfaces (the index
has its own mode, below). Entry points are self-pinning: "src.module:app"
derives to src/module.py and is kept only when that module is in the
inventory. While NO entry carries a file pin (the backfill is TPM-seat and
pending), the output is byte-identical to the input — the slice activates
inertly the moment pins land.

Index mode (--index): emits the COMPLETE interface index — every entry point,
route (method/path), schema (field NAMES only), error (status), and ui id
(testid) in the accumulated spec, each with its owning-file pin, "(unpinned)"
when no pin exists (and therefore always carried in body mode). This is the
stage-1 TPM intake view (D-141): nothing the accumulated spec holds is hidden
by the previous milestone's inventory, and full bodies arrive only for files
the TPM names after hearing the new feature's intent (tpm-pack.sh
--contracts-for). Bodies never live in the index: its completeness invariant
is D-120's no-silent-drop applied to the whole surface.

Usage: contracts-delta.py [--index] [path-to-contracts.json] > slice.json
SWBP_CONTRACT_FILES, when present, is the newline-delimited active inventory.
Otherwise the default inventory source is D-140-driven: the newest modern
DELTA snapshot (inventory_files-bearing) beside the contracts file is
authoritative and may be empty (a consolidation keeps no standing pin);
an all-legacy range falls back to the historical contracts.files.
Exit 0 with the slice; exit 1 when the contracts file is missing, unreadable,
not the expected shape, or the active-inventory snapshot is malformed (the
shell falls back to the full contracts file — never a silent standing slice).
"""
import json
import os
import re
import sys
from pathlib import Path

INDEX_MODE = len(sys.argv) > 1 and sys.argv[1] == "--index"
if INDEX_MODE:
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("scripts/.approved/contracts.json")
else:
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


def interface_index(contracts: dict) -> dict:
    """The complete interface index (D-141): every interface with its owning
    file and a minimal signature — names and pins only, never bodies.

    Shapes: `entry_points` are plain ids — they self-pin (the module is
    derivable from `src.pkg.mod:obj`), so no per-id file field is needed.
    The pinned families (`routes`/`schemas`/`errors`/`ui`) are grouped into
    `by_file`, keyed by owning file (or `(unpinned)`), with every entry's
    minimal signature nested under its file key — the file path is written
    once per owning file instead of repeated on ~120 entries (compact, and
    lossless: every interface id still appears, pinned or not)."""
    entry_points = list(contracts.get("entry_points", []))
    by_file: dict[str, dict] = {}
    for entry in contracts.get("routes", []):
        _add(by_file, "routes", entry_pin(entry), {
            "id": entry.get("id"), "method": entry.get("method"),
            "path": entry.get("path"),
        })
    for entry in contracts.get("schemas", []):
        fields = entry.get("fields", {})
        _add(by_file, "schemas", entry_pin(entry), {
            "id": entry.get("id"),
            "fields": list(fields.keys()) if isinstance(fields, dict) else [],
        })
    for entry in contracts.get("errors", []):
        _add(by_file, "errors", entry_pin(entry), {
            "id": entry.get("id"), "status": entry.get("status"),
        })
    for entry in contracts.get("ui", []):
        _add(by_file, "ui", entry_pin(entry), {
            "id": entry.get("id"), "testid": entry.get("testid"),
        })
    index = {
        "kind": "interface-index (D-141)",
        "counts": {
            "entry_points": len(entry_points),
            "routes": len(contracts.get("routes", [])),
            "schemas": len(contracts.get("schemas", [])),
            "errors": len(contracts.get("errors", [])),
            "ui": len(contracts.get("ui", [])),
        },
        "entry_points": entry_points,
        "by_file": by_file,
    }
    return index


def _add(by_file: dict, family: str, pin: str, entry: dict) -> None:
    """Lose nothing while grouping: drop a key only when it is an unpinned
    placeholder — the grouped key itself carries the pin, so the entry need
    not repeat it."""
    group = by_file.setdefault(pin or "(unpinned)", {})
    family_list = group.setdefault(family, [])
    family_list.append(entry)


def default_inventory(contracts_dir: Path, contracts: dict) -> list[str]:
    """Standalone (no SWBP_CONTRACT_FILES) inventory source (D-140).

    The newest DELTA-vN.json snapshot in the contracts' directory is
    authoritative when it is modern (carries inventory_files); its exact list
    is returned (possibly empty — a consolidation). If every retained delta is
    legacy or none exists, fall back to the standing contracts.files, the
    historical D-120 behavior. A malformed snapshot raises so the caller fails
    closed instead of silently re-slicing against standing surface.
    """
    newest: Path | None = None
    if contracts_dir.is_dir():
        def _version(delta: Path) -> int:
            match = re.match(r"DELTA-v(\d+)\.json$", delta.name)
            return int(match.group(1)) if match else -1
        for delta in sorted(
            contracts_dir.glob("DELTA-v*.json"), key=_version,
        ):
            newest = delta
    if newest is None:
        return list(contracts.get("files", []))
    snapshot = json.loads(newest.read_text())
    if not isinstance(snapshot, dict) or "inventory_files" not in snapshot:
        return list(contracts.get("files", []))
    inventory = snapshot.get("inventory_files")
    if not isinstance(inventory, list) or not all(
        isinstance(item, str) for item in inventory
    ):
        raise ValueError(f"{newest.name}: inventory_files is not an array of strings")
    return list(inventory)


def emit_json_slice(payload: dict) -> None:
    """Emit compact JSON only when it is no larger than its source (D-145)."""
    output = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ) + "\n"
    if len(output.encode()) > len(raw.encode()):
        sys.exit(1)
    sys.stdout.write(output)


if INDEX_MODE:
    emit_json_slice(interface_index(contracts))
    sys.exit(0)

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
    # D-140: never slice against the standing accumulated contracts.files when
    # the active inventory is available. A modern DELTA snapshot
    # (inventory_files-bearing) beside the contracts file is authoritative for
    # the standalone default — it may be empty (a consolidation carries no
    # build work), in which case no standing pin is kept. All-legacy ranges
    # (no modern snapshot anywhere) retain the historical contracts.files
    # behavior. A malformed snapshot fails closed rather than silently
    # reapplying the standing slice.
    try:
        files = set(default_inventory(path.parent, contracts))
    except (OSError, json.JSONDecodeError, ValueError):
        sys.exit(1)
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
# is EM context, not a human artifact. D-145 verifies the actual bytes instead
# of assuming compact JSON is smaller than an already-compact source.
emit_json_slice(sliced)
