#!/usr/bin/env python3
"""contracts-merge.py — staged-merge producer for contracts.json (D-136).

contracts.json accumulates every milestone's routes/schemas/errors/ui (the
15-routes/46-UI class). Making the TPM return the whole accumulated file to
change two entries is the full-file-replacement shape D-136 rejects: it makes
silent loss the default failure mode (an entry dropped or mutated off-screen
ships unnoticed) and forces the TPM to reproduce content it never saw.

Instead the TPM stages ONLY the changed/new entries — each carrying its `file`
pin (D-120/D-124) — in scripts/.approved/incoming/contracts.json, omitting any
id-array whose entries are all carried. D-137 adds explicit, family-scoped
tombstones under the staged-only `remove` object; omission still means carry.
This producer merges that delta onto the standing contracts.json and verifies
the merge MECHANICALLY, fail-closed:

  * The id-bearing arrays (routes/schemas/errors/ui) merge by id. The delta's
    changed set is the ids it names (the entries it stages). A staged entry
    with a KNOWN id updates it in place; a staged entry with a NEW id is
    appended; every id the delta does NOT name is carried byte-identical from
    standing (an id-array the delta omits entirely carries in full).
  * G1 — untouched remainder: every carried id must be byte-identical to
    standing (the checksum the merge is trusted on). A carried entry that
    differs is a merge-integrity failure and dies with the id named.
  * G2 — touched-unchanged: a staged entry byte-identical to standing changed
    nothing; it is the redundant-load the delta shape exists to remove, so it
    fails closed with the id named (this is what rejects a full-file return —
    its carried entries are all identical to standing).
  * G3 — new ids: any id in the merged file absent from standing must be one
    the delta named (present in the staged arrays).
  * G4 — explicit removals: every tombstone must name an existing item in the
    stated family, may appear only once, and may not also be staged as an
    update. Unknown, cross-family, duplicate, and update+remove directives die
    with the offending name. The transient `remove` object is never emitted.
  * entry_points apply the same exact-name tombstones, then union onto standing
    (unremoved surface preserved, new symbols appended) so INV-4 still covers
    carried tests; the merged file's entry_points then face the existing
    deterministic slice rule (D-120).

Everything else splits by kind: files/erd_version are required restatements
(the refreeze sanity check dies if omitted) and changed_files is a transient
per-freeze declaration; the carried accumulators (no_edit_files, externals,
test_mapping, smoke_checks) merge like the id-arrays do — omitted means
carried byte-identical from standing, staged explicit-empty is the only way
to clear them (D-136's remainder checksum applied to the scalar surface).

The merge is a PRODUCER, never an authority: the merged file it emits still
faces every existing freeze gate (check-spec-delta, check-test-surface,
pin-gate, D-78 live interface). Its only job is to reconstruct the full
contracts.json the delta implies, and to prove it touched nothing it did not
name.

Usage: contracts-merge.py <standing.json> <staged-partial.json> > merged.json
Exit 0 with the merged contracts on stdout; exit 1 with a REFREEZE FAIL
message naming the offending id on any guard violation or malformed input.
"""
import json
import sys
from pathlib import Path

# The id-bearing arrays that accumulate across milestones and therefore merge.
MERGE_KEYS = ("routes", "schemas", "errors", "ui")
REMOVE_KEYS = ("entry_points",) + MERGE_KEYS


def die(msg: str) -> None:
    sys.exit(f"REFREEZE FAIL (D-136 contracts merge): {msg}")


