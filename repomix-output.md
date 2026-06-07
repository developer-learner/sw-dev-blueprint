This file is a merged representation of the entire codebase, combined into a single document by Repomix.

# File Summary

## Purpose
This file contains a packed representation of the entire repository's contents.
It is designed to be easily consumable by AI systems for analysis, code review,
or other automated processes.

## File Format
The content is organized as follows:
1. This summary section
2. Repository information
3. Directory structure
4. Repository files (if enabled)
5. Multiple file entries, each consisting of:
  a. A header with the file path (## File: path/to/file)
  b. The full contents of the file in a code block

## Usage Guidelines
- This file should be treated as read-only. Any changes should be made to the
  original repository files, not this packed version.
- When processing this file, use the file path to distinguish
  between different files in the repository.
- Be aware that this file may contain sensitive information. Handle it with
  the same level of security as you would the original repository.

## Notes
- Some files may have been excluded based on .gitignore rules and Repomix's configuration
- Binary files are not included in this packed representation. Please refer to the Repository Structure section for a complete list of file paths, including binary files
- Files matching patterns in .gitignore are excluded
- Files matching default ignore patterns are excluded
- Files are sorted by Git change count (files with more changes are at the bottom)

# Directory Structure
```
.github/
  workflows/
    ci.yml
docs/
  ARCHITECTURE.md
  DECISIONS.md
  PRODUCT.md
  TESTING.md
scripts/
  bootstrap.sh
  new-project.sh
tasks/
  BACKLOG.md
  CURRENT.md
.env.example
.gitignore
BLUEPRINT.md
CLAUDE.md
CONVENTIONS.md
opencode.json
README.md
```

# Files

## File: docs/ARCHITECTURE.md
````markdown
# ARCHITECTURE.md — System Design

> Living document. Update when structure changes.
> LLMs read this to understand how the system fits together.

---

## System Overview

[One paragraph describing the overall system — what it does, how it's structured at a high level.]

---

## Data Models

> Define every entity, its fields, and relationships.
> Keep this updated — the LLM uses this to avoid inventing schema.

### [ModelName]

| Field | Type | Notes |
|-------|------|-------|
| id | int | primary key, auto-increment |
| created_at | datetime | set on insert |
| updated_at | datetime | set on update |

**Relationships:**
- has many [OtherModel]
- belongs to [AnotherModel]

---

## API Structure

```
GET    /api/v1/[resource]           list
POST   /api/v1/[resource]           create
GET    /api/v1/[resource]/:id       get one
PUT    /api/v1/[resource]/:id       update
DELETE /api/v1/[resource]/:id       delete
```

---

## Key Flows

> Describe the important user journeys as numbered steps.
> These prevent the LLM from misunderstanding how pieces connect.

### [Flow Name]

1. User does X
2. System checks Y
3. If Y passes → Z happens
4. Response returned

---

## External Services

| Service | Purpose | Notes |
|---------|---------|-------|
| [Service] | [What it does] | [Auth method, rate limits, etc.] |

---

## Infrastructure

```
[Environment]
├── App server:    [e.g. Railway, single instance]
├── Database:      [e.g. Postgres 15, managed]
├── Cache:         [e.g. Redis, optional]
├── File storage:  [e.g. S3 / Cloudflare R2]
└── CDN:           [e.g. Cloudflare]
```

---

## Known Constraints

> Things the LLM should know to avoid bad suggestions.

- [e.g. "Database is read-heavy — optimize for reads over writes"]
- [e.g. "No background job queue yet — everything is synchronous"]
- [e.g. "Single-tenant for now — no multi-tenancy logic needed"]
````

## File: docs/PRODUCT.md
````markdown
# PRODUCT.md — Product Context

> Evergreen. Describes what we're building and who it's for.
> Not a task list — that's in tasks/. This is the "why" layer.

---

## Problem Statement

[What problem does this product solve? Who has this problem?
One paragraph. Be specific about the pain, not the solution.]

---

## Target Users

| User type | Description | Primary need |
|-----------|-------------|--------------|
| [Type 1] | [Who they are] | [What they need most] |
| [Type 2] | [Who they are] | [What they need most] |

---

## Core Value Proposition

[One sentence: "We help [user] do [thing] so they can [outcome]."]

---

## What We Are Not Building

> Explicit non-goals prevent scope creep and misguided LLM suggestions.

- [e.g. "Not a marketplace — no buyer/seller dynamic"]
- [e.g. "Not a mobile app — web only for now"]
- [e.g. "Not a real-time collaboration tool — async is fine"]

---

## Success Metrics

| Metric | Target | How measured |
|--------|--------|--------------|
| [Metric] | [Value] | [Method] |

---

## Feature Flags / Rollout Notes

| Feature | Status | Notes |
|---------|--------|-------|
| [Feature] | [planned/in-dev/live/deprecated] | [Notes] |
````

## File: docs/TESTING.md
````markdown
# TESTING.md — Testing Strategy

> Strategy and conventions, not results.
> CI handles pass/fail tracking. This file tells the LLM how we test.

---

## Philosophy

- Test behavior, not implementation
- Tests should read like documentation
- If it's hard to test, the design is wrong — fix the design
- Coverage target: 80% on business logic (services/), not on route boilerplate

---

## Test Types

| Type | Location | Tool | When to write |
|------|----------|------|---------------|
| Unit | `tests/services/`, `tests/utils/` | pytest | Always — alongside new functions |
| Integration | `tests/integration/` | pytest | For flows that touch DB or external services |
| API | `tests/api/` | pytest + httpx | For every route |

---

## Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=src --cov-report=term-missing

# Specific file
pytest tests/services/test_project_service.py

# Specific test
pytest tests/services/test_project_service.py::test_create_project_returns_id

# Verbose
pytest -v

# Stop on first failure
pytest -x
```

---

## Test Database

```bash
# Tests use a separate test database
# Set in .env.test:
DATABASE_URL=postgresql://localhost/myapp_test

# Fixtures handle setup/teardown — never test against production DB
```

---

## Fixtures

```python
# conftest.py at tests/ root
# Standard fixtures available in all tests:

@pytest.fixture
def db_session():
    """Rolls back after each test."""
    ...

@pytest.fixture
def test_user():
    """A standard user for auth tests."""
    ...

@pytest.fixture
def auth_headers(test_user):
    """Authorization headers for API tests."""
    ...
```

---

## What We Don't Test

- FastAPI route boilerplate (the framework is already tested)
- Database migration scripts (tested by running them)
- Third-party library internals

---

## Known Issues / Flaky Tests

| Test | Issue | Workaround |
|------|-------|------------|
| [test name] | [why it's flaky] | [current workaround] |

---

## Mocking Policy

- Mock external HTTP calls (use `respx` for httpx)
- Mock email sending
- **Do not mock the database** — use a real test DB with transactions
- **Do not mock your own services** — if you need to mock it, split the dependency
````

## File: tasks/BACKLOG.md
````markdown
# BACKLOG.md — Task Queue

> Ordered by priority. Top = next up.
> When starting a task, move it to CURRENT.md and expand it into a full spec.

---

## Format

```
### [Task name]
**Priority:** [P0 critical / P1 high / P2 medium / P3 low]
**Why:** [One sentence on the value]
**Rough size:** [Small / Medium / Large]
**Depends on:** [Any blockers]
```

---

## Up Next

### [TASK_NAME]
**Priority:** P1
**Why:** [Value statement]
**Rough size:** Medium
**Depends on:** Nothing

---

## Later

### [TASK_NAME]
**Priority:** P2
**Why:** [Value statement]
**Rough size:** Large
**Depends on:** [Other task]

---

## Icebox (someday/maybe)

- [Vague idea 1]
- [Vague idea 2]

---

## Completed

| Task | Completed | Notes |
|------|-----------|-------|
| [Task] | [Date] | [Any learnings] |
````

## File: tasks/CURRENT.md
````markdown
# CURRENT.md — Active Task

> This is the session-level spec. Update before every coding session.
> The LLM reads this to know exactly what to build — and what to leave alone.
> When done, move to BACKLOG.md and write the next task here.

---

## Task: [TASK_NAME]

**Status:** [Not started | In progress | In review | Done]
**Branch:** `[feature/task-name]`
**Estimated effort:** [Small / Medium / Large]

---

## What

[One paragraph. What should exist when this task is complete that doesn't exist now.]

---

## Acceptance Criteria

> Written as checkboxes. Each one is testable.

- [ ] [Specific, observable outcome 1]
- [ ] [Specific, observable outcome 2]
- [ ] [Tests pass for the above]
- [ ] [No existing tests broken]

---

## Out of Scope

> Explicit. Prevents the LLM from building things you don't want yet.

- [Thing that sounds related but isn't this task]
- [Future feature that will come later]

---

## Files Likely Involved

> Give the LLM a map so it edits the right files.

```
src/services/[relevant_service].py   # main logic here
src/api/[relevant_router].py         # route handler
src/models/[relevant_model].py       # if schema changes
tests/services/test_[service].py     # unit tests
tests/api/test_[router].py           # API tests
```

---

## Notes / Context

[Anything the LLM needs to know that isn't in ARCHITECTURE.md or DECISIONS.md.
Temporary context for this task only.]

---

## Definition of Done

- [ ] Acceptance criteria all checked
- [ ] Tests written and passing
- [ ] `docs/ARCHITECTURE.md` updated if structure changed
- [ ] `docs/DECISIONS.md` updated if non-obvious choice was made
- [ ] No linter errors (`ruff check src/`)
- [ ] Branch merged to main
````

## File: .env.example
````
# .env.example — copy to .env and fill in. NEVER commit .env.

# --- App ---
DEBUG=false
SECRET_KEY=change-me

# --- Database (default stack: Postgres; swap for SQLite if Rule 3 adapted) ---
DATABASE_URL=postgresql://localhost/myapp
# SQLite alternative:
# DATABASE_URL=sqlite+aiosqlite:///./app.db

# --- LM Studio (local LLM, for OpenCode's lms provider) ---
OPENAI_API_BASE=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio

# --- Frontier (only needed for hybrid architect escalation) ---
# ANTHROPIC_API_KEY=sk-ant-...
````

## File: CONVENTIONS.md
````markdown
# CONVENTIONS.md — Code Style & Patterns

> OpenCode reads this file. These rules apply to every code change in this project.

---

## Python Style

```python
# ✅ Type hints on everything
def get_user(user_id: int) -> User | None:
    ...

# ✅ Pydantic for data shapes
class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None

# ✅ Loguru for logging
from loguru import logger
logger.info("User {user_id} created project {project_id}", user_id=1, project_id=2)

# ❌ Never print()
print("something happened")  # NO

# ❌ Never bare except
try:
    do_something()
except:             # NO — catch specific exceptions
    pass

# ✅ Specific exceptions
try:
    do_something()
except ValueError as e:
    logger.error("Validation failed: {e}", e=e)
    raise
```

---

## Function Design

```python
# ✅ One thing per function, named as a verb phrase
def calculate_project_completion_rate(project_id: int) -> float:
    ...

def send_welcome_email(user: User) -> bool:
    ...

# ❌ Functions that do multiple unrelated things
def process(data):   # too vague, too broad
    ...
```

---

## API Patterns (FastAPI)

```python
# ✅ Route handlers are thin — delegate to services
@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    body: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    return await project_service.create(db, current_user.id, body)

# ❌ Business logic in route handlers
@router.post("/projects")
async def create_project(body: CreateProjectRequest):
    # 50 lines of logic here — NO
```

---

## Error Handling

```python
# ✅ Custom exceptions for domain errors
class ProjectNotFoundError(Exception):
    def __init__(self, project_id: int):
        self.project_id = project_id
        super().__init__(f"Project {project_id} not found")

# ✅ HTTP exceptions at the API layer only
@router.get("/projects/{project_id}")
async def get_project(project_id: int) -> ProjectResponse:
    try:
        return await project_service.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
```

---

## Testing Patterns

```python
# ✅ Arrange / Act / Assert structure, always
def test_create_project_returns_correct_name():
    # Arrange
    request = CreateProjectRequest(name="My Project")
    
    # Act
    result = project_service.create(user_id=1, body=request)
    
    # Assert
    assert result.name == "My Project"

# ✅ Test names describe behavior, not implementation
def test_get_project_raises_when_not_found():    # ✅
def test_get_project_line_42():                  # ❌

# ✅ One assertion concept per test
# ❌ Asserting 10 different things in one test
```

---

## Git Commit Messages

```
# Format: <type>: <short description>
# Types: feat | fix | test | refactor | docs | chore

feat: add project archiving endpoint
fix: handle null description in project creation
test: add coverage for archive status transitions
refactor: extract project validation to separate service
docs: update ARCHITECTURE with new status flow
chore: bump pydantic to 2.7
```

---

## File Naming

```
src/services/project_service.py     # snake_case
src/models/user.py                  # singular model name
tests/services/test_project_service.py
scripts/seed_database.py
```

---

## Environment & Config

```python
# ✅ All config via environment variables
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    debug: bool = False
    
    class Config:
        env_file = ".env"

settings = Settings()

# ❌ Never
DATABASE_URL = "postgresql://localhost/mydb"  # hardcoded — NO
```
````

## File: opencode.json
````json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "lms": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LM Studio local",
      "options": { "baseURL": "http://127.0.0.1:1234/v1" },
      "models": { "qwen/qwen3-coder-next": { "name": "Qwen3 Coder Next (local)" } }
    }
  }
}
````

## File: README.md
````markdown
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

**Option A: GitHub UI**
1. Click "Use this template" on GitHub
2. Name your new repo
3. Clone it locally
4. Run `./scripts/bootstrap.sh <your-project-name>`

**Option B: CLI**
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
````

## File: scripts/bootstrap.sh
````bash
#!/bin/bash
# bootstrap.sh — Run once when starting a new project from this template
#
# Usage: ./scripts/bootstrap.sh <project-name>
#
# What it does:
#   1. Renames placeholders throughout docs
#   2. Creates AGENTS.md symlink → CLAUDE.md (OpenCode's preferred filename)
#   3. Copies opencode.json to global config location if not already present
#   4. Creates Python virtual environment
#   5. Installs base dependencies
#   6. Initializes git (if not already)
#   7. Prints next steps
#
# NOTE (Rule 3): This installs the DEFAULT stack (FastAPI + Postgres async).
# If this project uses a different stack (e.g. SQLite, Django, no DB), EDIT
# the dependency list below BEFORE running. Also update ci.yml and CONVENTIONS.md.

set -e

PROJECT_NAME=${1:-"my-project"}

echo "🚀 Bootstrapping project: $PROJECT_NAME"
echo ""

# --- Cross-platform sed in-place (macOS/BSD needs '' arg; GNU/Linux does not) ---
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(sed -i)        # GNU sed (Linux, CI)
else
  SED_INPLACE=(sed -i '')     # BSD sed (macOS)
fi

# --- Replace placeholders in docs ---
echo "📝 Updating docs with project name..."
find . -type f \( -name "*.md" -o -name "*.yml" -o -name "*.yaml" \) \
  -not -path "./.git/*" \
  -not -path "./.venv/*" \
  -exec "${SED_INPLACE[@]}" "s/\[PROJECT_NAME\]/$PROJECT_NAME/g" {} +

# --- AGENTS.md symlink (OpenCode reads AGENTS.md; symlink keeps one source of truth) ---
echo "🔗 Creating AGENTS.md → CLAUDE.md symlink..."
if [ ! -f AGENTS.md ]; then
  ln -s CLAUDE.md AGENTS.md
  echo "   AGENTS.md symlink created"
else
  echo "   AGENTS.md already exists, skipping"
fi

# --- OpenCode global config (copy only if not already configured) ---
OPENCODE_CONFIG_DIR="$HOME/.config/opencode"
OPENCODE_CONFIG="$OPENCODE_CONFIG_DIR/opencode.json"
if [ ! -f "$OPENCODE_CONFIG" ]; then
  echo "⚙️  Installing OpenCode global config..."
  mkdir -p "$OPENCODE_CONFIG_DIR"
  cp opencode.json "$OPENCODE_CONFIG"
  echo "   Config written to $OPENCODE_CONFIG"
  echo "   ⚠️  Verify the model name matches what LM Studio is serving:"
  echo "       curl http://localhost:1234/v1/models | python3 -m json.tool"
else
  echo "⚙️  OpenCode config already exists at $OPENCODE_CONFIG — not overwriting"
  echo "   Ensure it uses provider key 'lms' (not 'lmstudio') to avoid model name collision"
fi

# --- Python virtual environment ---
echo "🐍 Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# --- Base dependencies (DEFAULT STACK — edit for your project per Rule 3) ---
echo "📦 Installing base dependencies..."
pip install --upgrade pip

pip install \
  fastapi \
  "uvicorn[standard]" \
  pydantic \
  pydantic-settings \
  loguru \
  python-dotenv \
  httpx \
  asyncpg \
  alembic

pip install \
  pytest \
  pytest-asyncio \
  pytest-cov \
  ruff \
  mypy \
  respx

# Save to requirements file
pip freeze | grep -v "^-e" > requirements.txt
echo "Requirements saved to requirements.txt"

# --- .env file ---
if [ ! -f .env ] && [ -f .env.example ]; then
  echo "🔑 Creating .env from template..."
  cp .env.example .env
  echo ".env created — fill in your values before running"
fi

# --- Git ---
if [ ! -d .git ]; then
  echo "📁 Initializing git repo..."
  git init
  git add .
  git commit -m "chore: bootstrap from sw-dev-blueprint template"
fi

echo ""
echo "✅ Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  1. (Rule 3) Confirm the installed stack matches this project; adjust if not"
echo "  2. Fill in .env with your config values"
echo "  3. Update CLAUDE.md — project name, description, tech stack"
echo "  4. Update docs/PRODUCT.md with your product context"
echo "  5. Run Pre-Flight Check (BLUEPRINT.md Step 0)"
echo "  6. Start LM Studio, load qwen/qwen3-coder-next (non-thinking)"
echo "  7. Run: opencode"
echo "  8. In OpenCode: /models → select 'Qwen3 Coder Next (local)' under 'lms'"
echo "  9. Just tell it what you want to build"
echo ""
echo "Happy building 🛠"
````

## File: scripts/new-project.sh
````bash
#!/usr/bin/env bash
set -e

PROJECT_NAME="$1"
TARGET_DIR="$(pwd)/$PROJECT_NAME"
LLM_URL="http://localhost:1234/v1/chat/completions"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo "--- $* ---"; }

# Step 0: Pre-flight check (Hard Rule 1 & 4)
step "Pre-flight: checking local LLM at $LLM_URL ..."
PREFLIGHT_RAW="$(curl -s --max-time 30 "$LLM_URL" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-coder-next","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":5,"temperature":0}' \
  || true)"

[ -n "$PREFLIGHT_RAW" ] || die "no response from LM Studio. Is the server up with a model loaded?"

CONTENT="$(printf '%s' "$PREFLIGHT_RAW" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    msg = d["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    if not content and reasoning:
        print("THINKING_MODEL", end="")
    else:
        print(content, end="")
except Exception as e:
    print("PARSE_ERROR:" + str(e), end="")
')"

case "$CONTENT" in
  "")             die "pre-flight returned empty content. Model misconfigured?" ;;
  THINKING_MODEL) die "pre-flight: THINKING MODEL loaded (content empty, reasoning present). Load the non-thinking coder model (Hard Rule 1)." ;;
  PARSE_ERROR:*)  die "pre-flight JSON parse failed: ${CONTENT#PARSE_ERROR:}" ;;
  *)              echo "  ok: local LLM responded: $CONTENT" ;;
esac

# Step 1: Bootstrap
step "Running bootstrap..."
[ -x scripts/bootstrap.sh ] || die "scripts/bootstrap.sh missing or not executable."
./scripts/bootstrap.sh "$PROJECT_NAME" || die "bootstrap failed."

# Step 2: Git
step "Initializing git..."
git init || die "git init failed"

cat <<DONE
READY: $PROJECT_NAME is instantiated, bootstrapped, and pre-flight-verified.
Location: $TARGET_DIR

Next steps (do these while awake):
1. cd $TARGET_DIR
2. source .venv/bin/activate  (if not already active)
3. Adapt stack if needed (Rule 3): edit ci.yml / requirements if not FastAPI+Postgres
4. Run: opencode
   In OpenCode: /models → select "Qwen3 Coder Next (local)" under "lms"
   Then just describe what you want to build in plain English

Tests are ground truth (Rule 5).
Two strikes on the same error then stop (Rule 2).
DONE
````

## File: .gitignore
````
# Python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# Env / secrets
.env
.env.test
.env.*.local

# OpenCode
/.opencode/

# OS
.DS_Store
blueprint-dryrun*/
````

## File: BLUEPRINT.md
````markdown
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
  --include='*.md' --exclude-dir=.git
```

If it returns ANY lines, a placeholder survived — go back to Step 6,
fill, re-run, repeat until it returns nothing.

**Carve-out:** the `## Template` format block in `docs/DECISIONS.md` uses
placeholder brackets intentionally as an evergreen format reference.
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

**Over-speccing CURRENT.md** — OpenCode takes plain English. You don't need
a detailed acceptance-criteria checklist for every task. Write it out only
when the task is genuinely complex or you need explicit boundaries.

**Stale ARCHITECTURE.md** — If the LLM's model of your schema is wrong,
everything built on it is wrong. Update after every schema change.

**Skipping DECISIONS.md** — Every unlogged decision gets re-litigated next
session. The LLM has no memory; this is the only thing carrying context forward.

**Wrong provider name** — `lmstudio` collides with OpenCode's catalog. Always use `lms` (see OpenCode Configuration).

**Loading a thinking model** — Silent failure. Always verify with Pre-Flight
Step 0 before a session.

**Over-relying on frontier for everything** — 80% of tasks are routine.
Local handles them free. Save frontier for actual reasoning walls.

**Abdication** — The LLM fills any vacuum, including product decisions. You own:
what to build, acceptance criteria, architecture decisions, final review.

**Trusting self-reported success** — Only passing tests confirm success (Rule 5).

**Letting the error loop run** — Two strikes, then escalate or halt (Rule 2).

---

---

## Files the LLM Should Never Touch Without Explicit Instruction

- `DECISIONS.md` — human-authored record of deliberate choices; do not edit without explicit instruction
- `CLAUDE.md` correction log — human-maintained; rows added per the rule, not by the LLM
- `tasks/BACKLOG.md` completed section — historical record; entries move here from `CURRENT.md`, not edited

---

*This document is the entry point. Everything else flows from it.*
*Keep this file updated as the system evolves.*
````

## File: docs/DECISIONS.md
````markdown
# DECISIONS.md — Architectural Decision Log

> Every non-obvious technical decision goes here with the reasoning.
> This prevents the LLM from "helpfully" undoing choices you already made.
> Format: date, decision, why, what not to suggest.

---

## Template

```
## YYYY-MM-DD — [Decision title]

**Decision:** [What was decided]
**Alternatives considered:** [What else was evaluated]
**Reason:** [Why this choice was made]
**Do not suggest:** [What the LLM should not propose as a "fix"]
```

---

## Decisions

## [DATE] — [Your first decision here]

**Decision:** [e.g. Using raw SQL over ORM]
**Alternatives considered:** [e.g. SQLAlchemy, Tortoise ORM]
**Reason:** [e.g. Query complexity made ORM unreadable for our join-heavy patterns]
**Do not suggest:** Switching to an ORM. This was deliberate.

---

## [DATE] — Monorepo structure

**Decision:** Single repository for all services.
**Alternatives considered:** Separate repos per service.
**Reason:** Team size doesn't justify the overhead of managing multiple repos. Shared code is easier to refactor.
**Do not suggest:** Splitting into microservices repos until team grows past 5 engineers.

---

## 2026-06-04 — Pruned BLUEPRINT.md (557 → ~440 lines)

**Decision:** Apply the noise/redundancy findings from a parallel LLM audit; skip the lifecycle/strategy findings from a second LLM.
**Alternatives considered:** (a) accept both LLMs' suggestions and add new rules; (b) leave the file as-is; (c) full rewrite.
**Reason:** BLUEPRINT.md is the LLM's entry point. Every redundant line is context-window cost and a chance for ambiguity to compound. Pruning is a guardrail against drift, not cosmetics. Adding more rules (the second LLM's "fortify" suggestions: Doc-Sync hard rule, TDD loop, REVIEW checkpoints, `/reset-context`) would partially undo the trim and add bloat.
**Do not suggest:** Re-adding the dropped sections. The "Document Map" alone is sufficient; the verbose "Document Roles Explained" was redundant. "Step 5 — Adapt the stack" is a pointer to Rule 3, not a restatement. Bootstrap cleanup, OpenCode Configuration, and Quick Reference Card are now minimal — keep them so.

**Trimmed (12 items, ~115 lines removed):**
- Dropped "Document Roles Explained" (duplicated Document Map)
- Collapsed Bootstrap Step 5 to a 1-line pointer to Rule 3
- Trimmed Maintenance Contract from 6 rows to 4 (dropped obvious triggers)
- Trimmed Files Never to Touch from 5 items to 3 (universal best-practice items removed)
- Shrunk Bootstrap Step 4 cleanup (24→6 lines)
- Trimmed Step 7 preamble (dropped "Hard Rule 5" restatement)
- Shrunk OpenCode Configuration section (28→3 lines + pointer to `opencode.json`)
- Trimmed anti-pattern "wrong provider name" to a one-liner
- Deleted Quick Reference Card (restated diagram + rules)
- Fixed phantom "Step 4.5" reference on line 490 → "Step 4"
- Reduced duplicate "lms not lmstudio" mentions from 3 to 1
- Reduced "AGENTS.md symlinks to CLAUDE.md" mentions from 5 to 3 (one in prose + 2 short callouts)

---

## 2026-06-04 — Auto-load assumption corrected; CLAUDE.md / opencode.json fixes

**Decision:** (a) Rewrite `CLAUDE.md`'s intro to accurately describe its load behavior — file is *fetchable via tools*, not pre-loaded; the LLM is *expected* to read it. (b) Fix the project's `opencode.json` schema (OpenCode 1.15.13 rejects the old `providers` / top-level `models` form with "Unrecognized keys"). The original commit also added a "do not re-add dropped BLUEPRINT.md sections" mirror guard to `CLAUDE.md`; that mirror was later removed (see entry below) for template-hygiene reasons.

**Alternatives considered:** (a) Document the asymmetry but not fix it; (b) add a hook in BLUEPRINT.md to force the LLM to read CLAUDE.md first; (c) leave the broken `opencode.json` and tell users to delete it.

**Reason:** The architectural premise that "guards in CLAUDE.md auto-fire every session" was unverified and partially false. Empirical test showed the model uses the `read` tool to fetch content (not pre-loaded) and can misparse which guard applies. The memory layer is best-effort, not enforced. For things that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) that fire without the LLM's cooperation. Doc guards are strong hints, not hard gates.

