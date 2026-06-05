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

**Decision:** (a) Rewrite `CLAUDE.md`'s intro to accurately describe its load behavior — file is *fetchable via tools*, not pre-loaded; the LLM is *expected* to read it. (b) Mirror the "do not re-add dropped BLUEPRINT.md sections" guard into `CLAUDE.md`'s "What NOT To Do" → Operating guardrails, closing the asymmetry between auto-loaded (`CLAUDE.md`) and on-demand (`DECISIONS.md`) docs. (c) Fix the project's `opencode.json` schema (OpenCode 1.15.13 rejects the old `providers` / top-level `models` form with "Unrecognized keys").

**Alternatives considered:** (a) Document the asymmetry but not fix it; (b) add a hook in BLUEPRINT.md to force the LLM to read CLAUDE.md first; (c) leave the broken `opencode.json` and tell users to delete it.

**Reason:** The architectural premise that "guards in CLAUDE.md auto-fire every session" was unverified and partially false. Empirical test showed the model uses the `read` tool to fetch content (not pre-loaded) and can misparse which guard applies. The memory layer is best-effort, not enforced. For things that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) that fire without the LLM's cooperation. Doc guards are strong hints, not hard gates.

**Do not suggest:** Reverting `CLAUDE.md`'s intro to the "automatically read" claim, reverting `opencode.json` to the old `providers` schema, or removing the mirror guard. All three are now verified-correct by empirical test.

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

## 2026-06-04 — Built `scripts/check-doc-sanity.sh`; upgraded doc guards from advisory to enforced

**Decision:** Add a tracked Bash script (`scripts/check-doc-sanity.sh`) that runs 5 mechanical checks on the template repo, plus a new GitHub Actions job (`.github/workflows/ci.yml` → `doc-sanity` job) that runs the script on every push to main. Exit non-zero on failure → CI fails the build.

**Alternatives considered:** (a) Document the line-count rule and let humans catch regressions; (b) use a pre-commit framework with a YAML config; (c) put the checks in BLUEPRINT.md as doc guards only (no enforcement).

**Reason:** The empirical test (correction log row 6) proved doc guards are advisory — the LLM can misparse them, and they don't fail the build. The principle "prefer mechanical gates over doc guards for must-hold rules" is in DECISIONS.md and the log, but a principle in a doc doesn't enforce itself. The script is the enforcement.

**Do not suggest:** Removing the script, moving the checks back into BLUEPRINT.md as doc-only, or skipping the `doc-sanity` job in CI to "save time." All three are regressions to the design.

**Checks enforced (5):**
1. `BLUEPRINT.md` line count ≤ 450
2. No phantom sub-step references in `BLUEPRINT.md` (every `Step N.M` must have a matching `### Step N.M` heading)
3. No legacy CLI tool residue (CLAUDE.md:117 correction log row is the only allowed mention)
4. `AGENTS.md` is a symlink to `CLAUDE.md`
5. `opencode.json` parses as valid JSON (skipped if `jq` is unavailable)

**Self-exclusion:** the script excludes itself from the legacy-tool residue check. The grep string is the literal name of the legacy tool, so the script's own code would otherwise trip its own check. The exclusion is documented in an inline comment so a future maintainer doesn't strip it.

**Verified by:** Running `bash scripts/check-doc-sanity.sh` from the project root — `Passed: 5    Failed: 0    RESULT: PASS` (exit 0). The CI workflow will run the same script on every push; the test was the same as what CI runs.

**Bootstrap step for derived projects:** Add a line to `scripts/bootstrap.sh` that copies `scripts/check-doc-sanity.sh` into the new project. The check applies to the template's own docs; derived projects may want to extend it (e.g. add a placeholder check for tasks/ and docs/ once the bootstrap has been run). Not done in this commit — separate concern.

---

> Add new decisions above this line, newest first.
