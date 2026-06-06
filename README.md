# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Talk to OpenCode in plain English. It reads the guardrail
> docs, writes code, runs tests, reports back. Git is the undo. Tests are the truth.

---

## What's in here

```
sw-dev-blueprint/
├── BLUEPRINT.md               # 🌱 Master seed doc — the LLM's entry point (read first)
├── CLAUDE.md                  # 🧠 Master LLM context (auto-read by OpenCode + Claude Code)
├── AGENTS.md                  # Symlink → CLAUDE.md (OpenCode's preferred filename)
├── CONVENTIONS.md             # Code style rules
├── opencode.json              # OpenCode model config (LM Studio local + frontier escalation)
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
│   ├── CURRENT.md             # Active task spec (update every session)
│   └── BACKLOG.md             # Prioritized work queue
│
├── scripts/
│   └── bootstrap.sh           # One-time project setup script
│
└── .github/
    └── workflows/
        └── ci.yml             # GitHub Actions: test + lint on every push
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

## The working loop

```
0. PRE-FLIGHT (BLUEPRINT.md Step 0): verify LM Studio running + correct
   non-thinking model loaded + git + gh. Fail loudly if anything's off.
1. Start LM Studio, confirm qwen/qwen3-coder-next loaded (non-thinking)
2. Run: opencode
3. In OpenCode: /models → select "Qwen3 Coder Next (local)" under "lms"
   (NOT the default "Big Pickle/OpenCode Zen" cloud models)
4. Describe what you want in plain English — no need to pre-write CURRENT.md spec
5. OpenCode reads CLAUDE.md + CONVENTIONS.md, plans, writes code to disk
6. Run tests: pytest        ← ground truth; confirms success, not the LLM
7. If failing: paste error back into OpenCode
8. Same error twice? STOP → escalate to frontier model OR halt (Rule 2)
9. git diff to review, git reset to roll back if needed
10. Repeat
```

---

## LLM routing guide

| Task type | Use |
|-----------|-----|
| Routine features, boilerplate, tests | Local model via OpenCode (free) |
| Complex / multi-file refactor | Local model via OpenCode |
| Reasoning wall / escalation (Rule 2) | Switch OpenCode model to frontier (claude-sonnet or gpt) |
| Greenfield design, big decisions | Discuss in Claude.ai first → DECISIONS.md → tell OpenCode |

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