**Do not suggest:** Reverting `CLAUDE.md`'s intro to the "automatically read" claim, or reverting `opencode.json` to the old `providers` schema. Both are now verified-correct by empirical test.

**Verified by:**
- `opencode run --format json --dir /tmp/opencode-autoload-test "Read AGENTS.md..."` — event log showed `tool_use` with `read` tool; model fetched content but answered wrong
- `opencode --version` → `1.15.13` (matches the schema fix)
- `opencode run "What is 2+2?" --format default` from project dir → "Four." (schema fix loads cleanly under the installed version)

**Cross-cutting lesson (worth applying to all template projects):** Treat doc guards as advisory. For must-hold rules, build mechanical checks into scripts or CI:
- Placeholder completeness → grep (BLUEPRINT.md Step 7)
- File size budgets → `wc -l` in a pre-commit hook
- Schema validity → `opencode.json` parsed at session start
- Tests as ground truth → pytest in CI (BLUEPRINT.md Rule 5)
Doc guards catch the LLM's *intent*; mechanical gates catch the *result*. Both have a place. The test just proved the first is weaker than the design claimed.

---

## 2026-06-04 — Removed CLAUDE.md mirror guard (decoupling template from project)

**Decision:** Remove the one-line "Do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune" guard from `CLAUDE.md`'s "What NOT To Do" → Operating guardrails. The rule still lives in `DECISIONS.md` → "Pruned BLUEPRINT.md" entry.

