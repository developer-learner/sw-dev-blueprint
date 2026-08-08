# CURRENT.md — Session Notes

> This is the human-facing status page, NOT the spec. The PRD, ERD, contracts
> and test suite live frozen in `scripts/.approved/` + `tests/` and change
> only via `scripts/refreeze.sh` (D-31). Update this file at the start and end
> of every working session; halt notes (Rule 4) land here.

---

## Active Feature

**Feature:** [FEATURE_NAME]
**Frozen spec version:** [see `scripts/.approved/VERSION`]
**Orchestrator state:** [not started | running | exit 0 (done) | exit 1 (failed, see below) | exit 2 (TPM batch pending)]
**Branch:** `[feature/name]`

---

## Escalations In Flight

> Orchestrator exit 2 means a batch is waiting in
> `.pipeline-state/escalations/BATCH.md`. Track its round-trip here.

- [ ] Batch carried to the TPM chat: [DATE or n/a]
- [ ] TPM delta staged under `scripts/.approved/incoming/`: [DATE or n/a]
- [ ] Re-frozen as v[N] and orchestrator re-run: [DATE or n/a]

---

## Notes / Context

> Halt-and-notify notes (Rule 4) go here: what stopped, why, what decision is
> needed. Also temporary context for this session that isn't worth a
> DECISIONS.md entry.

- 2026-08-07: milestone-trim arc CLOSED in testchat (close-out verdict in
  `testchat/tasks/CURRENT.md`): 291 selftests green, both repos in sync,
  D-121/D-112 doc classes swept to zero. Next trigger = next real milestone
  freeze (the trim's lineage test).
- 2026-08-07: CEO decided **guard-as-warning** — `scripts/doc-consistency.sh`
  (enumerated retired-token scan over enumerated state-describing docs) is
  wired into the pre-commit hook, non-blocking by design (D-115: prose has no
  runtime blast radius). First run caught testchat `README.md:61` (D-121
  class — README.md was on no sweep list) and `examples/minimal-spec/README.md:6`
  (D-112 class). Recorded in CLAUDE.md correction log 2026-08-07.
- 2026-08-07: DECISIONS.md ledgers realigned with the testchat lineage
  (`71d7404`): container/relabel/size renumbered to D-123/124/125;
  D-112/D-116..D-120/D-122 back-ported from testchat verbatim. Both ledgers
  now agree number-for-number. Guard rule (correction log): code back-ports
  carry their DECISIONS entries in the same operation.
- 2026-08-07: metrics layer landed (D-126, CEO: shipping-pipeline verdict) —
  `scripts/metrics-report.py` aggregates the existing substrate into
  per-milestone rows in `.pipeline-state/logs/metrics.tsv` (+ `--evidence`
  block for D-115 retirement entries). Report only, never a gate. Testchat
  carries the mirrored D-126; 299 selftests green.


---

## Definition of Done (per feature)

Mechanical checks:

- Delta-mapped verdict green (`scripts/orchestrate.sh` exit 0; the full frozen suite is an on-demand `--full-suite` regression check, D-112)
- `docs/ARCHITECTURE.md` updated if structure changed
- `docs/DECISIONS.md` updated if a non-obvious choice was made
- No linter errors (`ruff check src/`)

The one judgment check (D-44 — the CEO's gate, never skipped or delegated):

- **CEO has used the running prototype and accepted the milestone.**
  "Tests green" means built-as-specified; only this means built-right.
  Record the acceptance here with a date.

Then: branch merged to main; entry moved to `BACKLOG.md` completed table
