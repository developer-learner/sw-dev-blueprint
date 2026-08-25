# TODO — combined (vortex + blueprint) — 2026-08-24

Single home for open work across both sessions. Lane tags:
**[B]** blueprint session · **[V]** vortex session.
Suggested green-light order: 2 → 3 (sweep, then ledger/tiering) → 4 (scope) → 5 (when funded) → 6 (when the milestone comes).

## ✅ Done
- [x] [V] Flap-bug thread — fix `c9b4fb7` → enum `91b86eb` → scope `9650d19` → refreeze v11/v12 `8097f33`/`85f0cbd`; coverage 88.15% ≥ 80%; CI green. Closed.
- [x] [V] Gate audit — pass 1 `b3f040f` (wiring 40/1/0) + pass 2 `65da200` (teeth 38/3/2); report `vortex/tasks/AUDIT-gates-2026-08-24.md`
- [x] [V] Decision memo — `6c07c49`, `vortex/tasks/DECISION-MEMO-builder-vs-template-2026-08-24.md`, CI green, verified
- [x] [B+V] Direction settled — both: template at seed, builder for life — ledgered as D-170 (`docs/DECISIONS.md`)
- [x] [V] Memory file — `~/.claude/CLAUDE.md` (Vortex remote; release-gate = host pre-push, 493 control-plane tests only)

## 1. Hygiene — close the loops (done 2026-08-24)
- [x] [V] `vortex/tasks/CURRENT.md` refresh — flap-bug closed, audit + memo + direction recorded, steady state set
- [x] [V] Memo resolution pointer — RESOLVED line at top of the decision memo
- [x] [B] Direction decision ledgered — D-170 in `docs/DECISIONS.md`
- [x] [B] Combined TODO persisted — this file

## 2. Group A — foundation batch
- [x] [B] 3 fixture tests (2a shortlist) — `check-ac-postconditions.py`, `check-test-direction.py`, `flake-ledger.py`; done 2026-08-24: 6 tests appended to selftest_gates.py (violation + clean companion per gate)
- [x] [B] `tpm-lint.sh` — retired (D-171): capability lives in `refreeze.sh --diff`; evidence = audit pass 1 (DOC-ONLY, zero live invocations, no selftest); the D-117 citation was a misattribution — retirement admitted under D-115
- [x] [B] 6 provenance backfills — done 2026-08-24: provenance section added to the audit report (first-add commits + the doc-consistency correction-log entry; tpm-lint birth = D-38 per header, first commit in current history is the D-131 restore)

## 3. Builder path — measurement (order matters)
- [x] [B] 2b mutation sweep across gates — done 2026-08-25: 6 mutants authored for the three 2a gates (`docs/research/2026-08-24-d161-gates-mutants.tsv`); `scripts/mutation-pass.sh` on HEAD `0518bad` (isolated exact-HEAD `--no-local` clone, suite runs under `PYTHONDONTWRITEBYTECODE=1` — stale-.pyc vacuity addressed); suite = full `selftest_gates.py` (428 tests, baseline green); **6/6 killed, 0 survived, 0 authoring errors**; report `docs/research/2026-08-24-d161-gates-mutation-report.md`
- [ ] [B] 2b-ext mutation sweep across the remaining gates — scope note 2026-08-25: the 2b run above mutation-proves only the three 2a gates (6 mutants); the other gates have fixture-level teeth (audit pass 2: 38 with teeth) but no mutation proof yet. Authoring mutants for them is a separate, larger run; "verified teeth" claims must stay scoped to the three until it lands
- [ ] [B] Catch ledger (standing) — after the sweep; don't stand a ledger on teeth that might not bite
- [ ] [B] Tiering + cost accounting — after the sweep; the real retirement instrument (replaces retire-on-silence)
- [ ] [V] Vortex recording hook for the catch ledger — joins when the ledger lands

## 4. Born-linked pivot
- [ ] [B] Scope first, then build — seed path yields project-local files + links, skipping the copy. Precision: one template-derived file stays real (`check-drift.yml`, GitHub necessity); `ci.yml`/`container-build.yml` are project-local by design
- [ ] [V] Verify vortex integrity after seed-path changes (manifest, symlinks, full suite)

## 5. Vortex product debt — needs go + TPM seat (D-139)
- [ ] [V] Memory-figure mismatch — `top` PhysMem vs psutil-used; pick one source of truth; src change + refreeze pairing
- [ ] [V] `_anneal_probe` hardening — single 5s shot → bounded retry; src change + refreeze pairing
- (both green-lit → they ride one refreeze pass)

## 6. Rides the next milestone (no clock)
- [ ] [V] Silent-halt live-fire — double coder-failure → does caps-exhausted escalation get reached end-to-end? Run + report on the next real orchestrate run

## Standing (recurring, not completable)
- [ ] [V] Post-blueprint-landing verification — full product suite (all test files, scope labeled, never a subset) + CI green, after every blueprint commit touching linked files
