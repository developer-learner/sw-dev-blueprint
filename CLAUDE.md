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
├── tests/                # mirrors src/ structure; derives from PRD (INV-1)
├── docs/                 # architecture, decisions, product
├── tasks/                # current work (PRD) + backlog
│   └── CURRENT.md        # ⬅ PRD — acceptance criteria, frozen on approval
├── scripts/
│   ├── bootstrap.sh      # one-time setup (sets core.hooksPath)
│   ├── phase-gate.sh     # lane + integrity gate (INV-2/3, frozen spec)
│   ├── orchestrate.sh    # shell-driven task-DAG conductor (owns all procedure)
│   ├── validate-plan.py  # plan.json gate (atomicity, DAG, coverage, mapping)
│   ├── refreeze.sh       # ONLY path frozen TPM artifacts change (human y/N)
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
- Use `loguru` for logging — never `print()`
- One responsibility per function — if it needs a comment explaining what it does, split it
- Tests live in `tests/` mirroring `src/` structure (e.g. `src/services/user.py` → `tests/services/test_user.py`)
- Write tests alongside new code, not after
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

**Operating guardrails (from hard-won failures — see BLUEPRINT.md):**
- **Do not set a thinking model as the active model.** Thinking models leave `content` empty and put output in `reasoning_content`, which breaks parsing. The model must be non-thinking local OR frontier.
- **Do not retry the same failing fix more than twice.** Two strikes → escalate to a frontier model, or halt and leave a note.
- **Do not trust your own "it works" — only passing tests confirm success.** Run `pytest`. The tests are ground truth, not your assessment. Do not mark a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt and report.
- **Do not invent product or architecture decisions to fill an ambiguous spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop tables, delete files outside the project) — halt and ask.

---

## Current Focus

See `tasks/CURRENT.md` for the active PRD. Start a session with `@pm` to write or update it.

---

## Capability Ladder (D-27)

| Tier | Where it runs | Produces | Writes |
|------|---------------|----------|--------|
| **CEO** (human) | conversation | business intent | — |
| **TPM** (frontier LLM) | human-operated **web chat**, outside OpenCode | PRD, ERD + `contracts.json`, the test suite | nothing directly — installed via `scripts/refreeze.sh` (human-approved diff), frozen in `scripts/.approved/` + `tests/` |
| **EM** (mid-tier LLM) | OpenCode agent `em` | `tasks/plan.json` (decomposition), `tasks/diagnosis.json` (consults) | `tasks/**` only |
| **Coder** (local LLM) | OpenCode agent `coder` | one file per task | that one file only (gate-enforced) |

Tests are **run by the shell** (`pytest --json-report`, parsed by
`scripts/orchestrate.sh`) — there is no test agent. The shell orchestrator is
the only actor with procedural authority: it validates the plan, walks the
DAG, runs gates and acceptance, owns all state and escalation counters
(D-26). The EM advises at exactly two shell-initiated points; it never drives.

**The loop:** TPM spec frozen (`refreeze.sh`, human y/N) → `scripts/orchestrate.sh`
→ EM emits plan → validated → coder executes one task at a time → mapped
frozen tests + gate after each → full frozen suite green = done. Failures
climb the escalation ladder (`docs/ESCALATION.md`); spec problems come back
as a batched bundle for the TPM web chat and re-enter via `refreeze.sh`.

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
