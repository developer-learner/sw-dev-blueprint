# ESCALATION.md — The TPM Round-Trip

> The TPM seat (CEO-assigned per session, D-139) may run in a **web chat
> operated by a human** — it is not necessarily a callable service. The
> filesystem is the only integration between the web chat and this repo.
> Every escalation is therefore a manual browser
> round-trip, and minimizing round-trips is an explicit design goal (D-29):
> the orchestrator **batches** escalations and halts once, at a stopping
> point, after every runnable subtree has been driven as far as it can go.

## The ladder (all counters shell-owned, in `.pipeline-state/`)

| Rung | Trigger | Actor | Bounded by |
|------|---------|-------|-----------|
| retry | task fails once | coder (same brief + failure appended) | `MAX_TASK_STRIKES` (2) |
| consult | task fails twice | EM writes schema-bound diagnosis (verdict+reason only — the shell stamps `task_id`); an invalid reply earns one retry carrying the validator's errors (D-71) | 1 retry, then halt |
| `brief_wrong` | EM verdict | revised brief, strikes reset | `MAX_BRIEF_REVISIONS` (default 1) |
| `decomposition_wrong` | EM verdict | EM re-emits plan, re-validated | `MAX_PLAN_REVISIONS` (2) |
| `transient_or_environmental` | EM verdict backed by positive external/resource/non-reproduction evidence | **operator-review halt**; evidence preserved; no automatic retry, re-probe, plan change, or TPM escalation (D-169) | explicit operator re-run after inspection/repair |
| spec defect (D-79) | plan budget exhausted AND the D-78 satisfiability audit of the frozen spec fails | **batched TPM bundle** — no further EM strikes, no model swaps | human round-trip |
| `contract_or_test_wrong` / caps exhausted / spec drift | EM verdict or shell signal | **batched TPM bundle** | human round-trip |
| PRD ambiguous | TPM (in chat) | CEO decides | human |

"Spec drift" is the mechanically detected case: every task passed its mapped
tests but the final verdict run is red (in mapped scope the failures are, by
definition, delta-dependent nodes — an inter-task coupling break). It routes
EM→TPM and never to coder retries (D-28/D-112).

"Transient/environmental" is not a fourth blame bucket for unexplained
failures. It requires affirmative evidence of a named condition outside the
brief, decomposition, contract, and test. The orchestrator writes
`.pipeline-state/operator-review/<task-id>.md` and exits 1. It does not create
a TPM batch. A later run occurs only because the operator inspected or repaired
the condition and explicitly launched it; the task then receives the preserved
failure context and a fresh bounded strike allowance.

"Spec defect" (D-79) is the other mechanically detected case, one phase
earlier: when the plan gate has rejected `MAX_PLAN_REVISIONS` consecutive
plans, the orchestrator audits the puzzle before the ladder blames the
solver — it re-runs the D-78 satisfiability check on the frozen spec against
the current tree. Two identical rejections are as much evidence about the
spec as about the EM (testchat M28: two different EM models failed
identically against v51/v52, which were unimplementable by ANY EM — the
ladder burned ~75 minutes of model swaps against an impossible spec, a
capability-independent failure no better model can fix). If the audit fails,
the halt is a SPEC DEFECT routed straight to the TPM bundle; swapping EM
models or refreshing the plan budget is explicitly the wrong move. If the
audit passes, the normal actor-path halt applies unchanged.

## Outbound: the escalation bundle

When the DAG can make no further progress, the orchestrator writes one bundle
per escalated item under `.pipeline-state/escalations/<task-id>/bundle.md` and
aggregates them into a single copy-pasteable file:

```
.pipeline-state/escalations/BATCH.md
```

Each bundle contains, self-contained (the TPM has no repo access):

1. **Header** — kind (`spec-wrong` | `caps-exhausted` | `spec-drift` |
   `spec-defect`), task id (`DRIFT` and `SPEC-DEFECT` are run-level, not
   task-level), frozen spec version.
2. **Task entry** — the full `plan.json` entry, verbatim JSON (task-level
   bundles only).
3. **Evidence** — failing test node-ids / smoke command, plus the pytest JSON
   report copied alongside the bundle; for `spec-defect`, the validator's
   rejections and the D-78 audit output naming the unsatisfiable contracts.
4. **EM diagnosis** — the schema-validated verdict and reason, verbatim
   (`spec-defect` bundles carry none: the defect is proved mechanically,
   no EM consult involved).
5. **Frozen artifacts involved** — the referenced `contracts.json` entries and
   the full source of each failing frozen test file (capped at 200 lines).

The operator pastes `BATCH.md` into the TPM chat **in one message**.

## Inbound: the delta

The TPM replies with a **delta**: the complete new content of only the changed
frozen files. The operator saves them under `scripts/.approved/incoming/`,
preserving paths:

```
scripts/.approved/incoming/
├── contracts.json        # only if contracts changed
├── ERD.md                # only if the ERD prose changed
├── ERD-DELTA.md          # required for every behavioral delta (D-107)
├── PRD.md                # only if the PRD changed
├── REMOVED               # optional tests/*.py removals, one path per line
├── captures/             # only captures declared by contracts.externals
│   └── provider.json
└── tests/
    └── test_items.py     # only the changed test files
```

then runs:

```bash
scripts/refreeze.sh scripts/.approved/incoming
```

`ERD-DELTA.md` uses the four required sections from `docs/TPM-ROLE.md`;
refreeze checks that newly introduced AC ids and `contracts.changed_files`
are represented there. Refreeze then runs every mechanical preflight
(D-56/D-78/D-87/D-88/D-107/INV-4
plus staged-test parse+lint+determinism), prints the diff and DIFF-SHA for
review, and — on preflight-green — applies automatically (D-95/D-121):
`--approve` and `--interactive` no longer exist — there is no human
approval flag on the refreeze lane; `--diff` stays a read-only preview.
Re-freezes as version N+1 and records
`DELTA-vN.json`. On the next
`scripts/orchestrate.sh` run, only the affected subtree (tasks whose mapped
tests, contracts, or file were touched by the delta, plus transitive
dependents) is reset and re-run (D-31).

## Rules

- No agent can write anything under `scripts/.approved/` or `tests/` — frozen
  artifacts change **only** through `refreeze.sh` (hash-pinned by
  `scripts/.approved/frozen-manifest`, verified by every gate run,
  fail-closed).
- The orchestrator exits with code **2** when a batch is waiting — distinct
  from failure (1) and success (0) — so wrappers can detect "awaiting TPM".
- Bundles are runtime diagnostics (`.pipeline-state/` is gitignored); the
  durable record of the round-trip is the freeze commit (`refreeze vN`
  message tag, written by `scripts/refreeze.sh`).
