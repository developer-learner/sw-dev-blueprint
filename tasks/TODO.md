# TODO — combined (vortex + blueprint) — 2026-08-24

Single home for open work across both sessions. Lane tags:
**[B]** blueprint session · **[V]** vortex session.
Suggested green-light order: 2 → 3 (sweep, then ledger/tiering) → 4 (scope) → 5 (when funded) → 6 (when the milestone comes).

**Open work is split into two buckets:**
- **FEATURE WORK** — the product build (born-linked pivot). Green-lit to start; carries its own guardrails (scope-first, verify-after, standing verification).
- **MAINTENANCE** — ongoing hardening, debt, and standing guardrails. Latent, **not blocking** feature work.

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
- [x] [B] 2b-ext mutation sweep across the remaining gates — done 2026-08-25: 68 mutants (2 × 34 gates, `docs/research/2026-08-25-d161-gates-ext-mutants.tsv`); `scripts/mutation-pass.sh` on HEAD `2cd9c72` (isolated exact-HEAD clone, full `selftest_*.py` glob as oracle, `PYTHONDONTWRITEBYTECODE=1`); **45 killed, 23 survived** (19 proven / 7 partial / 8 unproven); report `docs/research/2026-08-25-d161-gates-ext-mutation-report.md`; the 23 survivors are the oracle-gap map (11 unexercised branches, 2 fixture no-ops, 10 unasserted output/exit); scope note: `check-test-surface.py` not swept (audit pass-2 omitted it) — fixture-verified, not mutation-proven, tracked under MAINTENANCE
- [x] [B] Catch ledger (standing) — done 2026-08-25: `scripts/catch-ledger.py` (record/count/report; dedupe by gate+spec-version; fail-closed on malformed ledger); wired into all 8 hard-gate die sites in `refreeze.sh` via best-effort `record_catch` (never masks the gate's verdict); 5 selftest cases incl. a wiring test proving a rejected staged delta leaves a catch on record; full suite 433 passed; manifest regen
- [x] [B] Tiering + cost accounting — done 2026-08-25: `scripts/gate-inventory.tsv` (41 gates: kind, teeth, probe cmd), `scripts/gate-cost.py` (per-gate wall-time probe, median of N), `scripts/gate-tiering.py` (T1 core / T2 standard / T3 review / n-a; combines teeth + catch ledger + cost; fail-closed on corrupt ledger; review evidence, never a build gate). T3 names a gate for human examination, not a retirement decision (D-170). Teeth column now carries proven/partial/unproven from the 2b-ext sweep; partial treated as demonstrated teeth. 6 selftest cases; full suite 510 passed; manifest regen

---

# FEATURE WORK

## 4. Born-linked pivot
- [ ] [B] Scope first, then build — seed path yields project-local files + links, skipping the copy. Precision: one template-derived file stays real (`check-drift.yml`, GitHub necessity); `ci.yml`/`container-build.yml` are project-local by design
- [ ] [V] Verify vortex integrity after seed-path changes (manifest, symlinks, full suite)

---

# MAINTENANCE (ongoing — hardening, debt, standing guardrails; latent, not blocking feature work)

## 3b. Oracle-gap fixes — from the 2b-ext mutation sweep (23 survivors)
The 2b-ext sweep (45/68 killed) surfaced 23 survivors — real mutations the
selftest suite failed to catch. Each is a **named** oracle gap, not "improve
coverage." Grouped by fix type; do the cheap asserts (group 1) first.
Source: `docs/research/2026-08-25-d161-gates-ext-mutation-report.md`.

### Group 1 — unasserted output/exit (10) · cheapest: add the missing assert
- [ ] [B] `new-project.sh` — assert the bootstrap pre-check message (survivor: message changed, unobserved)
- [ ] [B] `extract-test-functions.py` — assert which leading-comment lines are included vs dropped
- [ ] [B] `check-drift.sh` — assert BEHIND exits 2 (survivor: rc=1 instead of 2, unobserved)
- [ ] [B] `mutation-pass.sh` — assert the baseline runs under PYTHONDONTWRITEBYTECODE=1
- [ ] [B] `status.sh` — assert the LLM port probe uses the documented default port
- [ ] [B] `feature-summary.py` — assert the archive time window (recent counted, old skipped)
- [ ] [B] `feature-summary.py` — assert outcome-line parsing precedence
- [ ] [B] `metrics-report.py` — assert waste counting (failures = waste, successes not)
- [ ] [B] `update-template.sh` — assert "nothing to review" only when no changes exist
- [ ] [B] `refreeze_delta.py` — assert D-140 notice fires on non-behavioral freezes only

### Group 2 — unexercised branch (11) · add a fixture that drives the branch
- [ ] [B] `new-project.sh` — fixture that triggers the thinking-model pre-flight (Hard Rule 1)
- [ ] [B] `check-drift.sh` — fixture with matching + divergent files to exercise the sync condition
- [ ] [B] `sandbox-run.sh` — fixture that attempts a .git/.githooks write (blocklist)
- [ ] [B] `sandbox-run.sh` — fixture with an escape path outside the repo root
- [ ] [B] `link-template.sh` — fixture with correct + mismatched approval hash
- [ ] [B] `bootstrap.sh` — fixture that exercises the dubious-ownership trust path
- [ ] [B] `llm-call.sh` — fixture with a reasoning-only reply (thinking-model detection)
- [ ] [B] `llm-call.sh` — fixture with a seat-mismatch (wrong model)
- [ ] [B] `tpm-agent.sh` — fixture exercising --view vs default launch
- [ ] [B] `tpm-agent.sh` — fixture with a non-existent settings file
- [ ] [B] `update-template.sh` — fixture with correct + mismatched approval hash

### Group 3 — fixture no-op (2) · make the stub observable
- [ ] [B] `status.sh` — stub podman so the section's presence/absence is assertable
- [ ] [B] `teardown.sh` — stub limactl to record stop vs start so the action is assertable

## check-test-surface.py mutation proof (the one gate never swept)
- [ ] [B] `check-test-surface.py` — the one real hard gate omitted from audit pass-2 (fixture-verified, **not** mutation-proven). Author ~2 mutants + a short `mutation-pass.sh` run to close the last proof gap.

## 5. Vortex product debt — needs go + TPM seat (D-139)
- [ ] [V] Memory-figure mismatch — `top` PhysMem vs psutil-used; pick one source of truth; src change + refreeze pairing
- [ ] [V] `_anneal_probe` hardening — single 5s shot → bounded retry; src change + refreeze pairing
- (both green-lit → they ride one refreeze pass)

## 6. Rides the next milestone (no clock)
- [ ] [V] Silent-halt live-fire — double coder-failure → does caps-exhausted escalation get reached end-to-end? Run + report on the next real orchestrate run

## Vortex recording hook for the catch ledger
- [ ] [V] Vortex recording hook for the catch ledger — joins when the ledger lands (wire `record_catch` into Vortex's refreeze lane, best-effort, never masks the gate's verdict)

## Standing (recurring, not completable)
- [ ] [V] Post-blueprint-landing verification — full product suite (all test files, scope labeled, never a subset) + CI green, after every blueprint commit touching linked files
- [ ] [B] Measurement instruments — run `gate-tiering.py` + review the catch ledger periodically (report-only evidence for gate health / retirement review, never a build gate; D-170)