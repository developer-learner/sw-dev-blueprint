#!/usr/bin/env python3
"""apply-edit-blocks.py <target-file> <raw-reply-file> — D-59 coder applier.

The coder's contract for EXISTING files is anchored edit blocks:

    <<<<<<< SEARCH
    (exact copy of a short existing section)
    =======
    (that section with the change applied)
    >>>>>>> REPLACE

or the literal line `=== NO CHANGES ===` when the brief is already satisfied
(the mapped tests still gate the task either way).

Fail-closed: every SEARCH must match the target exactly once; a missing or
ambiguous anchor, or a truncated block, aborts with nothing written. Code the
model never quotes is code it can never delete — the M5..M7 deletion disease
(testchat: full-file retypes silently dropped 99 and 119 lines of working
logic) is impossible by construction.

Exit: 0 applied (or no-op) · 1 failure, reason on stderr, target untouched.
"""
import re
import sys

OPEN, SEP, CLOSE = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"
NO_CHANGES = "=== NO CHANGES ==="


def fail(msg: str) -> None:
    print(f"edit-block FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_blocks(raw: str) -> list[tuple[str, str]]:
    """Extract well-formed blocks; any dangling opener means truncation."""
    blocks = []
    pos = 0
    while True:
        s = raw.find(OPEN, pos)
        if s == -1:
            break
        m = raw.find(SEP, s)
        e = raw.find(CLOSE, s)
        if m == -1 or e == -1 or not (s < m < e):
            fail("malformed or truncated edit block (opener without separator/closer)")
        search = raw[s + len(OPEN):m].strip("\n")
        replace = raw[m + len(SEP):e].strip("\n")
        if not search.strip():
            fail("edit block with empty SEARCH section")
        blocks.append((search, replace))
        pos = e + len(CLOSE)
    return blocks


def main() -> None:
    if len(sys.argv) != 3:
        fail("usage: apply-edit-blocks.py <target-file> <raw-reply-file>")
    target, reply_path = sys.argv[1], sys.argv[2]
    raw = open(reply_path).read()

    no_changes_declared = bool(
        re.search(rf"^\s*{re.escape(NO_CHANGES)}\s*$", raw, re.M)
    )
    blocks = parse_blocks(raw)
    if no_changes_declared and blocks:
        # A reply that both declares NO CHANGES and carries edit blocks is
        # ambiguous — treating it as a no-op silently discards the edits.
        # Fail; the retry rung then re-briefs with the specific error.
        fail(
            "reply contains both '=== NO CHANGES ===' and edit blocks; "
            "pick one — either omit all edit blocks (true no-op) or omit "
            "the NO-CHANGES line (real edit)"
        )
    if no_changes_declared:
        print("no changes (coder judged brief already satisfied — mapped tests still gate)")
        return
    if not blocks:
        fail("reply contained no edit blocks and no NO-CHANGES line")

    src = open(target).read()

    # Uniqueness is validated against the ORIGINAL file — the one the coder
    # actually saw — for every block, before anything is applied. Checking
    # against progressively-mutated text let an anchor that was ambiguous in
    # the original become "unique" after an earlier block in the same reply
    # consumed one of its occurrences (audit find, 2026-07-11): the exact
    # confident-wrong-edit class this applier exists to make impossible.
    for i, (search, _replace) in enumerate(blocks, 1):
        n = src.count(search)
        if n == 0:
            head = search.splitlines()[0][:60] if search.splitlines() else ""
            fail(f"block {i}: SEARCH not found in {target} (starts: {head!r})")
        if n > 1:
            fail(f"block {i}: SEARCH matches {n} places in {target} — ambiguous anchor")

    out = src
    for i, (search, replace) in enumerate(blocks, 1):
        if out.count(search) != 1:
            fail(
                f"block {i}: SEARCH was unique in the original file but not "
                f"after earlier blocks were applied — blocks overlap or "
                f"repeat; nothing written"
            )
        out = out.replace(search, replace, 1)

    # Post-apply integrity (testchat M20/M21): a REPLACE payload that itself
    # contains marker lines parses as a well-formed block yet writes raw
    # conflict markers into the target — the corruption then ships silently
    # (browsers skip malformed CSS; greps still match). The applied result
    # must never contain any marker line, fail-closed.
    for ln in out.splitlines():
        stripped = ln.strip()
        if stripped.startswith("<<<<<<<") or stripped.startswith(">>>>>>>") or stripped == SEP:
            fail(
                f"applied result would contain an edit-block marker line "
                f"({stripped[:30]!r}) — a REPLACE payload embedded markers; "
                f"nothing written"
            )

    open(target, "w").write(out)
    print(f"applied {len(blocks)} edit block(s) to {target}")


if __name__ == "__main__":
    main()
