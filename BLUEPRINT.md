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

**The execution model — a capability ladder (D-27):** each tier gets exactly
the scope its capability class can carry, and the shell owns all procedure.

| Tier | Where it runs | Produces |
|------|---------------|----------|
| **CEO** (human) | conversation | business intent; approvals |
| **TPM** (frontier LLM) | **web chat** (D-38) or scoped repo agent via `tpm-agent.sh` (D-39) | PRD, ERD + `contracts.json`, the test suite |
| **Conductor** (any capable LLM) | whatever chat agent the CEO chooses (Claude Code, OpenCode, a plain shell) | no artifacts — runs the scripts, shuttles TPM I/O, reports to the CEO (D-40) |
| **EM** (mid-tier LLM) | one HTTP completion, no tools (`scripts/llm-call.sh`, D-53) | `tasks/plan.json` (decomposition), `tasks/diagnosis.json` (consults) — shell writes both |
| **Coder** (local LLM) | one HTTP completion, no tools (`scripts/llm-call.sh`, D-53) | one file per task, sentinel-wrapped in the reply |

Tests are **run by the shell** (`scripts/orchestrate.sh` → pytest inside the
sandbox) — there is no test agent. The TPM's spec enters the repo only through
`scripts/refreeze.sh` (a human-approved diff), after which it is frozen and
hash-pinned. The orchestrator validates the EM's plan mechanically
(`scripts/validate-plan.py`), walks the task DAG, calls the coder for each
task (one `scripts/llm-call.sh` HTTP completion, no tools), writes the reply
to exactly the task's file, then runs pytest inside the sandbox (`--network
none`, repo mounted read-only, `.cache/` writable) and gates every step. A
feature is done when the FULL frozen suite is green. See `docs/TPM-ROLE.md` for the top tier's
job description and `docs/ESCALATION.md` for how failures climb.

**No agent harness sits in the execution path (D-53).** EM and coder have no
filesystem or tool access at all — the orchestrator reads whatever context a
call needs, sends one completion, and writes the reply to disk itself. The
conductor is the only agent-shaped seat in the whole system, and it never
touches trusted state (denied on `tests/`, `scripts/`, `src/`, the control
plane); which chat tool plays that seat is a preference, not an architecture
decision.

**The shape of the whole thing is neurosymbolic — naming it, for once.** Every
tier generates probabilistically and is checked symbolically before the next
tier consumes anything: JSON Schema at the door (`scripts/schemas/`), semantic
consistency at the ledger (`scripts/validate-plan.py` — target uniqueness, DAG
acyclicity, the oracle-mapping bijection, referential integrity against frozen
contract ids), and satisfiability entailment before a spec is installable at
all (D-78 `spec_preflight`). `scripts/.approved/contracts.json` is the domain
model those checks reason over — a versioned, human-approved formal
specification of a feature's entities and their relationships.

The door/ledger split is deliberate and load-bearing: schemas hold shape,
`validate-plan.py` holds meaning, and the boundary is written into
`plan.schema.json`'s own description field so neither layer drifts into the
other. Two corollaries the generic form of this idea omits — a symbolic check
binds only a seat that cannot route around it (hence Rule 7's write-boundaries
being physical rather than requested), and a check whose verdict nothing
consumes is decoration rather than a gate (D-85). Gate strength is priced
against blast radius, never maximized: Rule 9.

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
| **GitHub** | The remote. Off-machine backup, host for `gh repo create --template`, and the fleet's drift-check CI (D-33). |
| **venv** | Per-project dependency isolation. NOT a security sandbox — it stops dependency collisions, not destructive commands. |
| **podman** | The sandbox pytest/smoke_check runs in. `scripts/sandbox-run.sh` mounts the repo read-only, disables the network, and grants `.cache/` read-write for the test report (D-30). Post-D-53 nothing agent-side runs *inside* the sandbox — the EM and coder are host-side HTTP calls, and their output is guarded by shell-owned lanes (phase-gate.sh), not by container mounts. The sandbox exists so untrusted **generated code** executes in isolation, not to contain the agents that produced it. |
| **LM Studio** | The local inference server (`localhost:1234`) for the coder tier (and, typically, the EM tier). Most common failure point — verify the correct non-thinking model is loaded (Pre-Flight Step 0). |
| **scripts/llm-call.sh** | The ONLY way the pipeline talks to a model (D-53): one bare HTTP completion per call, no harness, no tools, no memory between calls. Reads the CEO's role→model mapping and hard-halts rather than silently substituting a model if a role is unmapped. |
| **A conductor (any chat agent)** | The CEO's single interface (D-40) — Claude Code, OpenCode, or anything similar. Runs the scripts and reports back; the CEO runs no commands. Never in the trust-critical path: EM/coder don't go through it (D-53), so the choice of conductor is a preference, not an architecture decision. |
| **TPM (frontier LLM)** | Runs in a web chat the human operates, outside the conductor. Authors the spec and the test suite; answers escalation batches. Never touches the repo — its output enters via `scripts/refreeze.sh`. |
| **EM (mid-tier LLM)** | One `scripts/llm-call.sh` completion, no tools. Decomposes the frozen spec into `tasks/plan.json`; diagnoses failures on consult. The shell writes `tasks/plan.json` / `diagnosis.json` from its reply — the model never touches the filesystem. Advisory — the shell decides. |
| **Coder (local LLM)** | One `scripts/llm-call.sh` completion, no tools. MUST be non-thinking; the CEO picks which loaded LM Studio model backs it in `~/.config/sw-dev-blueprint/models.env` — the repo never names a model. Replies with the one file its task names, sentinel-wrapped; the shell writes it to disk. |
| **pytest / CI** | The test harness = **ground truth**, machine-readable via `.cache/test-report.json`. The suite is TPM-authored and frozen; the shell runs it. |
| **The docs** | The memory layer for stateless LLMs (this file + CLAUDE.md + CONVENTIONS.md + docs/ + tasks/). |
| **AGENTS.md** | Symlink to CLAUDE.md. OpenCode's preferred filename, kept for CEOs who use OpenCode as their conductor; symlink keeps content in sync with no duplication. |
| **phase-gate.sh** | Mechanical lane + integrity enforcement — per-phase write whitelists, control-plane manifests, frozen-spec hashes. Fail-closed. |
| **.template-version** | This project's link to the template it was born from (D-33). `scripts/check-drift.sh` compares against it; `scripts/update-template.sh` pulls upstream control-plane fixes. |

---

## Document Map

Three tiers. An agent executing the Bootstrap Sequence reads every file
below, tier by tier, in order. A human adopts progressively: **tier 1 before
your first run** (`QUICKSTART.md` walks it), **tier 2 before authoring your
first real spec**, **tier 3 on demand** — when a run fails, when you operate
a fleet, or as reference. Reading everything up front is not the adoption
path.

**Tier 1 — before your first run:**

| Order | File | Purpose |
|-------|------|---------|
| 1 | `README.md` | System overview + working loop |
| 2 | `QUICKSTART.md` | Zero to a green frozen suite on one Linux box — the example build |
| 3 | `CLAUDE.md` | Project identity, stack, guardrails, capability ladder (every session) |
| 4 | `CONVENTIONS.md` | Code style and patterns (every session) |
| 5 | `examples/minimal-spec/` | What the TPM's four artifacts actually look like — a real frozen spec |

**Tier 2 — before your first real spec:**

| Order | File | Purpose |
|-------|------|---------|
| 6 | `docs/TPM-ROLE.md` | The top tier's job description — how to run the TPM chat |
| 7 | `docs/CEO-PLAYBOOK.md` | Operator runbook for the human at the top of the ladder |
| 8 | `docs/PRODUCT.md` | What we're building and why |
| 9 | `docs/ARCHITECTURE.md` | Data models, API, key flows |
| 10 | `docs/TESTING.md` | How we test + machine-readable report format |
| 11 | `scripts/.approved/` | **The frozen spec** — PRD, ERD, contracts, VERSION (every session once it exists — the oracle) |
| 12 | `tasks/CURRENT.md` | Session notes: active work, halt notes, status (every session) |
| 13 | `tasks/BACKLOG.md` | Upcoming work queue (planning sessions) |

**Tier 3 — when something fails, or reference:**

| Order | File | Purpose | Trigger |
|-------|------|---------|---------|
| 14 | `docs/ESCALATION.md` | The failure ladder + TPM bundle format | First run that exits 2 |
| 15 | `docs/DECISIONS.md` | Why choices were made (the ladder: D-26..D-84) | Before suggesting alternatives |
| 16 | `scripts/orchestrate.sh` + `scripts/phase-gate.sh` | The procedure owner + the gate | Before hand-running the pipeline internals |
| 17 | `docs/CONDUCTOR-ROLE.md` | System prompt for the conductor seat | Setting up a conductor |
| 18 | `opencode.json` + `.opencode/prompts/*.md` | OpenCode conductor config (optional, D-53) + the EM/coder prompt surface read by `scripts/llm-call.sh` | Conductor setup; prompt work |
| 19 | `docs/DEV-VM-SETUP.md` | The macOS host / Linux VM split | macOS hosts — required before any run there |

> **Platform note:** `scripts/orchestrate.sh` hard-refuses to run on macOS
> and requires a Linux environment (Lima VM on Apple Silicon, or bare
> Linux). `scripts/refreeze.sh` runs on the macOS host. The split-brain is
> deliberate — see `docs/DEV-VM-SETUP.md` for the setup that made it
> work in practice.

> `docs/SANDBOX-VALIDATION.md` is a historical validation record from
> 2026-06-07 (pre-D-53); kept for provenance, not current setup guidance.

---

## Hard Rules (Non-Negotiable — Apply Even When Unsupervised)

> These exist because they are silent, hard-to-diagnose failures that will
> waste hours if violated — especially when running unattended and no
> human is awake to catch them. Do not override without explicit human
> instruction in `tasks/CURRENT.md`.

### Rule 1 — The coder model must NOT be a thinking model

A thinking model emits its output into `reasoning_content` and leaves `content`
empty, which breaks agent parsing (empty/invalid response → silent failure or
JSON error).

- The active coder model MUST be non-thinking.
- Which specific model that is, is the CEO's choice — never hardcoded in
  this blueprint or anywhere in the repo; it lives in the CEO's own
  `~/.config/sw-dev-blueprint/models.env` (D-53). Avoid any model with
  "thinking" or "reasoner" in the name.
- Frontier models (Claude, GPT) are safe — they are not thinking models.
- Verify before relying: see Pre-Flight Step 0 — confirm `content` is
  populated and `reasoning_content` is empty or absent.

### Rule 2 — Escalation is bounded and climbs the ladder (never loops sideways)

A weaker model can loop: bad fix → new error → bad fix → ... burning time and
introducing technical debt. Cap it hard.

- **Inside the pipeline this is mechanical (D-29):** the orchestrator owns all
  counters — `MAX_TASK_STRIKES=2`, then an EM consult; bounded brief/plan
  revisions; then a batched TPM bundle in
  `.pipeline-state/escalations/BATCH.md`. No agent retries on its own.
- **Outside the pipeline (interactive sessions), apply the same discipline
  manually:** if the SAME error fails to resolve after TWO attempts, STOP.
  Escalate up one tier or halt and notify the human (Rule 4).
- Escalation goes UP, never sideways: coder failing twice → the task brief or
  plan is wrong (EM's problem), not a reason for more coder retries. Plan
  revisions failing → the spec is wrong (TPM's problem). The TPM cannot
  resolve → the human decides.

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

Per-project adaptations belong in `scripts/.manifest-project`; files listed in
`scripts/.manifest-template` are template-owned — change them in the template
and pull with `scripts/update-template.sh`, never by hand-editing the child
(D-33/D-34).

### Rule 4 — Halt-and-notify conditions (stop; do not guess)

When unsupervised, STOP and write a clear note in `tasks/CURRENT.md` (under
"Notes / Context") rather than proceeding, if ANY of these hold:

- The escalation ladder is exhausted (Rule 2) or the orchestrator exited 2
  with a TPM batch the human has not yet carried to the chat
- A destructive operation is implied (`rm -rf`, dropping tables,
  `git push --force`, deleting files outside the project)
- The task is ambiguous and proceeding would require inventing a product or
  architecture decision (that is the human's job)
- LM Studio at `localhost:1234` is unreachable, or podman is unavailable
  (the orchestrator refuses to run unsandboxed)
- The frozen spec cannot be met as written

The dangerous failure is acting confidently when wrong — not stopping.

### Rule 5 — Tests are ground truth, not your self-assessment

Never report a task complete based on your own judgment. The orchestrator
runs the frozen suite; a task is done only when its mapped tests pass, and a
feature is done only when the FULL frozen suite is green with no regressions.
"It looks correct" is not evidence. The tests are.

### Rule 6 — Tests derive from the spec, and nobody downstream writes them

The test suite is authored by the TPM from the PRD and the ERD contracts —
**before the implementation exists, by a tier that never sees it** (INV-1,
now structural). It enters the repo only via `scripts/refreeze.sh` and is
hash-pinned in `scripts/.approved/frozen-manifest`.

- No agent — EM, coder, or any interactive session — authors or edits tests.
- Tests may observe only the locked surface: imports from
  `contracts.entry_points`, routes from `contracts.routes` (INV-4, checked
  mechanically at freeze time by `scripts/check-test-surface.py`).
- A test written against the code only proves the code is self-consistent —
  a consistent bug passes. The frozen spec is the sole oracle.

### Rule 7 — Role write-boundaries are physical, not requested

- The EM writes `tasks/` only. The coder writes exactly the ONE file its
  task names. Nothing agent-side may touch `scripts/`, `tests/`, `.git/`,
  or `.githooks/`.
- Enforced structurally, not by prompts: post-D-53 the model replies never
  touch the filesystem — the **shell writes every artifact** from the reply
  (EM reply → `tasks/plan.json`; coder reply → the one file its task names,
  parsed from a sentinel block; any other path in the reply is a coder
  FAILURE, not a write). `scripts/phase-gate.sh` re-verifies the working
  tree after every phase and fails closed on any file outside the lane
  (fixed in `d2b5572` — the task-phase gate is now a hard halt again).
  Do not phrase boundaries as instructions to a model — asking a model to
  self-restrain does not substitute for the shell being the sole writer.
- On a wall, escalate UP one tier (Rule 2). No tier invents the decision of
  the tier above it.

### Rule 8 — Task briefs are precision tools, and atomicity is structural

Local coder-class models are strong at code generation but weak at agentic
follow-through: they will not reliably infer scope, self-check against an
acceptance condition, or flag ambiguity — they execute exactly what's
specified or they drift. The system absorbs this structurally:

- **One task = one file, validated mechanically.** `scripts/validate-plan.py`
  rejects any plan where a task names more than one file, two tasks share a
  file, or a task lacks an acceptance signal (mapped frozen tests or a
  `smoke_check`). Multi-file work must be split into dependent tasks.
- **Every brief the EM writes must be self-contained**: exact file path,
  exact signatures, exact inputs/outputs, the contract ids it implements.
  Zero inference gaps — if executing the brief correctly requires the coder
  to infer intent, the decomposition is wrong (that is an EM defect, and the
  escalation ladder routes it there).
- **End every brief with an explicit self-verify action** ("re-open `<file>`
  and confirm `<condition>`") — it reduces retries; Rule 5 still decides.

### Rule 9 — Gate strength proportional to blast radius (gate-symmetry)

Every seat's output artifact receives a mechanical validity check at handoff.
Gate density must be proportional to the artifact's blast radius — how much
downstream work an undetected defect destroys — and never inversely
proportional to the seat's capability:

- **High blast radius:** the TPM's frozen spec gates an entire pipeline run
  (all EM plans, all coder tasks, all test runs). D-78 (satisfiability
  preflight), D-80 (debt sweep), INV-4 (test surface), D-75 (red-before-green),
  and D-56 (external-capture verification) now apply BEFORE the spec is
  installable.
- **Medium blast radius:** the EM's plan gates the task DAG.
  `validate-plan.py` checks atomicity, coverage, mapping, and budget.
- **Lower blast radius:** the coder's single-file output gates one task.
  Phase gate (INV-2), D-68 (swallowed errors), lint, and mapped frozen tests
  all fire per task.

The design failure this rule prevents: the weakest seat (coder) had four
checks per task; the strongest seat (TPM) had only integrity checks (hashes,
INV-4) and zero semantic-validity checks on its spec. Defects entered ungated
at the top and burned the bottom of the ladder (M23's three TPM spec bugs;
all four M28 recuts). The principle from the M4 conductor postmortem applies:
capability changes the failure class, not the need for gates — strong models
fail quietly upstream where gates are absent; weak models fail loudly
downstream where they exist. Never omit a gate because the seat is capable.

---

## Step 0 — Pre-Flight Check (run BEFORE anything else)

> Do not write code or instantiate until all checks pass. Fail LOUDLY if any
> check fails — a silent wrong-model is the most common and most expensive failure.

**1. LM Studio reachable + correct (non-thinking) coder model loaded:**

```bash
# discover whatever model the CEO has loaded (never hardcode one)
MODEL=$(curl -s http://localhost:1234/v1/models | python3 -c \
  'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])')
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with just OK\"}],\"max_tokens\":5}"
```

PASS only if BOTH:
- the models endpoint returned at least one loaded model, AND
- `content` is populated (e.g. `"OK"`) and `reasoning_content` is absent or empty.

If no model is listed → nothing loaded, fix in LM Studio.
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

**5. Conductor available (whatever chat agent the CEO is using):**
Not the pipeline's dependency — EM/coder never go through it (D-53). Only
relevant if the CEO's chosen conductor needs its own check, e.g.
`opencode --version` if using OpenCode.

**6. podman available (the orchestrator refuses to run unsandboxed):**
```bash
podman info --format '{{.Host.Arch}}'
```

If any check fails, STOP and report exactly which one. Do not proceed.

---

## The System in One Diagram

```
CEO business intent ──► TPM (frontier LLM — web chat D-38 or scoped repo agent D-39)
                          │  writes PRD + ERD/contracts + the test suite
                          ▼
            scripts/refreeze.sh  ← CEO approves the diff (THE approval gate:
                          │        terminal y/N, or conductor-driven
                          │        --diff / --approve <hash> via the
                          │        conductor's own ask-prompt, D-42 — CEO
                          │        reads, then approves)
                          │  spec frozen: scripts/.approved/ + tests/, hash-pinned
                          ▼
            scripts/orchestrate.sh (shell owns ALL procedure)
                          │
              EM (one HTTP completion, no tools, D-53) ──► shell writes
              tasks/plan.json ──► validate-plan.py gate
                          │
              per task, in DAG order:
                Coder (one HTTP completion, no tools, D-53) replies with the
                file, sentinel-wrapped ──► shell writes it ──► phase-gate task
                ──► mapped frozen tests
                          │
              all tasks done ──► FULL frozen suite green = done
                fail → escalation ladder (retry → EM consult → bounded revisions
                        → batched TPM bundle → refreeze → affected subtree resumes)
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
ask for their names). The PRD itself is NOT yours to write — that is the
TPM's job, and it arrives via `scripts/refreeze.sh` (Rule 6).

### Step 4 — Run bootstrap, then curated cleanup

`scripts/bootstrap.sh` sets up the venv, git hooks (`core.hooksPath`), and
stamps `.template-version` with the template commit this child was born from
(the fleet's drift baseline, D-33). Verify the stamp took:

```bash
grep '^ref=' .template-version   # must NOT read ref=UNSTAMPED
```

If it reads `UNSTAMPED` (offline bootstrap), stamp later with
`scripts/update-template.sh --stamp`.

Then delete the one-shot setup scripts; preserve the memory layer
(`BLUEPRINT.md`, `CLAUDE.md` / `AGENTS.md`, `CONVENTIONS.md`, all of `docs/`)
and the control plane (`scripts/`, `.githooks/`):

```bash
rm -f scripts/bootstrap.sh scripts/new-project.sh
```

If unsure whether a file is memory-layer or scaffold, halt and ask (Rule 4).

### Step 5 — Adapt the stack

Apply Rule 3. Record adaptations in `scripts/.manifest-project`
(`bash scripts/regen-manifest.sh scripts/.manifest-project` after editing).

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

**After first commit:** the project is live. The first feature starts in the
TPM web chat (see `docs/TPM-ROLE.md`), freezes via `scripts/refreeze.sh`, and
builds via `scripts/orchestrate.sh`.

---

## Cost Model

| Tier | Model class | Why |
|------|-------------|-----|
| TPM | Frontier (web chat, human-operated) | Spec authorship and test authorship are the highest-leverage, hardest-to-verify work — concentrate the strongest model there, at conversation cadence (no API cost) |
| EM | Mid-tier | Decomposition and diagnosis need reasoning but are schema-validated — a mechanical gate catches what the model gets wrong |
| Coder | Local (LM Studio, CEO-chosen model) | Free, fast; atomic one-file tasks with exact briefs are exactly what coder-class local models do well |
| Tests | None (shell runs pytest) | Running tests requires no judgment; authoring them does (TPM) |

**Rule:** capability problems climb the ladder via the escalation protocol
(D-29) — never by quietly swapping a bigger model into a lower tier.

---

## Staying Current with the Template (D-33/D-34)

Children do not hand-port fixes — that is how control planes silently fork.

- `.template-version` records which template commit this project was born
  from; `bootstrap.sh` stamps it.
- `scripts/check-drift.sh` (also a weekly CI job) three-way-compares every
  template-owned file: child vs template-at-birth vs template-at-HEAD.
  `BEHIND` = the template improved, pull it. `LOCALLY_MODIFIED` = someone
  hand-edited a template-owned file in the child — either revert it or move
  the file to `scripts/.manifest-project` as a declared adaptation.
- `scripts/update-template.sh` pulls upstream control-plane changes the same
  way refreeze works: one aggregate diff, interactive y/N, hash re-pin,
  `[template-update <sha>]` commit.
- Fixes discovered in a child get committed to the TEMPLATE first, then
  pulled into children. (See the 2026-06-30 correction-log entry in
  CLAUDE.md for the incident that forced this.)

---

## Model Configuration (D-53)

EM and coder are mapped to models in `~/.config/sw-dev-blueprint/models.env`
(CEO-owned, never committed to any repo — same spirit as D-41, successor to
the `opencode.json` agent mapping):

```bash
SWBP_EM_MODEL=<id as served by the local endpoint>
SWBP_CODER_MODEL=<id as served by the local endpoint>
```

`scripts/llm-call.sh` reads this file (environment variables of the same
name override it) and hard-halts if a role has no mapping — never a silent
substitution. There is no model-naming collision to work around: the pipeline
talks to LM Studio's `/v1/chat/completions` directly, with no intermediate
provider catalog.

`opencode.json` at the project root is unrelated to this — it only configures
OpenCode if the CEO happens to use it as their conductor (see Component
Inventory above).

---

## The Maintenance Contract

| Trigger | Action | File |
|---------|--------|------|
| Non-obvious decision made | Log it with reasoning | `DECISIONS.md` |
| LLM made a mistake you corrected | Add guard | `CLAUDE.md` correction log |
| Task completed | Move to completed table | `BACKLOG.md` |
| Schema changed | Update data models | `ARCHITECTURE.md` |
| Spec wrong (tests can't be met as written) | TPM delta → `refreeze.sh` | `scripts/.approved/` |

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

**Working around the freeze** — If the spec is wrong, the move is a TPM delta
through `refreeze.sh`, never editing frozen files in place (the gate fails
closed on any hash mismatch) and never "fixing" a test to match the code.

**Hand-editing template-owned files in a child** — That fork is silent until
it bites. `check-drift.sh` will flag it; the fix goes to the template first.

**Trusting self-reported success** — Only passing tests confirm success (Rule 5).

**Tests that confirm the code instead of the spec** — INV-1 violation. Now
structural (the TPM writes tests before the code exists), but the principle
still governs any human-written test: derive from the spec, not from `src/`.

---

## Files the LLM Should Never Touch Without Explicit Instruction

- `DECISIONS.md` — human-approved record of deliberate choices; do not edit without explicit instruction
- `CLAUDE.md` correction log — human-maintained; rows added per the rule, not by the LLM
- `tasks/BACKLOG.md` completed section — historical record; entries move here from `CURRENT.md`, not edited
- `scripts/.approved/` and `tests/` — the frozen spec; changes ONLY via `scripts/refreeze.sh`
- `scripts/`, `.githooks/` in a child project — template-owned; changes ONLY via `scripts/update-template.sh`

---

*This document is the entry point. Everything else flows from it.*
*Keep this file updated as the system evolves.*
*Keep this document lean — prune redundancy, cross-reference instead of duplicating.*
*Length is a smell to investigate, not a hard limit; there is no enforced line count.*
