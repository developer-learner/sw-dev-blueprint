# BACKLOG.md — Task Queue

> Ordered by priority. Top = next up.
> When starting a task, move it to CURRENT.md and expand it into a full spec.
> Source: testchat M1–M4 supervised-run retrospective (2026-07-05).
>
> **Scope:** this is the blueprint's authoritative future-work queue. Active
> work → `CURRENT.md`; transient cross-session/cross-repo working notes →
> `TODO.md` (not authoritative). Other repos' backlogs live in those repos.

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

### Trim CLAUDE.md / split the decision log into DECISIONS.md
**Priority:** P3
**Why:** `CLAUDE.md` (~79 KB) is ~2× the master seed doc and is what every agent loads each run, so its size is a direct per-run context cost — and by BLUEPRINT.md's own standard (L729, "length is a smell to investigate") the flagship doc set should practice the context-budgeting the blueprint preaches. The `.gitignore` doctrine block already names `DECISIONS.md` as the intended home for D-entries, so the target state is documented; this task moves the decision log (D-33, D-40, D-95/96, …) out of the hot path into `DECISIONS.md` without losing history, and trims BLUEPRINT.md/CLAUDE.md accordingly. This is a curation task with real judgment (correction log, doctrine, cross-references) — do it as a focused solo change, NOT bundled into a hygiene commit, to avoid a contested rebase against active parallel sessions.
**Rough size:** Medium (curation, not code)
**Depends on:** a quiet window with no competing large edits to CLAUDE.md/BLUEPRINT.md

### Escalation-ladder validation: observe the first run that climbs it
**Priority:** P2
**Why:** D-70 (2026-07-15, CEO directive) armed the ladder — `MAX_TASK_STRIKES` now defaults to 2, ending ~23 milestones of the consult/verdict machinery as dead code. Arming is not validating (Rule 6): the item closes only when a real run exercises it. Observe on the first milestone where a task strikes twice: schema-valid diagnosis produced; `brief_wrong` revision actually changes the brief; `caps-exhausted` packages a usable TPM bundle; D-69 budget contains the total. Then the CEO calls it: validated, or fix what the run exposed.
**Rough size:** Small (observation, not code)
**Depends on:** the next testchat milestone run where a task organically fails twice

**Status 2026-09-03 — qualifying run observed (testchat T8 build, 2026-09-02); awaiting the CEO call.**
The v115 run (plane `6132185`, 01:28–01:35) exercised the full ladder organically on two tasks:
- **retry** — T1 and T3 each struck twice per brief revision (`MAX_TASK_STRIKES=2`); 8 coder calls total (`.coder-archive/115.T{1,3}.{0,1}.{1,2}.*`).
- **schema-valid diagnosis** — 2× `brief_wrong` carrying `verdict`+`reason`+`revised_brief`: T1 at 01:29:54 (brief's bare-exception clause violated D-74 lint BLE001/S110), T3 at 01:34:27 (brief contradicted the router-gate design) (`.em-archive/2026-09-02_{012954,013427}_diagnosis/reply.json`).
- **`brief_wrong` revision actually changes the brief** — in-run: the EM's `revised_brief` was written to the task brief and retried. T1 r0→r1 prompt diff: "On non-200 or exception return []" → "catch specific exceptions (httpx.HTTPError, OSError, ValueError) — do NOT use a bare `except Exception` (BLE001) — log the exception… no lint violations (BLE001, S110)" — exactly the diagnosed defect.
- **`caps-exhausted` packages a usable TPM bundle** — both tasks exhausted `MAX_BRIEF_REVISIONS=1` → `package_escalation "caps-exhausted"` (`orchestrate.sh:2364/2385`) → batch halt. The bundle drove the v116 brief-only refreeze (`641aa8d`) → v119 success. (The bundle file itself was transient `.pipeline-state/escalations/`, since cleaned; the code path and its effect are durable.)
- **D-69 budget contains the total** — run ≈ 7 min ≪ 1200 s default; bounded, no thrash.
- **outcome accepted** — v119 `[success]` (`aa3deea`, plane `6132185a850e` recorded in the commit); milestone closed by the v121 consolidation (`c6d78fe`).
What the run exposed: brief defects (lint awareness, router-gate consistency) — not machinery defects. The ladder caught, diagnosed, revised, and escalated exactly as designed.

---

## Icebox (someday/maybe)

- EM-tier collapse experiment: M1–M4 showed EM is strong at decomposition, weak at diagnosis — test whether a frontier TPM emitting the plan directly (skipping EM) changes outcomes.
- Coder model upgrade pass: the coder was the weakest link in every milestone; re-run a milestone with a stronger local model (models.env change only) and compare strike rates.
- mlx-serve as LM Studio alternative (OpenAI+Anthropic+Ollama endpoints, ~35% faster decode on Apple Silicon) — revisit when model-serving friction matters.

---

## Completed

| Task | Completed | Notes |
|------|-----------|-------|
| Immutable-plane update across a successful multi-task run: live proof | 2026-09-03 | Plane update `403dc9f` `[template-link 6132185a850e]` (testchat, 2026-09-02 01:20 — `6f51d63`→`6132185`, the T7 M1 `orchestrate.sh` fix) followed by a successful **8-task** run on the new plane: v119 `[success]` `aa3deea` (09:53, commit records `plane 6132185a850e`; T3 real coder work `119.T3.0.1`). Corroborated by the v121 8-task no-edit success (`c6d78fe`, `run-exit.log` rc=0 69 s) and by the v115 run's 8-coder-call ladder exercise on the same plane (the hardest run shape the new plane could face). |
| EM plan gate: give the EM a self-correction signal on carried-contract claims | 2026-08-30 | D-173: `--active-erd-context` closes with a machine-computed changed-contracts section (the same `delta_changed_contract_ids` union the ride-along gate enforces) + claim rule. Option (a) was already in place — the v14 archive proves the rejection names the ids; the ticket's "names no ids" clause was an inaccurate recollection and is superseded. Option (b) is the fix that shipped, rendered in `validate-plan.py` (the file's owner), not `contracts-delta.py`. B3's mechanical lane remains the best fix when its precondition holds. |
| Correction-log row: Perl `s{}{}` interpolation eats shell variables in generated code | 2026-08-23 | Added to CLAUDE.md: generator-level interpolation can erase intended shell variables before the shell ever sees them; use literal patching or explicitly escape and exercise generated invocations. |
| EM diagnosis taxonomy: represent transient/environmental failures | 2026-08-23 | D-169 adds a positive-evidence-only verdict. The shell preserves an operator-review record and halts; it never retries, re-probes, rewrites the plan, or escalates to TPM automatically. |
| EM diagnosis hardening: A/B denser diagnosis brief | 2026-08-23 | Three archived consults replayed through both variants: both fixed 2 schema-invalid replies; neither could honestly classify a transient failure. Dense candidate not shipped; evidence isolates the missing verdict taxonomy. |
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
