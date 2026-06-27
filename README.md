# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Talk to the PM agent (`@pm`) in plain English. It writes a
> PRD. You approve. The architect plans, build writes code, test validates from the
> PRD. Git is the undo. Tests are the truth.

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
│   └── prompts/               # Agent role definitions (pm/architect/build/test)
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

## The working loop — four-role pipeline

```
Human casual instruction  ──►  PM (PRD in tasks/CURRENT.md)
                                   │  ← human approves (criteria freeze here)
                                   ▼
                          scripts/orchestrate.sh ──► Architect → eng plan
                                                       │
                                                       ▼
                                                  Build (src/ only) ──► Test (tests/ only, from PRD)
                                                                               │
                                                                        pass → done
                                                                        fail → route up (see Rule 2/7)
```

**Your touch-points:** write the casual instruction, scan Flagged Assumptions + Acceptance
Criteria, approve the PRD. The loop runs autonomously after that.

See **BLUEPRINT.md → Hard Rules** for the escalation and boundary rules, and the full
diagram under "The System in One Diagram".

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

## Using the agents

Start a session, then switch agents with `@name`:

1. **`@pm`** — write a PRD from your casual instruction. The PM reads the
   project's context (CLAUDE.md, CONVENTIONS.md, DECISIONS.md), drafts
   acceptance criteria in `tasks/CURRENT.md`, and presents for your approval.
   Only approve once the criteria look right — they freeze here.
 2. **`scripts/orchestrate.sh`** — after the PRD is approved, the orchestrator
    drives the loop: calls the architect to plan, build to write `src/`,
    test to validate, runs `scripts/phase-gate.sh` after each phase, runs
    pytest, and routes failures. Results are written to `tasks/CURRENT.md`.
3. **`@pm`** (again) — review the results with the PM. Decide: next feature
   (loop back to step 1), fix bugs (loop back to step 2), or done.

You never talk to `@build` or `@test` directly — the orchestrator calls them.

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
