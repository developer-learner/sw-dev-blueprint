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
- [ ] [B] 3 fixture tests (2a shortlist) — `check-ac-postconditions.py`, `check-test-direction.py`, `flake-ledger.py`; pattern exists in selftest_gates.py
- [ ] [B] `tpm-lint.sh` — retire or wire; if retire, cite the audit report (pass 1: DOC-ONLY, zero live invocations) as the evidence; verify the D-117 citation first (D-117 = air-gapped TPM-pack fixture)
- [ ] [B] 6 provenance backfills — `doc-consistency`, `em-bench`, `extract-test-functions`, `flake-ledger`, `manifest-drift-guard`, `tpm-lint`; lift from correction log, don't author new

## 3. Builder path — measurement (order matters)
- [ ] [B] 2b mutation sweep across gates — one-shot first (mutate each gate's detection logic, assert its fixture test fails); run after Group A so it covers 41/41 at 2a
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
