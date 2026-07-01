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

## D-34 — 2026-07-01 — Template propagation: update-template.sh (the refreeze pattern, applied to the control plane)

**Decision:** Children pull control-plane improvements with `scripts/update-template.sh`: it resolves the template (a local clone via `--from`, or `gh repo clone` of the `.template-version` slug), takes the file list from the **template's** `.manifest-template` at the target ref (so files added upstream flow in), shows the human one aggregate diff, requires an interactive y/N (`--dry-run` to inspect without a tty), applies contents **and exec bits**, installs the template's manifest verbatim, advances `ref=` in `.template-version`, regenerates `.manifest-project`, runs the integrity gate as a post-apply check, and commits `[template-update <sha>]`. Files removed upstream are reported for manual deletion, never auto-deleted. `--stamp` mode retrofits a pre-D-33 child (writes `ref=` only). Same protected-artifact protocol as D-31: staged delta → human diff-approval → hash re-pin → versioned commit.

**Alternatives considered:** (a) Generalize `refreeze.sh` into one approve-delta engine serving both spec and control plane — considered and rejected: the two flows share only the approval UX (~40 lines); everything else differs (staging source, validation steps — INV-4 and node-id collection are spec-only — and post-apply actions). A forced common engine is parameter soup; a shared *pattern* with two small tools is cheaper to hold. Revisit only if a third protected-artifact class appears. (b) git subtree/submodule for `scripts/` — Tier 3 machinery; see D-35 for the trigger. (c) Auto-apply in CI — propagation into a child is a human-approved act, same reasoning as D-31.

**Reason:** This closes the documented incident class directly: the Rule 8 fix that lived only in spark until hand-ported becomes `update-template.sh` + one y. Detection (D-33) says *that* you're behind; this is *how* you catch up, with the same fail-closed integrity guarantees as every other protected write.

**Do not suggest:** Auto-applying template updates. Letting the tool delete files. Running it inside the template repo (it refuses).

---

## D-33 — 2026-07-01 — Fleet drift: birth-SHA identity, ownership-split manifests, drift detection

**Decision:** Three pieces. (1) **Birth-SHA**: `.template-version` records `repo=` (template slug) and `ref=` (template HEAD SHA at instantiation, stamped by `bootstrap.sh`, retrofittable via `update-template.sh --stamp`); `gh repo create --template` leaves no upstream link, so this is the only moment fleet identity can be captured. (2) **Ownership split**: the control-plane manifest becomes `scripts/.manifest-template` (template-owned logic — gates, orchestrator, validators, schemas, prompts, hooks, drift tooling) and `scripts/.manifest-project` (per-project adaptations under Rule 3 — `.gate-paths`, `opencode.json`, `Containerfile`, `ci.yml`, the doc layer). phase-gate verifies both, fail-closed; drift is computed over exactly the template list, so a Rule 3 adaptation is never a false positive. One-shot setup scripts are deliberately unlisted: children delete them at instantiation, and the read-only mounts (D-30) already cover them. (3) **Detection**: `scripts/check-drift.sh` does a three-way compare per template-owned file (child vs template@birth vs template@HEAD) → IN_SYNC / BEHIND (exit 2, CI warns) / LOCALLY_MODIFIED, MISSING_IN_CHILD, CHILD_ONLY (exit 1, CI fails); `.github/workflows/check-drift.yml` runs it on push and weekly, skipping itself in the template repo and unstamped children.

**Alternatives considered:** (a) No fleet story — the documented failure: the Rule 8 fix lived only in spark until hand-ported. (b) One mixed manifest plus a separate drift-file list — two lists drift from each other; ownership belongs in the manifest itself. (c) Auto-sync on drift — propagation is a human-approved act (D-34); detection and propagation stay separate so CI never rewrites a child.

**Reason:** Drift you cannot compute is drift you discover in production. The birth-SHA is cheap now and unrecoverable later; the split makes "adapted" and "drifted" mechanically distinguishable; the CI job makes a quiet child hear the template move.

**Do not suggest:** Auto-applying template changes in CI. Putting template-owned files in `.manifest-project` to silence a drift failure — that is the drift, formalized.

---

## D-32 — 2026-07-01 — INV-4: test-visible surface ⊆ ERD-locked surface (lowest-confidence gate)

**Decision:** New invariant, same class as INV-1/2/3. Whatever the frozen tests observe is de-facto locked, whether or not the ERD meant to lock it — so the two locks are kept aligned mechanically: `scripts/check-test-surface.py` statically checks that tests import only `contracts.entry_points` entries (`module` or `module:symbol`) and exercise only declared `contracts.routes` path templates (segment-wise match, `{param}` wildcards). It runs inside `scripts/refreeze.sh` on the merged preview (current frozen tests + incoming delta), BEFORE the human approval prompt — a TPM test that reaches past the contracts is rejected before it can be frozen, and before it can silently shrink the EM's design space.

**Confidence flag — read this before trusting it:** this is the **lowest-confidence mechanism in the gate set**, and deliberately so. It is a grep-level static check (regex on imports and client-verb calls), in the same spirit as INV-3's grep. It catches the accident class — the test author is a frontier model following instructions, not an adversary — and does not catch dynamic imports, computed paths, or indirect observation. Tighten it from incidents per the correction-log habit; do not pre-harden speculatively.

**Alternatives considered:** (a) No check — the seam rule ("TPM locks contracts, EM owns the rest") becomes decoration the first time a test asserts on an internal. (b) AST-based analysis or import-hook enforcement at test runtime — heavier machinery than the failure class justifies today; adopt only after the crude check demonstrably misses real incidents. (c) Generating test fixtures from contracts so tests physically cannot reach elsewhere — the strongest form; noted as the escalation path if (b)'s trigger fires.

**Reason:** INV-4 is what makes the seam rule real: the EM owns everything inside the locked surface only if nothing outside the contracts can fail a build.

**Do not suggest:** Treating INV-4 as a security boundary. Loosening it by allow-listing individual violations instead of locking the surface properly in contracts.json.

---

