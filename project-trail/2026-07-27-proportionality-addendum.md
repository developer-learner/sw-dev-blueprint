# Proportionality addendum — make small milestones cost small

Relayed from the testchat session (2026-07-27, addendum to the gate handoff,
committed there at `e69e49a`). Testchat rationale in
`~/dev/testchat/project-trail/2026-07-27-blueprint-gate-handoff.md`; this
file captures the blueprint-side scope.

## Standing constraint (CEO, 2026-07-27)

**All product code is written by the local coder seat; frontier LLMs spec
and supervise only.** A fast-lane/direct-build bypass was proposed and
rejected on two grounds: it trims checks, and it routes coding to the
frontier seat. Efficiency work targets proportionality (cost scales with
delta size), never bypass.

## Target

A one-file, one-AC UI feature through the full pipeline — PRD, ERD, EM,
local coder writing all code, frozen tests, every gate — in **~10–12 min**.

Most pipeline costs already scale with delta size (test authoring,
per-task acceptance, coder call, freeze mechanics). Two do not; both are
template-owned.

## Fix A — EM emits only the affected subtree

Evidence: testchat M31, mlx-serve 4-bit. Plan call 282s = 68% of a 413s
run; 19,572-char plan re-emitted for a 3-task delta; historical calls
247–282s. Cost is O(inventory) because the prompt demands one task per
`contracts.files` entry every time (D-64 bijection).

Sketch that preserves D-64: the bijection is a property of the *validated
artifact*, not of the generation. On a re-freeze with a prior validated
plan on disk:

1. Shell computes the affected set (`validate-plan.py --affected` —
   exists).
2. EM prompt: carried-forward tasks pasted as immutable context (ids
   stable), instruction to emit tasks ONLY for affected files, mapping
   only the delta's test node-ids, `depends_on` may reference
   carried-forward ids.
3. Shell merges: carried-forward tasks verbatim + EM subtree, drops tasks
   for files removed from the inventory, bumps plan version.
4. The EXISTING full-plan validation runs unchanged — bijection, total
   coverage, exactly-once mapping, DAG. Nothing about the gate weakens.

Greenfield (no prior plan) falls back to full emission, unchanged.
Revision cycles re-emit the subtree only — which also fixes the known
mtplx overflow (revision carrying a full prior plan ≈ 34k tokens > 32768
window; a subtree revision fits easily). Expected effect on a small
delta: ~282s → well under 60s, and the largest single cost in every run
becomes proportional.

## Fix B — freeze-time verification works off-VM, delta-scoped

Steady-state design already intends one full-suite run per milestone
(D-28, at run end) with the freeze verifying only the delta (D-75
red-before-green). Two defects observed live at the v65 freeze on the
macOS host:

* `collecting test node-ids... pytest: 0 node-ids (<AST — import errors
  likely, using AST)` — collection tries the sandbox, unreachable outside
  the Lima VM, and the AST fallback silently writes **suffix-less**
  node-ids (no Playwright `[chromium]`). v64's frozen file has the same
  artifact, so this has been failing quietly for a while.
* `red-check INCONCLUSIVE: no readable report (sandbox or collection
  problem)` — D-75 has no host fallback, so the freeze's only mechanical
  test check degrades to an advisory precisely where TPMs actually run
  refreeze.

Proposal: both steps try direct host pytest (`PYTHONPATH=. pytest
--collect-only -q` / targeted delta run) when the sandbox is
unavailable, recording which path ran in the freeze output. Fail closed
to AST only when both are impossible, and say so loudly. Also worth a
rule line in the refreeze docs: a full-suite run belongs at freeze time
ONLY for catch-up freezes where `src/` changed outside the pipeline
(the v65 case); steady-state freezes verify the delta and leave the full
suite to the run.

## Fix C (cheap, optional) — parallelize the one remaining full-suite run

Single full-suite run (~4.5 min at 176 tests, growing) is the last fixed
cost. `pytest-xdist -n 2..4` for the Playwright set is plausible (per-test
contexts are already isolated); invocation in `sandbox-run.sh` /
orchestrate acceptance; conftest is child tests-lane (lands via
refreeze). testchat has this filed as P2 backlog. Halving the run takes
the envelope ~12 → ~10 min.

## Acceptance

A one-file, one-AC UI milestone on a testchat-shaped child runs
end-to-end — spec, freeze, EM subtree plan, local coder, mapped
acceptance, one full suite — in **~10–12 minutes with zero gates
removed**. The next small testchat feature is intended as the live proof.

---

# Addendum 2 — three template cuts (reviewed and approved 2026-07-27)

Second audit pass: per-seat work that repeats every milestone without
serving the feature ask. Reviewed against the blueprint's own integrity
definition before approval — the M4 postmortem's conclusion stands:
integrity here lives in the structural gates (`validate-plan.py`,
phase-gate, fail-closed appliers), the frozen suite, the escalation
ladder, and the human freeze approval. None of the three cuts touches
those; two strengthen them. CEO/operator approved the package with the
conditions below.

## Cut 1 — briefs for existing files are delta-only

