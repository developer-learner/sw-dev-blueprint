# BLUEPRINT.md — SW Dev Blueprint: Master Seed Document

> **For LLMs:** This is your entry point. Read this entire document first.
> Then fetch the GitHub repository linked below, read each file in the order
> specified, run the **Pre-Flight Check (Step 0)**, and only then execute the
> bootstrap sequence. Do not skip steps. Obey the **Hard Rules** even when
> unsupervised.

---

## What This Is

`sw-dev-blueprint` is a GitHub template repository that provides the complete
documentation, configuration, and tooling scaffold for LLM-assisted software
development. Every new software project bootstraps from this template instead
of starting from scratch.

**The core idea:** LLMs have no memory between sessions. This template is the
memory layer — a structured set of documents that tells any LLM everything it
needs to know about a project, how to write code for it, and what not to do.

**The execution model:** A frontier LLM (F) acts as **architect** (plans the
change). A local LLM (L) acts as **editor** (writes the code to disk). Aider
orchestrates the two. Git provides the undo. Tests provide the ground truth.

---

## GitHub Repository

```
https://github.com/YOUR_USERNAME/sw-dev-blueprint
```

> **LLM instruction:** Fetch each file listed in the Document Map below from
> this repository. Read them in order before taking any action.

---

## Component Inventory

The full stack this system runs on. Know every object before operating it.

| Object | Role |
|--------|------|
| **git** | Version control + the LLM's undo button. Every edit auto-commits; any mistake is `/undo` or `git reset` away. Also: backup, attribution, collaboration. |
| **GitHub** | The remote. Off-machine backup, and the host that makes `gh repo create --template` work. (Distinct from git — git is local.) |
| **venv** | Per-project dependency isolation. NOT a security sandbox — it stops dependency collisions, not destructive commands. |
| **LM Studio** | The local inference server (`localhost:1234`). Most common failure point — verify the correct model is loaded (Pre-Flight Step 0). |
| **Aider** | The execution harness. Runs architect/editor mode. Edits files, runs commands, auto-commits. |
| **F — Frontier LLM** | The architect/brain. Reasons, plans. Reached via API key (paid, planning-only so cheap) or via chat (Claude.ai) for greenfield discussion. |
| **L — Local LLM** | The editor/hands. Writes diffs. MUST be non-thinking (e.g. qwen3-coder-next). |
| **pytest / CI** | The test harness = **ground truth**. The agent does not decide if it succeeded — the tests do. |
| **The docs** | The memory layer for stateless LLMs (this file + CLAUDE.md + CONVENTIONS.md + docs/ + tasks/). |
| **Entry-point script** | The one command that ties it all together for unattended instantiation. |

---

## Document Map

Read these files from the repository in this exact order:

| Order | File | Purpose | When to read |
|-------|------|---------|--------------|
| 1 | `README.md` | System overview + working loop | Always — first |
| 2 | `CLAUDE.md` | Project identity, stack, guardrails | Always — every session |
| 3 | `CONVENTIONS.md` | Code style and patterns | Always — every session |
| 4 | `.aider.conf.yml` | Model routing configuration | Setup + model changes |
| 5 | `docs/PRODUCT.md` | What we're building and why | New features |
| 6 | `docs/ARCHITECTURE.md` | Data models, API, key flows | Any code change |
| 7 | `docs/DECISIONS.md` | Why choices were made | Before suggesting alternatives |
| 8 | `docs/TESTING.md` | How we test | Writing or running tests |
| 9 | `tasks/CURRENT.md` | Active task spec | Every coding session |
| 10 | `tasks/BACKLOG.md` | Upcoming work queue | Planning sessions |

---

## Hard Rules (Non-Negotiable — Apply Even When Unsupervised)

> These exist because they are silent, hard-to-diagnose failures that will
> waste hours if violated — especially when you are running unattended and no
> human is awake to catch them. Do not override without explicit human
> instruction in `tasks/CURRENT.md`.

