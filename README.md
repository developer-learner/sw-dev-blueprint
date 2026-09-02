# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Tell the TPM — the spec seat, named by you per session
> (D-139: a frontier LLM in a web chat, a scoped repo agent, or the LLM already
> on the job) — what you want. It
> writes the PRD, the contracts, and the tests. The freeze applies itself once
> every mechanical preflight is green (D-121). The shell
> orchestrator drives an EM (mid-tier) to plan and a local coder to execute, one
> file per task. Git is the undo. The frozen tests are the truth.

**New here?** Start with **`QUICKSTART.md`** — it takes you from zero to this
pipeline building a real 21-test example project on one Linux box, before any
theory. The rest of the docs are tiered (see BLUEPRINT.md → Document Map):
what you must read grows with what you're doing, not all at once.

---

## What's in here

```
sw-dev-blueprint/
├── QUICKSTART.md              # ⚡ Zero to a green frozen suite on one Linux box — a human's first stop
├── BLUEPRINT.md               # 🌱 Master seed doc — read after this README; its Document Map sets the full order
├── CLAUDE.md                  # 🧠 Master LLM context (read by OpenCode + Claude Code via their file tools — best-effort, not auto-loaded)
├── AGENTS.md                  # Symlink → CLAUDE.md (OpenCode's preferred filename)
├── CONVENTIONS.md             # Code style rules
├── opencode.json              # OPTIONAL — only if using OpenCode as your conductor (D-53)
├── .env.example               # Environment variable template
├── .gitignore                 # Python + OpenCode gitignore
│
├── docs/
│   ├── ARCHITECTURE.md           # Data models, API structure, key flows
│   ├── BROWSER-ORACLE-DESIGN.md  # The D-58 browser oracle: how UI acceptance runs
│   ├── CEO-PLAYBOOK.md           # CEO seat rules — decisions with numbers, inform-first
│   ├── CONDUCTOR-ROLE.md         # The conductor seat's job description
│   ├── DECISIONS.md              # Why choices were made (prevents LLM drift)
│   ├── DEV-VM-SETUP.md           # Linux VM for orchestration + test execution
│   ├── ENGINEERING-CONSTITUTION.md # Non-negotiable engineering principles (D-172) — canonical
│   ├── ESCALATION.md             # Failure ladder + TPM bundle format
│   ├── PRODUCT.md                # Evergreen product context
│   ├── SANDBOX-VALIDATION.md     # Sandbox construction + validation evidence
│   ├── TESTING.md                # Testing strategy + conventions
│   └── TPM-ROLE.md               # The top tier's job description
│
├── tasks/
│   ├── CURRENT.md             # Session notes — active work, halt notes
│   └── BACKLOG.md             # Prioritized work queue
│
├── .opencode/
│   └── prompts/               # EM/coder system prompts — read directly by llm-call.sh
├── scripts/
│   ├── bootstrap.sh           # One-time project setup script
│   ├── phase-gate.sh          # INV-2 boundary enforcement
│   ├── llm-call.sh            # ONE bare HTTP completion per call — no harness (D-53)
│   └── orchestrate.sh         # Code-driven build→test loop conductor
│
└── .github/
    └── workflows/
        └── ci.yml             # GitHub Actions: test + lint on every push
```

> **Template files under `docs/` and `tasks/` are intentionally generic skeletons.** They are filled with project-specific content at bootstrap and by the first frozen spec. There is no `src/` in the template — the frozen ERD's file inventory (`contracts.files`) determines what the coder creates, per project. Do not judge the template by the skeletons — judge it by the process that fills them.

---

## What you need

Honest expectation: **~an hour of setup before your first run**, most of it
container-image builds and model downloads.

