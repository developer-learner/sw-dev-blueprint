# HANDOFF — sw-dev-blueprint changes proposed from testchat M28

date: 2026-07-19 (M28 close-out + same-day postmortem; supersedes the two-item version)
status: EXECUTED 8/9 (2026-07-19, same day) — moved here from testchat/tasks/
on pickup, per the parking note this header replaced. Historical record; the
body below is the proposal as written. Item 6 is the only survivor, promoted
to tasks/BACKLOG.md.
source (paths are testchat-relative): docs/POSTMORTEM-2026-07-19-m28.md, tasks/CURRENT.md 2026-07-19 state, CLAUDE.md correction log 2026-07-19.

Disposition ledger:

| Item | Result | Where |
|------|--------|-------|
| 1 satisfiability preflight | DONE — D-78 | `48195a3` (ground-truthed against real v51/v53) |
| 2 spec-defect ladder rung | DONE — D-79 | `5aac080` (drive-plan.sh end-to-end selftests) |
| 3 flake-vs-drift (D-77) | DONE — D-77 | `eec11a4` keyed triage on plan mapping but left isolation GATING (2/2 passes required) — this row previously claimed the design correction was in; it was not. Corrected 2026-07-19 second pass: isolation demoted to recorded corroboration, D-77 entry amended. |
| 4 D-68 debt sweep at freeze | DONE — D-80 | `57ee499` (advisory at the human gate) |
| 5 gate-symmetry doctrine | DONE — D-81 | `3f9345a` (BLUEPRINT.md Rule 9) |
| 6 EM diagnosis hardening | OPEN | tasks/BACKLOG.md (schema-retry half shipped as D-71; denser-brief half needs a design session) |
| 7 hand-fix ledger + UI-ACs | DONE — D-82 | `5532d8b` |
| 8 freeze hygiene | DONE — D-83 | `966a689` (doc rule + <1h refreeze NOTE, warn-only) |
| 9 housekeeping (.bak) | DONE | `eec11a4` |

Ordered by leverage.

## 1. Freeze-time satisfiability preflight in refreeze.sh  [highest leverage]

**Defect it prevents:** v51 froze the `GET /api/v1/models/catalog` route with
no implementing files in `contracts.files`. validate-plan.py's exact
plan↔inventory bijection made the spec unimplementable by ANY EM — but that
check only runs downstream, so the defect cost ~75 minutes, two EM model
swaps, and a seat escalation before the v53 recut named it.

**Change:** before the human approval prompt (y/N or `--approve <hash>`),
refreeze.sh mechanically verifies every changed/new contract (routes,
entry_points) has implementing files in the delta's `contracts.files`.
Fail closed, naming the uncovered contracts. The bijection logic already
exists in validate-plan.py — extract it to a shared helper or add a
spec-only mode; do not duplicate it.

## 2. Escalation-ladder diagnosis rung: audit the puzzle before swapping the solver

**Defect it prevents:** the ladder interprets every gate failure as evidence
about the actor (retry → consult → swap model → escalate seat). It has no
branch for "the upstream artifact is impossible." Two different EM models
failing identically at the same gate is evidence about the artifact, not
the actors — a maximally capable EM still fails against v51. This is
capability-independent, i.e. not fixable by better models.

**Change:** in orchestrate.sh (which owns the counters): after the second
plan-gate rejection — regardless of whether the model was swapped — run the
item-1 spec self-consistency check. If it fails, halt as SPEC DEFECT and
route to the TPM bundle without consuming further EM strikes or inviting
model swaps. Document the rung in docs/ESCALATION.md.

## 3. D-77 — flake-vs-drift discrimination before the DRIFT halt

**Defect it prevents:** M28's final full suite tripped SPEC DRIFT on
`test_thinking_placeholder_shows_then_clears` (AC-42, M9-era timing test,
unrelated to the delta); 3 orchestrate retries failed on the same node;
CEO manually bypassed with `[success]` `69708e4`.

**Change (orchestrate.sh, ~30-50 lines around the DRIFT branch + D-77 in
DECISIONS.md + selftest):** when the full suite fails after all tasks
passed, check whether the failing test's exercised file(s) are inside the
delta's `contracts.files`. Outside the delta → log WARNING, treat as
carried-forward flake, do not declare DRIFT. Optionally also re-run the
node in isolation for evidence.

