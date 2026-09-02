# CURRENT.md — Session Notes

> This is the human-facing status page, NOT the spec. The PRD, ERD, contracts
> and test suite live frozen in `scripts/.approved/` + `tests/` and change
> only via `scripts/refreeze.sh` (D-31). Update this file at the start and end
> of every working session; halt notes (Rule 4) land here.
>
> **Scope:** this file is *status* — what is active or halted now. The
> prioritized queue of not-yet-started work is `BACKLOG.md`; the transient
> cross-session working checklist is `TODO.md`. Don't grow a second queue here.

---

## Active Feature

The blueprint is a template repository — it ships no product features of its
own. "Active work" here means changes to the template itself, tracked in the
notes below and in `docs/DECISIONS.md`. The per-project instance of this file
(in a derived repo like testchat) tracks that project's milestone instead,
using the fields below:

**Feature:** templates/tools — T7 trusted-commit-broker (M1 landed D-174, M2
designed D-176) + T11 rich-adoption (Phase 0 done D-175, v1 spec drafting)
**Frozen spec version:** n/a — the template's own files mutate via its normal
commits, not `refreeze.sh` (children's specs still freeze there)

- 2026-09-01: **T7 M1 landed (D-174) + T7 M2 designed (D-176) + T11 Phase 0 done (D-175).** CEO ruling of the day: Option 3 approved as staged (M1 now, M2 after the three prerequisites), Rich approved for Phase 0, T6 untouched. M1: trusted commit broker at every pipeline commit site, author/committer separation, `Swbp-*` trailers, provider-returned model preference, run-id, coder-prompt byte-capture; suite 548 green; published `1b455f0` + bootstrap fix `1684e0b`. M2 design (no code yet, awaiting go): out-of-band pinned-fingerprint trust anchor, atomic durable evidence under `.swbp-evidence/<run-id>/`, attestation semantics stated for the record, verifier report-first → T1 after one clean cycle — `tasks/T7-m2-design.md`. T11 Phase 0: rich-adoption born — rich 15.0.0 pinned at `v15.0.0`/`6ac483cb`, baseline 956/25/0 with lockfile deps (pygments 2.21.0 breaks 8 legacy tests → lockfile is the dependency authority), 73-file legacy pin, plane LINKED at `1684e0b` (run #2 born on the broker plane; first child commit `0127c3bf` carries the full trailer set), pre-spec tunnel state recorded, child verification green. **v1 spec
      drafted (Phase 1 prep):** M1 = `Table.add_rows` +
      `Table.from_rows` (purely additive, delegates to `add_row` cell
      semantics), 12-test frozen suite with deterministic rendered-
      output contracts; refreeze --diff all preflights green (v0→v1);
      tests fail cleanly against unmodified code (target state);
      legacy 956-test suite stays a pinned snapshot, not carried into
      the frozen gate (D-165). Freeze + live run await the Linux dev VM
      slot (orchestrate hard-dies on Darwin, D-152).
- 2026-09-01 (later): **Fleet pin adoption (D-177).** The Track A
      reconcile (manifest-only re-hash) had left both legacy children
      check-drift RED (`MISSING_IN_CHILD: scripts/git-provenance.sh` —
      union semantics: template@HEAD lists the file, children lacked
      it) with pre-broker pins (Vortex `ec81667`, Testchat `9a5ac32`).
      CEO delegated the pin decision to Track C; **adopted now at
      `6f51d63`** — "defer" was not a stable option (pre-broker pins
      can't be drift-green while the shared checkout is post-M1).
      `link-template.sh --ref 6f51d63` on both: Vortex `b7fb2c2`,
      Testchat `f08ad6e` (both `[template-link 6f51d6313669]` with the
      full `Swbp-*` trailer set); pins advanced, check-drift green on
      both, trees clean. **Fleet state: all three children on the
      D-174 broker plane** (Vortex `6f51d63`, Testchat `6f51d63`,
      rich-adoption `1684e0b` — advances at its Phase 1 run time).
- 2026-09-01 (later): **T8 Testchat v115 spec drafted + staged (offline; build not started).** The delegated next serialized item: recut Testchat's router seams from the single hardcoded `ROUTER_MODEL_ID` (v107 assumption) onto Vortex v26's full dynamic ready set. Staged in testchat `scripts/.approved/incoming/` (durable copy `tasks/T8-v115-spec-draft/`, pushed `ed9ffe0`): PRD delta AC-175..AC-181 (AC-175..178 supersede AC-170..173; AC-179 = mid-flight 404-race not-ready message, exact string; AC-181 = constant retirement), ERD-DELTA v115 (changed files `src/services/models.py` + `src/api/chat.py`, `src/api/models.py` acceptance-only; 7 new/renamed test families pinned in the delta's mapping section — not frozen node-ids yet), contracts delta (`erd_version` 115, `test_mapping` = standing 20 minus the 2 retired v107 422-rejection pins), 20-test oracle (pytest-httpserver simulates Vortex; S6-safe local-def mocks). All `refreeze.sh --diff` preflights green (DIFF-SHA `d9dab64d`); oracle vs unmodified code **8 failed / 12 passed** — the 8 are exactly the new-behavior pins. Run sequence when the window opens (Linux dev VM, one-live-run-at-a-time): `refreeze.sh` (D-121 auto-apply) → `orchestrate.sh`. Gates learned: `contracts.files` must cover every `test_mapping` target (not just changed files); S5's AC-span extraction reaches from an AC's first mention to the next AC/`##` heading, so design prose with state verbs inside a span trips the post-condition rule.
      Vortex's next live run = the broker's second live validation.

- 2026-08-23: **D-169 implemented.** Diagnosis now has an explicit,
  positive-evidence-only `transient_or_environmental` verdict. It writes a
  preserved operator-review record and halts with no automatic retry,
  re-probe, plan mutation, or TPM escalation; only an explicit operator rerun
  re-enters the bounded task path. The change closes the taxonomy gap isolated
  by the diagnosis A/B rather than shipping the denser prompt candidate.

- 2026-08-15: Adversarial review of both repos (2026-07-01 REVIEW.md follow-up)
  produced two must-fix defects, now landed as code: **D-150** — failed B3
  plan synthesis no longer clobbers `tasks/plan.json` (temp file + mv, reason
  readable again); **D-151** — `refreeze.sh` is now transactional (git-identity
  preflight, clean-lane guard on tests/ + scripts/.approved/, HEAD rollback +
  unstage on a failed freeze commit). Both carry ledger entries. Second batch
  landed same day: **D-152** — refreeze fails fast on stock macOS (dies
  immediately without sha256sum, loud warning with coreutils — the host-run
  fixture suite stays green), and **D-153** — placeholder gate hardened
  (lowercase-led + Type-1 uppercase-class tokens caught, markdown links filtered,
  verbatim-record exceptions documented) + doc sweep (QUICKSTART Step 5
  rewritten to the D-121 auto-apply reality, .env.example dead LM
  Studio/ANTHROPIC config removed, plan.schema tests-description reworded to
  the D-119/D-130 omit rule, live docs verified to carry no dead manifest
names). Open queue: third batch landed same day as **D-154** (fail-open
  pass: `curl -f` on the LLM preflight, `gh auth status` named in CI health,
  `[plan]`/`[task]` commits no longer swallow real failures — status-guarded,
  D-151 class), **D-155** (INV-1 cross-check scans disk for pytest-collectible
  files — the gitignore blind spot is closed), **D-156** (mypy pinned
  `==2.3.1` in the Containerfile — the mypy-green cache can no longer go
  stale). Fourth batch landed same day: **D-157** (LOW batch — coder
  `=== FILE:` extraction greedy (no more first-marker truncation), llm-call
  fence-strip prose-tolerant + count-guarded, mkdir-lock pid-window fail-closed,
  `$REMOVED_FILES` loops line-based with the house empty guard (space-in-path
  word-split was a wrong-path deletion), new-project.sh `LLM_HOST` override;
  the review's "remove docs/.pm-last-review" was REFUTED — it is Rule 1's
  backstop, valid ancestor, PM-owned, kept). Remaining closed same day:
  **D-158** — `scripts/.manifest-template` now covers the full script
  inventory (bootstrap.sh + new-project.sh added — they were the only two
  control-plane scripts the drift gate could not see; 64 entries after
  regen); ledger back-port executed (testchat now mirrors D-1..D-157
  verbatim, padded `comm` clean, testchat-local renumbered to D-158);
  same-LLM TPM mode already documented (D-139 language in TPM-ROLE.md,
  both repos). Testchat: input bounds + same-origin gate on bodyless POST
  routes + stale refreeze-pending.diff removed (D-159), script paths
  env-ified (testchat D-158, committed `a42076a`). Re-verification of the
  whole remediation: every valid HIGH/MEDIUM finding confirmed fixed in
  code; one substantive miss found and closed — **README file tree** now
  lists all 11 docs/ files (D-159), and the D-153 placeholder gate was
  independently confirmed live (BLUEPRINT.md Step 7, real and consistent;
  template-repo hits are Step-6 skeleton rows + the two documented
  exceptions). Mechanized same day (Rule 3 ruling): **D-160** — bootstrap
  arms `.placeholder-gate`; `phase-gate manifest` enforces Step 7 at the
  commit door (exemptions: records/archives/runtime — project-trail,
  .em-archive, .pipeline-state, .measurement, .tpm, .venv*, .cache, data,
  HANDOFF-*, CURRENT/BACKLOG, DECISIONS, BLUEPRINT, date-led rows, `](`
  links); armed and proven on testchat — planted token → GATE FAIL, and
  arming surfaced two real residual template rows in child docs, now
  de-bracketed (TESTING.md flake-table example, ESCALATION.md `[refreeze
  vN]` prose). **D-161**: oracle-strength gap recorded as open — the
  frozen suite's discrimination is unverified (D-75 continuation: per-run
  mutation still rejected; freeze-cadence one-shot report-only pass named
  as the shape of any fix; Rule 5 "ground truth" wording corrected in the
  same batch — BLUEPRINT.md, CLAUDE.md, and new-project.sh's child
  CLAUDE.md template now say "binding automated completion evidence";
  REVIEW.md and historical entries untouched). **D-162/D-163/D-164**
  (same-day batch, record-only — no code changed): TPM read wall
  recorded as requiring a materialized view (a settings allowlist is not
  a boundary); comparative eval deferred until independent oracle
  authorship exists; multi-file transactional task groups sequenced
  behind measured oracle strength. Rule 5's D-44 acceptance sentence was
  already present in `BLUEPRINT.md` and `docs/CEO-PLAYBOOK.md`; the earlier
  "still pending" note was stale and is reconciled here. **D-162 implemented**
  (same day): the materialized TPM
  view shipped — `scripts/tpm-view.sh` builds `.tpm/view/` (spec +
  frozen tests + sanitized escalations, outbox symlinked to
  `.tpm/outbox`), `tpm-agent.sh --view` roots the agent there with
  `tpm-view-settings.json`; src/ physically absent; three selftests
  (454 total).

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

- **2026-09-01 (Track C session)**: CEO-gated decision notes prepared —
  `tasks/T7-provenance-decision.md` (Git provenance: trusted commit broker
  design, options 1–3, recommendation full-staged M1/M2, blind-test plan)
  and `tasks/T11-oss-subject-decision.md` (OSS adoption subject #2: five
  PyPI-verified candidates, recommendation Rich, program shape Phase 0–2).
  T6 (organic ladder observation) status recorded in `tasks/TODO.md` §7 —
  no new organic run since 2026-08-30; close criterion (one uninterrupted
  full-ladder run accepted against D-70/D-69) still unmet. No code written
  (Rule 3: T7/T11 gated on the CEO's go/subject). Both repos' trees clean
  after this commit.

- **2026-08-08 (session end — 2)**: post-handoff hygiene batch closed in
  testchat (`d0ac352`): AC-48 audit DONE (text recovered from refreeze v20,
  §5.1 lint fails — re-cut drafted into the next TPM bundle; see testchat
  BACKLOG.md); `.opencode/node_modules` removed. CEO decision memos
  (manifest-drift hard-gate vs warning; statuses coverage tooling) were
  deliberately NOT drafted — they were due to the CEO conversation, and the
  session stopped there. Both repos clean, in sync at `1f7d1c4`.
- **2026-08-08 (handoff)**: S6 reverse-direction lint shipped + amended —
  `scripts/check-test-direction.py` (+ D-128, D-128 amend): check 1 rejects
  whole-world URL mocks (bare Mock / fake that ignores its URL param),
  scoped to delta-touched tests only (testchat's live frozen suite carries 9
  legacy whole-mock sites — a whole-suite halt would brick every refreeze;
  caught by the parallel session's live probe, then resurrected as the
  D-128 amend); check 2 rejects carried tests citing ACs the delta ADDS.
  Wired as S6 in refreeze.sh after INV-4 (merged preview). 304 selftests,
  4 of them S6; both repos in sync (drift @ `0598ab6`). Live-suite status:
  grandfathered (testchat 9) — intended; their eloquence re-cut requires a
  TPM refreeze. Parallel session: em.md verbatim node-ids (`9a623c6` →
  testchat `05418dc`) shipped; mypy-into-sandbox parked in that lane;
  one-writer per control-plane file until both sessions clear.
- 2026-08-08: current node of the handoff — see `testchat/tasks/CURRENT.md`
  2026-08-08 section for the CEO-visible handoff (open P1: AC-42 TPM
  bundle; CEO-demoted MTPLX; two directional decisions waiting on the CEO:
  manifest-drift hard-gate vs warning, statuses coverage tooling).
- 2026-08-08: **correction-log row for this column** (both CLAUDE.md):
  fixture-only gate validation is insufficient — a new refreeze gate must
  be exercised against the LIVE frozen suite before wiring (Rule 6 on
  gates; D-128 amend). Also collation guard: grep the shipped preflight
  list before listing a gate as "to build".
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
- 2026-08-07 (later): durability defect in the metrics layer — `.pipeline-state`
  is wiped by the success teardown, so the original sink could never
  accumulate. Fixed same day: sources are now only post-teardown-durable
  artifacts (`.measurement/counters`, timings copies, `.em-archive`,
  flake ledger), output moved to `.measurement/metrics.tsv`, and the success
  path records the row automatically (`|| true`). Correction row logged;
  D-126 amended in place; 300 selftests green.


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
- 2026-08-08: sandbox privilege property verified + pinned (D-127): the container
  has run as agent/1000 since the template bootstrap (verified live in the
  dev-vm); the M29 backlog premise ("container ran as root") was stale —
  that incident was macOS-vs-Linux psutil semantics. The constraint-2
  verifier now asserts non-root uid (check 6).