EM prompt rule: a brief for an existing file describes only the change,
never restates current behavior. Grounding: D-59 already makes the
*output* side delta-only (anchored SEARCH/REPLACE; the coder never
retypes what it isn't changing), so unstated behavior is structurally
untouched — restating it in the brief protects nothing and invites
D-65-class stray edits to regions the task doesn't own. Also kills the
v64 brief-cap collision class at the root.

**Condition:** no compensating "change nothing else" line in the brief
template — that is negative-constraint framing, which Rule 8 exists to
forbid for local coders. Ship it bare.

## Cut 2 — one-file deltas get a shell-constructed plan; no EM call

When the D-86 scope declaration plus the frozen delta map to exactly one
affected file, the shell constructs the plan mechanically: carried-forward
tasks verbatim, one task for the affected file, the delta's test node-ids
mapped to it. The honest justification is NOT "no judgment exists" — it
is (a) the constructed plan passes the SAME `validate-plan.py` gate
(bijection, coverage, exactly-once mapping, D-64 closure are properties
of the artifact, not of its author — the same argument Fix A makes), and
(b) if the mechanical plan is mis-scoped, mapped tests go red and the
escalation ladder summons the EM at its consult rung anyway. The EM moves
from every-happy-path overhead to on-demonstrated-need. Its own record
(M9 invented contract-id, M15 ignored ERD prose twice) says its
happy-path review was the weak link, not a safeguard.

**Condition:** the constructed plan takes the identical `[plan]` commit +
validation flow as an EM-authored one — the audit trail must not fork.

## Cut 3 — split the spec: standing doc + per-delta doc

Standing spec (architecture, conventions, suite properties, standing
risks — changes rarely) + per-delta spec (this feature's ACs, mapping,
inventory changes — the only thing authored per milestone). The original
pitch undersold it: beyond TPM authoring time and ~20k tokens off every
EM prompt, the real prize is the freeze gate itself. A 62KB re-touched
ERD makes the y/N diff un-reviewable, which quietly turns the one human
gate into a rubber stamp — five broken refreezes went through it.
Feature-sized per-delta diffs make approval actually possible.

**Condition:** both docs live inside the existing freeze — hash-pinned
together in `scripts/.approved/`, the per-delta doc stamped with the
standing doc's version it was authored against. The 2026-06-30
stale-manifest correction is the precedent: two artifacts that can drift
must be pinned under one manifest. No new machinery.

## Landed (same day)

Fixes and cuts implemented in the reviewed order, selftests 145 → 167 green:

* **Fix B** → `228cc26` (D-90): collection + D-75 red-check host
  fallbacks, junitxml on the host path, TESTING.md full-suite-at-freeze
  rule, 2 selftests running the real `--diff`/`--approve` apply path in a
  sandbox-less fixture. CI selftest job gains ruff (`32ba044`) — the
  fixture tests hit the D-67 gate.
* **Fix A** → `ae4d8ce` (D-91): `--subtree-scope` / `--merge-subtree`
  modes, `plan_subtree_prepare` + subtree branch in `ensure_plan`, em.md
  delta-re-plan clause, 12 selftests incl. two end-to-end `ensure_plan`
  drives (one-call subtree re-plan; zero-call docs-only merge).
* **Cut 1** → `70f0c0c` (D-92): the delta-only-brief rule lands identically
  in em.md and both EM prompt strings (full + subtree). Bare wording — no
  "change nothing else" compensation, because Rule 8 forbids that framing.
* **Cut 2** → `fa01ad6` (D-93): `--subtree-scope` gained `trivial_construct`;
  `--construct-one-file` builds the subtree mechanically from the prior
  task; ensure_plan takes zero EM calls when 1 re-emit + 0 new files + 0
  contract changes; falls through to EM subtree on rejection. Refactored
  the mechanical builder out of a shell heredoc into validate-plan.py to
  keep drive-plan.sh's sed extractor happy. 7 new selftests.
* **Cut 3** → `d033991` (D-94): optional `ERD-DELTA.md` accepted alongside
  `ERD.md` — whitelist, CHANGED_DOCS, diff-show, manifest pin, EM context
  (backward-compat via `build_context` skip-missing), D-89 union so
  moving prose can't silence the mass advisory. TPM-ROLE.md documents the
  adoption threshold (~20KB, wherever the y/N diff stops being
  reviewable). 3 selftests: accept+pin, whitelist rejects strays,
  backward-compat when no delta doc staged.
* Fix C unchanged — testchat P2 backlog.
* Template sync: D-88..D-91 relayed into testchat by a parallel CEO
  session earlier (testchat `4990cf7 [template-update 2e6dece]`); Cut
  1/2/3 (blueprint HEAD after this session) awaits the next
  `update-template.sh` run — mechanism unchanged.

## Revised ordering (supersedes the Fix A-first note above)

**Fix B before Fix A.** Fix A buys latency; Fix B closes a live silent
hole in the red-check at the gate the operator personally approves —
suffix-less node-ids have been frozen quietly since v64, and every
freeze approved while A is being built is a freeze approved with its
only mechanical test check dark. B is 1–2h, A is 4–6h. Then A. The cuts:
Cut 1 is a prompt edit, any time; Cut 3 lands at the next spec recut;
Cut 2 composes with A's subtree machinery. With the cuts landed, the
one-file envelope tightens from ~10–12 min toward ~8.
