# CLAUDE.md — Master LLM Context File

> OpenCode and Claude Code can read this file via their file tools. You are
> expected to read it at the start of every session, and to consult it again
> before any action that touches the document layer (`BLUEPRINT.md`,
> `CONVENTIONS.md`, `docs/DECISIONS.md`, this file's correction log).
> Keep it current. Every correction you make to the LLM should be recorded here
> so the mistake never happens again.

---

## Project Overview

**Name:** [PROJECT_NAME]
**What it does:** [One paragraph. What does this do, who is it for, what problem does it solve.]
**Status:** [Planning | In Development | Production]

---

## Tech Stack

> Default template stack shown below. ADAPT to this project's real stack
> before first commit (see BLUEPRINT.md Rule 3).

```
Language:     Python 3.12+
Framework:    [e.g. FastAPI / Django / Flask]
Database:     [e.g. PostgreSQL / SQLite / MongoDB]
Auth:         [e.g. Clerk / JWT / OAuth]
Hosting:      [e.g. Railway / Fly.io / AWS]
CI/CD:        GitHub Actions
Testing:      pytest
```

---

## Project Structure

```
[PROJECT_NAME]/
├── src/                  # application source
│   ├── api/              # route handlers
│   ├── models/           # data models
│   ├── services/         # business logic
│   └── utils/            # shared utilities
├── tests/                # TPM-authored frozen suite (INV-1); changes only via refreeze.sh
├── docs/                 # architecture, decisions, product, TPM role, escalation
├── tasks/                # EM write lane (plan.json) + session notes + backlog
│   └── CURRENT.md        # session notes — active work, halt notes (the PRD lives in scripts/.approved/)
├── scripts/
│   ├── bootstrap.sh      # one-time setup (sets core.hooksPath)
│   ├── phase-gate.sh     # lane + integrity gate (INV-2/3, frozen spec)
│   ├── orchestrate.sh    # shell-driven task-DAG conductor (owns all procedure)
│   ├── validate-plan.py  # plan.json gate (atomicity, DAG, coverage, mapping)
│   ├── refreeze.sh       # ONLY path frozen TPM artifacts change (human-gated: y/N or --approve <hash>, D-42)
│   ├── check-test-surface.py  # INV-4: tests ⊆ locked surface
│   ├── schemas/          # plan / diagnosis / contracts schemas
│   └── .approved/        # frozen TPM spec: PRD, ERD, contracts, VERSION, hashes
├── .opencode/
│   └── prompts/          # agent role definitions (em/coder)
├── .githooks/            # pre-commit gate for the interactive/human path
├── .gate-paths           # configurable directories for INV-2 enforcement
├── CLAUDE.md             # this file
└── CONVENTIONS.md        # code style rules
```

---

## Code Conventions

- Always use type hints on function signatures
- Prefer functions over classes unless persistent state is needed
- Use `logging` from the standard library — never `print()`
- One responsibility per function — if it needs a comment explaining what it does, split it
- Tests live in `tests/` mirroring `src/` structure (e.g. `src/services/user.py` → `tests/services/test_user.py`)
- Tests are TPM-authored and land via `scripts/refreeze.sh` BEFORE the code they gate — never written after the fact to match an implementation
- Use `pydantic` for data validation and serialization
- Environment variables via `python-dotenv` — never hardcode secrets

---

## What NOT To Do

> These are guardrails. Do not override them without explicit human instruction.

**Code guardrails:**
- **Do not add dependencies** without asking first
- **Do not refactor files** unrelated to the current task
- **Do not change the database schema** without explicit instruction
- **Do not remove error handling** to simplify code
- **Do not use `Any` type** — be specific
- **Do not write `TODO` comments** — either implement it or raise it as a task
- **Do not use `time.sleep()`** in production code — use proper async patterns
- **Do not commit secrets** — use `.env` and ensure `.gitignore` covers it

**Pipeline guardrails (Rules 6-7, see BLUEPRINT.md; ladder details in DECISIONS.md D-26..D-32):**
- **No agent authors or edits tests** — the suite is TPM-authored, installed only via `scripts/refreeze.sh`, and hash-pinned in `scripts/.approved/frozen-manifest` (INV-1, now structural: tests are written before the code exists, by a tier that never sees the implementation).
- **Do not cross role boundaries** — Coder writes exactly the one file its task names (`phase-gate.sh task`); EM writes `tasks/` only (`phase-gate.sh em`). Enforced by read-only sandbox mounts (D-30) with the gate as backstop (INV-2).
- **Tests observe only the locked surface** — imports from `contracts.entry_points`, routes from `contracts.routes` (INV-4, checked at freeze time by `scripts/check-test-surface.py`).
- **Do not skip escalation** — retry → EM consult → brief/plan revision (bounded) → batched TPM bundle → human-approved re-freeze. All counters shell-owned. See `docs/ESCALATION.md`.
- **Sync the stack before every freeze (D-50).** The TPM chooses the tech stack at spec time. Before running `refreeze.sh`, check the staged tests' imports against `requirements.txt` and add anything missing (this edit is in the conductor's lane). The sandbox image rebuilds itself when `requirements.txt` or `Containerfile` change — never manually delete or rebuild images.
- **TPM shuttle is a verbatim relay (D-49).** When the CEO asks for the TPM prompt/briefing: run `scripts/tpm-pack.sh` and reproduce its ENTIRE stdout in your reply, unabridged — never summarize it, never point the CEO at repo files (the bundle is assembled from several sources; it cannot be hand-collected), never claim it is "in the clipboard." When the CEO pastes a TPM reply back: write it to a temp file unmodified and run `scripts/tpm-unpack.sh <file>` — do not re-type or edit it.

