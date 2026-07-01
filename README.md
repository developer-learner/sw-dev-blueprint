# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Tell the TPM (frontier LLM, web chat) what you want. It
> writes the PRD, the contracts, and the tests. You approve the freeze. The shell
> orchestrator drives an EM (mid-tier) to plan and a local coder to execute, one
> file per task. Git is the undo. The frozen tests are the truth.

---

## What's in here

```
sw-dev-blueprint/
├── BLUEPRINT.md               # 🌱 Master seed doc — the LLM's entry point (read first)
├── CLAUDE.md                  # 🧠 Master LLM context (auto-read by OpenCode + Claude Code)
├── AGENTS.md                  # Symlink → CLAUDE.md (OpenCode's preferred filename)
├── CONVENTIONS.md             # Code style rules
├── opencode.json              # OpenCode model + agent config (4-role pipeline)
├── .env.example               # Environment variable template
├── .gitignore                 # Python + OpenCode gitignore
│
├── docs/
│   ├── ARCHITECTURE.md        # Data models, API structure, key flows
│   ├── DECISIONS.md           # Why choices were made (prevents LLM drift)
│   ├── PRODUCT.md             # Evergreen product context
│   └── TESTING.md             # Testing strategy + conventions
│
├── tasks/
│   ├── CURRENT.md             # PRD — acceptance criteria, frozen on approval
│   └── BACKLOG.md             # Prioritized work queue
│
├── .opencode/
│   └── prompts/               # Agent role definitions (em/coder)
├── scripts/
│   ├── bootstrap.sh           # One-time project setup script
│   ├── phase-gate.sh          # INV-2 boundary enforcement
│   └── orchestrate.sh         # Code-driven build→test loop conductor
│
└── .github/
    └── workflows/
        └── ci.yml             # GitHub Actions: test + lint on every push
```

> **Template files under `src/`, `docs/`, and `tasks/` are intentionally generic skeletons.** They are replaced with project-specific content by the Architect phase on your first pipeline run. Do not judge the template by the skeleton — judge it by the process that fills them.
```

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
CEO business intent ──► TPM (frontier LLM, WEB CHAT — outside OpenCode)
                          │  writes PRD + ERD/contracts + the test suite
                          ▼
            scripts/refreeze.sh  ← human approves the diff (THE approval gate)
                          │  spec frozen: scripts/.approved/ + tests/, hash-pinned
                          ▼
            scripts/orchestrate.sh (shell owns ALL procedure)
                          │
              EM (mid-tier, OpenCode) ──► tasks/plan.json ──► validate-plan.py gate
                          │
              per task, in DAG order:
                Coder (local) writes ONE file ──► phase-gate task ──► mapped frozen tests
                          │
              all tasks done ──► FULL frozen suite green = done
                fail → escalation ladder (retry → EM consult → bounded revisions
                        → batched TPM bundle → refreeze → affected subtree resumes)
```

**Your touch-points:** give the TPM chat your intent, approve the refreeze diff,
run the orchestrator, and answer escalation batches by carrying
`.pipeline-state/escalations/BATCH.md` to the TPM chat. See `docs/ESCALATION.md`.

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
   task plan, the coder executes one file per task inside a read-only-repo
   sandbox, gates and mapped frozen tests run after each task, and the feature
   is done only when the FULL frozen suite is green. Exit 2 means an
   escalation batch is waiting in `.pipeline-state/escalations/BATCH.md` —
   paste it into the TPM chat, stage the returned delta, refreeze, re-run.

You never talk to `em` or `coder` directly — the orchestrator calls them at
shell-chosen points, and everything they produce is schema-validated.

---

## Model configuration

OpenCode config lives in `~/.config/opencode/opencode.json` (global) or
`opencode.json` at the project root.

> ⚠️ **Critical:** use provider key `lms` NOT `lmstudio` — the name `lmstudio`
> collides with OpenCode's built-in catalog and loads wrong model names.
> See `opencode.json` in this repo for the exact working config.

> ⚠️ **Rule 1:** Do NOT use a thinking model (e.g. qwen3.6-35b-a3b).
> Verify with Pre-Flight Step 0 that `content` is populated and
> `reasoning_content` is empty.

To escalate to a frontier model inside OpenCode: `/models` → select Claude or GPT.

---

*Read `BLUEPRINT.md` first — it is the entry point and contains the Hard Rules,
the Pre-Flight Check, and the full component inventory.*
