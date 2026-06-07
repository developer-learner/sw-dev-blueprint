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

**The execution model:** You talk to the **PM agent** (`@pm`) in plain English.
The PM translates your instruction into a structured PRD (`tasks/CURRENT.md`).
Once you approve, `scripts/orchestrate.sh` drives the build→test loop:
it calls the **Architect** to plan, then **Build** to write `src/`, then
**Test** to write `tests/` (from the PRD), runs `scripts/phase-gate.sh`
after each phase, runs pytest, and routes failures per Rule 2/7. Results
flow back to the PM for your review.

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
| **pytest / CI** | The test harness = **ground truth**, now machine-readable via `.cache/test-report.json`. |
| **The docs** | The memory layer for stateless LLMs (this file + CLAUDE.md + CONVENTIONS.md + docs/ + tasks/). |
| **AGENTS.md** | Symlink to CLAUDE.md. OpenCode's preferred filename; symlink keeps content in sync with no duplication. |
| **Four agents** (pm/architect/build/test) | Role pipeline: PM writes PRD, Architect plans + orchestrates, Build writes `src/`, Test writes `tests/`. Defined in `opencode.json`. |
| **phase-gate.sh** | Mechanical INV-2 enforcement — rejects cross-boundary edits before commit. |

---

## Document Map

Read these files from the repository in this exact order:

| Order | File | Purpose | When to read |
|-------|------|---------|--------------|
| 1 | `README.md` | System overview + working loop | Always — first |
| 2 | `CLAUDE.md` | Project identity, stack, guardrails | Always — every session |
| 3 | `CONVENTIONS.md` | Code style and patterns | Always — every session |
| 4 | `opencode.json` | OpenCode model + agent configuration | Setup + model/agent changes |
| 5 | `.opencode/prompts/*.md` | Agent role prompts (pm/architect/build/test) | Agent setup |
| 6 | `docs/PRODUCT.md` | What we're building and why | New features |
| 7 | `docs/ARCHITECTURE.md` | Data models, API, key flows | Any code change |
| 8 | `docs/DECISIONS.md` | Why choices were made | Before suggesting alternatives |
| 9 | `docs/TESTING.md` | How we test + machine-readable report format | Writing or running tests |
| 10 | `tasks/CURRENT.md` | **PRD** — acceptance criteria, flagged assumptions, frozen on approval | Every session — test oracle |
| 11 | `tasks/BACKLOG.md` | Upcoming work queue | Planning sessions |
| 12 | `scripts/phase-gate.sh` | Mechanical INV-2 gate (build↔test boundary) | After each phase |

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
- In the role pipeline, escalation goes UP one layer:
  - Test failing twice → Build agent is not the fix (the approach is wrong) → re-assign Architect to re-plan.
  - Architect plan producing failing tests twice → the PRD is contradictory or ambiguous → escalate to PM.
  - PM cannot resolve → human must decide (Rule 4).

### Rule 3 — Adapt the template to the actual stack before first commit

The template defaults to **FastAPI + SQLite + pytest**. CI does NOT run
Postgres by default. If THIS project uses Postgres, you MUST adapt these
files BEFORE bootstrapping:

- `.gate-paths` — if your project uses directories other than `src/` and `tests/`
- `scripts/bootstrap.sh` — add `asyncpg` to dependencies
- `.github/workflows/ci.yml` — uncomment the Postgres service block and
  its DATABASE_URL env in the test step
- `CONVENTIONS.md` — framework-specific patterns
- `docs/ARCHITECTURE.md` — the infrastructure section

For non-Postgres stacks (SQLite, no DB, etc.): the defaults are already
correct — just skip the CI Postgres blocks.

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

### Rule 6 — Tests derive from the PRD, not from the code

The test agent's source of truth is `tasks/CURRENT.md` acceptance criteria, written in EARS,
plus the API contract in `docs/ARCHITECTURE.md`. It may read interface
signatures and routes to know what to call; it must NOT infer "correct"
behavior from `src/` implementation. A test written against the code only
proves the code is self-consistent — a consistent bug passes. The frozen
PRD is the sole oracle (INV-1).

### Rule 7 — Role write-boundaries; escalate up, never sideways

- Build edits `src/` only. Test edits `tests/` only. Neither edits the PRD
  or the other's directory (INV-2).
- Enforced by `scripts/phase-gate.sh` (mechanical), not agent permissions
  alone — OpenCode agent permissions are non-transitive (a restricted agent
  can bypass limits via the Task tool).
- On a wall, halt and escalate UP one layer (see Rule 2 escalation paths).
  No layer invents the decision of the layer above it.

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
Human casual instruction
      │
      ▼  (PM translates — lossy, the only human-checked step)
PRD + acceptance criteria  [tasks/CURRENT.md, committed]
      │  ← HUMAN APPROVAL GATE (Status: Approved). Criteria freeze here.
      ▼
Architect → eng plan (ARCHITECTURE.md / DECISIONS.md)
      │
      ▼
Build (src/ only) ──► Test (tests/ only, derives from PRD) ──► pytest --json-report
                                                                        │
                                                pass → done   fail → route up (Rule 2/7)
                                                                    ├ build bug → Build
                                                                    └ spec wrong → Architect → PM → human