def load(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read {path}: {exc}")
    if not isinstance(data, dict):
        die(f"{path} is not a JSON object")
    return data


def canon(entry: object) -> str:
    """Canonical bytes for byte-identity comparison (order-insensitive)."""
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def removal_directives(staged: dict) -> dict[str, set[str]]:
    """Parse D-137's staged-only, family-scoped tombstones fail-closed."""
    raw = staged.get("remove", {})
    if not isinstance(raw, dict):
        die("staged remove directive must be an object")
    unknown = sorted(set(raw) - set(REMOVE_KEYS))
    if unknown:
        die("staged remove directive names unknown family/families: "
            + ", ".join(unknown))
    parsed: dict[str, set[str]] = {}
    for key in REMOVE_KEYS:
        values = raw.get(key, [])
        if not isinstance(values, list):
            die(f"staged remove.{key} must be an array")
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                die(f"staged remove.{key} entries must be non-empty strings")
            if value in seen:
                die(f"staged remove.{key} names {value} twice")
            seen.add(value)
        parsed[key] = seen
    return parsed


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: contracts-merge.py <standing.json> <staged-partial.json>",
              file=sys.stderr)
        return 2
    standing = load(sys.argv[1])
    staged = load(sys.argv[2])
    removals = removal_directives(staged)

    # Scalar keys split two ways:
    #   * required restatements — files and erd_version: the refreeze sanity
    #     check demands them on the staged file, dying before this producer
    #     runs if omitted; changed_files is a per-freeze TRANSIENT
    #     declaration (carrying the previous freeze's would be a lie).
    #   * carried accumulators — no_edit_files, externals, test_mapping,
    #     smoke_checks: D-136's byte-identical remainder extends to them. An
    #     artifact that omits one carries the standing value intact; a
    #     staged EXPLICIT empty ([]/{}) is the only way to clear it. A
    #     silent omission must not strip the frozen spec of its coder
    #     protections, external captures, test pins, or smoke checks just
    #     because a behavioural freeze forgot to restate them.
    merged = {key: value for key, value in staged.items() if key != "remove"}
    for key in ("no_edit_files", "externals", "test_mapping", "smoke_checks"):
        if key not in merged and key in standing:
            merged[key] = standing[key]

    for key in MERGE_KEYS:
        standing_entries = standing.get(key) or []
        staged_entries = staged.get(key) or []
        if not isinstance(standing_entries, list) or not isinstance(staged_entries, list):
            die(f"contracts.{key} must be an array in both files")

        # Index standing by id, preserving order. A standing entry with no id
        # would be silently un-carriable, so fail closed rather than drop it.
        standing_by_id: dict[str, object] = {}
        standing_order: list[str] = []
        for entry in standing_entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                die(f"standing contracts.{key} has an entry with no id — "
                    f"cannot merge safely")
            eid = entry["id"]
            if eid in standing_by_id:
                die(f"standing contracts.{key} names {eid} twice — "
                    f"ambiguous carry")
            standing_by_id[eid] = entry
            standing_order.append(eid)

        removed_set = removals[key]
        for eid in sorted(removed_set):
            if eid not in standing_by_id:
                die(f"remove.{key} names {eid}, which is not present in "
                    f"standing contracts.{key}")

        # The delta's changed set for this array is the ids it stages.
        staged_by_id: dict[str, object] = {}
        staged_order: list[str] = []
        for entry in staged_entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                die(f"staged contracts.{key} has an entry with no id")
            eid = entry["id"]
            if eid in staged_by_id:
                die(f"staged contracts.{key} names {eid} twice")
            if eid in removed_set:
                die(f"contracts.{key} entry {eid} is both staged and removed")
            # G2: a staged entry identical to standing changed nothing.
            if eid in standing_by_id and canon(entry) == canon(standing_by_id[eid]):
                die(f"{key} entry {eid} is staged but byte-identical to "
                    f"standing — the delta must carry only changed/new "
                    f"entries (drop it, or it is a no-op)")
            staged_by_id[eid] = entry
            staged_order.append(eid)
        changed_set = set(staged_order) | removed_set

        # Produce the merged array: carried/updated entries in standing order,
        # then genuinely new entries in the delta's order.
        out: list[object] = []
        for eid in standing_order:
            if eid not in removed_set:
                out.append(
                    staged_by_id[eid]
                    if eid in staged_by_id else standing_by_id[eid]
                )
        for eid in staged_order:
            if eid not in standing_by_id:
                out.append(staged_by_id[eid])

        # G1 + G3: verify the produced array against standing.
        for entry in out:
            eid = entry["id"]
            if eid in standing_by_id and eid not in changed_set:
                # untouched remainder must survive byte-identical
                if canon(entry) != canon(standing_by_id[eid]):
                    die(f"{key} entry {eid} was not named changed but differs "
                        f"from standing (merge integrity)")
            if eid not in standing_by_id and eid not in changed_set:
                # a new id the delta did not name — cannot happen from a clean
                # overlay, so its presence is a producer bug worth failing on
                die(f"{key} entry {eid} is new but not in the delta's "
                    f"changed set")

        if key in standing or key in staged:
            merged[key] = out

    # entry_points: explicit D-137 removals, then the standing+delta union.
    standing_eps = standing.get("entry_points") or []
    staged_eps = staged.get("entry_points") or []
    if not isinstance(standing_eps, list) or not isinstance(staged_eps, list):
        die("contracts.entry_points must be an array in both files")
    removed_eps = removals["entry_points"]
    for ep in sorted(removed_eps):
        if ep not in standing_eps:
            die(f"remove.entry_points names {ep}, which is not present in "
                "standing contracts.entry_points")
        if ep in staged_eps:
            die(f"entry point {ep} is both staged and removed")
    seen: set[str] = set()
    eps: list[str] = []
    for ep in list(standing_eps) + list(staged_eps):
        if ep not in removed_eps and ep not in seen:
            eps.append(ep)
            seen.add(ep)
    merged["entry_points"] = eps

    sys.stdout.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
