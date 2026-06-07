# DECISIONS.md — Architectural Decision Log

> Every non-obvious technical decision goes here with the reasoning.
> This prevents the LLM from "helpfully" undoing choices you already made.
> Format: date, decision, why, what not to suggest.

---

## Template

```
## YYYY-MM-DD — [Decision title]

**Decision:** [What was decided]
**Alternatives considered:** [What else was evaluated]
**Reason:** [Why this choice was made]
**Do not suggest:** [What the LLM should not propose as a "fix"]
```

---

## Decisions

## [DATE] — [Your first decision here]

**Decision:** [e.g. Using raw SQL over ORM]
**Alternatives considered:** [e.g. SQLAlchemy, Tortoise ORM]
**Reason:** [e.g. Query complexity made ORM unreadable for our join-heavy patterns]
**Do not suggest:** Switching to an ORM. This was deliberate.

---

## [DATE] — Monorepo structure

**Decision:** Single repository for all services.
**Alternatives considered:** Separate repos per service.
**Reason:** Team size doesn't justify the overhead of managing multiple repos. Shared code is easier to refactor.
**Do not suggest:** Splitting into microservices repos until team grows past 5 engineers.

---

## 2026-06-04 — Pruned BLUEPRINT.md (557 → ~440 lines)

**Decision:** Apply the noise/redundancy findings from a parallel LLM audit; skip the lifecycle/strategy findings from a second LLM.
**Alternatives considered:** (a) accept both LLMs' suggestions and add new rules; (b) leave the file as-is; (c) full rewrite.
**Reason:** BLUEPRINT.md is the LLM's entry point. Every redundant line is context-window cost and a chance for ambiguity to compound. Pruning is a guardrail against drift, not cosmetics. Adding more rules (the second LLM's "fortify" suggestions: Doc-Sync hard rule, TDD loop, REVIEW checkpoints, `/reset-context`) would partially undo the trim and add bloat.
**Do not suggest:** Re-adding the dropped sections. The "Document Map" alone is sufficient; the verbose "Document Roles Explained" was redundant. "Step 5 — Adapt the stack" is a pointer to Rule 3, not a restatement. Bootstrap cleanup, OpenCode Configuration, and Quick Reference Card are now minimal — keep them so.

**Trimmed (12 items, ~115 lines removed):**
- Dropped "Document Roles Explained" (duplicated Document Map)
- Collapsed Bootstrap Step 5 to a 1-line pointer to Rule 3
- Trimmed Maintenance Contract from 6 rows to 4 (dropped obvious triggers)
- Trimmed Files Never to Touch from 5 items to 3 (universal best-practice items removed)
- Shrunk Bootstrap Step 4 cleanup (24→6 lines)
- Trimmed Step 7 preamble (dropped "Hard Rule 5" restatement)
- Shrunk OpenCode Configuration section (28→3 lines + pointer to `opencode.json`)
- Trimmed anti-pattern "wrong provider name" to a one-liner
- Deleted Quick Reference Card (restated diagram + rules)
- Fixed phantom "Step 4.5" reference on line 490 → "Step 4"
- Reduced duplicate "lms not lmstudio" mentions from 3 to 1
- Reduced "AGENTS.md symlinks to CLAUDE.md" mentions from 5 to 3 (one in prose + 2 short callouts)

---

## 2026-06-04 — Auto-load assumption corrected; CLAUDE.md / opencode.json fixes

**Decision:** (a) Rewrite `CLAUDE.md`'s intro to accurately describe its load behavior — file is *fetchable via tools*, not pre-loaded; the LLM is *expected* to read it. (b) Fix the project's `opencode.json` schema (OpenCode 1.15.13 rejects the old `providers` / top-level `models` form with "Unrecognized keys"). The original commit also added a "do not re-add dropped BLUEPRINT.md sections" mirror guard to `CLAUDE.md`; that mirror was later removed (see entry below) for template-hygiene reasons.

**Alternatives considered:** (a) Document the asymmetry but not fix it; (b) add a hook in BLUEPRINT.md to force the LLM to read CLAUDE.md first; (c) leave the broken `opencode.json` and tell users to delete it.

**Reason:** The architectural premise that "guards in CLAUDE.md auto-fire every session" was unverified and partially false. Empirical test showed the model uses the `read` tool to fetch content (not pre-loaded) and can misparse which guard applies. The memory layer is best-effort, not enforced. For things that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) that fire without the LLM's cooperation. Doc guards are strong hints, not hard gates.

**Do not suggest:** Reverting `CLAUDE.md`'s intro to the "automatically read" claim, or reverting `opencode.json` to the old `providers` schema. Both are now verified-correct by empirical test.

