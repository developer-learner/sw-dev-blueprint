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

### Linux Dev VM for zero-prompt agent operation
**Priority:** P0
**Why:** testchat M4 proved conductor constraints must be structural (a frontier conductor crossed every advisory lane under goal pressure); the VM boundary also eliminates permission-prompt babysitting entirely. Absorbs two retrospective items: the llm-call.sh round-trip smoke test (owed since 2026-07-03) and the sandbox directive.
**Rough size:** Large
**Depends on:** Nothing — full spec in `tasks/HANDOFF-dev-vm.md`

---

## Later

### Escalation-ladder validation run
**Priority:** P2
**Why:** The retry → EM consult → brief/plan revision → TPM ladder has never been allowed to complete (M4 bypassed it at strike 1). Per Operating Rule 6, an untriggered safeguard is inconclusive — one honest run where a stuck task climbs the full ladder is needed before trusting it.
**Rough size:** Medium (process, not code)
**Depends on:** Next derived-project milestone; Dev VM recommended first (removes the conductor's incentive to take over)

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
