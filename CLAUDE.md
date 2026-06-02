# CLAUDE.md — Master LLM Context File

> This file is automatically read by Aider and Claude Code at session start.
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
- **Do not set a thinking model as Aider architect or editor.** Thinking
  models leave `content` empty and put output in `reasoning_content`, which
  breaks parsing. Architect/editor must be non-thinking local OR frontier.
- **Do not retry the same failing fix more than twice.** Two strikes →
  escalate the architect to frontier, or halt and leave a note.
- **Do not trust your own "it works" — only passing tests confirm success.**
  Run `pytest`. The tests are ground truth, not your assessment. Do not mark
  a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt
  and report.
- **Do not invent product or architecture decisions to fill an ambiguous
  spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop
  tables, delete files outside the project) — halt and ask.

---

## Current Focus

See `tasks/CURRENT.md` for the active task spec.

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