```

---

## Bootstrap Sequence — Instantiate a New Project

> Read this if you are an AI coding agent and a user has given you this
> repo's URL plus a project name, and asked you to create a project.
> You do everything. The user runs no terminal commands. You have a shell,
> git, and `gh` authed as the repo owner.

**Inputs you were given:** this repo URL, and a project name (call it NAME).

**Do these in order. Do not skip the gate at the end.**

### Step 0 — Pre-Flight Check

Run the Pre-Flight Check section above. Do not skip. If any check fails,
halt and report exactly which one.

### Step 1 — Create the repo from this template

Default is **private**. If the user explicitly asked for a public repo, use
`--public` instead.

```bash
gh repo create NAME --template developer-learner/sw-dev-blueprint --private --clone
cd NAME
```

Verify before continuing:

```bash
gh repo view NAME --json isTemplate,visibility
```

Expect `isTemplate: false`, visibility matching the flag you chose.
If creation failed (name collision, auth, network), halt and tell the user.
Do not improvise a name.

### Step 2 — Read all documents (you)

Read every file in the Document Map before writing a single line of code.
This is not optional.

### Step 3 — Check if the user already gave a spec

Did the user give you more than a repo URL and a name? Examples of "more":
"Build a CLI for parsing CSV files," "A FastAPI backend for tracking
expenses," or any description of what the project does.

- **If yes:** Use what they gave you. Identify gaps (stack, team contacts,
  deployment target) and ask only about those — do not re-ask for what
  you already know.
- **If no:** Ask what they're building. You must not invent a description.

From that conversation, write: description and status in CLAUDE.md and
README; the real tech stack in CLAUDE.md (replace the default template
stack); initial notes in docs/; the Key Contacts rows in CLAUDE.md (or
ask for their names). You do not need a full architecture yet — that grows
with the code.

### Step 4 — Curated cleanup

Delete the one-shot setup scripts; preserve the memory layer (`BLUEPRINT.md`, `CLAUDE.md` / `AGENTS.md`, `CONVENTIONS.md`, all of `docs/`):

```bash
rm -f scripts/bootstrap.sh scripts/new-project.sh
```

If unsure whether a file is memory-layer or scaffold, halt and ask (Rule 4).

### Step 5 — Adapt the stack

Apply Rule 3.

### Step 6 — Fill every placeholder

Replace all template placeholders: `[PROJECT_NAME]`, `[NAME]`, `[DATE]`,
`[One paragraph...]`, bracketed stack examples in CLAUDE.md, template
rows in tasks/ and docs/, etc.

### Step 7 — GATE: verify with a check, not your own judgment

You cannot trust "I filled everything in." Run:

```bash
grep -rnE '\[[A-Z][A-Z_ ]+\]|\[[A-Z][a-z]+ [a-z]' . \
  --include='*.md' --include='*.json' --exclude-dir=.git \
  --exclude='DECISIONS.md' --exclude='BLUEPRINT.md'
```

If it returns ANY lines, a placeholder survived — go back to Step 6,
fill, re-run, repeat until it returns nothing.

`DECISIONS.md` and `BLUEPRINT.md` are excluded: the first uses intentional
placeholder brackets in its `## Template` format block; the second lists
`[PROJECT_NAME]` and `[NAME]` as fill examples in Step 6.
Everything else must be clean.

### Step 8 — First commit and push

Only after the gate is clean and the stack matches:

```bash
git add -A && git commit -m "Instantiate NAME from sw-dev-blueprint"
git push -u origin main
```

**The contract:** the user gave you a URL and a name. Everything else —
description, stack, structure, contents — you derive from talking to them
and write yourself. The grep gate, not your self-report, confirms you
finished.

**After first commit:** the project is live. Future sessions start at
`tasks/CURRENT.md` or plain English.

---

## Cost Model

| Role | Model tier | Why |
|------|-----------|-----|
| Build, Test | Local (`lms/qwen/qwen3-coder-next`) | Free, fast, handles 80% of tasks (routine code + tests) |
| PM, Architect | Frontier (`<frontier>`) | Spec work and reasoning walls — local is not strong enough for ambiguous or architectural decisions |

**Rule:** use frontier for build/test only when Rule 2 fires (same failure twice) and a re-plan doesn't fix it.

---

## OpenCode Configuration

See `opencode.json` at the project root for the working config.

**Naming gotcha:** use provider key `lms`, NOT `lmstudio` — the latter collides with OpenCode's built-in catalog and silently loads cloud model names instead of your local model. Known issue as of OpenCode 1.15.x.

---

## The Maintenance Contract

| Trigger | Action | File |
|---------|--------|------|
| Non-obvious decision made | Log it with reasoning | `DECISIONS.md` |
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
6. **Run curated cleanup** — Step 4 (strip template-only files) if not done
   already

The project is not "dead" — it is transitioned. Future sessions should check
BACKLOG.md first rather than CURRENT.md.

---

## Anti-Patterns to Avoid

**Stale ARCHITECTURE.md** — If the LLM's model of your schema is wrong,
everything built on it is wrong. Update after every schema change.

**Skipping DECISIONS.md** — Every unlogged decision gets re-litigated next
session. The LLM has no memory; this is the only thing carrying context forward.

**Loading a thinking model** — Silent failure. Always verify with Pre-Flight
Step 0 before a session.

**Over-relying on frontier for everything** — 80% of tasks are routine.
Local handles them free. Save frontier for actual reasoning walls.

**Trusting self-reported success** — Only passing tests confirm success (Rule 5).

**Tests that confirm the code instead of the spec** — INV-1 violation. The
test agent must derive expected behavior from the PRD, not from `src/`.

---

---

## Files the LLM Should Never Touch Without Explicit Instruction

- `DECISIONS.md` — human-authored record of deliberate choices; do not edit without explicit instruction
- `CLAUDE.md` correction log — human-maintained; rows added per the rule, not by the LLM
- `tasks/BACKLOG.md` completed section — historical record; entries move here from `CURRENT.md`, not edited

---

*This document is the entry point. Everything else flows from it.*
*Keep this file updated as the system evolves.*
*Keep this document lean — prune redundancy, cross-reference instead of duplicating.*
*Length is a smell to investigate, not a hard limit; there is no enforced line count.*