## D-31 — 2026-07-01 — Versioned re-freeze: frozen spec changes only via human-approved delta

**Decision:** The TPM's artifacts (PRD.md, ERD.md, contracts.json in `scripts/.approved/`; the test suite in `tests/`) are hash-pinned by `scripts/.approved/frozen-manifest` and verified by **every** phase-gate run, fail-closed. They change through exactly one path: `scripts/refreeze.sh`. The operator stages the TPM's delta (full new content of only the changed files) under `scripts/.approved/incoming/`; refreeze shows the human the complete diff, requires an interactive y/N (this diff-approval IS the approval gate — it also replaces the old `Status: Approved` honor-string for the initial freeze), applies, re-collects test node-ids in the sandbox, writes `DELTA-vN.json` (changed contract ids + changed/removed test node-ids), bumps `VERSION`, regenerates the frozen-manifest, and commits `[refreeze vN]`. On the next run the orchestrator resumes **only the affected subtree**: the stale plan is re-derived by the EM, unchanged task entries keep their done status via fingerprints, and `validate-plan.py --affected DELTA-vN.json` additionally resets tasks whose mapped test content changed under an unchanged entry (plus transitive dependents). Escalated/blocked tasks get a fresh chance under the new spec.

**Alternatives considered:** (a) Frozen-forever spec — the repo's own history shows what boxed-in agents do against an unsatisfiable oracle (a gate was once quietly weakened to force a pass); wrongness needs a protocol, not a workaround. (b) Silently mutable spec — the pre-D-08 freeze-trap failure, where a re-plan architect overwrote the approved contract. (c) Approval recorded as a status string an agent can write — the original LOW-severity hole; an interactive tty prompt on a diff is not agent-forgeable through any lane. (d) Full re-run after every delta — wastes the completed subtree; the delta file exists precisely to compute the minimal reset.

**Reason:** This threads both historical failure modes: no silent mutation (agents physically cannot write the frozen artifacts — D-30 mounts + manifest check), and no dogmatic freeze (a bounded, versioned, human-approved revision path exists, and the `[refreeze vN]` commit is the durable record of every TPM round-trip).

**Do not suggest:** Letting any agent stage or apply a delta. Skipping the interactive prompt for "trivial" deltas. Editing files under `scripts/.approved/` or `tests/` directly — the next gate run fails closed on the manifest.

---

## D-30 — 2026-07-01 — Sandbox flip: read-only repo + per-lane rw mounts; pre-commit hook for the human path

**Decision:** `scripts/sandbox-run.sh` mounts the repo **read-only** and grants write access per-lane via `--rw <relpath>` (coder: build lane only; EM: `tasks/` only; test runs and smoke checks: `.cache/` only or nothing). `--rw` refuses `scripts/`, `.git/`, and `.githooks/` unconditionally — the control plane is never agent-writable. The agent user's HOME moves to a container tmpfs (OpenCode/pip session data must not live in the read-only repo). For the interactive/human entry point, `.githooks/pre-commit` enforces the active pipeline phase (from `.pipeline-state/phase` + `task_target`) and always verifies the control-plane manifest and the frozen spec; `bootstrap.sh` sets `core.hooksPath=.githooks`.

**Alternatives considered:** (a) Keep the whole-repo rw mount and rely on phase-gate detection — a prior external review demonstrated a one-phase gate-neutralization: an agent could rewrite `phase-gate.sh` plus the manifest inside its phase, and the post-phase check would execute the compromised gate. Detection-after loses to a writable detector. (b) Per-file rw mounts for the coder — Podman bind-mount granularity makes single-file mounts brittle for files that don't exist yet; lane-level mount + the `task` gate's exactly-one-file check gives the same guarantee. (c) Overlay/copy-on-write sandboxes — heavier machinery for the same property.

**Reason:** Prevention beats detection where prevention is one flag. INV-2 violations and gate-tampering become physically impossible on the orchestrated path; the gate remains as backstop for the path mounts cannot cover (a human driving directly). The control-plane manifest finally has its out-of-band anchor: the only writers of `scripts/` are the human and CI.

**Do not suggest:** Re-widening the mount to the whole repo for agent convenience. Allowing `--rw scripts/...` for any phase. Removing phase-gate because the mounts "already handle it" — the hook path and defense-in-depth are why it stays.

---

## D-29 — 2026-07-01 — Escalation ladder with batched, filesystem-only TPM round-trips

**Decision:** Escalation is a shell-owned ladder with every counter in `.pipeline-state/`: task retry (strike 1, failure evidence appended to the same brief) → EM consult at two strikes (schema-bound verdict) → `brief_wrong` (revised brief, max 2 per task) → `decomposition_wrong` (plan re-emit, re-validated, max 2 per run) → `contract_or_test_wrong` / caps exhausted / spec drift → **batched TPM bundle** → human applies the TPM's delta via `scripts/refreeze.sh` → affected subtree resumes. PRD-ambiguity escalates from the TPM to the CEO in chat. Because the TPM is a human-operated web chat (not a callable service), the shell packages each escalation as a self-contained copy-pasteable bundle (`.pipeline-state/escalations/<id>/bundle.md`, aggregated into `BATCH.md`), keeps driving every independent subtree to its own stopping point first, and halts exactly once with exit code 2. Format: `docs/ESCALATION.md`.

**Alternatives considered:** (a) Halt-and-ping on first escalation — one browser round-trip per defect; with N independent seam problems that is N round-trips instead of 1. (b) An API integration to the frontier model — assumes a service the operator does not run; the filesystem is the only integration that exists. (c) Let the EM decide when to escalate — escalation is procedure, and procedure is shell-owned (D-26).

**Reason:** Judgment escalates exactly one tier per rung, every rung is bounded, and the expensive rung (human + frontier) is batched. The bundle must be self-contained (task entry, evidence, EM diagnosis, referenced contract entries, failing frozen-test sources) because the TPM has no repo access.

**Do not suggest:** Escalating straight to the TPM without an EM diagnosis (the diagnosis is what makes the bundle actionable). Unbounded brief revisions. Letting an agent write into `.pipeline-state/escalations/`.

