# BACKLOG.md — Task Queue

> Ordered by priority. Top = next up.
> When starting a task, move it to CURRENT.md and expand it into a full spec.
> Source: testchat M1–M4 supervised-run retrospective (2026-07-05).

---

## Format

```
### [Task name]
**Priority:** [P0 critical / P1 high / P2 medium / P3 low]
**Why:** [One sentence on the value]
**Rough size:** [Small / Medium / Large]
**Depends on:** [Any blockers]
```

---

## Up Next

### EM diagnosis hardening: denser diagnosis brief (M28 handoff item 6)
**Priority:** P2
**Why:** Mid-tier diagnosis is the ladder's weak rung, on record since M23 (schema-invalid diagnosis, empty task_id — gate refused correctly) and still thin on 2026-07-17 (first schema-valid production diagnosis, but rambling prose). The bounded schema-retry half already shipped (D-71: validator errors echoed back, one retry); the open half is the diagnosis BRIEF — what context makes a mid-tier model diagnose accurately (D-73's FAIL_DETAIL landed since; whether it closed the gap is unmeasured). Carried from the 07-15 open items via the M28 handoff (item 6, `tasks/HANDOFF-M28-blueprint-items.md`).
**Rough size:** Medium (needs bench evidence — A/B the brief against recorded consult transcripts, not intuition)
**Depends on:** entries accumulating in `.em-archive/` (capture + replay shipped 2026-07-19; failure-path capture added same day — invalid-JSON and schema-invalid diagnoses now land in the corpus with outcome/validation metadata, and `em-bench.sh` scores them FIXED/STILL_INVALID under a variant brief, which is the A/B signal this item needs. First real entries collected in testchat's v56 run: 3 plan emissions including both 4-bit gate rejections, 1 diagnosis `verdict=brief_wrong`); then a design session on the brief variants, not a quick commit

### Escalation-ladder validation: observe the first run that climbs it
**Priority:** P2
**Why:** D-70 (2026-07-15, CEO directive) armed the ladder — `MAX_TASK_STRIKES` now defaults to 2, ending ~23 milestones of the consult/verdict machinery as dead code. Arming is not validating (Rule 6): the item closes only when a real run exercises it. Observe on the first milestone where a task strikes twice: schema-valid diagnosis produced; `brief_wrong` revision actually changes the brief; `caps-exhausted` packages a usable TPM bundle; D-69 budget contains the total. Then the CEO calls it: validated, or fix what the run exposed.
**Rough size:** Small (observation, not code)
**Depends on:** the next testchat milestone run where a task organically fails twice

---

## Icebox (someday/maybe)

- EM-tier collapse experiment: M1–M4 showed EM is strong at decomposition, weak at diagnosis — test whether a frontier TPM emitting the plan directly (skipping EM) changes outcomes.
- Coder model upgrade pass: the coder was the weakest link in every milestone; re-run a milestone with a stronger local model (models.env change only) and compare strike rates.
- mlx-serve as LM Studio alternative (OpenAI+Anthropic+Ollama endpoints, ~35% faster decode on Apple Silicon) — revisit when model-serving friction matters.

---

## Completed

| Task | Completed | Notes |
|------|-----------|-------|
| 6 plumbing fixes ported from testchat M1 (fd-0, enable_thinking, error body, think-strip, mkdir, loguru) | 2026-07-03 | Commits `b73c2b7`..`5f4a59e` |
| 3 structural gates: DAG-brief consistency, smoke_check executability, smoke_check→TPM tier | 2026-07-04 | `9b4e379` |
| AST-first node-id collection (D-51 revised) | 2026-07-05 | `83073f2` — fixes M3's 8/19 partial collection |
| Brief length gate (2000 chars, Rule 8) | 2026-07-05 | `459ff25` |
| Constraints-first EM briefs | 2026-07-05 | `cae402a` |
| Model profiles (`model-profiles.toml`, consulted by llm-call.sh) | 2026-07-05 | `3f5e397` — context 67K→8K/16K was the biggest EM quality lever |
| orchestrate pre-flight fails closed on missing hooksPath | 2026-07-05 | `8b92e09` — bootstrap.sh had silently never run on testchat |
| Correction-log entry: conductor compliance is never a safety mechanism | 2026-07-05 | `c0f4a38` |
| refreeze: ast.parse staged tests before the diff | 2026-07-05 | `3114eee` — M4's broken TPM test syntax now caught pre-approval |
| orchestrate: pre-flight clean-tree check | 2026-07-05 | `e4b5b7a` — dirty host tree no longer misattributed to the first tier |
| refreeze: REMOVED manifest for retiring test files | 2026-07-05 | `338f4a3` — removals are a first-class, human-approved part of the delta |
| validate-plan: regression bucket for carried-forward tests | 2026-07-05 | `c111442` — chosen semantics: plan-level `regression` array, accepted by the final full-suite pass; 24/24 selftests |
| Spec-drift policy decided | 2026-07-05 | D-54: test surface is binding, ERD prose is advisory; deviations must be reported, refreeze re-trues drifted prose. CEO delegated the call. |
| Linux Dev VM for zero-prompt agent operation | 2026-07-06 | `c7c78c4`..`68ba1da` — Lima VM provisioned (4 CPU/8 GiB, virtiofs, Podman native), D-55 parameterization, OSC 52 shims, conductors installed. Acceptance pending: first unattended orchestrate.sh run inside the VM. |
| D-57: carried-forward regression bucket computed by the shell | 2026-07-07 | `c92c06f` — testchat M6: EM failed twice transcribing 58 ids; ownership signal from import/route reachability; 33/33 selftests |
| Smoke-test budget for cold model starts (SMOKE_MAX_TIME, 240s) | 2026-07-07 | `9789c1e` — M6 false pre-flight failure on cold 122B EM |
| MAX_PLAN_REVISIONS default 2 | 2026-07-07 | `b380326` — validator feedback loop fixes plans on second emit |
| refreeze surfaces D-56 externals count at the approval gate | 2026-07-07 | `1705dfc` — testchat froze v8/v9 with externals undeclared; the capture gate had never fired |
| Browser oracle (D-58): frozen suite sees the frontend | 2026-07-08 | `568a8dd` — contracts.ui locked testids, chromium sandbox layer, determinism gate; spike `13dd6b5` measured +1.2GB image |
| D-59: coder edits existing files via anchored blocks | 2026-07-09 | `e5d17bf` + applier `0cd9c9b`/`55ea0ec` — full-file retype deleted 99/119 lines twice; 11/11 anchors in controlled re-runs |
| D-60: coder-capability sizing law into em.md/TPM-ROLE.md | 2026-07-09 | `b89f270` — M7 bundled three concerns per brief twice; knowledge lived in folklore |
| Audit fix: applier validates anchors against the ORIGINAL file | 2026-07-11 | `8834ec7` — multi-block replies could sneak an ambiguous anchor past the uniqueness check (reproduced) |
| Audit fix: D-58 UI gate page-receiver rule | 2026-07-11 | `cc19761` — `page.click("button")` froze unlocked DOM with no gate feedback (reproduced) |
| Audit fix: refreeze determinism gate catches aliased sleeps | 2026-07-11 | `2b3671a` — literal `time\.sleep` grep missed `import time as t` / bare `sleep(` |
| D-61: hash-bound `--approve` for update-template.sh | 2026-07-11 | D-42 pattern on the second protected-artifact class; retires the pty/expect workaround for conductor-driven pulls |
| D-77 flake branch selftest coverage (`drive-drift.sh`) | 2026-07-22 | `1930723` — 7 pytest cases pinning the 5 review-named behaviors; Rule 6 discharged for the budget-skip pin via stash-test; 100 → 107 selftests |

---

## Declined

- **Fast path: skip the coder when mapped tests already pass** — CEO decision 2026-07-13: dropped. Savings are minutes per ratify milestone; the pipeline's reliability comes from one path with no shortcuts, and the skip removes a per-task check (Rule 3 relaxation). Ratify milestones (D-63) simply eat the no-op coder calls.
