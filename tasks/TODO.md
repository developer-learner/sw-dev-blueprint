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
> PARKED 2026-08-25 (CEO): remaining items below deferred while vortex builds its next feature; revisit after that milestone lands.

- [ ] [B] Scope first, then build — seed path yields project-local files + links, skipping the copy. Precision: one template-derived file stays real (`check-drift.yml`, GitHub necessity); `ci.yml`/`container-build.yml` are project-local by design
- [ ] [V] Verify vortex integrity after seed-path changes (manifest, symlinks, full suite)

---

# MAINTENANCE (ongoing — hardening, debt, standing guardrails; latent, not blocking feature work)

## 3b. Oracle-gap fixes — from the 2b-ext mutation sweep (23 survivors)
The 2b-ext sweep (45/68 killed) surfaced 23 survivors — real mutations the
selftest suite failed to catch. Each is a **named** oracle gap, not "improve
coverage." Grouped by fix type; do the cheap asserts (group 1) first.
Source: `docs/research/2026-08-25-d161-gates-ext-mutation-report.md`.

### Group 1 — unasserted output/exit (10) · cheapest: add the missing assert — **done 2026-08-25**
All 10 closed: source-text assertions added to `selftest_gates.py` (`test_group1_oracle_gaps_2b_ext`, `88cb9f6` + `3f14f44` for the update-template uniqueness fix); re-verified with a focused 10-mutant `mutation-pass.sh` on HEAD `3f14f44` — **10/10 killed, 0 survived** (`docs/research/2026-08-25-d161-group1-oracle-fixes-results.tsv`); the 9 affected gates are now `proven` in `gate-inventory.tsv`.
- [x] [B] `new-project.sh` — assert the bootstrap pre-check message (survivor: message changed, unobserved)
- [x] [B] `extract-test-functions.py` — assert which leading-comment lines are included vs dropped
- [x] [B] `check-drift.sh` — assert BEHIND exits 2 (survivor: rc=1 instead of 2, unobserved)
- [x] [B] `mutation-pass.sh` — assert the baseline runs under PYTHONDONTWRITEBYTECODE=1
- [x] [B] `status.sh` — assert the LLM port probe uses the documented default port
- [x] [B] `feature-summary.py` — assert the archive time window (recent counted, old skipped)
- [x] [B] `feature-summary.py` — assert outcome-line parsing precedence
- [x] [B] `metrics-report.py` — assert waste counting (failures = waste, successes not)
- [x] [B] `update-template.sh` — assert "nothing to review" only when no changes exist
- [x] [B] `refreeze_delta.py` — assert D-140 notice fires on non-behavioral freezes only

### Group 2 — unexercised branch (11) · add a fixture that drives the branch
- [x] [B] `new-project.sh` — fixture that triggers the thinking-model pre-flight (Hard Rule 1) — `91a4544`, drill-killed
- [x] [B] `check-drift.sh` — fixture with matching + divergent files to exercise the sync condition (IN_SYNC → exit 0; mutant misreads as BEHIND → exit 2) — `1e759f3`, drill-killed
- [x] [B] `sandbox-run.sh` — fixture that attempts a .git/.githooks write (blocklist) (`--rw .git` refused pre-podman) — `1e759f3`, drill-killed
- [x] [B] `sandbox-run.sh` — fixture with an escape path outside the repo root (valid `--rw src` allowed, not "escapes repo root") — `1e759f3`, drill-killed
- [x] [B] `link-template.sh` — fixture that attempts to retire a `../..` traversal path and asserts the unsafe-retired-path guard blocks it (mislabeled as the approval-hash, which `selftest_linked_template.py` already covers — `a0cb2f7` was redundant) — `6a3f771`, drill-killed
- [x] [B] `bootstrap.sh` — fixture that exercises the dubious-ownership trust path — `d6ee9cb`, drill-killed (also exhausts the identity-preflight survivor, pass F)
- [x] [B] `llm-call.sh` — fixture with a reasoning-only reply (thinking-model detection) — `4164698`, drill-killed
- [x] [B] `llm-call.sh` — fixture with a seat-mismatch (wrong model) — `d192ccc`, drill-killed
- [x] [B] `tpm-agent.sh` — fixture exercising --view vs default launch — `f47e2de`, drill-killed
- [x] [B] `tpm-agent.sh` — fixture with a non-existent settings file (default mode uses repo settings file, not `-missing`) — `695e13e`, drill-killed
- [x] [B] `update-template.sh` — fixture with correct + mismatched approval hash — `e102e14`, drill-killed