### Rule 1 — The architect model must NOT be a thinking model
A thinking model emits its output into `reasoning_content` and leaves
`content` empty, which breaks Aider's parsing (empty/invalid response →
JSON failure).
- Architect (`model:`) must be either a NON-THINKING local model
  (e.g. `qwen3-coder-next`) OR a frontier model.
- The editor (`editor-model:`) must ALSO be non-thinking.
- NEVER set a local thinking model (e.g. `qwen3.6-35b-a3b`) as architect or
  editor, no matter how strong its reasoning is.
- Verify before relying: see Pre-Flight Step 0 — confirm `content` is
  populated and `reasoning_content` is empty.

### Rule 2 — Escalation tripwire (prevents error-correction spirals)
A weaker local model can loop: bad fix → new error → bad fix → ... burning
time and introducing technical debt. Cap it hard.
- If the SAME error fails to resolve after TWO attempts by the local editor,
  STOP. Do not attempt a third fix.
- Escalate: switch the architect to a frontier model for this task (see
  `.aider.conf.yml`), OR halt and notify the human (Rule 4).
- Never let the loop retry the same failing fix more than twice.

### Rule 3 — Adapt the template to the actual stack before first commit
The template defaults to **FastAPI + PostgreSQL + pytest**. If THIS project's
stack differs (e.g. SQLite, a different framework, no DB), you MUST adapt
these files BEFORE bootstrapping:
- `scripts/bootstrap.sh` — the dependencies installed
- `.github/workflows/ci.yml` — the services block (e.g. remove the Postgres
  service for a SQLite project)
- `CONVENTIONS.md` — framework-specific patterns
- `docs/ARCHITECTURE.md` — the infrastructure section
Do not run a Postgres CI service for a project that does not use Postgres.

### Rule 4 — Halt-and-notify conditions (stop; do not guess)
When unsupervised, STOP and write a clear note in `tasks/CURRENT.md` (under
"Notes / Context") rather than proceeding, if ANY of these hold:
- Tests still fail after escalation (Rule 2 exhausted)
- A destructive operation is implied (deleting files outside the project,
  dropping tables, `git push --force`, `rm -rf`)
