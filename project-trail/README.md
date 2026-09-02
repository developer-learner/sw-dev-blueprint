# project-trail/ — the project's running trail (exploratory companion to the frozen specs)

The unauthoritative running record of everything AROUND the system: rejected
alternatives with their reasoning, explorations and benchmarks, incident
writeups, near-misses, scratch thinking, external context (links, quotes,
things read that shaped a prior). The frozen specs and DECISIONS.md are
optimized for the pipeline to consume; this directory is the corpus a model
will later be asked to parse — at milestone or project close — to extract
learnings and produce a CEO summary (D-84). Write what that future reader
would need that no authoritative artifact captures: the why behind a choice,
the paths not taken, what broke and how it looked from the operator seat.

Rules:

- **Project-authored, routinely.** The working session (conductor seat)
  writes notes as part of normal doc upkeep — same authorship lane as
  `docs/` and `tasks/CURRENT.md` — and the human adds whatever they like.
  Expected cadence: a narrative note for what is worth remembering — major
  incidents, decisions, and explorations — not a mechanical per-session entry.
  Breadth is welcome, but the signal is what a future reader could not
  reconstruct from the tree (DECISIONS.md, specs, git). Pipeline phases (EM/coder)
  remain structurally excluded — this directory is outside every
  `.gate-paths` lane, so INV-2 fails closed on any pipeline-phase write.
- **Notes are narrative, never evidence.** An agent-written note is a claim
  by that session. The authoritative record stays in DECISIONS.md, the
  frozen specs, and git history; when a note and the tree disagree, the tree
  wins (Operating Rule 5 — see the 2026-07-19 disposition-ledger overclaim
  in the CLAUDE.md correction log for why this rule is written down).
- **Nothing here is authoritative** and nothing in the pipeline reads it.
  References are one-way: a note cites decisions and specs by number/path;
  nothing cites back. No gate may ever depend on a note's presence, absence,
  or content.
- **Keep files committed** — INV-2 counts untracked files repo-wide during
  runs.
- **Flat and dated:** `YYYY-MM-DD-short-slug.md`, grep over hierarchy.
  Incident writeups keep `status: historical`.
- **DECISIONS.md remains the single decision log.** When a note graduates
  into a rule or spec, it travels the normal decision/refreeze flow; the
  note stays behind as the why-trail.

No required fields, no taxonomy, no linter — structure would slow the
capture, and the mining model handles unstructured. The one quality bar:
a note should say something the git history alone cannot.
