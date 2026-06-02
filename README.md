# sw-dev-blueprint

> A GitHub template repository for LLM-assisted software development.
> One-time setup. Every new project bootstraps from this.
>
> **Execution model:** Frontier LLM (F) = architect/plans. Local LLM (L) =
> editor/writes code. Aider orchestrates. Git is the undo. Tests are the truth.

---

## What's in here

```
sw-dev-blueprint/
├── BLUEPRINT.md               # 🌱 Master seed doc — the LLM's entry point (read first)
├── CLAUDE.md                  # 🧠 Master LLM context (auto-read by Aider + Claude Code)
├── CONVENTIONS.md             # Code style rules (auto-read by Aider)
├── .aider.conf.yml            # Aider model routing (local default / frontier hybrid)
├── .env.example               # Environment variable template
├── .gitignore                 # Python + Aider gitignore
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

**Option A: GitHub UI**
1. Click "Use this template" on GitHub
2. Name your new repo
3. Clone it locally
4. Run `./scripts/bootstrap.sh <your-project-name>`

**Option B: CLI**
```bash
gh repo create my-new-project --template your-username/sw-dev-blueprint --private
cd my-new-project
./scripts/bootstrap.sh my-new-project
```

---

## The working loop

```
0. PRE-FLIGHT (BLUEPRINT.md Step 0): verify LM Studio + correct non-thinking
   model loaded + git + gh. Fail loudly if anything's off.
1. Fill in tasks/CURRENT.md with what you're building (be specific)
2. Start LM Studio, load your non-thinking model
3. Run: aider --architect src/
4. Describe what you want at the architect> prompt
5. Review the plan → approve or reject
6. Editor writes the code + git commits
7. Run tests: pytest        ← ground truth; this confirms success, not the LLM
8. If failing: paste error back into aider
9. Same error twice? STOP → escalate architect to frontier OR halt (Rule 2)
10. /diff to review, /undo to roll back if needed
11. Repeat
```

---

## LLM routing guide

| Task type | Use |
|-----------|-----|
| Routine features, boilerplate, tests | Local model (free), both architect + editor |
| Complex / multi-file refactor | Local architect/editor mode |
| Reasoning wall / escalation (Rule 2) | Frontier architect + local editor (hybrid in .aider.conf.yml) |
| Greenfield design, big decisions | Discuss in Claude.ai first → DECISIONS.md → CURRENT.md → Aider |

---

## Keeping docs current

| Trigger | Action |
|---------|--------|
| New dependency | Update ARCHITECTURE.md |
| Non-obvious decision | Log in DECISIONS.md |
| New code convention | Add to CONVENTIONS.md |
| LLM made a mistake you corrected | Add guard to CLAUDE.md correction log |
| Task done | Move to BACKLOG.md completed table, write next CURRENT.md |

---

## Model configuration

Edit `.aider.conf.yml` to switch between local and frontier:

```yaml
# Local (free) — DEFAULT
model: openai/qwen/qwen3-coder-next
editor-model: openai/qwen/qwen3-coder-next

# Hybrid (frontier plans, local edits) — escalation
model: claude-sonnet-4-5
editor-model: openai/qwen/qwen3-coder-next
```

> ⚠️ Neither model may be a THINKING model — it breaks Aider parsing. Verify
> with Pre-Flight Step 0.

Set env vars before running:
```bash
# For local LM Studio
export OPENAI_API_BASE=http://localhost:1234/v1
export OPENAI_API_KEY=lm-studio

# For Anthropic frontier (only when using the hybrid block)
export ANTHROPIC_API_KEY=sk-ant-...
```

---

*Read `BLUEPRINT.md` first — it is the entry point and contains the Hard Rules,
the Pre-Flight Check, and the full component inventory.*