**Design correction from 2026-07-19 evidence:** the original proposal made
isolation-retry the primary signal. It cannot be: the same test later
failed 4/4 IN ISOLATION under memory load (nemotron + an LM Studio model
resident — the browser attaches after the stub's ~1.2s hold has passed).
The **delta-inventory check must be the primary discriminator**;
isolation-retry is corroborating evidence only.

## 4. D-68 debt sweep at freeze time

**Defect it prevents:** a legacy file's first post-D-68 edit fails the gate
on pre-existing unjustified handlers regardless of the new work. Fired
twice: app.js (2026-07-17 incident #2, cleared by live-fix `1eb4054`) and
models.py T11 (M28 — forced the v54 recut, and both local EMs revised the
wrong handler during the escalation). The 07-17 template-debt note already
named this; it was recorded, not mechanized.

**Change:** refreeze.sh scans the delta's `contracts.files` for bare/
unjustified exception handlers (the D-68 pattern) and prints the list at
freeze time, so remediation directives (like M28c) enter the spec on day
one instead of surfacing mid-run.

## 5. Gate-symmetry doctrine (BLUEPRINT.md design rule / DECISIONS.md entry)

**The inherent template flaw M28 exposed:** gate density is inversely
proportional to seat capability. The local coder's output is checked four
ways within seconds (phase gate, D-68, lint, mapped tests); the TPM's
frozen spec — the artifact with the largest blast radius — gets only
integrity checks (hashes, INV-4, D-67), zero semantic-validity checks.
Defects enter ungated at the top and are discovered by burning the bottom
of the ladder. M23's cost ledger ("ALL THREE spec bugs the TPM's") and all
four M28 recuts fit the same pattern.

**Change:** codify the rule — every seat's output artifact receives a
mechanical validity check at handoff; gate strength proportional to blast
radius, never inversely to seat capability. Items 1 and 4 are the first
two instances. Precedents to cite: the M4 conductor postmortem ("never
rely on compliance for any invariant — constraints must be structural")
and the 2026-06-04 correction ("mechanical gates over doc guards").
Capability changes the failure class, not the need for gates: weak models
fail loudly downstream where gates exist; strong models fail quietly
upstream where they don't.

## 6. EM diagnosis hardening (open since M23)

M23 exposed mid-tier diagnosis as the weak rung (schema-invalid diagnosis,
empty task_id — gate refused correctly, halt); 07-17 mlx-serve produced
the first schema-valid production diagnosis but with rambling prose.
Candidate: one bounded schema-retry that echoes the validation error back
to the EM, and/or a denser diagnosis brief. Carried from the 07-15 open
items; still unaddressed.

## 7. Hand-fix ledger as a close-out metric + UI-AC guidance (TPM role doc)

M28 broke the zero-hand-fix streak held since M7: 11 post-`[success]`
live-fixes, all UI interaction detail the frozen ACs never pinned
(cancel-path reverts, status honesty, gating, a races-on-reload class).
Two small changes: (a) the close-out ritual records the post-success
live-fix count per milestone so the trend is visible; (b) docs/TPM-ROLE.md
gains a note that UI milestones need interaction-path ACs (cancel paths,
status truthfulness, refresh/reload races), not only happy-path
assertions.

## 8. Freeze hygiene (advisory, CEO-PLAYBOOK/TPM-ROLE)

Both defect-bearing M28 freezes (v51 23:34, v52 23:49) were authored
minutes after closing M27 (22:50), at the end of a long day, across a
pause/resume and multiple model changes. Advisory line: a new milestone's
spec is next-session work by default; at minimum, refreeze could warn
when the previous `[success]` landed under an hour ago in the same
session. Keep advisory — this is a human-rhythm issue, not a gate.

## 9. Housekeeping

`sw-dev-blueprint/tasks/HANDOFF-2026-07-16-state.md.bak` is an untracked
editor backup (predates its sibling by ~24 min; nothing depends on it).
`rm` it; optionally add `*.bak` to blueprint's `.gitignore`.

---

## Not blueprint work (stays in testchat)

- AC-42 test re-cut/hardening — TPM lane at next refreeze (INV-1-frozen;
  P1 on tasks/BACKLOG.md with the 2026-07-19 in-isolation evidence).
- M13 app.js module split spec backfill — testchat pipeline work.
- All incident documentation — per CEO placement rule (2026-07-19),
  postmortems stay in the project repo; blueprint receives only the
  generic process changes above.