**Reason:** CLAUDE.md is a template — `[PROJECT_NAME]` is still a placeholder. Baking a project-specific date ("2026-06-04 prune") into a template file makes the rule meaningless for any future project created from this template. The visibility argument was real but the template-vs-project boundary was muddied. The principle (don't re-add dropped sections) stays binding via DECISIONS.md's "Do not suggest" line and the correction log capture.

**Do not suggest:** Re-adding the mirror guard. Cross-reference, don't copy.

---

> Add new decisions above this line, newest first.
````

## File: CLAUDE.md
````markdown
# CLAUDE.md — Master LLM Context File

> OpenCode and Claude Code can read this file via their file tools. You are
> expected to read it at the start of every session, and to consult it again
> before any action that touches the document layer (`BLUEPRINT.md`,
> `CONVENTIONS.md`, `docs/DECISIONS.md`, this file's correction log).
> Keep it current. Every correction you make to the LLM should be recorded here
> so the mistake never happens again.

---

## Project Overview

**Name:** [PROJECT_NAME]
**What it does:** [One paragraph. What does this do, who is it for, what problem does it solve.]
**Status:** [Planning | In Development | Production]

---

## Tech Stack

> Default template stack shown below. ADAPT to this project's real stack
> before first commit (see BLUEPRINT.md Rule 3).

```
Language:     Python 3.12+
Framework:    [e.g. FastAPI / Django / Flask]
Database:     [e.g. PostgreSQL / SQLite / MongoDB]
Auth:         [e.g. Clerk / JWT / OAuth]
Hosting:      [e.g. Railway / Fly.io / AWS]
CI/CD:        GitHub Actions
Testing:      pytest
```

---

## Project Structure

```
[PROJECT_NAME]/
├── src/                  # application source
│   ├── api/              # route handlers
│   ├── models/           # data models
│   ├── services/         # business logic
│   └── utils/            # shared utilities
├── tests/                # mirrors src/ structure
├── docs/                 # architecture, decisions, product
├── tasks/                # current work + backlog
├── scripts/              # dev utilities
├── CLAUDE.md             # this file
└── CONVENTIONS.md        # code style rules
```

---

## Code Conventions

- Always use type hints on function signatures
- Prefer functions over classes unless persistent state is needed
- Use `loguru` for logging — never `print()`
- One responsibility per function — if it needs a comment explaining what it does, split it
- Tests live in `tests/` mirroring `src/` structure (e.g. `src/services/user.py` → `tests/services/test_user.py`)
- Write tests alongside new code, not after
- Use `pydantic` for data validation and serialization
- Environment variables via `python-dotenv` — never hardcode secrets

---

## What NOT To Do

> These are guardrails. Do not override them without explicit human instruction.

**Code guardrails:**
- **Do not add dependencies** without asking first
- **Do not refactor files** unrelated to the current task
- **Do not change the database schema** without explicit instruction
- **Do not remove error handling** to simplify code
- **Do not use `Any` type** — be specific
- **Do not write `TODO` comments** — either implement it or raise it as a task
- **Do not use `time.sleep()`** in production code — use proper async patterns
- **Do not commit secrets** — use `.env` and ensure `.gitignore` covers it

**Operating guardrails (from hard-won failures — see BLUEPRINT.md):**
- **Do not set a thinking model as the active model.** Thinking models leave `content` empty and put output in `reasoning_content`, which breaks parsing. The model must be non-thinking local OR frontier.
- **Do not retry the same failing fix more than twice.** Two strikes → escalate to a frontier model, or halt and leave a note.
- **Do not trust your own "it works" — only passing tests confirm success.** Run `pytest`. The tests are ground truth, not your assessment. Do not mark a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt and report.
- **Do not invent product or architecture decisions to fill an ambiguous spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop tables, delete files outside the project) — halt and ask.

---

## Current Focus

See `tasks/CURRENT.md` for the active task spec (or just describe it in plain English to OpenCode).

---

## Key Contacts / Roles

| Role | Name |
|------|------|
| Product owner | [NAME] |
| Lead dev | [NAME] |

---

## LLM Correction Log

> When the LLM makes a mistake and you correct it, log it here.
> This is the most valuable section — it prevents repeat mistakes.
> A project 6 months in should have a rich log. That means the system is working.

| Date | Mistake | Guard Added |
|------|---------|-------------|
| [DATE] | [What went wrong] | [What rule prevents recurrence] |
| 2026-06-04 | LLM followed the Step 5 "Fill in the blanks" table literally and updated only the 4 listed files — 4 other files (TESTING.md, CONVENTIONS.md, tasks/CURRENT.md, tasks/BACKLOG.md) still had template placeholders. `[NAME]` survived in CLAUDE.md contacts until caught by external review. | Replace the table's authority with a placeholder-shaped grep as the verification gate. A maintained list drifts out of sync with reality; a grep check cannot. The table stays as a guide but the grep is the gate. Also: never rely on a maintained list for completeness — use a check. |
| 2026-06-04 | No "project is done" transition existed. After feature-complete, there was no defined end state — CURRENT.md had stale template text, backlog stayed open, docs were in "active development" voice. | Add a "Project Completion / Maintenance Transition" section to BLUEPRINT.md with a checklist. Add a curated cleanup step (Step 4.5) for template-only files, preserving the memory-layer docs (BLUEPRINT, CLAUDE, CONVENTIONS, all of docs/). |
| 2026-06-04 | Bootstrap Sequence assumed the user runs new-project.sh/bootstrap.sh in a terminal and starts opencode manually; no agent-driven path from just a URL + name. | Rewrote Steps 0–8 in agent-first voice: agent does create-from-template, doc read, spec-or-ask branch, cleanup, stack adaptation, placeholder fill, grep-gate verification, and first commit — user runs nothing. Removed obsolete bootstrap-run and opencode-start steps; gate (Rule 5) is the completion check. |
| 2026-06-04 | Commit `80c3e3f` (swap Aider→OpenCode) updated primary narrative (README, BLUEPRINT, scripts, opencode.json) but left 3 cosmetic Aider references behind (CONVENTIONS.md:3, .env.example:12, .gitignore Aider block) and never created the `AGENTS.md` symlink that README:17 and BLUEPRINT.md:54 already advertised. Template shipped in a broken-by-design state for OpenCode auto-load. | After any agent/CLI migration commit, run `grep -ril '<old-tool>' .` (excluding throwaway dirs) to catch residue, and verify every doc claim that names a file with `ls` / `git ls-files` before committing. Documented artifacts are contracts — treat doc-vs-reality drift as a release blocker. |
| 2026-06-04 | BLUEPRINT.md grew to 557 lines through 4 feature additions (Hard Rules, Bootstrap Sequence, Project Completion, Maintenance Contract). Document Map + Document Roles Explained covered the same ground twice. Bootstrap Steps 4/5/7 re-stated Rules 3 & 5 verbatim. Slogans (`lms not lmstudio`, "tests are ground truth", "same error twice") repeated 3-5 times. Phantom "Step 4.5" reference at line 490 with no such step in the sequence. Quick Reference Card restated the diagram. The file was ~22% larger than it needed to be. | After any doc edit, count lines (`wc -l`); BLUEPRINT.md target ≤450. After any sequence-of-steps section, verify every referenced step number (`Step N` or `Step N.M`) is reachable from a `### Step X` heading. Redundancy is context-window cost and a chance for ambiguity to compound — pruning is a guardrail, not cosmetics. |
| 2026-06-04 | Empirical test of the OpenCode auto-load claim: ran `opencode run --format json --dir /tmp/opencode-autoload-test "Read AGENTS.md..."` and inspected the event log. Three findings: (1) OpenCode did NOT pre-load AGENTS.md into context — the model invoked the `read` tool to fetch it. The CLAUDE.md intro claim "automatically read at session start" was false. (2) The tool-fetched content was correct. (3) The model got the answer wrong anyway — picked the first 2026-06-04 entry instead of the most recent. | The memory layer is *best-effort, not enforced*. Guards in CLAUDE.md are availability to a session, not a guarantee. When asserting any "auto-load" / "automatically read" claim, verify empirically (run the tool, ask a content-only question); a symlink existing is not proof. For anything that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) over doc guards — those fire without the LLM's cooperation. Doc guards are strong hints, not hard gates. |
| 2026-06-04 | Added a one-line "do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune" guard to CLAUDE.md "What NOT To Do" (commit `281819b`). The rule duplicated a `DECISIONS.md` "Do not suggest" line and baked a project-specific date into a template file (CLAUDE.md still has `[PROJECT_NAME]` placeholder). The visibility argument was real but the template-vs-project boundary was muddied. | Template files hold generic guards; project-specific rules live in `DECISIONS.md` and the correction log. When a rule has a date or event tied to one specific session, it does not belong in the template — even if CLAUDE.md is the most-read file. Cross-reference, don't copy. |
````