| Piece | Why | Notes |
|-------|-----|-------|
| macOS (Apple Silicon) host + a **Linux VM** (Lima works), or bare Linux | Both orchestration and refreeze test execution belong in Linux — see `docs/DEV-VM-SETUP.md` | The Mac remains the UI/model-server host; generated tests never execute there |
| **Podman** | The sandbox that runs the frozen suite over generated code (`--network none`, read-only repo). Mandatory — no unsandboxed fallback (D-30/D-114) | Pre-warm inside Linux with `scripts/sandbox-run.sh -- true` |
| **LM Studio** (or any OpenAI-compatible local server) | Serves the EM and coder seats | Map roles in `~/.config/sw-dev-blueprint/models.env` — the repo never names models (D-41) |
| A **~27B-class dense local model, non-thinking, 32K context** | The proven floor for the coder/EM seats — smaller or heavily-MoE models failed task-level work in this repo's own history (D-12/D-14/D-66). Quantization: 4-bit is the CEO default (D-72); keep an 8-bit variant loadable for reactive escalation on the D-72 trigger signals | "Non-thinking" is a hard rule (BLUEPRINT.md Rule 1) |
| **ruff** inside Linux | `refreeze.sh` lints staged tests at the freeze door and fails closed without it (D-67) | Install it in the dev VM |
| **python3, git**; `gh` optional | Gate scripts, version control, template drift-check | — |
| A **frontier LLM** (any — web chat, agent CLI, or the LLM already on the job) | Plays the TPM seat you name per session (D-139): writes the spec + tests you freeze | No API needed — the filesystem is the only integration (D-29) |

Want to see what you're signing up for before installing anything? Read
**`examples/minimal-spec/`** — a complete, real frozen spec (PRD, ERD,
contracts, 21 tests) that this pipeline built into a working API.

---

## Starting a new project

Give an agent this repo's URL and your project name — the agent does the rest.
See **BLUEPRINT.md → Bootstrap Sequence** for the full agent-driven flow.

**If you prefer the one-time terminal path:**
1. Create from template on GitHub UI ("Use this template")
2. Clone locally
3. Run `./scripts/bootstrap.sh <your-project-name>`

```bash
gh repo create my-new-project --template developer-learner/sw-dev-blueprint --private
cd my-new-project
./scripts/bootstrap.sh my-new-project
```

Existing local children can use one shared, version-pinned Blueprint control
plane instead of owning copied scripts:

```bash
bash /path/to/sw-dev-blueprint/scripts/link-template.sh \
  --from /path/to/sw-dev-blueprint --dry-run
```

Apply the printed plan by rerunning without `--dry-run` (or bind review with
`--approve <PLAN-SHA>`). The child keeps its product code, frozen spec/tests,
project configuration, tasks, and evidence. Template-owned paths become
relative links; the drift workflow remains a real file so GitHub can bootstrap
the pinned Blueprint checkout in CI. Later `scripts/update-template.sh` calls
automatically preserve linked mode.

---

## The working loop — capability ladder (D-27)

```
CEO business intent ──► TPM (CEO-assigned seat, D-139 — web chat, scoped agent, or the same LLM)
                          │  writes PRD + ERD/contracts + the test suite
                          ▼
            scripts/refreeze.sh  ← mechanical preflights are the gate; auto-applies on green (D-95)
                          │  spec frozen: scripts/.approved/ + tests/, hash-pinned
                          ▼
            scripts/orchestrate.sh (shell owns ALL procedure)
                          │
              EM (one HTTP completion, no tools, D-53) ──► shell writes
              tasks/plan.json ──► validate-plan.py gate
                          │
              per task, in DAG order:
                Coder (one HTTP completion, no tools, D-53) replies with the
                file ──► shell writes it ──► phase-gate task ──► mapped frozen tests
                          │
              all tasks done ──► delta-mapped verdict green = done (D-112)
                fail → escalation ladder (retry → EM consult → bounded revisions
                        → batched TPM bundle → refreeze → affected subtree resumes)
```

**Your touch-points:** give the TPM chat your intent, read the refreeze diff
(`--diff` prints it; apply is automatic on green preflights, D-121),
run the orchestrator, and answer escalation batches by carrying
`.pipeline-state/escalations/BATCH.md` to the TPM chat. See `docs/ESCALATION.md`.

---

## The gate layer — neurosymbolic, if you want the term

The loop above rests on one bet: every seat generates probabilistically, so
every seat's artifact gets a mechanical check before anything downstream
consumes it. That is a **neurosymbolic** architecture — neural generation,
symbolic validation — and the pieces map onto the usual split:

