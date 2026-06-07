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

## 2026-06-06 — Demoted BLUEPRINT.md line-count gate to heuristic

**Decision:** Removed the failing `wc -l BLUEPRINT.md <= 450` check from CI and the correction log's hard-target language. The 450 number was self-imposed by the model during a pruning session, never a human requirement. Line count is a proxy that does not measure the real goal (no redundant/ambiguous content). Enforcement is replaced with a heuristic note at the bottom of BLUEPRINT.md.

**Reason:** Enforcing a specific line count as a CI failure pressures edits to delete real content — including safety rules — to stay green. A mechanical gate is right for binary invariants (INV-2, placeholder completeness), wrong for a judgment call like doc leanness. The anti-bloat principle is genuine (BLUEPRINT is the LLM's entry point; redundancy is token cost and ambiguity risk), but enforcement should be human review and cross-reference discipline, not a numeric gate.

**Do not suggest:** Re-adding a failing line-count check, or compressing rules to hit a number. The "do not re-add pruned sections" guards in DECISIONS.md and human review are the correct mechanisms — they target redundancy directly.

---

## 2026-06-06 — Code-driven orchestration loop

**Decision:** Moved loop control out of `architect.md` (where an LLM must remember to run the gate, read the test report, count strikes, and route) and into `scripts/orchestrate.sh`. The orchestrator is a shell script that drives the build→test loop deterministically: it starts a headless `opencode serve`, calls each agent via `opencode run --attach --agent <name>`, runs `scripts/phase-gate.sh` after each phase, parses the JSON test report via `python3 -c`, computes a `sha1(sorted(failing_node_ids))` signature for two-strike detection, and escalates to re-plan on identical failure signatures. The architect prompt shrinks to "produce/refresh the plan only."

**Reason:** Loop control in an LLM prompt is a doc-guard — the architect could forget to run the gate, mis-count strikes, or skip escalation. Moving it to a script makes the gate invocation, the two-strike counter, and the halt deterministic — each is a line of shell code, not a remembered instruction. Additionally, each scoped `opencode run` sidesteps the non-transitive-permission bug (each agent runs in its own invocation with its own permissions) and prevents context bloat over long loops. The script wraps each agent call in a `run_agent` function that is the single indirection point for future sandbox adoption.

**Do not suggest:** Putting orchestration logic back into `architect.md`, or auto-approving the PRD (the orchestrator refuses to run unless `Status: Approved`). Adding a queue, daemon, web UI, or multi-feature scheduling — one approved PRD, one run. Replacing the shell script with an orchestration framework (adopt OpenHands later if needed — note it in DECISIONS, don't pre-build for it).

**Server details (for posterity, empirically verified on OpenCode 1.15.13):**
- `opencode serve --port <n>` starts a headless server; default port is 0 (random), use `--port` explicitly.
- `opencode run --attach <url> --agent <name> <prompt>` calls a specific agent on the running server.
- Server is killed on script exit via `trap cleanup EXIT`.

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

## 2026-06-06 — Sandbox Wiring in Orchestrator

**Decision:** `scripts/orchestrate.sh` routes agent calls and pytest through `scripts/sandbox-run.sh` when the `SANDBOX=1` environment variable is set. The sandbox path wraps each agent call with `timeout "${AGENT_TIMEOUT}"` (the container runs Debian where `timeout` is available from coreutils). The non-sandbox path uses `$TIMEOUT_CMD "${AGENT_TIMEOUT}"` (`gtimeout` on macOS, `timeout` on Linux). `SANDBOX_LLM_HOST` is read from the environment; both `orchestrate.sh` and `sandbox-run.sh` default it to `host.containers.internal` independently. When the orchestrator drives the run, its exported value is inherited by the container launcher; run standalone, `sandbox-run.sh` supplies its own default. The orchestrator does not hard-code the address — it reads the variable set upstream.

**Alternatives considered:**
- (a) Always run inside the sandbox, no fallback — breaks for developers without Podman
- (b) Hard-code `host.containers.internal` directly in `orchestrate.sh` — duplicates the address assumption that step 0 is supposed to prove
- (c) No sandbox path — forfeits container isolation

**Reason:** The `SANDBOX=1` env var is a single indirection point. Defaulting to `SANDBOX=0` preserves the existing non-sandbox workflow for development. The sandbox path delegates entirely to `sandbox-run.sh`, which is the single script that manages Podman flags, volume mounts, and the LLM host address. The orchestrator only knows `host.containers.internal` via the env var chain, not as a literal.

**Do not suggest:** Hard-coding `host.containers.internal` in `orchestrate.sh`; removing the `SANDBOX=0` fallback; adding a second sandboxing mechanism.

---

## 2026-06-06 — macOS Compatibility Fixes for Sandbox Scripts

**Decision:** `scripts/sandbox-run.sh` and `scripts/orchestrate.sh` use `pwd -P` instead of `pwd` to resolve macOS `/tmp` → `/private/tmp` symlink for Podman bind-mount path matching. `sandbox-run.sh` uses Podman's built-in `--timeout` flag instead of external `timeout(1)` (which does not exist on macOS). `orchestrate.sh` detects `gtimeout` (macOS, from `brew install coreutils`) vs `timeout` (Linux) for its script-level agent timeout.

**Alternatives considered:**
- (a) Install coreutils on macOS and alias `timeout` — requires every macOS dev to opt in
- (b) Skip timeout entirely on macOS — agents hang indefinitely
- (c) Use Podman's `--timeout` only (already present) and skip the script-level wrapper — the wrapper is needed for the non-sandbox path and as a belt-and-suspenders guard

**Reason:** macOS is the primary development platform (verified by `uname`). The `/tmp` symlink (`/tmp` → `/private/tmp`) causes Podman bind-mount failures because the container resolves the physical path differently than the host. External `timeout(1)` is a Linux-only command. Podman's `--timeout` flag works on both platforms and replaces it. The `gtimeout`/`timeout` detection on the orchestrator's non-sandbox path follows the same pattern as the project's other platform-detection logic.

**Do not suggest:** Removing macOS support; switching to a Linux-only requirement; wrapping `timeout` in a shell function that fails silently.

---

## 2026-06-06 — Agent Permission Model: No Catch-All Deny

**Decision:** The test agent's `edit` permission uses explicit `src/**": "deny"` and `tests/**": "allow"` with no `**": "deny"` catch-all. The catch-all overrode the specific allow because `**` matches `tests/` paths. Build agent keeps `tests/**": "deny"` with `**": "allow"` as its catch-all — reversed logic because build's allowed set (everything except tests) is too broad to enumerate.

**Alternatives considered:**
- (a) Keep `**": "deny"` and list every non-test directory explicitly — brittle, misses new directories
- (b) Use `--dangerously-skip-permissions` server-side — bypasses the entire permission model
- (c) Single agent with no role separation — violates INV-2

**Reason:** Explicit + allow with no deny catch-all is the simplest permission config that lets the test agent write files. OpenCode's permission engine applies matching deny rules regardless of specificity — a `**`: deny always catches `tests/` paths. Removing the catch-all fixes this at the config level.

**Do not suggest:** Re-adding `**": "deny"` to the test agent; adding `--dangerously-skip-permissions` as a permanent fix.

---

## 2026-06-06 — Local Model Tier: Qwen3.6-35B-A3B for Build/Test

**Decision:** Build and test agents default to `lms/qwen/qwen3.6-35b-a3b` (35B parameters, 3B active). The 7B `qwen3-coder-next` model produces malformed tool calls (omits required fields like `filePath` and `content` from the Write tool) and is removed from any file-writing role. PM and architect agents remain on `[FRONTIER_MODEL]` per the cost-tier design.

**Alternatives considered:**
- (a) Run all agents on frontier models — higher cost, negates local-tier savings
- (b) Wait for better 7B tool-calling support — uncertain timeline
- (c) Use Gemma-4-31B — not tested, but 35B Qwen writes files correctly

**Reason:** The 35B model is the smallest local model found that reliably constructs valid OpenCode tool calls. It writes files, installs dependencies, and passes gates. The two-tier cost model (frontier for planning, local for build/test) is preserved — the threshold is 35B, not 7B.

**Do not suggest:** Reverting build/test to the 7B model; running build/test on frontier models permanently.

---

## 2026-06-07 — Pipeline robustness fixes (container deps, PYTHONPATH, gate recovery)

**Decision:** Bake `fastapi uvicorn httpx pydantic` into Containerfile, add `PYTHONPATH=/work` to sandbox-run.sh, soften gate violations from hard-halt to cleanup+continue, and add `pip install` fallback before pytest.

**Alternatives considered:** Installing via `pip install --user` at runtime (fails — user site-packages not on Python search path), installing via build agent (lost on container exit), mounting host `site-packages` (fragile).

**Reason:** Non-root `agent` user (UID 1000) has no sudo and `pip install --user` drops to `~/.local/lib/python3.12/site-packages/` which Python does not search by default. The 35B model sometimes writes tests during build phase despite explicit prompts — cleanup+continue is more productive than halting. `pip install` before pytest ensures deps survive container rebuilds.

**Do not suggest:** Installing deps via the build agent (agent runs in disposable container, install lost on exit). Hard-halting on gate violations (35B model needs graceful recovery). Removing `PYTHONPATH` (required for `from src.main import app`).

---

> Add new decisions above this line, newest first.
