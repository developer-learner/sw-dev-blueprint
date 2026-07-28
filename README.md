# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Tell the TPM (frontier LLM, web chat) what you want. It
> writes the PRD, the contracts, and the tests. You approve the freeze. The shell
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
├── CLAUDE.md                  # 🧠 Master LLM context (auto-read by OpenCode + Claude Code)
├── AGENTS.md                  # Symlink → CLAUDE.md (OpenCode's preferred filename)
├── CONVENTIONS.md             # Code style rules
├── opencode.json              # OPTIONAL — only if using OpenCode as your conductor (D-53)
├── .env.example               # Environment variable template
├── .gitignore                 # Python + OpenCode gitignore
│
├── docs/
│   ├── ARCHITECTURE.md        # Data models, API structure, key flows
│   ├── DECISIONS.md           # Why choices were made (prevents LLM drift)
│   ├── PRODUCT.md             # Evergreen product context
│   ├── TESTING.md             # Testing strategy + conventions
│   ├── TPM-ROLE.md            # The top tier's job description
│   └── ESCALATION.md          # Failure ladder + TPM bundle format
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
| macOS (Apple Silicon) host + a **Linux VM** (Lima works), or bare Linux | `scripts/orchestrate.sh` hard-refuses macOS; `scripts/refreeze.sh` runs on the host. The split is deliberate — see `docs/DEV-VM-SETUP.md` | Podman image stores are **per side**; pre-warm with `scripts/sandbox-run.sh -- true` on both |
| **Podman** | The sandbox that runs the frozen suite over generated code (`--network none`, read-only repo). Mandatory — no unsandboxed fallback (D-30) | Host: `podman machine start` before a freeze |
| **LM Studio** (or any OpenAI-compatible local server) | Serves the EM and coder seats | Map roles in `~/.config/sw-dev-blueprint/models.env` — the repo never names models (D-41) |
| A **~27B-class dense local model, non-thinking, 32K context** | The proven floor for the coder/EM seats — smaller or heavily-MoE models failed task-level work in this repo's own history (D-12/D-14/D-66). Quantization: 4-bit is the CEO default (D-72); keep an 8-bit variant loadable for reactive escalation on the D-72 trigger signals | "Non-thinking" is a hard rule (BLUEPRINT.md Rule 1) |
| **ruff** on the host | `refreeze.sh` lints staged tests at the freeze door and fails closed without it (D-67) | `brew install ruff` |
| **python3, git**; `gh` optional | Gate scripts, version control, template drift-check | — |
| A **frontier LLM web chat** (any) | Plays the TPM seat: writes the spec + tests you freeze | No API needed — the filesystem is the only integration (D-29) |

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

---

## The working loop — capability ladder (D-27)

```
CEO business intent ──► TPM (frontier LLM, WEB CHAT — outside the conductor)
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
              all tasks done ──► FULL frozen suite green = done
                fail → escalation ladder (retry → EM consult → bounded revisions
                        → batched TPM bundle → refreeze → affected subtree resumes)
```

**Your touch-points:** give the TPM chat your intent, approve the refreeze diff,
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
versioned, frozen, human-approved. Call it an ontology if the word helps.

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

1. **TPM (web chat)** — describe what you want in the frontier chat. It returns
   the PRD, the ERD with machine-readable `contracts.json`, and the test suite.
   Save them under `scripts/.approved/incoming/` and run `scripts/refreeze.sh`:
   review the diff, approve with y — the spec freezes here (version-stamped,
   hash-pinned; no agent can touch it).
2. **`scripts/orchestrate.sh`** — drives everything: the EM emits a validated
   task plan, the coder receives one prompt per task (host-side HTTP, no
   filesystem access — the shell writes the reply to disk), mapped frozen
   tests then run **inside** a read-only-repo sandbox (`--network none`,
   `.cache/` writable), lane gates re-check after every phase, and the
   feature is done only when the FULL frozen suite is green. Exit 2 means an
   escalation batch is waiting in `.pipeline-state/escalations/BATCH.md` —
   paste it into the TPM chat, stage the returned delta, refreeze, re-run.

> **Platform:** `orchestrate.sh` must run on Linux (Lima VM on Apple
> Silicon works; `refreeze.sh` runs on the macOS host).

Neither EM nor coder has any tool or filesystem access at all (D-53) — the
orchestrator reads whatever context a call needs, sends ONE HTTP completion
via `scripts/llm-call.sh`, and writes the reply to disk itself. There is no
agent harness anywhere in this path.

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
