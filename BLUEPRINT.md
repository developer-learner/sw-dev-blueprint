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

**The execution model:** You talk to OpenCode in plain English. OpenCode reads
the guardrail docs (CLAUDE.md / AGENTS.md, CONVENTIONS.md), plans, writes code
to disk, and reports back. Git provides the undo. Tests provide the ground truth.

---

## GitHub Repository

```
https://github.com/developer-learner/sw-dev-blueprint
```

> **LLM instruction:** Fetch each file listed in the Document Map below from
> this repository. Read them in order before taking any action.

---

## Component Inventory

The full stack this system runs on. Know every object before operating it.

| Object | Role |
|--------|------|
| **git** | Version control + the LLM's undo button. Every edit is committable; any mistake is `git reset` away. Also: backup, attribution, collaboration. |
| **GitHub** | The remote. Off-machine backup, and the host that makes `gh repo create --template` work. (Distinct from git — git is local.) |
| **venv** | Per-project dependency isolation. NOT a security sandbox — it stops dependency collisions, not destructive commands. |
| **LM Studio** | The local inference server (`localhost:1234`). Most common failure point — verify the correct non-thinking model is loaded (Pre-Flight Step 0). |
| **OpenCode** | The coding agent. Reads CLAUDE.md/AGENTS.md + CONVENTIONS.md automatically, talks plain English, writes files to disk, runs commands. Install: `brew install sst/tap/opencode`. |
| **Local LLM** | The model OpenCode uses. MUST be non-thinking (e.g. `qwen/qwen3-coder-next` via LM Studio). In OpenCode: `/models` → select under "lms" provider. |
| **Frontier LLM** | Escalation model. Used when local hits a reasoning wall (Rule 2). Switch inside OpenCode with `/models`. |
| **pytest / CI** | The test harness = **ground truth**. The agent does not decide if it succeeded — the tests do. |
| **The docs** | The memory layer for stateless LLMs (this file + CLAUDE.md + CONVENTIONS.md + docs/ + tasks/). |
| **AGENTS.md** | Symlink to CLAUDE.md. OpenCode's preferred filename; symlink keeps content in sync with no duplication. |

---

## Document Map

Read these files from the repository in this exact order:

| Order | File | Purpose | When to read |
|-------|------|---------|--------------|
| 1 | `README.md` | System overview + working loop | Always — first |
| 2 | `CLAUDE.md` | Project identity, stack, guardrails | Always — every session |
| 3 | `CONVENTIONS.md` | Code style and patterns | Always — every session |
| 4 | `opencode.json` | OpenCode model configuration | Setup + model changes |
| 5 | `docs/PRODUCT.md` | What we're building and why | New features |
| 6 | `docs/ARCHITECTURE.md` | Data models, API, key flows | Any code change |
| 7 | `docs/DECISIONS.md` | Why choices were made | Before suggesting alternatives |
| 8 | `docs/TESTING.md` | How we test | Writing or running tests |
| 9 | `tasks/CURRENT.md` | Active task spec | Every coding session |
| 10 | `tasks/BACKLOG.md` | Upcoming work queue | Planning sessions |

---

## Hard Rules (Non-Negotiable — Apply Even When Unsupervised)

> These exist because they are silent, hard-to-diagnose failures that will
> waste hours if violated — especially when running unattended and no
> human is awake to catch them. Do not override without explicit human
> instruction in `tasks/CURRENT.md`.

### Rule 1 — The model must NOT be a thinking model

A thinking model emits its output into `reasoning_content` and leaves `content`
empty, which breaks agent parsing (empty/invalid response → silent failure or
JSON error).

- The active model in OpenCode MUST be non-thinking.
- Local non-thinking models: `qwen/qwen3-coder-next` (verified working).
- Local thinking models to NEVER use as agent: `qwen3.6-35b-a3b` and any
  model with "thinking" or "reasoner" in the name.
- Frontier models (Claude, GPT) are safe — they are not thinking models.
- Verify before relying: see Pre-Flight Step 0 — confirm `content` is
  populated and `reasoning_content` is empty or absent.

### Rule 2 — Escalation tripwire (prevents error-correction spirals)

A weaker local model can loop: bad fix → new error → bad fix → ... burning
time and introducing technical debt. Cap it hard.

- If the SAME error fails to resolve after TWO attempts, STOP.
- Escalate: switch to a frontier model inside OpenCode (`/models` → Claude
  or GPT), OR halt and notify the human (Rule 4).