### Group 3 — fixture no-op (2) · make the stub observable
- [x] [B] `status.sh` — stub podman so the section's presence/absence is assertable — `90f1d20`, drill-killed
- [x] [B] `teardown.sh` — stub limactl to record stop vs start so the action is assertable — `90f1d20`, drill-killed

## check-test-surface.py mutation proof (the one gate never swept)
- [x] [B] `check-test-surface.py` — mutation proof closed without new tests: 2 authored mutants (import allowlist inverted; route match inverted) both KILLED by the existing fixture suite at HEAD `90f1d20` (`/tmp/inv4-mutants-results.tsv`; recorded in the D-161 results TSV).

## 5. Vortex product debt — needs go + TPM seat (D-139)
- [x] [V] Memory-figure mismatch — `top` PhysMem vs psutil-used; pick one source of truth; src change + refreeze pairing — vortex `6884ae1` + refreeze v13 `697cc17`: `/api/status` now names its source (`ram_source: vm_stat|psutil`); AM figure is truth, silent basis flip closed
- [x] [V] `_anneal_probe` hardening — single 5s shot → bounded retry; src change + refreeze pairing — vortex `6884ae1` + refreeze v13 `697cc17`: transport exceptions retry ≤3 (0.5s gap); loading-503 stays single-shot so spawn poll cadence governs
- (both green-lit → they ride one refreeze pass)

## 6. Rides the next milestone (no clock)
- [ ] [V] Silent-halt live-fire — double coder-failure → does caps-exhausted escalation get reached end-to-end? Run + report on the next real orchestrate run

## Vortex recording hook for the catch ledger
- [x] [V] Vortex recording hook for the catch ledger — done 2026-08-26: the wiring itself is the shared `refreeze.sh` (inherited via symlink; `record_catch` at all 8 hard-gate die sites, best-effort `|| true`, never masks the verdict). The missing piece was hygiene: `.catch-ledger.json` (CWD-relative runtime witness) was unignored in both repos — it would dirty the child's tree and ride `git add -A` into freeze commits. Now gitignored in the Blueprint (template → future children) and in Vortex. Live-fire in a throwaway vortex clone: capsule-altering staged PRD → `check-prd-additive` catch recorded (spec v14) → proper die; ledger lands in the child root, tree stays clean.

## 7. CEO-gated items — rulings received 2026-09-01 (Track C)

> Per the cross-cutting rules: these items cannot start code until the CEO
> decides; the Track C LLM prepares option notes, not code. T-numbers are the
> session register in `vortex/tasks/TODO.md`; item numbers are the canonical
> backlog register in `vortex/tasks/BACKLOG.md`. **CEO ruling 2026-09-01
> unblocked T7 (M1) and T11 (Phase 0, Rich); both are now executing.**

