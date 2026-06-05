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
├── tests/                # mirrors src/ structure
├── docs/                 # architecture, decisions, product
├── tasks/                # current work + backlog
├── scripts/              # dev utilities
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

**Operating guardrails (from hard-won failures — see BLUEPRINT.md):**
- **Do not set a thinking model as the active model.** Thinking models leave `content` empty and put output in `reasoning_content`, which breaks parsing. The model must be non-thinking local OR frontier.
- **Do not retry the same failing fix more than twice.** Two strikes → escalate to a frontier model, or halt and leave a note.
- **Do not trust your own "it works" — only passing tests confirm success.** Run `pytest`. The tests are ground truth, not your assessment. Do not mark a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt and report.
- **Do not invent product or architecture decisions to fill an ambiguous spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop tables, delete files outside the project) — halt and ask.
- **Do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune** (Document Roles Explained, Quick Reference Card, verbose Bootstrap Step 5, etc.). Adding them back is a regression. Full rationale and dropped-list in `docs/DECISIONS.md` → "2026-06-04 — Pruned BLUEPRINT.md". The ≤450-line guard in the correction log is the backstop.

---

## Current Focus

See `tasks/CURRENT.md` for the active task spec (or just describe it in plain English to OpenCode).

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
| 2026-06-04 | LLM followed the Step 5 "Fill in the blanks" table literally and updated only the 4 listed files — 4 other files (TESTING.md, CONVENTIONS.md, tasks/CURRENT.md, tasks/BACKLOG.md) still had template placeholders. `[NAME]` survived in CLAUDE.md contacts until caught by external review. | Replace the table's authority with a placeholder-shaped grep as the verification gate. A maintained list drifts out of sync with reality; a grep check cannot. The table stays as a guide but the grep is the gate. Also: never rely on a maintained list for completeness — use a check. |
| 2026-06-04 | No "project is done" transition existed. After feature-complete, there was no defined end state — CURRENT.md had stale template text, backlog stayed open, docs were in "active development" voice. | Add a "Project Completion / Maintenance Transition" section to BLUEPRINT.md with a checklist. Add a curated cleanup step (Step 4.5) for template-only files, preserving the memory-layer docs (BLUEPRINT, CLAUDE, CONVENTIONS, all of docs/). |
| 2026-06-04 | Bootstrap Sequence assumed the user runs new-project.sh/bootstrap.sh in a terminal and starts opencode manually; no agent-driven path from just a URL + name. | Rewrote Steps 0–8 in agent-first voice: agent does create-from-template, doc read, spec-or-ask branch, cleanup, stack adaptation, placeholder fill, grep-gate verification, and first commit — user runs nothing. Removed obsolete bootstrap-run and opencode-start steps; gate (Rule 5) is the completion check. |
| 2026-06-04 | Commit `80c3e3f` (swap Aider→OpenCode) updated primary narrative (README, BLUEPRINT, scripts, opencode.json) but left 3 cosmetic Aider references behind (CONVENTIONS.md:3, .env.example:12, .gitignore Aider block) and never created the `AGENTS.md` symlink that README:17 and BLUEPRINT.md:54 already advertised. Template shipped in a broken-by-design state for OpenCode auto-load. | After any agent/CLI migration commit, run `grep -ril '<old-tool>' .` (excluding throwaway dirs) to catch residue, and verify every doc claim that names a file with `ls` / `git ls-files` before committing. Documented artifacts are contracts — treat doc-vs-reality drift as a release blocker. |
| 2026-06-04 | BLUEPRINT.md grew to 557 lines through 4 feature additions (Hard Rules, Bootstrap Sequence, Project Completion, Maintenance Contract). Document Map + Document Roles Explained covered the same ground twice. Bootstrap Steps 4/5/7 re-stated Rules 3 & 5 verbatim. Slogans (`lms not lmstudio`, "tests are ground truth", "same error twice") repeated 3-5 times. Phantom "Step 4.5" reference at line 490 with no such step in the sequence. Quick Reference Card restated the diagram. The file was ~22% larger than it needed to be. | After any doc edit, count lines (`wc -l`); BLUEPRINT.md target ≤450. After any sequence-of-steps section, verify every referenced step number (`Step N` or `Step N.M`) is reachable from a `### Step X` heading. Redundancy is context-window cost and a chance for ambiguity to compound — pruning is a guardrail, not cosmetics. |
| 2026-06-04 | Empirical test of the OpenCode auto-load claim: ran `opencode run --format json --dir /tmp/opencode-autoload-test "Read AGENTS.md..."` and inspected the event log. Three findings: (1) OpenCode did NOT pre-load AGENTS.md into context — the model invoked the `read` tool to fetch it. The CLAUDE.md intro claim "automatically read at session start" was false. (2) The tool-fetched content was correct. (3) The model got the answer wrong anyway — picked the first 2026-06-04 entry instead of the most recent. | The memory layer is *best-effort, not enforced*. Guards in CLAUDE.md are availability to a session, not a guarantee. When asserting any "auto-load" / "automatically read" claim, verify empirically (run the tool, ask a content-only question); a symlink existing is not proof. For anything that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) over doc guards — those fire without the LLM's cooperation. Doc guards are strong hints, not hard gates. |