- Never let the loop retry the same failing fix more than twice.

### Rule 3 — Adapt the template to the actual stack before first commit

The template defaults to **FastAPI + PostgreSQL + pytest**. If THIS project's
stack differs (e.g. SQLite, a different framework, no DB), you MUST adapt
these files BEFORE bootstrapping:

- `scripts/bootstrap.sh` — the dependencies installed
- `.github/workflows/ci.yml` — the services block (remove Postgres for SQLite)
- `CONVENTIONS.md` — framework-specific patterns
- `docs/ARCHITECTURE.md` — the infrastructure section

Do not run a Postgres CI service for a project that does not use Postgres.

### Rule 4 — Halt-and-notify conditions (stop; do not guess)

When unsupervised, STOP and write a clear note in `tasks/CURRENT.md` (under
"Notes / Context") rather than proceeding, if ANY of these hold:

- Tests still fail after escalation (Rule 2 exhausted)
- A destructive operation is implied (`rm -rf`, dropping tables,
  `git push --force`, deleting files outside the project)
- The task is ambiguous and proceeding would require inventing a product or
  architecture decision (that is the human's job)
- LM Studio at `localhost:1234` is unreachable
- Acceptance criteria in `CURRENT.md` cannot be met as written

The dangerous failure is acting confidently when wrong — not stopping.

### Rule 5 — Tests are ground truth, not your self-assessment

Never report a task complete based on your own judgment. Run `pytest`. A task
is done only when its acceptance-criteria tests pass AND no existing tests
broke. "It looks correct" is not evidence. The tests are.

---

## Step 0 — Pre-Flight Check (run BEFORE anything else)

> Do not write code or instantiate until all checks pass. Fail LOUDLY if any
> check fails — a silent wrong-model is the most common and most expensive failure.

**1. LM Studio reachable + correct (non-thinking) model loaded:**

```bash
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder-next","messages":[{"role":"user","content":"Reply with just OK"}],"max_tokens":5}'
```

PASS only if BOTH:
- the response `model` field matches `qwen/qwen3-coder-next` (not a fallback), AND
- `content` is populated (e.g. `"OK"`) and `reasoning_content` is absent or empty.

If `model` echoes a different name → wrong model loaded, fix in LM Studio.
If `content` is empty and `reasoning_content` is populated → thinking model
loaded, swap to non-thinking (Rule 1).

**2. git available and identity configured:**
```bash
git --version && git config user.name && git config user.email
```

**3. Python 3.12+:**
```bash
python3 --version
```

**4. gh CLI authenticated:**
```bash
gh auth status
```

**5. OpenCode installed:**
```bash
opencode --version
```

If any check fails, STOP and report exactly which one. Do not proceed.

---

## The System in One Diagram

```
Human intention
      │
      ▼
Plain English to OpenCode   ← just talk; no need to pre-write a detailed spec
      │
      ▼
Pre-Flight Check (Step 0)   ← verify LM Studio / model / git / gh
      │
      ▼
OpenCode
      │
      ├── auto-reads: CLAUDE.md (or AGENTS.md symlink) + CONVENTIONS.md
      ├── reads: ARCHITECTURE.md + DECISIONS.md (on demand / when relevant)
      │
      ├── Plans the change
      ├── Writes code to disk
      └── Reports back
      │
      ▼
Tests run: pytest   ← GROUND TRUTH
      │
      ├── Pass → done, update docs, next task
      └── Fail → paste error into OpenCode, loop
                   │
                   └── Same error twice? → STOP (Rule 2): escalate or halt
```

---

## Document Roles Explained

### `CLAUDE.md` / `AGENTS.md` — The Brain

The single most important file. OpenCode reads `AGENTS.md` automatically at
startup (which symlinks to `CLAUDE.md` — same content, one source of truth).
Contains: what the project is, tech stack, code conventions, **what NOT to do**
(guardrails), and the **LLM correction log** (every mistake logged here prevents
recurrence).

**Maintain it like this:** every time the LLM does something wrong and you
correct it, add a row to the correction log. The file gets smarter over time.

### `CONVENTIONS.md` — The Style Guide

Code patterns with explicit good/bad examples. Read every session.

### `docs/ARCHITECTURE.md` — The Map

Data models, API routes, key flows. Prevents the LLM inventing schema.

### `docs/DECISIONS.md` — The Memory

Why non-obvious choices were made. "Do not suggest X" entries stop the LLM
re-litigating solved problems every session.

### `docs/PRODUCT.md` — The Why

Evergreen product context: problem, users, non-goals.

### `docs/TESTING.md` — The Test Contract

Testing strategy, conventions, fixtures. Tests are ground truth (Rule 5).

### `tasks/CURRENT.md` — The Session Spec (optional with OpenCode)

With OpenCode you can just talk — it doesn't require a pre-written spec.
Use this file when the task is complex enough to warrant writing it out,
or when you want to capture acceptance criteria explicitly. Keep it simple:
a few bullet points beats a bureaucratic template.

### `tasks/BACKLOG.md` — The Queue

Prioritized work. Done tasks move here; next becomes CURRENT.md.

---

## Bootstrap Sequence

### For LLMs executing this for the first time on a new project:

**Step 0 — Pre-Flight Check** (above). Do not skip.

**Step 1 — Fetch the template**
```bash
gh repo create <project-name> \
  --template developer-learner/sw-dev-blueprint \
  --private
cd <project-name>
```

**Step 2 — Read all documents**
Read every file in the Document Map before writing a single line of code.

**Step 3 — Adapt the stack (Rule 3)**
Confirm the default stack (FastAPI + Postgres) matches this project.
If not, edit `bootstrap.sh`, `ci.yml`, `CONVENTIONS.md`, `ARCHITECTURE.md` first.

**Step 4 — Run bootstrap**
```bash
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh <project-name>
```

**Step 4.5 — Strip template-only files (curated)**

These files served their one-time purpose. Remove them:

```bash
rm scripts/bootstrap.sh
rm scripts/new-project.sh  # if present
```

**Do NOT remove:**
- `BLUEPRINT.md` — the operating manual for any future LLM session on this project
- `CLAUDE.md` / `AGENTS.md` — project identity and correction log
- `CONVENTIONS.md` — code style rules
- Any `docs/` file — architecture, decisions, product, testing are all living documents

The rule: preserve the memory layer (docs + agent config). Delete the one-shot setup scripts.

If you cloned the template rather than using "Use this template," the template's git history is inherited. Start fresh:

```bash
rm -rf .git && git init
```

**Step 5 — Fill in the blanks**

Verify every template placeholder is replaced before first commit. This grep targets placeholder-shaped brackets `[UPPERCASE]`, `[UPPER_CASE]`, and `[Capitalized phrase]` while ignoring code like `["key"]` or `[-1, 1]`:

```bash
grep -rnE '\[[A-Z][A-Z_ ]+\]|\[[A-Z][a-z]+ [a-z]' . \
  --include='*.md' --include='*.json' --include='*.sh' \
  --include='*.plist' --include='*.yml' --include='*.yaml' \
  | grep -v '.git/' | grep -v 'node_modules/' | grep -v '.build/'
```

This must return **zero project-specific placeholders** before commit.

Carve-out: the `## Template` format block in `docs/DECISIONS.md` uses placeholder-shaped brackets intentionally — it is an evergreen format reference for future LLM entries. Either mark it with a comment the grep can exclude, or simply note that this block is exempt.

Commonly missed files (not exhaustive — the grep is the source of truth):

| File | What to check |
|------|---------------|
| `CLAUDE.md` | Project name, description, contacts (`[NAME]`) |
| `docs/PRODUCT.md` | Problem, users, metrics |
| `docs/ARCHITECTURE.md` | Infrastructure, data models |
| `docs/DECISIONS.md` | Stale template rows (not the Template block) |
| `docs/TESTING.md` | Framework-specific commands, fixtures |
| `CONVENTIONS.md` | Language-specific examples |
| `tasks/CURRENT.md` | `[TASK_NAME]` and spec body |
| `tasks/BACKLOG.md` | Template task entries |

**Step 6 — Start coding**
```bash
# Confirm LM Studio is running with qwen/qwen3-coder-next loaded, then:
opencode
# Inside OpenCode: /models → select "Qwen3 Coder Next (local)" under "lms"
# Then just describe what you want to build in plain English
```

---

## LLM Routing Decision Tree

```
What kind of task is this?
│
├── Boilerplate / CRUD / tests / known patterns
│     └── Local model via OpenCode (free, fast)
│           /models → qwen/qwen3-coder-next under "lms"
│
├── Multi-file refactor / moderate complexity
│     └── Local model via OpenCode — it handles multi-file natively
│
├── Hitting a reasoning wall / Rule 2 escalation
│     └── Switch model inside OpenCode
│           /models → Claude or GPT (frontier)
│
└── Greenfield architecture / major product decision
      └── Discuss in chat (Claude.ai) first
            → Write outcome into DECISIONS.md
            → Tell OpenCode what to build
```

**Cost note:** Frontier models cost money. Local handles 80% of tasks free.
Switch to frontier only when local demonstrably can't solve the problem.

---

## OpenCode Configuration

OpenCode config is in `~/.config/opencode/opencode.json` (global) or
`opencode.json` at the project root (project-level).

**Critical naming gotcha:** use provider key `lms`, NOT `lmstudio`.
The name `lmstudio` collides with OpenCode's built-in catalog and loads
wrong model names. This is a known issue as of OpenCode 1.15.x.

```json
{
  "providers": {
    "lms": {
      "name": "LM Studio local",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1",
        "apiKey": "lm-studio"
      }
    }
  },
  "models": {
    "default": "lms::qwen/qwen3-coder-next"
  }
}
```

> See the `opencode.json` file in this repo for the full working config.

---

## The Maintenance Contract

| Trigger | Action | File |
|---------|--------|------|
| New dependency added | Document it | `ARCHITECTURE.md` |
| Non-obvious decision made | Log it with reasoning | `DECISIONS.md` |
| New code pattern established | Add example | `CONVENTIONS.md` |
| LLM made a mistake you corrected | Add guard | `CLAUDE.md` correction log |
| Task completed | Move to completed table | `BACKLOG.md` |
| Schema changed | Update data models | `ARCHITECTURE.md` |

**The correction log rule** is the most important habit. It turns every LLM
mistake into a permanent improvement. A project 6 months in should have a
`CLAUDE.md` full of hard-won guards — that's a sign the system is working.

---

## Project Completion / Maintenance Transition

When a project reaches feature-complete and enters maintenance mode:

1. **Archive CURRENT.md** — move its content to BACKLOG.md Completed table,
   then clear CURRENT.md to reflect no active task
2. **Mark backlog** — review tasks/BACKLOG.md, close or defer remaining items
   with notes
3. **Final correction-log review** — ensure every LLM mistake from the
   development cycle is logged in CLAUDE.md. Unlogged corrections expire
   when sessions end
4. **Update PRODUCT.md** — flip status from "in development" to "maintenance"
   or "complete" in the Feature Flags table
5. **README** — if the app is distributed as a binary, add an "End users"
   section alongside the "Developers" build instructions
6. **Run curated cleanup** — Step 4.5 (strip template-only files) if not done
   already

The project is not "dead" — it is transitioned. Future sessions should check
BACKLOG.md first rather than CURRENT.md.

---

## Anti-Patterns to Avoid

**Over-speccing CURRENT.md** — OpenCode takes plain English. You don't need
a detailed acceptance-criteria checklist for every task. Write it out only
when the task is genuinely complex or you need explicit boundaries.

**Stale ARCHITECTURE.md** — If the LLM's model of your schema is wrong,
everything built on it is wrong. Update after every schema change.

**Skipping DECISIONS.md** — Every unlogged decision gets re-litigated next
session. The LLM has no memory; this is the only thing carrying context forward.

**Using the wrong provider name** — `lmstudio` in opencode.json silently loads
cloud model names instead of your local model. Always use `lms`.

**Loading a thinking model** — Silent failure. Always verify with Pre-Flight
Step 0 before a session.

**Over-relying on frontier for everything** — 80% of tasks are routine.
Local handles them free. Save frontier for actual reasoning walls.

**Abdication** — The LLM fills any vacuum, including product decisions. You own:
what to build, acceptance criteria, architecture decisions, final review.

**Trusting self-reported success** — Only passing tests confirm success (Rule 5).

**Letting the error loop run** — Two strikes, then escalate or halt (Rule 2).

---

## Quick Reference Card

```
Start session:    Pre-Flight (Step 0) → opencode → /models → select lms model
During session:   Just talk in plain English
                  /models      switch model (local ↔ frontier)
                  git diff     review changes
                  git reset    roll back
After session:    Run pytest → log decisions → update architecture
Stuck on design:  Come to Claude.ai → spec it → tell OpenCode
Test failing:     Paste full error into OpenCode
Same error twice: STOP → /models → switch to frontier OR halt (Rule 2)
Wrong model bug:  Re-run Pre-Flight Step 0 — check LM Studio
Provider issues:  Verify opencode.json uses "lms" not "lmstudio"
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