- [ ] [B] **T7 (backlog #13) — model-specific Git provenance: M1 DONE (D-174), M2 DESIGNED (D-176), M2 code awaiting go.** CEO approved Option 3 as staged, M1 authorized initially. M1 landed: trusted commit broker (`scripts/git-provenance.sh`), author/committer separation, `Swbp-*` trailers, provider-returned model preference (llm-call meta sidecar), run-id, coder-prompt capture, 10 blind selftests (suite 548 green); first adoption cycle = rich-adoption linked install (commit `0127c3bf` carries the full trailer set). M2 design now complete per the CEO's three prerequisites: out-of-band pinned-fingerprint trust anchor (machine tier `~/.swbp/provenance/` + public tier `docs/PROVENANCE.md`), atomic durable evidence (`.swbp-evidence/<run-id>/` committed with the task commit, 5 MB fail-closed guard), attestation semantics stated for the record (+ `Swbp-Call-Id:` trailer); verifier report-first → T1 after one clean cycle. **No M2 code until the CEO says go.** Vortex/Testchat adoption: **DONE 2026-09-01 (D-177)** — both children re-linked at `6f51d63` (Vortex `b7fb2c2`, Testchat `f08ad6e`), pins advanced to the broker plane, check-drift green; forced by check-drift's union semantics (pre-broker pins can't be drift-green while the shared checkout is post-M1). Fleet state: all three children on the broker plane (rich-adoption at `1684e0b`, advances at its Phase 1 run time).
- [ ] [B] **T11 (backlog #18) — mature OSS adoption subject #2: Phase 0 DONE (D-175), Phase 1 awaiting machine slot.** rich-adoption: rich 15.0.0 pinned at tag `v15.0.0` (`6ac483cb`, MIT); baseline 956 passed / 25 skipped / 0 failed (lockfile deps — pygments 2.21.0 breaks 8 legacy syntax tests, lockfile is the dependency authority); `legacy-pin.json` (73 files, provenance never oracle); project files adapted (Rule 3); plane linked at `1684e0b` (broker plane — run #2 doubles as the M1 adoption cycle); pre-spec tunnel state recorded; child verification green (legacy suite, 548/548 plane selftests after adding `pytest-json-report` to the venv, phase-gate, check-drift in sync). Phase 1 (v1 spec + first freeze + live milestone M–L): **spec DRAFTED** — M1 = `Table.add_rows(rows)` + `Table.from_rows(columns, rows)` in `rich/table.py` (purely additive, thin delegates to the existing `add_row` cell machinery), 12-test frozen suite with deterministic rendered-output contracts; `refreeze.sh --diff` all preflights green (v0→v1, 4 new contracts); tests fail cleanly against unmodified code (target state); legacy-suite decision recorded (956-test upstream suite stays a pinned snapshot, not carried into the frozen gate — the spec's own tests are the only gate, D-165). The freeze + live run NOT started: needs the **Linux dev VM** (orchestrate hard-dies on Darwin, D-152) around the single-run machine slot.
- [ ] [B] **T6 (backlog #9) — observe one organic two-strike ladder climb.** CEO: leave untouched until an organic qualifying run occurs. Status 2026-09-01: no new organic run since 2026-08-30 (last: spec v20 success, plane `605a998`). Rungs observed so far span multiple runs — 08-22/23: schema-valid `brief_wrong` diagnosis + materially revised brief + usable TPM batch; 08-28: D-71 diagnosis retry rung (2× schema-invalid → retry) then a D-169 `transient_or_environmental` halt; 08-28→08-30: task-level failure, resume, success. Still missing per the backlog's own close criterion: **one uninterrupted organic run** exercising the complete retry → diagnosis → revised-brief/TPM path with the outcome accepted against D-70/D-69. Observe, don't manufacture — closes on the next qualifying run.

## Standing (recurring, not completable)
- [ ] [V] Post-blueprint-landing verification — full product suite (all test files, scope labeled, never a subset) + CI green, after every blueprint commit touching linked files
  - **Executed 2026-08-26 (pi session):** since the `cd58d3b` sync, the two blueprint commits touched `tasks/TODO.md` only (not linked) — no verification strictly owed; ran the full baseline anyway. It caught a real defect: the 2026-08-25 batch (`4164698`, `560850ab`) had left the CI selftest lint red (1× F841 unused `outer`, 5× E741 `l` in `selftest_gates.py`) — origin's CI selftest job has been red since `560850ab`. Fixed in `ffebfe9` (ruff-clean + manifest regen; 525 selftests green). Vortex side: pin advanced to `ffebfe9` (`4f1c441`), check-drift IN_SYNC, ruff scripts+src clean, mypy clean, selftests 525/525, full product suite 58/58 across all 10 test files, coverage 88.71% ≥ 80 floor.
- [ ] [B] Measurement instruments — run `gate-tiering.py` + review the catch ledger periodically (report-only evidence for gate health / retirement review, never a build gate; D-170)
  - **Executed 2026-08-26 (pi session):** 41 gates → T1=14 (every hard gate proven-teeth after the 2b/2b-ext sweeps + oracle-gap fixes), T2=2 (`doc-consistency`, `manifest-drift-guard` — both advisory by design), T3=0, n/a=25. Catch ledger: zero catches recorded — no hard gate has rejected a real staged delta in the wild yet. Nothing flagged for human review. Cost column empty (no cost TSV; a `gate-cost.py` probe is optional and not part of this standing item).
  - **Executed 2026-08-31 (pi session):** unchanged — T1=14, T2=2, T3=0, n/a=25; catch ledger still empty (no in-the-wild rejection since). No gate flagged for human examination. (Ran alongside the fault_role/em_model/.measurement-hygiene commit `09aec03`; the new fault_role field will make the next real failure's attribution mechanical — first in-the-wild row is the live validation.)