- The task spec is ambiguous and proceeding would require inventing a product
  or architecture decision (that is the human's job — see Abdication)
- A required service (LM Studio at `localhost:1234`) is unreachable
- Acceptance criteria in `CURRENT.md` cannot be met as written
The dangerous failure is acting confidently when wrong — not stopping.

### Rule 5 — Tests are ground truth, not your self-assessment
Never report a task complete based on your own judgment. Run `pytest`. A task
is done only when its acceptance-criteria tests pass AND no existing tests
broke. "It looks correct" is not evidence. The tests are.

---

## Step 0 — Pre-Flight Check (run BEFORE anything else)

> Do not write code or instantiate until all checks pass. Fail LOUDLY if any
> check fails — a silent wrong-model is the most common and most expensive
> failure.

**1. LM Studio reachable + correct (non-thinking) model loaded:**
```bash
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder-next","messages":[{"role":"user","content":"Reply with just OK"}],"max_tokens":5}'
```
PASS only if BOTH:
- the response `model` field matches the intended editor model (NOT a
  different model that LM Studio fell back to), AND
- `content` is populated (e.g. "OK") and `reasoning_content` is empty.

If `model` echoes a different name, the wrong model is loaded — fix it in
LM Studio before proceeding. If `content` is empty and `reasoning_content`
is populated, you have loaded a THINKING model — load a non-thinking one
(Rule 1).

**2. git available and identity configured:**
```bash
git --version && git config user.name && git config user.email
```

**3. Python 3.12+:**
```bash
python3 --version
```

**4. gh CLI authenticated (needed for template instantiation):**
```bash
gh auth status
```

If any check fails, STOP and report exactly which one. Do not proceed.

---

## The System in One Diagram

```
Human intention
      │
      ▼
tasks/CURRENT.md          ← you write this before each session (be specific!)
      │
      ▼
Pre-Flight Check (Step 0)  ← verify LM Studio / model / git / gh
      │
      ▼
Aider (architect mode)
      │
      ├── reads: CLAUDE.md + CONVENTIONS.md + CURRENT.md  (always)
      ├── reads: ARCHITECTURE.md + DECISIONS.md           (on demand)
      │
      ├── Architect pass (F): proposes a plan
      │         │
      │         ▼
      │   Human reviews → approve or reject   (or auto-accept if configured)
      │         │
      ▼         ▼
      Editor pass (L): writes code to disk
      │
      ▼
Git commit (automatic)
      │
      ▼
Tests run: pytest   ← GROUND TRUTH
      │
      ├── Pass → done, update docs, next task
      └── Fail → paste error into Aider, loop
                   │
                   └── Same error twice? → STOP (Rule 2): escalate or halt
```

---

## Document Roles Explained

### `CLAUDE.md` — The Brain
The single most important file. Aider and Claude Code read this automatically
at startup. Contains: what the project is, tech stack (exact versions), code
conventions, **what NOT to do** (the guardrails), and the **LLM correction
log** (every mistake logged here prevents recurrence).

**Maintain it like this:** every time the LLM does something wrong and you
correct it, add a row to the correction log. The file gets smarter over time.

### `CONVENTIONS.md` — The Style Guide
Code patterns with explicit good/bad examples. Read every session.

### `docs/ARCHITECTURE.md` — The Map
Data models, API routes, key flows. Prevents the LLM inventing schema.

### `docs/DECISIONS.md` — The Memory
Why non-obvious choices were made. The highest-leverage doc most teams skip.
"Do not suggest X" entries stop the LLM re-litigating solved problems.

### `docs/PRODUCT.md` — The Why
Evergreen product context: problem, users, non-goals.

### `docs/TESTING.md` — The Test Contract
Testing strategy, conventions, fixtures. Tests are ground truth (Rule 5).

### `tasks/CURRENT.md` — The Session Spec
Updated before every session. **The quality of the output is capped by the
quality of this file.** Vague spec → bad result, and the system cannot fix
that for you. Acceptance criteria as checkboxes; explicit out-of-scope.

### `tasks/BACKLOG.md` — The Queue
Prioritized work. Done tasks move here; next becomes CURRENT.md.

---

## Bootstrap Sequence

### For LLMs executing this for the first time on a new project:

**Step 0 — Pre-Flight Check** (above). Do not skip.

**Step 1 — Fetch the template**
```bash
gh repo create <project-name> \
  --template YOUR_USERNAME/sw-dev-blueprint \
  --private
cd <project-name>
```

**Step 2 — Read all documents**
Read every file in the Document Map before writing a single line of code.

**Step 3 — Adapt the stack (Rule 3)**
Before running bootstrap, confirm the template's default stack (FastAPI +
Postgres) matches this project. If not, edit `bootstrap.sh`, `ci.yml`,
`CONVENTIONS.md`, and `ARCHITECTURE.md` to the real stack first.

**Step 4 — Run bootstrap**
```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh <project-name>
```

**Step 5 — Fill in the blanks**
Replace `[PLACEHOLDER]` values:

| File | Placeholders to fill |
|------|---------------------|
| `CLAUDE.md` | Project name, description, tech stack, team |
| `docs/PRODUCT.md` | Problem statement, users, success metrics |
| `docs/ARCHITECTURE.md` | Data models, API routes, infrastructure |
| `.env` (copy from `.env.example`) | All secret values |

**Step 6 — Write the first task**
Fill `tasks/CURRENT.md`. Be specific. Acceptance criteria as checkboxes.

**Step 7 — Start coding**
```bash
# Confirm LM Studio is running with the model loaded, then:
export OPENAI_API_BASE=http://localhost:1234/v1
export OPENAI_API_KEY=lm-studio
aider --architect src/
```

---

## LLM Routing Decision Tree

