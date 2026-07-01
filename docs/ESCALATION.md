# ESCALATION.md — The TPM Round-Trip

> The TPM (frontier LLM) runs in a **web chat operated by a human** — it is not
> a callable service. The filesystem is the only integration between the web
> chat and this repo. Every escalation is therefore a manual browser
> round-trip, and minimizing round-trips is an explicit design goal (D-29):
> the orchestrator **batches** escalations and halts once, at a stopping
> point, after every runnable subtree has been driven as far as it can go.

## The ladder (all counters shell-owned, in `.pipeline-state/`)

| Rung | Trigger | Actor | Bounded by |
|------|---------|-------|-----------|
| retry | task fails once | coder (same brief + failure appended) | `MAX_TASK_STRIKES` (2) |
| consult | task fails twice | EM writes schema-bound diagnosis | — |
| `brief_wrong` | EM verdict | revised brief, strikes reset | `MAX_BRIEF_REVISIONS` (2) |
| `decomposition_wrong` | EM verdict | EM re-emits plan, re-validated | `MAX_PLAN_REVISIONS` (2) |
| `contract_or_test_wrong` / caps exhausted / spec drift | EM verdict or shell signal | **batched TPM bundle** | human round-trip |
| PRD ambiguous | TPM (in chat) | CEO decides | human |

"Spec drift" is the mechanically detected case: every task passed its mapped
tests but the full frozen suite is red. It routes EM→TPM and never to coder
retries (D-28).

## Outbound: the escalation bundle

When the DAG can make no further progress, the orchestrator writes one bundle
per escalated item under `.pipeline-state/escalations/<task-id>/bundle.md` and
aggregates them into a single copy-pasteable file:

```
.pipeline-state/escalations/BATCH.md
```

Each bundle contains, self-contained (the TPM has no repo access):

1. **Header** — kind (`spec-wrong` | `caps-exhausted` | `spec-drift`), task id,
   frozen spec version.
2. **Task entry** — the full `plan.json` entry, verbatim JSON.
3. **Evidence** — failing test node-ids / smoke command, plus the pytest JSON
   report copied alongside the bundle.
4. **EM diagnosis** — the schema-validated verdict and reason, verbatim.
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
├── PRD.md                # only if the PRD changed
└── tests/
    └── test_items.py     # only the changed test files
```

then runs:

```bash
scripts/refreeze.sh scripts/.approved/incoming
```

refreeze shows the diff, requires an interactive human y/N (the approval
gate), re-freezes as version N+1, and records `DELTA-vN.json`. On the next
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
  durable record of the round-trip is the `[refreeze vN]` commit.