---

## D-28 — 2026-07-01 — Oracle projection: EM schedules frozen TPM tests, authors nothing

**Decision:** Test authorship lives at the TPM tier, frozen via re-freeze (D-31). The per-task acceptance signal of the hot loop is a **projection** of that frozen oracle: each plan task lists the frozen test node-ids expected to pass once it and its dependencies are done. The EM schedules tests onto tasks; it never authors acceptance. The plan gate enforces the mapping is total and exactly-once. Feature completion has exactly one definition: the FULL frozen suite green. The case "every task passed its projection but the full suite is red" is mechanically detected as **spec drift** and routes EM→TPM (decomposition fix or spec delta) — never to coder retries. Tasks with no covering test carry an explicitly non-oracular `smoke_check`; the validator rejects tasks with neither.

**Alternatives considered:** (a) EM authors per-task acceptance checks — re-creates oracle-authorship at the mid tier, the exact hole this redesign exists to close (the green signal must not be authored below the judgment tier). (b) Run the full suite after every task — most failures would be absent-dependency noise, drowning the real signal. (c) No per-task signal, only the final suite — failure attribution collapses; every defect surfaces at integration.

**Reason:** The working oracle of the loop and the truth oracle are the same artifact viewed through a schedule, so they cannot drift in content — only in scheduling, which the exactly-once mapping check and the drift signal both catch mechanically. INV-1 ("tests derive from the spec, not the code") is now structural rather than advisory: the tests are written before the code exists, by a tier that never sees the implementation, and no agent can edit them.

**Do not suggest:** Letting any agent author or edit tests. Treating a task's mapped-tests-green as feature-done. Routing a spec-drift signal to the coder.

---

## D-27 — 2026-07-01 — Capability ladder: TPM (web-chat frontier) / EM (mid-tier) / coder (local); test-runner agent deleted

**Decision:** The four-role pipeline (pm/architect/build/test agents) is replaced by a capability ladder matched to task type. **CEO** (human): business intent. **TPM** (frontier LLM in a human-operated web chat, outside OpenCode): PRD, ERD with machine-readable contracts, and the test suite — the smallest, highest-leverage artifacts — installed and frozen via `scripts/refreeze.sh`. **EM** (mid-tier free online LLM, OpenCode agent `em`): decomposition and diagnosis only, per D-26. **Coder** (local LLM, OpenCode agent `coder`): one file per task, pure execution. The pm/architect/build/test prompts and the test agent are deleted; tests are RUN by the orchestrator via `pytest --json-report` — a shell command needs no agent wrapped around it (Rule 5: an LLM whose job is to run a command and describe the output can only add error).

**Alternatives considered:** (a) Keep architect as a local agent — decomposition against locked seams is mid-tier work, but plan-sized judgment (contracts, tests) is not; splitting TPM/EM matches each artifact to the cheapest tier that can own it. (b) Keep a test agent to run pytest — deleted for the Rule 5 reason above. (c) All-frontier — forfeits the cost model; the ladder exists to spend frontier tokens only on spec/contract/test artifacts and escalation deltas.

**Reason:** Frontier pays per token and never stops; local is a fixed cost trending better. The ladder bets on that trendline while keeping every load-bearing artifact (contracts, tests) at the judgment tier and every procedure in shell. The seam rule: the TPM locks cross-component contracts (cheap for it, catastrophic when wrong below); the EM owns everything inside them.

**Do not suggest:** Re-adding a test-authoring or test-running agent. Giving the EM a write lane beyond `tasks/`. Calling the TPM programmatically (it is a human-operated chat; see D-29).

---

## D-26 — 2026-07-01 — Schema-validated artifact handoffs; plan.json validation gate

**Decision:** Every inter-tier handoff is a schema-validated artifact on disk; the shell orchestrator is the only actor with procedural authority. The EM's sole channel of authority is `tasks/plan.json` (schema: `scripts/schemas/plan.schema.json`), mechanically validated by `scripts/validate-plan.py` before any coder runs: one file per task and one task per file (structural atomicity), acyclic DAG, exact bijection with the frozen ERD file inventory, every frozen test node-id mapped to exactly one task, every referenced contract id present in the frozen contracts, plan freshness against `scripts/.approved/VERSION`. The plan carries **no status field** — the validator rejects one. Task status, ordering, completion, and escalation counters live in `.pipeline-state/`, owned by the shell. EM consult responses are likewise schema-bound (`scripts/schemas/diagnosis.schema.json`, verdict enum `brief_wrong | decomposition_wrong | contract_or_test_wrong`).

**Alternatives considered:** (a) EM reports decomposition and progress conversationally, orchestrator parses prose — trusts narration, the exact failure class this project exists to reject. (b) EM drives the loop itself and self-reports completion — re-creates the pre-D-05 failure (LLM forgets gates, miscounts strikes) one tier up. (c) Full `jsonschema` dependency — validator is stdlib-only (`json`/`hashlib`) to match the orchestrator's existing pre-flight contract.

**Reason:** A bad decomposition must fail loudly at validation time, not surface three phases later as an integration error. This is D-05 (deterministic shell owns procedure) applied uniformly: LLMs produce content, shell computes everything computable — so the EM's residual authority is exactly the content of its decomposition and diagnoses, nothing procedural.

**Do not suggest:** Adding a status/progress field to plan.json for the EM to maintain. Letting any agent update `.pipeline-state/`. Parsing EM free-text instead of the diagnosis schema.

---

## D-25 — 2026-06-26 — INV-3: Decision traceability gate (Adoption 3)

**Decision:** Every non-documentation decision in DECISIONS.md (tagged with a D-NN ID) MUST appear in ARCHITECTURE.md. The architect→build handoff is mechanically blocked by `scripts/phase-gate.sh architect` — the gate greps ARCHITECTURE.md for each D-ID and exits non-zero if any are missing. Documentation-only decisions are exempted via a `**Documentation-only:**` marker in the decision body.