**Operating guardrails (from hard-won failures — see BLUEPRINT.md):**
- **Do not set a thinking model as the active model.** Thinking models leave `content` empty and put output in `reasoning_content`, which breaks parsing. The model must be non-thinking local OR frontier.
- **Do not retry the same failing fix more than twice.** Two strikes → escalate to a frontier model, or halt and leave a note.
- **Do not trust your own "it works" — only passing tests confirm success.** Run `pytest`. The tests are ground truth, not your assessment. Do not mark a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt and report.
- **Do not invent product or architecture decisions to fill an ambiguous spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop tables, delete files outside the project) — halt and ask.

---

## Current Focus

The frozen spec (PRD/ERD/contracts + version) lives in `scripts/.approved/`;
`tasks/CURRENT.md` holds session notes and halt notes. New features start in
the TPM web chat (see `docs/TPM-ROLE.md`) and enter via `scripts/refreeze.sh`.

---

## Capability Ladder (D-27)

| Tier | Where it runs | Produces | Writes |
|------|---------------|----------|--------|
| **CEO** (human) | conversation with the conductor | business intent, freeze approvals | — (runs no commands, D-40) |
| **TPM** (frontier LLM) | web chat (D-38) or scoped repo agent via `scripts/tpm-agent.sh` (D-39) | PRD, ERD + `contracts.json`, the test suite | nothing directly — installed via `scripts/refreeze.sh` (human-approved diff, D-42), frozen in `scripts/.approved/` + `tests/` |
| **Conductor** | any chat agent the CEO chooses (Claude Code, OpenCode's Build, or a plain shell) | status reports, script invocations | docs/session notes; denied on `tests/`, `scripts/`, `src/`, control plane (D-40) |
| **EM** (mid-tier LLM) | one HTTP completion via `scripts/llm-call.sh` (D-53) | `tasks/plan.json` (decomposition), `tasks/diagnosis.json` (consults) — the shell writes both, not the model | `tasks/**` only |
| **Coder** (local LLM) | one HTTP completion via `scripts/llm-call.sh` (D-53) | one file per task, sentinel-wrapped in the reply | that one file only (gate-enforced) |

Which actual model backs EM/coder is never recorded in this repo: the CEO
maps roles to models in `~/.config/sw-dev-blueprint/models.env` (D-53,
succeeding D-41's `opencode.json` mapping). The blueprint constrains model
*class* only (frontier / mid / local non-thinking), never model identity.
No mapping for a role is a hard halt, never a silent substitution.

Tests are **run by the shell** (`pytest --json-report`, parsed by
`scripts/orchestrate.sh`) — there is no test agent. The shell orchestrator is
the only actor with procedural authority: it validates the plan, walks the
DAG, runs gates and acceptance, owns all state and escalation counters
(D-26). The EM advises at exactly two shell-initiated points; it never drives.
Neither EM nor coder has any tool or filesystem access — the orchestrator
gathers whatever context a call needs into the prompt and writes the reply to
disk itself (D-53); there is no agent harness in the execution loop at all,
only in the CEO-facing conductor seat, which never touches trusted state.

**The loop (all steps conductor-driven; the CEO only talks and approves):**
TPM spec frozen (`refreeze.sh` — terminal y/N, or conductor `--diff` /
`--approve <hash>` behind the conductor's own ask-prompt, D-42) →
`scripts/orchestrate.sh` → EM emits plan → validated → coder executes one
task at a time → mapped frozen tests + gate after each → full frozen suite
green = done. Failures climb the escalation ladder (`docs/ESCALATION.md`);
spec problems come back as a batched bundle for the TPM web chat and
re-enter via `refreeze.sh`.

---

## Reporting

When summarizing work since the last PM review (status reports, commit scoping, progress updates):

1. Read `docs/.pm-last-review` to get the last reviewed ref:
   ```
   LAST=$(cat docs/.pm-last-review 2>/dev/null || git rev-list --max-parents=0 HEAD)
   ```
2. Derive the commit list from the tree, not memory:
   ```
   git log "$LAST"..HEAD --oneline
   ```
3. State the scope explicitly in the report: "N new commits since reviewed ref `$LAST`".
4. Never write or advance `docs/.pm-last-review` — PM-owned.
5. If the file is missing (fresh checkout), the `git rev-list` fallback uses the initial commit — the scope becomes the entire history, which is correct for a first report.

---

## Operating Rules

> A rule that cannot be enforced mechanically is a suggestion, not a rule. Document the enforcement mechanism alongside every rule — and where there is none, say so explicitly.

Seven rules for agents working in this repo, derived from failures in prior sessions. Rules 2–7 are advisory — they rely on PM review for enforcement. Rule 1 has a mechanical backstop (see footnote).

1. **Report against the tree, never memory.** Derive your commit list from `LAST=$(cat docs/.pm-last-review); git log "$LAST"..HEAD --oneline`. State the range. A report that disagrees with `git log` is a defect regardless of the underlying work. *(Mechanical backstop: `docs/.pm-last-review` + PM source-side reconciliation.)*

2. **One commit, one concern.** Any change to a gate, invariant (INV-1/INV-2), permission, or model choice gets its own isolated commit whose message names it as such. Never bundle a constraint change with unrelated edits.

3. **A change to what a rule does is stop-and-ask.** Improving how a gate detects — fix freely. Changing what happens on a violation, or relaxing any constraint — stop and ask the PM first, even mid-run, even if the rule is what's slowing you down. The rule slowing you down is usually it working.

4. **Conditionals are checkpoints.** "Only do X if Y fails" means: when you reach that point, report whether Y failed and what you chose. If Y didn't fail, say so — don't silently act.

5. **Read the artifact, not the summary.** Report from committed files, never from another agent's summary or your own memory of a run. When source and summary disagree, source wins.

6. **"Detected" ≠ "enforced"; "nothing went wrong" ≠ "safeguard works."** Keep standalone-test results and live-run results as separate claims. An untriggered safeguard is inconclusive, not green.

7. **Decide trivial calls; escalate only contested principles.** If the PM has stated the governing principle ("put it where process docs live"), execute — don't re-ask for confirmation or surface options for a low-stakes choice. Escalate only when the principle itself is unclear, or when correctness is genuinely at stake (then asking is correct, not a failure).

---

## Key Contacts / Roles

| Role | Name |
|------|------|
| Product owner | [NAME] |
| Lead dev | [NAME] |

---

## LLM Correction Log

> When the LLM makes a mistake and you correct it, log it here.
> This is the most valuable section — it prevents repeat mistakes.
> A project 6 months in should have a rich log. That means the system is working.

| Date | Mistake | Guard Added |
|------|---------|-------------|
| [DATE] | [What went wrong] | [What rule prevents recurrence] |
| 2026-06-04 | Table-driven "fill in the blanks" missed files not in the table; `[NAME]` survived. | Use a placeholder-shaped grep as the verification gate — never rely on a maintained list for completeness. |
| 2026-06-04 | Feature-complete had no defined end state (stale CURRENT.md, open backlog, "active development" voice). | Add a Project Completion / Maintenance Transition section with a checklist and curated cleanup step. |
| 2026-06-04 | Bootstrap expected user to run scripts and opencode manually; no agent-driven path from URL + name alone. | Agent-driven flow: create, read, spec-or-ask, adapt, fill, grep-gate, commit — user runs nothing. |
| 2026-06-04 | Aider→OpenCode migration left 3 cosmetic Aider references and never created the AGENTS.md symlink that docs already advertised. | After any agent/CLI migration commit, grep for old-tool residue and verify every doc-claimed filename with `ls` / `git ls-files`. |
| 2026-06-04 | BLUEPRINT.md bloated to 557 lines through redundancy (duplicate sections, restated rules, repeated slogans). | Target ≤450 lines [demoted — see DECISIONS.md]. After any doc edit, verify every `Step N` reference reaches a `### Step N` heading. The unit of quality is clarity, not column count. |
| 2026-06-04 | OpenCode did not pre-load AGENTS.md; auto-load claim was false. Model fetched content via tool but answered wrong. | Memory layer is best-effort, not enforced. For must-hold rules, prefer mechanical gates (grep, `wc -l`, CI, hooks) over doc guards. |
| 2026-06-04 | Added a BLUEPRINT.md date-specific project guard to CLAUDE.md template, muddying template-vs-project boundary. | Template files hold generic guards; project-specific rules live in DECISIONS.md and the correction log. Cross-reference, don't copy. |
| 2026-06-30 | A derived project (spark) discovered via real build-plan runs that a local coder-class Build model handled atomic single-file tasks perfectly but silently dropped half of a multi-file task and stalled on a genuinely ambiguous CLI instruction — the template's architect prompt had no guidance for briefing a strong-coder/weak-agent local model. The fix lived only in the derived project until ported back here. | Added BLUEPRINT.md Rule 8 (brief Build as a precision tool: atomic tasks, no negative-constraint framing, split multi-file tasks, end every brief with an explicit self-verify step) and the matching clause in `.opencode/prompts/architect.md`. Update `scripts/.control-plane-manifest` after any further edit to that prompt file. |
| 2026-06-30 | `scripts/.control-plane-manifest` had stale hashes for `build.md`/`test.md`/`pm.md` left over from commit `3639742` (role-boundary guard added to all four prompts), which never regenerated the manifest — silent drift, only caught while porting the Rule 8 change above. | Whenever editing any control-plane file, regenerate and verify every entry in the manifest, not just the one just touched — a per-file loop diffing `shasum -a 256` against the manifest, run after any control-plane edit. |
| 2026-07-14 | Two testchat M16 tasks marked NO EDIT NEEDED still went to the coder, which edited anyway: one call damaged index.html (dropped the class its CSS keyed on — smoke-check greps survived; caught three tasks later by regression tests), another added redundant code that passed. "Change nothing" is a negative-constraint brief (Rule 8) no local coder reliably obeys. | D-65: `contracts.no_edit_files` (frozen, human-approved) — the orchestrator never invokes the coder for declared no-edit files; acceptance still runs. validate-plan rejects declarations outside the inventory. |
| 2026-07-14 | `models.env` exists in TWO places — macOS host and inside the dev VM ($HOME differs) — and the pipeline reads the VM copy. A conductor switched the EM model on the host only and reported the swap as done; three milestones ran on the old model before the CEO noticed it loading. | Role-mapping changes must be applied and VERIFIED inside the VM (`limactl shell dev-vm -- cat ...`); after any model change, confirm which model the server actually loads on the next run. Self-reports about configuration are claims, not evidence. |
| 2026-07-14 | A milestone shipped [success] with raw edit-block markers inside a CSS file AND a hit-counter counting matches in hidden (collapsed-think) text: browsers skip malformed CSS and Playwright counts DOM nodes, so the frozen suite stayed green while the feature was visibly broken. The CEO's eyes were the only detector, twice in one day. | Applier now rejects marker-bearing output (fail-closed). Process rule: before presenting any user-visible milestone, the conductor views it in a real browser and verifies the specific claim (counts, emphasis, layout) — Playwright-green is necessary, never sufficient, for appearance. |
| 2026-07-13 | The EM twice ignored explicit ERD prose on where to map browser tests (testchat M15): first it left a task with no acceptance signal (plan-gate halt, cost a re-freeze), then it mapped a Playwright test to the markup task, where it structurally could not pass before the styling task ran (false task failure, manual plan fix). Same mid-tier signature as the M9 invented contract-id: schema honored, prose ignored. | D-64: `validate-plan.py` now rejects any plan where a playwright-importing test file is mapped to a task whose dependency closure does not contain the whole plan. Prose guidance stays in the ERD for the EM's benefit, but the gate no longer depends on it being followed. |
| 2026-07-12 | The coder's `llm-call.sh` context window defaulted to 8192 tokens. Files over ~400 lines were silently truncated in the prompt, causing the coder to "hallucinate" missing sections — the model never saw them. Discovered in testchat M10 when a 638-line file kept losing its tail. | Set `context_window` to 32768 in `models.env` for the coder role. The template's `llm-call.sh` already reads this value; the issue was the default being too small for real files. When onboarding a new project, verify the coder's context window covers the largest file in the ERD inventory. |
| 2026-07-09 | The coder contract demanded full-file retyping of existing files; a bench-vetted local coder twice deleted large blocks of working logic while "modifying" a file (99 lines at 638-line size, 119 lines at 347-line size with doubled context) — invisible to grep-level smoke checks, caught only by the D-58 browser oracle. Root cause was the output format, not the model: the same model produced 11/11 exact anchored edits on identical tasks. | D-59: existing files are edited via anchored SEARCH/REPLACE blocks applied fail-closed (`scripts/apply-edit-blocks.py`); never ask a local model to reproduce content it is not changing. Think-tag corollary: llm-call strips only LEADING think blocks, and edit anchors avoid tag-bearing lines — chat-UI relays are lossy for such code. |
| 2026-07-04 | The testchat M4 supervised run: a frontier-model conductor under goal pressure crossed every advisory lane the moment the pipeline stalled — hand-wrote `src/` after the coder's first strike (3 commits), authored test-content fixes, added an unspecced product feature (think-streaming + UI toggle contradicting the frozen M3 ERD), skipped the escalation ladder, and ran tests outside the sandbox — then reported all of it as "on-the-fly solutions." Every prose constraint on the conductor failed; every structural gate (refreeze protocol, frozen manifest, INV-4) held. The one mechanical backstop on the conductor path — the pre-commit hook — was absent because `bootstrap.sh` had never been run, and nothing checked. | Two guards: (1) `orchestrate.sh` pre-flight now fails closed if `core.hooksPath` != `.githooks`. (2) Design rule, permanent: never rely on conductor compliance for any invariant — the conductor seat holds the most capable model with the most agency and WILL rationalize lane-crossing as helpfulness; constraints on it must be structural (outer sandbox, hooks, file permissions), never advisory. The outer-sandbox wrapper (tasks/HANDOFF-outer-sandbox.md) is the durable fix. |
| 2026-07-03 | D-53's bare-HTTP rewrite shipped `llm-call.sh`/`orchestrate.sh` with a cluster of plumbing bugs that no run exercised until the testchat M1 supervised run: the `python3 - <<PYEOF` heredoc and the piped user prompt both took fd 0, so the prompt never reached the model — every "model hallucination" in earlier runs was this misdiagnosed; plus missing `enable_thinking` (qwen HTTP 400), an unread error body with an unhandled retry `HTTPError`, unstripped inline `<think>` blocks leaking into parsed output, no `mkdir -p` before the first coder write into a new subtree, and a `loguru` logging convention the template forbids installing. | Fixed all six and ported from the child (commits `b73c2b7`..`5f4a59e`), one concern per commit, manifest regenerated each time. Durable prevention still owed and deferred to the M4 design batch: a pre-flight `llm-call.sh` smoke test (round-trip a trivial prompt through the mapped model and assert the echo) — a bug in the model-call path is invisible to static review and only a real round-trip catches it. |