| Layer | Where | What it catches |
|-------|-------|-----------------|
| **Types, at the door** | `scripts/schemas/*.json` (plan, contracts, diagnosis), enforced server-side via `response_format: json_schema` where the backend supports it | malformed artifacts: wrong shape, unknown keys, bad enum values |
| **Logic, at the ledger** | `scripts/validate-plan.py` | well-formed artifacts that are still incoherent: duplicate file targets, dependency cycles, test node-ids mapped twice or never, contract ids that don't exist, a plan derived from a stale `erd_version` |
| **Entailment, before the freeze** | `spec_preflight()` (D-78) | specs no plan could satisfy — a route whose implementing file is outside the inventory is unbuildable by *any* EM, and that is provable from the spec alone |

`scripts/.approved/contracts.json` is the domain model those checks reason
over: entities (`files`, `routes`, `schemas`, `errors`, `externals`,
`entry_points`, `ui`), their relationships, and the constraints binding them —
versioned, frozen, gate-approved at freeze time (D-121). Call it an ontology if the word helps.

Two things this repo learned that the general form of the idea leaves out:

1. **A validator only binds a seat that cannot route around it.** A capable
   model under goal pressure doesn't emit invalid output — it bypasses the
   validator. In one supervised run the conductor hand-wrote `src/`, authored
   test fixes, and skipped escalation; every prose rule failed and every
   structural gate held. Hence the sandbox, the lane gates, the pre-commit
   hook. Symbolic checks guard the artifact; structure guards the road.
2. **A verdict nobody consumes is not a gate** (D-85). Adding a checking layer
   is the easy part. A child project's CI sat red for 46 consecutive runs on a
   single type error — during which its 151-test suite never ran in CI at all,
   and a `[success]` milestone shipped inside that window. Before adding any
   check, name who reads the verdict.

Constraint strength is priced against blast radius, not maximized —
see BLUEPRINT.md Rule 9.

---

## Keeping docs current

| Trigger | Action |
|---------|--------|
| New dependency | Update ARCHITECTURE.md |
| Non-obvious decision | Log in DECISIONS.md |
| New code convention | Add to CONVENTIONS.md |
| LLM made a mistake you corrected | Add guard to CLAUDE.md correction log |
| Task done | Move to BACKLOG.md completed table |

---

## Using the tiers

1. **TPM (the seat you name, D-139)** — tell the assigned LLM what you want
   (web chat, scoped agent, or the same LLM on the job). It returns
   the PRD, the ERD with machine-readable `contracts.json`, and the test suite.
   Save them under `scripts/.approved/incoming/` and run `scripts/refreeze.sh`:
   `--diff` previews; the freeze auto-applies on green preflights (D-121) —
   the spec is version-stamped, hash-pinned; no agent can touch it.
2. **`scripts/orchestrate.sh`** — drives everything end to end: validated
   plan → one coder call per task → mapped frozen tests in the sandbox →
   gates after every phase. Exit 2 means an escalation batch is waiting in
   `.pipeline-state/escalations/BATCH.md` — paste it into the TPM chat,
   stage the returned delta, refreeze, re-run.
   Tier detail and Hard Rules: **BLUEPRINT.md**; failure ladder: `docs/ESCALATION.md`.

> **Platform:** orchestration and operational refreezes run on Linux (a Lima
> VM on Apple Silicon works). Generated tests never execute on macOS.

---

## Model configuration

EM and coder are mapped to models in `~/.config/sw-dev-blueprint/models.env`
(CEO-owned, global, never committed to any repo):

```bash
SWBP_EM_MODEL=<id as served by LM Studio>
SWBP_CODER_MODEL=<id as served by LM Studio>
```

The repo never names a model. Load whatever you like in LM Studio;
`scripts/llm-call.sh` hard-halts rather than silently substituting a model
if a role has no mapping.

> ⚠️ **Rule 1:** Do NOT use a thinking model for any agent tier.
> Verify with Pre-Flight Step 0 that `content` is populated and
> `reasoning_content` is empty.

`opencode.json` at the project root is unrelated to model mapping — it only
configures OpenCode if you happen to use it as your conductor.

---

*Humans: start with `QUICKSTART.md` and go deeper on demand. Agents: read
`BLUEPRINT.md` first — it is the entry point and contains the Hard Rules,
the Pre-Flight Check, and the full component inventory.*