```
What kind of task is this?
│
├── Boilerplate / CRUD / tests / known patterns
│     └── Local model (free, fast)
│           model + editor-model: qwen/qwen3-coder-next via LM Studio
│
├── Multi-file refactor / moderate complexity
│     └── Local model in architect/editor mode
│           aider --architect  (both local, non-thinking)
│
├── Hitting a reasoning wall / stuck on design / Rule 2 escalation
│     └── Escalate ARCHITECT to frontier for this task
│           model: claude-sonnet-4-5 (or current) in .aider.conf.yml
│           editor-model: qwen/qwen3-coder-next (still local)
│
└── Greenfield architecture / major product decision
      └── Discuss in chat (Claude.ai) first
            → Write outcome into DECISIONS.md
            → Write spec into tasks/CURRENT.md
            → Then hand to Aider
```

**Cost note:** Frontier-as-architect costs money but only for *planning*
calls (the editor stays local), typically 30–50% cheaper than running the
whole task on frontier. Reserve it for the hard 20%.

---

## The Maintenance Contract

The system only works if the docs stay current.

| Trigger | Action | File |
|---------|--------|------|
| New dependency added | Document it | `ARCHITECTURE.md` |
| Non-obvious decision made | Log it with reasoning | `DECISIONS.md` |
| New code pattern established | Add example | `CONVENTIONS.md` |
| LLM made a mistake you corrected | Add guard | `CLAUDE.md` correction log |
| Task completed | Move to completed table | `BACKLOG.md` |
| Starting a new session | Update what you're building | `CURRENT.md` |
| Schema changed | Update data models | `ARCHITECTURE.md` |

**The correction log rule** is the most important habit. It turns every LLM
mistake into a permanent improvement.

---

## Anti-Patterns to Avoid

**Vague CURRENT.md** — Bad: "Add user auth." Good: acceptance-criteria
checklist with specific endpoints, behaviors, and explicit out-of-scope items.

**Stale ARCHITECTURE.md** — If the LLM's model of your schema is wrong,
everything built on it is wrong. Update after every schema change.

**Skipping DECISIONS.md** — Every unlogged decision gets re-litigated next
session. The LLM has no memory; this is the only thing carrying context forward.

**Over-relying on frontier for everything** — 80% of tasks are routine.
Local handles them free. Save frontier for actual reasoning walls.

**Abdication** — The LLM fills any vacuum, including product decisions.
**You own:** what to build, acceptance criteria, architecture decisions, final
review. **The LLM owns:** how to implement, boilerplate, syntax, tests.

**Trusting self-reported success** — The LLM will claim "done" when it isn't
(it will even fabricate completion at a wall). Only passing tests confirm
success (Rule 5).

**Letting the error loop run** — A weak model spirals on a bad fix. Two
strikes, then escalate or halt (Rule 2).

---

## Quick Reference Card

```
Start session:    Pre-Flight (Step 0) → update tasks/CURRENT.md
                  → run aider --architect src/
During session:   /ask    understand code without editing
                  /diff   review changes before accepting
                  /undo   roll back last commit
                  /add <file>   add file to context
After session:    Run pytest → log decisions → update architecture
                  → mark task done
Stuck:            Come to Claude.ai → spec the solution → paste into CURRENT.md
Test failing:     Paste full error into aider architect prompt
Same error twice: STOP → escalate architect to frontier OR halt (Rule 2)
Model too slow:   Switch editor-model to smaller local model in .aider.conf.yml
Need more power:  Swap model: to a frontier model in .aider.conf.yml
Wrong model bug:  Re-run Pre-Flight Step 0 — LM Studio likely loaded the
                  wrong / a thinking model
```

---

## Files the LLM Should Never Touch Without Explicit Instruction

- `DECISIONS.md` — human-authored record of deliberate choices
- `.env` — secrets
- `CLAUDE.md` correction log — human-maintained
- Database migration files after they've been run
- `tasks/BACKLOG.md` completed section — historical record

---

*This document is the entry point. Everything else flows from it.*
*Keep this file updated as the system evolves.*