**Verified by:**
- `opencode run --format json --dir /tmp/opencode-autoload-test "Read AGENTS.md..."` — event log showed `tool_use` with `read` tool; model fetched content but answered wrong
- `opencode --version` → `1.15.13` (matches the schema fix)
- `opencode run "What is 2+2?" --format default` from project dir → "Four." (schema fix loads cleanly under the installed version)

**Cross-cutting lesson (worth applying to all template projects):** Treat doc guards as advisory. For must-hold rules, build mechanical checks into scripts or CI:
- Placeholder completeness → grep (BLUEPRINT.md Step 7)
- File size budgets → `wc -l` in a pre-commit hook
- Schema validity → `opencode.json` parsed at session start
- Tests as ground truth → pytest in CI (BLUEPRINT.md Rule 5)
Doc guards catch the LLM's *intent*; mechanical gates catch the *result*. Both have a place. The test just proved the first is weaker than the design claimed.

---

## 2026-06-04 — Removed CLAUDE.md mirror guard (decoupling template from project)

**Decision:** Remove the one-line "Do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune" guard from `CLAUDE.md`'s "What NOT To Do" → Operating guardrails. The rule still lives in `DECISIONS.md` → "Pruned BLUEPRINT.md" entry.

**Reason:** CLAUDE.md is a template — `[PROJECT_NAME]` is still a placeholder. Baking a project-specific date ("2026-06-04 prune") into a template file makes the rule meaningless for any future project created from this template. The visibility argument was real but the template-vs-project boundary was muddied. The principle (don't re-add dropped sections) stays binding via DECISIONS.md's "Do not suggest" line and the correction log capture.

**Do not suggest:** Re-adding the mirror guard. Cross-reference, don't copy.

---

## 2026-06-06 — Adopted EARS for acceptance criteria

**Decision:** Acceptance criteria in `tasks/CURRENT.md` are now written in EARS notation (THE SYSTEM SHALL / WHEN...SHALL / WHILE...SHALL / IF...THEN SHALL / WHERE...SHALL). Each criterion is a single observable clause that maps one-to-one to a test case. The PM prompt enforces this at PRD time; the test prompt reinforces the mapping at test time. Template examples in CURRENT.md demonstrate all five forms plus an HTML-comment reference guide.

**Reason:** EARS forces each requirement into a single testable clause, giving the test agent an unambiguous oracle and tightening INV-1 enforcement. Vague prose criteria ("handles errors gracefully", "works correctly") were the weak point — the tester had to interpret intent, which reintroduces the ambiguity the pipeline was designed to eliminate. A one-clause-to-one-test mapping makes the test agent's job mechanical and removes the interpretation gap.

**Do not suggest:** Reverting to free-form prose criteria, or forcing all five EARS forms when a single SHALL clause suffices (avoid ceremony — see the repo's anti-over-engineering history, BLUEPRINT.md and DECISIONS.md prune entries).

---

## 2026-06-06 — Four-role PRD→Plan→Build→Test pipeline

**Decision:** Adopted a four-role pipeline (PM, Architect, Build, Test) with two non-negotiable invariants: INV-1 (tests derive from the PRD, never from `src/` implementation) and INV-2 (Build never edits `tests/`; Test never edits `src/`). The PRD in `tasks/CURRENT.md` is the single oracle — the human's casual instruction is translated into structured acceptance criteria and flagged assumptions, then frozen on Approval. The Architect is also the orchestrator: it delegates build→test, runs `scripts/phase-gate.sh` after each phase, reads `.cache/test-report.json`, and routes failures per Rule 2/7 (build bug→build, same failure twice→re-plan, plan fails twice→PM).

**Alternatives considered:** (a) Extend the existing single-agent loop with role instructions in CLAUDE.md; (b) use OpenCode agent permissions alone for INV-2 enforcement; (c) keep the flat loop and add no roles.

**Reason:** A single-agent loop conflates planning, writing, and testing in one context — the model's self-judgment replaces the test-report oracle (Rule 5 drift) and nothing prevents it from writing tests that confirm what `src/` does rather than what the spec says (INV-1 violation). Separate roles with frozen contracts force the verification gap that catches bugs. OpenCode's agent permissions (`permission.edit` globs) are non-transitive — a restricted agent can bypass limits via the Task tool (opencode issues #12566, #20549) — so INV-2 is enforced mechanically by `scripts/phase-gate.sh`, not by permissions alone. Doc guards catch intent; mechanical gates catch the result (documented pattern from the 2026-06-04 auto-load entry). Cost rationale: build/test use the local model (free, 80% of tasks); pm/architect use frontier for reasoning walls and spec work.

**Do not suggest:** Letting the test agent read `src/` implementation to author tests (INV-1). Enforcing INV-2 with agent permissions alone — the git gate is the binding layer. Merging the four roles back into a single agent — the whole point is the verification gap between them. Letting the build or test agent edit the PRD or architecture docs.

---

> Add new decisions above this line, newest first.