**Rationale:** This is INV-3, same class as INV-1 and INV-2 — a mechanical, blocking gate. It closes the gap where an architect could make a decision in DECISIONS.md that never reaches the build agent (ARCHITECTURE.md is the build agent's source of truth). The grep is intentionally simple — no manifest, no registry, just string matching. This keeps the ceremony low enough that the gate is a net time-saver (catches forgotten updates) rather than a tax.

**Alternatives considered:** (a) A separate decision-manifest file — extra indirection, more things to keep in sync. (b) Requiring D-IDs in the build prompt verbatim — over-constrained, the prompt already references ARCHITECTURE.md. (c) No gate, rely on architect discipline — advisory only, contradicts the project's mechanical-gate philosophy.

**Do not suggest:** Central registry of D-IDs (the headings ARE the registry). Making the gate check for coverage in the build prompt instead of ARCHITECTURE.md.

---

## D-24 — 2026-06-26 — File-based pipeline state persistence (Adoption 2)

**Decision:** All pipeline loop state (iteration count, re-plan count, failure signature, repeat counter, current phase) is written to `.pipeline-state/` files before each agent phase. On crash, the orchestrator resumes by reading these files. `.pipeline-state/` is gitignored — runtime diagnostics only.

**Alternatives considered:** (a) Pass state via git commit messages and re-parse them — fragile, human-hostile format. (b) Store in environment variables passed to a supervisor — doesn't survive container restart. (c) Ephemeral shell variables (current design) — lost on crash.

**Reason:** A crash mid-loop (Podman OOM, network drop, host reboot) currently loses all state. The state file is a single checkpoint written BEFORE each phase, surviving anything short of `rm -rf .pipeline-state/`. Also the foundation for the OpenHands port, where the orchestrator will be an LLM agent that reads/writes files instead of shell variables.

**Do not suggest:** Version-controlling `.pipeline-state/` (ephemeral diagnostic data). Using a database, Redis, or any networked state store. Writing state after the phase (loses info on crash mid-phase).

---

## D-23 — 2026-06-26 — Fresh context per task (Adoption 1)

**Documentation-only:** This decision documents a design principle already satisfied by the shell-orchestrator architecture.

**Decision:** The orchestrator MUST spawn each build and test task in a clean context window. State transfers between tasks via structured files on disk, never via conversation history.

**How the shell orchestrator satisfies this:** `scripts/orchestrate.sh` wraps each agent phase in a separate `opencode run --attach --agent <name>` invocation (line 79-81). Each invocation starts fresh. The orchestrator itself is a shell script — no LLM context to rot.

**Target for OpenHands port:** When the orchestrator becomes an LLM agent, the coordinator loop must stay under 40% of its context budget.

**Do not suggest:** Passing state between phases as part of the agent prompt. Merging the orchestrator loop into a single agent context window.

---

## [DATE] — [Your first decision here]

**Decision:** [e.g. Using raw SQL over ORM]
**Alternatives considered:** [e.g. SQLAlchemy, Tortoise ORM]
**Reason:** [e.g. Query complexity made ORM unreadable for our join-heavy patterns]
**Do not suggest:** Switching to an ORM. This was deliberate.

---

## [DATE] — Monorepo structure (template placeholder — skip D-ID assignment)

**Decision:** Single repository for all services.
**Alternatives considered:** Separate repos per service.
**Reason:** Team size doesn't justify the overhead of managing multiple repos. Shared code is easier to refactor.
**Do not suggest:** Splitting into microservices repos until team grows past 5 engineers.

---

## D-01 — 2026-06-04 — Pruned BLUEPRINT.md (557 → ~440 lines)

**Decision:** Apply the noise/redundancy findings from a parallel LLM audit; skip the lifecycle/strategy findings from a second LLM.
**Documentation-only:** This decision documents a doc-pruning action; it does not change the API or build plan.
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

## D-02 — 2026-06-04 — Auto-load assumption corrected; CLAUDE.md / opencode.json fixes

**Decision:** (a) Rewrite `CLAUDE.md`'s intro to accurately describe its load behavior — file is *fetchable via tools*, not pre-loaded; the LLM is *expected* to read it. (b) Fix the project's `opencode.json` schema (OpenCode 1.15.13 rejects the old `providers` / top-level `models` form with "Unrecognized keys"). The original commit also added a "do not re-add dropped BLUEPRINT.md sections" mirror guard to `CLAUDE.md`; that mirror was later removed (see entry below) for template-hygiene reasons.

**Documentation-only:** This decision documents a measurement and fix to doc guards and config; it does not change the API or build plan.

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

## D-03 — 2026-06-04 — Removed CLAUDE.md mirror guard (decoupling template from project)

**Decision:** Remove the one-line "Do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune" guard from `CLAUDE.md`'s "What NOT To Do" → Operating guardrails. The rule still lives in `DECISIONS.md` → "Pruned BLUEPRINT.md" entry.

**Documentation-only:** This decision documents a doc decoupling action; it does not change the API or build plan.

**Reason:** CLAUDE.md is a template — `[PROJECT_NAME]` is still a placeholder. Baking a project-specific date ("2026-06-04 prune") into a template file makes the rule meaningless for any future project created from this template. The visibility argument was real but the template-vs-project boundary was muddied. The principle (don't re-add dropped sections) stays binding via DECISIONS.md's "Do not suggest" line and the correction log capture.

**Do not suggest:** Re-adding the mirror guard. Cross-reference, don't copy.

---

## D-04 — 2026-06-06 — Demoted BLUEPRINT.md line-count gate to heuristic

**Decision:** Removed the failing `wc -l BLUEPRINT.md <= 450` check from CI and the correction log's hard-target language. The 450 number was self-imposed by the model during a pruning session, never a human requirement. Line count is a proxy that does not measure the real goal (no redundant/ambiguous content). Enforcement is replaced with a heuristic note at the bottom of BLUEPRINT.md.

**Documentation-only:** This decision documents a CI gate change; it does not change the API or build plan.

**Reason:** Enforcing a specific line count as a CI failure pressures edits to delete real content — including safety rules — to stay green. A mechanical gate is right for binary invariants (INV-2, placeholder completeness), wrong for a judgment call like doc leanness. The anti-bloat principle is genuine (BLUEPRINT is the LLM's entry point; redundancy is token cost and ambiguity risk), but enforcement should be human review and cross-reference discipline, not a numeric gate.

**Do not suggest:** Re-adding a failing line-count check, or compressing rules to hit a number. The "do not re-add pruned sections" guards in DECISIONS.md and human review are the correct mechanisms — they target redundancy directly.

---

## D-05 — 2026-06-06 — Code-driven orchestration loop

**Decision:** Moved loop control out of `architect.md` (where an LLM must remember to run the gate, read the test report, count strikes, and route) and into `scripts/orchestrate.sh`. The orchestrator is a shell script that drives the build→test loop deterministically: it starts a headless `opencode serve`, calls each agent via `opencode run --attach --agent <name>`, runs `scripts/phase-gate.sh` after each phase, parses the JSON test report via `python3 -c`, computes a `sha1(sorted(failing_node_ids))` signature for two-strike detection, and escalates to re-plan on identical failure signatures. The architect prompt shrinks to "produce/refresh the plan only."

**Reason:** Loop control in an LLM prompt is a doc-guard — the architect could forget to run the gate, mis-count strikes, or skip escalation. Moving it to a script makes the gate invocation, the two-strike counter, and the halt deterministic — each is a line of shell code, not a remembered instruction. Additionally, each scoped `opencode run` sidesteps the non-transitive-permission bug (each agent runs in its own invocation with its own permissions) and prevents context bloat over long loops. The script wraps each agent call in a `run_agent` function that is the single indirection point for future sandbox adoption.

**Do not suggest:** Putting orchestration logic back into `architect.md`, or auto-approving the PRD (the orchestrator refuses to run unless `Status: Approved`). Adding a queue, daemon, web UI, or multi-feature scheduling — one approved PRD, one run. Replacing the shell script with an orchestration framework (adopt OpenHands later if needed — note it in DECISIONS, don't pre-build for it).

**Server details (for posterity, empirically verified on OpenCode 1.15.13):**
- `opencode serve --port <n>` starts a headless server; default port is 0 (random), use `--port` explicitly.
- `opencode run --attach <url> --agent <name> <prompt>` calls a specific agent on the running server.
- Server is killed on script exit via `trap cleanup EXIT`.

---

## D-06 — 2026-06-06 — Adopted EARS for acceptance criteria

**Decision:** Acceptance criteria in `tasks/CURRENT.md` are now written in EARS notation (THE SYSTEM SHALL / WHEN...SHALL / WHILE...SHALL / IF...THEN SHALL / WHERE...SHALL). Each criterion is a single observable clause that maps one-to-one to a test case. The PM prompt enforces this at PRD time; the test prompt reinforces the mapping at test time. Template examples in CURRENT.md demonstrate all five forms plus an HTML-comment reference guide.

**Reason:** EARS forces each requirement into a single testable clause, giving the test agent an unambiguous oracle and tightening INV-1 enforcement. Vague prose criteria ("handles errors gracefully", "works correctly") were the weak point — the tester had to interpret intent, which reintroduces the ambiguity the pipeline was designed to eliminate. A one-clause-to-one-test mapping makes the test agent's job mechanical and removes the interpretation gap.

**Do not suggest:** Reverting to free-form prose criteria, or forcing all five EARS forms when a single SHALL clause suffices (avoid ceremony — see the repo's anti-over-engineering history, BLUEPRINT.md and DECISIONS.md prune entries).

---

## D-07 — 2026-06-06 — Four-role PRD→Plan→Build→Test pipeline

**Decision:** Adopted a four-role pipeline (PM, Architect, Build, Test) with two non-negotiable invariants: INV-1 (tests derive from the PRD, never from `src/` implementation) and INV-2 (Build never edits `tests/`; Test never edits `src/`). The PRD in `tasks/CURRENT.md` is the single oracle — the human's casual instruction is translated into structured acceptance criteria and flagged assumptions, then frozen on Approval. The Architect is also the orchestrator: it delegates build→test, runs `scripts/phase-gate.sh` after each phase, reads `.cache/test-report.json`, and routes failures per Rule 2/7 (build bug→build, same failure twice→re-plan, plan fails twice→PM).

**Alternatives considered:** (a) Extend the existing single-agent loop with role instructions in CLAUDE.md; (b) use OpenCode agent permissions alone for INV-2 enforcement; (c) keep the flat loop and add no roles.

**Reason:** A single-agent loop conflates planning, writing, and testing in one context — the model's self-judgment replaces the test-report oracle (Rule 5 drift) and nothing prevents it from writing tests that confirm what `src/` does rather than what the spec says (INV-1 violation). Separate roles with frozen contracts force the verification gap that catches bugs. OpenCode's agent permissions (`permission.edit` globs) are non-transitive — a restricted agent can bypass limits via the Task tool (opencode issues #12566, #20549) — so INV-2 is enforced mechanically by `scripts/phase-gate.sh`, not by permissions alone. Doc guards catch intent; mechanical gates catch the result (documented pattern from the 2026-06-04 auto-load entry). Cost rationale: build/test use the local model (free, 80% of tasks); pm/architect use frontier for reasoning walls and spec work.

**Do not suggest:** Letting the test agent read `src/` implementation to author tests (INV-1). Enforcing INV-2 with agent permissions alone — the git gate is the binding layer. Merging the four roles back into a single agent — the whole point is the verification gap between them. Letting the build or test agent edit the PRD or architecture docs.

---

## D-08 — 2026-06-09 — AC9 compliance: mandatory sandbox + freeze trap closure

**Decision:** Two changes for temp PM review compliance:

1. **AC9 (no sandbox override):** Removed the `I_UNDERSTAND_UNSANDBOXED` override entirely. `orchestrate.sh` now fails immediately if `SANDBOX != 1` — no fallback path, no debug flag. Containerized execution is mandatory.
2. **Freeze trap (P3 fix):** Moved `ARCHITECTURE.approved.md` from `docs/` (architect's writable lane) to `scripts/.approved/` (outside every agent's whitelisted directory). The orchestrator creates the directory and copies the file after the architect gate passes; no agent can touch it.

**Reason:** The frozen AC9 criterion specified no env var or flag that disables containerized execution. The `I_UNDERSTAND_UNSANDBOXED` override existed as a conversational suggestion from the PM during code review but violated the frozen spec. Debug frequency is low enough that the friction is negligible — strict compliance avoids the "advisory safety" pattern the project exists to reject. The freeze trap was exposed by an empirical test: a re-plan architect could and did overwrite `docs/ARCHITECTURE.approved.md` because `docs/` is the architect's permitted directory. Moving the file to `scripts/.approved/` makes the constraint structural (wrong lane) rather than rule-based (gate carve-out).

**Do not suggest:** Re-adding `I_UNDERSTAND_UNSANDBOXED` or any sandbox-disable flag. Moving `ARCHITECTURE.approved.md` back to `docs/`. Both were deliberate removals against verified defects.

---

## D-09 — 2026-06-06 — Sandbox Wiring in Orchestrator

**Decision:** `scripts/orchestrate.sh` routes agent calls and pytest through `scripts/sandbox-run.sh` when the `SANDBOX=1` environment variable is set. The sandbox path wraps each agent call with `timeout "${AGENT_TIMEOUT}"` (the container runs Debian where `timeout` is available from coreutils). The non-sandbox path uses `$TIMEOUT_CMD "${AGENT_TIMEOUT}"` (`gtimeout` on macOS, `timeout` on Linux). `SANDBOX_LLM_HOST` is read from the environment; both `orchestrate.sh` and `sandbox-run.sh` default it to `host.containers.internal` independently. When the orchestrator drives the run, its exported value is inherited by the container launcher; run standalone, `sandbox-run.sh` supplies its own default. The orchestrator does not hard-code the address — it reads the variable set upstream.

**Alternatives considered:**
- (a) Always run inside the sandbox, no fallback — breaks for developers without Podman
- (b) Hard-code `host.containers.internal` directly in `orchestrate.sh` — duplicates the address assumption that step 0 is supposed to prove
- (c) No sandbox path — forfeits container isolation

**Reason:** The `SANDBOX=1` env var is a single indirection point. Defaulting to `SANDBOX=0` preserves the existing non-sandbox workflow for development. The sandbox path delegates entirely to `sandbox-run.sh`, which is the single script that manages Podman flags, volume mounts, and the LLM host address. The orchestrator only knows `host.containers.internal` via the env var chain, not as a literal.

**Do not suggest:** Hard-coding `host.containers.internal` in `orchestrate.sh`; removing the `SANDBOX=0` fallback; adding a second sandboxing mechanism.

> **2026-06-09 correction:** The "SANDBOX=0 fallback" and "always run inside the sandbox" alternatives were revisited for AC9 compliance. The sandbox is now mandatory (no fallback). This decision entry is historical context; the current behavior is documented in the 2026-06-09 entry above.

---

## D-10 — 2026-06-06 — macOS Compatibility Fixes for Sandbox Scripts

**Decision:** `scripts/sandbox-run.sh` and `scripts/orchestrate.sh` use `pwd -P` instead of `pwd` to resolve macOS `/tmp` → `/private/tmp` symlink for Podman bind-mount path matching. `sandbox-run.sh` uses Podman's built-in `--timeout` flag instead of external `timeout(1)` (which does not exist on macOS). `orchestrate.sh` detects `gtimeout` (macOS, from `brew install coreutils`) vs `timeout` (Linux) for its script-level agent timeout.

**Alternatives considered:**
- (a) Install coreutils on macOS and alias `timeout` — requires every macOS dev to opt in
- (b) Skip timeout entirely on macOS — agents hang indefinitely
- (c) Use Podman's `--timeout` only (already present) and skip the script-level wrapper — the wrapper is needed for the non-sandbox path and as a belt-and-suspenders guard

**Reason:** macOS is the primary development platform (verified by `uname`). The `/tmp` symlink (`/tmp` → `/private/tmp`) causes Podman bind-mount failures because the container resolves the physical path differently than the host. External `timeout(1)` is a Linux-only command. Podman's `--timeout` flag works on both platforms and replaces it. The `gtimeout`/`timeout` detection on the orchestrator's non-sandbox path follows the same pattern as the project's other platform-detection logic.

**Do not suggest:** Removing macOS support; switching to a Linux-only requirement; wrapping `timeout` in a shell function that fails silently.

---

## D-11 — 2026-06-06 — Agent Permission Model: No Catch-All Deny

**Decision:** The test agent's `edit` permission uses explicit `src/**": "deny"` and `tests/**": "allow"` with no `**": "deny"` catch-all. The catch-all overrode the specific allow because `**` matches `tests/` paths. Build agent keeps `tests/**": "deny"` with `**": "allow"` as its catch-all — reversed logic because build's allowed set (everything except tests) is too broad to enumerate.

**Alternatives considered:**
- (a) Keep `**": "deny"` and list every non-test directory explicitly — brittle, misses new directories
- (b) Use `--dangerously-skip-permissions` server-side — bypasses the entire permission model
- (c) Single agent with no role separation — violates INV-2

**Reason:** Explicit + allow with no deny catch-all is the simplest permission config that lets the test agent write files. OpenCode's permission engine applies matching deny rules regardless of specificity — a `**`: deny always catches `tests/` paths. Removing the catch-all fixes this at the config level.

**Do not suggest:** Re-adding `**": "deny"` to the test agent; adding `--dangerously-skip-permissions` as a permanent fix.

---

## D-12 — 2026-06-06 — Local Model Tier: Qwen3.6-35B-A3B for Build/Test

**Decision:** Build and test agents default to `lms/qwen/qwen3.6-35b-a3b` (35B parameters, 3B active). The 7B `qwen3-coder-next` model produces malformed tool calls (omits required fields like `filePath` and `content` from the Write tool) and is removed from any file-writing role. PM and architect agents remain on `[FRONTIER_MODEL]` per the cost-tier design.

**Alternatives considered:**
- (a) Run all agents on frontier models — higher cost, negates local-tier savings
- (b) Wait for better 7B tool-calling support — uncertain timeline
- (c) Use Gemma-4-31B — not tested, but 35B Qwen writes files correctly

**Reason:** The 35B model is the smallest local model found that reliably constructs valid OpenCode tool calls. It writes files, installs dependencies, and passes gates. The two-tier cost model (frontier for planning, local for build/test) is preserved — the threshold is 35B, not 7B.

**Do not suggest:** Reverting build/test to the 7B model; running build/test on frontier models permanently.

---

## D-13 — 2026-06-07 — Pipeline robustness fixes (container deps, PYTHONPATH, gate recovery)

**Decision:** Bake `fastapi uvicorn httpx pydantic` into Containerfile, add `PYTHONPATH=/work` to sandbox-run.sh, soften gate violations from hard-halt to cleanup+continue, and add `pip install` fallback before pytest.

**Alternatives considered:** Installing via `pip install --user` at runtime (fails — user site-packages not on Python search path), installing via build agent (lost on container exit), mounting host `site-packages` (fragile).

**Reason:** Non-root `agent` user (UID 1000) has no sudo and `pip install --user` drops to `~/.local/lib/python3.12/site-packages/` which Python does not search by default. The 35B model sometimes writes tests during build phase despite explicit prompts — cleanup+continue is more productive than halting. `pip install` before pytest ensures deps survive container rebuilds.

**Do not suggest:** Installing deps via the build agent (agent runs in disposable container, install lost on exit). Hard-halting on gate violations (35B model needs graceful recovery). Removing `PYTHONPATH` (required for `from src.main import app`).

---

## D-14 — 2026-06-07 — Context window ceiling measurement and fix

**Decision:** Measured the largest 35B agent payload (test agent: `.opencode/prompts/test.md` ~721B + orchestrator instruction ~166B + opencode system preamble ~8000B). Total estimated at ~3000 tokens. Raised LM Studio context length for `qwen/qwen3.6-35b-a3b` from the 8192 default to 32768 (32K) — four orders of magnitude over the measured need, with generous headroom for conversation history. The model natively supports 262144 (`max_position_embeddings` confirmed via HuggingFace config). Lever used: context bump, not prompt trim — the prompts themselves are small; the ceiling was LM Studio's default.

**Reason:** The 35B model's default context window in LM Studio (8192) was too small for the combined system preamble + agent prompt + instruction, causing context-length errors in prior runs. The model supports 256K native; 32K is a comfortable operating point that leaves GPU memory headroom (35.16 GiB used, 128 GiB available on M5 Max).

**Also changed:** `developer.separateReasoningContentInAPI` in `~/.lmstudio/settings.json` from `true` to `false`. When `true`, Qwen models that have reasoning enabled return `content: ''` with output in `reasoning_content` — opencode reads `content` only, so the model was unusable. Merging reasoning into `content` (even with the `<think>` block) keeps the model functional. To fully disable thinking (no reasoning tokens wasted), toggle the "Think" switch off in LM Studio UI for this model.

**Do not suggest:** Lowering context below 32K; switching to the `-ud-mlx` variant for context reasons only (the regular model seats 32K comfortably); trimming the agent prompts (they are not the bottleneck).

---

## D-15 — 2026-06-07 — INV-2 gate: halt, not cleanup

**Decision:** Reverted the INV-2 gate handler in `scripts/orchestrate.sh` from cleanup+continue back to halt-and-flag (exit 1 with violation note in `tasks/CURRENT.md`). The prompt-hardening ("Write src/ only", "Write tests/ only") from the same commit was kept.

**Alternatives considered:** (a) Keep cleanup+continue — unblocks the run but silently swallows a boundary violation that should be visible. (b) Leave the gate as-is (soft-halt with inspection note but no exit) — same problem, different disguise.

**Reason:** A boundary violation (build wrote to `tests/` or test wrote to `src/`) is evidence that the model or instructions are wrong. That signal must stop the run and be recorded, not auto-swept. The halt is the enforcement; the gate (phase-gate.sh) is the detector. Cleaning up and continuing makes the violation invisible to the human keystone. The price of a halted run is the cost of INV-2 working correctly.

**Do not suggest:** Re-introducing cleanup+continue; treating a gate violation as a routine iteration failure rather than a process break.

---

## D-16 — 2026-06-07 — Model pin: qwen/qwen3.6-35b-a3b (base) as default

**Decision:** Standardize on `qwen/qwen3.6-35b-a3b` (base model, 8-bit MLX, 37.75 GB) as the local build/test agent model. The `-ud-mlx` variant exists at 21.66 GB (4-bit) as a lower-memory fallback. The `opencode.json` config already points to the base model — this entry confirms it as the deliberate choice, not an accidental default.

**Alternatives considered:** (a) `qwen3.6-35b-a3b-ud-mlx` — 4-bit quantized, 21.66 GB, faster load but slightly lower quality. (b) `qwen/qwen3-coder-next` — 80B, 44.86 GB, too large for routine agent calls. (c) `[FRONTIER_MODEL]` — reserved for pm/architect only.

**Reason:** The base model seated 32K context at 35.16 GiB on M5 Max (128 GB unified memory), leaving ~90 GB for other workloads. The MLX variant loads in 21.66 GB but introduces a different serving path (unsorted, unproven for this project). The base model is the one the prompts were written and validated for. The two-tier cost model (frontier for planning, local for build/test) is preserved with a line at 35B, not 7B.

**Do not suggest:** Switching to `-ud-mlx` as the default; running build/test on frontier models permanently; dropping below 35B for writing agents.

---

## D-17 — 2026-06-07 — Template deps: app packages baked into Containerfile

**Decision:** Keep `fastapi uvicorn httpx pydantic` baked into the Containerfile and `PYTHONPATH=/work` in `sandbox-run.sh` as template defaults. These are not validation-harness-only — they fix a universal bug: the non-root `agent` user (UID 1000) cannot `pip install --user` into system site-packages. Any FastAPI project in this template runs into the same failure.

**Alternatives considered:** (a) Remove baked deps, require every project to add its own via `requirements.txt` — every new project re-debugs the same user-site-packages issue. (b) Switch to root container user — defeats the isolation purpose. (c) Install via build agent at runtime — lost on container exit, which is why the orchestrator's `pip install` fallback exists on line 123.

**Reason:** The four packages cover the most common FastAPI stack. The `pip install` fallback in `orchestrate.sh` line 123 is now redundant and should be removed as a follow-up — the Containerfile guarantees the deps are present at build time. The `PYTHONPATH=/work` fix is similarly universal: without it, `from src.main import app` fails in the container regardless of project.

**Do not suggest:** Removing these deps from the Containerfile. Removing `PYTHONPATH=/work`. Both will cause the same failures for every new project and the fix will be re-discovered each time.

---

## D-18 — 2026-06-07 — 32K context as pinned default for local model

**Decision:** Confirmed the 32,768 token context length as the pinned operational setting for `qwen/qwen3.6-35b-a3b`. Measured the largest agent payload at ~3,000 tokens (test agent prompt + instruction + opencode system preamble). 32K provides 10x headroom for conversation history.

**Alternatives considered:** (a) 8,192 (LM Studio default) — caused context-length errors in prior runs. (b) 131,072 or 262,144 (model max) — unnecessary GPU memory consumption, model seats 32K at 35.16 GiB.

**Reason:** The model natively supports 262,144 tokens (`max_position_embeddings` confirmed via HuggingFace config). 32K is a comfortable operating point that leaves GPU memory headroom (35.16 GiB used across the available 128 GiB). No prompt trimming needed — the bottleneck was LM Studio's default.

**Do not suggest:** Lowering context below 32K; raising to 256K without a demonstrated need.

---

## D-19 — 2026-06-07 — docs/.pm-last-review: PM-owned ref marker

**Decision:** Introduced `docs/.pm-last-review` — a one-line file holding the last PM-reviewed commit hash. The build agent reads it at report time to scope its commit list; no agent writes or advances it. "Reviewed" means verified and accepted by the PM — not pushed, not agent-declared done. This is the same artifact-over-memory principle the project enforces on tests (PRD → tests, never src → tests), applied to reporting: the marker removes the retrieval failure (ref buried in chat), but the PM's source-side reconciliation remains the actual guarantee.

**Alternatives considered:** (a) Storing the ref in the build agent's session/context — proven unreliable, this entire fix is why. (b) Tagging the repo with each review — noisy and requires push permissions. (c) Reading the ref from a PM-API call — overengineered.

**Reason:** The previous design relied on the PM's ref persisting in conversation history across turns. It didn't. A file in the repo is persistent, versioned, and readable by tool calls. The PM advances it only after verifying the work. The file assists, it doesn't replace the human check.

**Do not suggest:** Any agent writing to this file; removing the PM's source-side reconciliation because the file exists.

## D-20 — 2026-06-07 — Advisory vs mechanical enforcement

**Decision:** Of the seven Operating Rules, only Rule 1 ("report against the tree") has a mechanical backstop — `docs/.pm-last-review` for the ref plus the PM's source-side reconciliation as the ultimate check. Rules 2–7 are advisory: they rely on PM review for enforcement and no agent workflow enforces them mechanically.

**Documentation-only:** This decision documents a process observation; it does not change the API or build plan.

**Reason:** Honest labeling prevents these rules from being mistaken for guarantees. The durable safeguard is the PM's verification, not the doc. Aspirational claims that a rule "prevents" or "ensures" something erode trust when inevitably violated.

**Do not suggest:** Claiming mechanical enforcement where none exists; adding commit-scope hooks or other automated enforcement without a separate PM decision.

---

## D-21 — 2026-06-07 — Operating Rules: rationale per rule

**Documentation-only:** This entry documents rationale for Operating Rules; it does not change the API or build plan.

**Rule 1 (report against the tree):** A hallucinated "6 commits" and an undisclosed model swap each cost a full PM review cycle to catch. The marker file makes the ref retrievable outside conversation history.

**Rule 2 (one commit, one concern):** A safety-rule change (gate halt→cleanup) was bundled with prompt edits and a pip fallback in a single commit, bypassing review. Bundling is how serious changes slip through.

**Rule 3 (stop-and-ask on constraint changes):** The gate soften was treated as routine de-blocking. Changing what happens on violation is a process decision, not a fix.

**Rule 4 (conditionals are checkpoints):** The `-ud-mlx` fallback was used silently despite its precondition (base model failure) never occurring. The swap was only caught in post-hoc review.

**Rule 5 (read the artifact):** A validation report was written from the build agent's chat summary, not from the committed artifact. The summary was less accurate than the file it described.

**Rule 6 ("detected" ≠ "enforced"):** A standalone gate-test result was placed under a live-run section, implying the pipeline enforced a boundary that was switched off at the time.

**Rule 7 (decide trivial calls):** A placement question (where in AGENTS.md to put the Reporting section) burned three turns when the PM had already stated "put it where process docs live." Re-asking after the principle is clear wastes cycles. Asking is not failure when correctness is at stake — that's the second clause of the rule.

---

## D-22 — 2026-06-07 — INV-2 gate: halt, not auto-clean (reaffirmed)

**Decision:** The INV-2 gate exits with code 1 on any boundary violation (build writes tests/, test writes src/). It does not auto-clean, retry, or continue. A boundary violation is a signal for the human keystone — evidence that the instruction or model is wrong — not noise to sweep.

**Reason reaffirmed after:** A prior session softened the gate to cleanup+continue, which silently swallowed violations. The build agent wrote to tests/ (correctly detecting), the gate auto-swept it, and the run continued as if nothing happened. That defeat is why the halt exists. The cost of a halted run is the cost of INV-2 working correctly.

**Do not suggest:** Re-softening to cleanup+continue without PM sign-off.

> Add new decisions above this line, newest first.
