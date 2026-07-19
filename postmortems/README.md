# postmortems/ — incident archive

One file per incident that **changed how the system works** — a rule, gate, or
invariant exists (or changed) because of it. Not every bug qualifies: if only
code changed, it goes in the correction log, not here. Naming:
`YYYY-MM-DD-short-slug.md` (incident date). Header: title, `date:`,
`status: historical`. Suggested sections — what happened, root cause, what
changed as a result, lessons — none required; one page, precision over
completeness. Human-authored; agents may read on request but never write
(advisory for the conductor seat; pipeline phases are structurally excluded —
this directory is outside every `.gate-paths` lane, so INV-2 fails closed on
any pipeline-phase write). Nothing here is authoritative and nothing in the
pipeline reads it (D-76): postmortems cite decisions and specs by number/path;
nothing cites back. Keep files committed — INV-2 counts untracked files
repo-wide during runs. If a file wouldn't answer a specific future question,
don't write it.
