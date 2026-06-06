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

# --- Base dependencies (DEFAULT: FastAPI + SQLite. For Postgres, add
# asyncpg + alembic. See BLUEPRINT.md Rule 3.) ---
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
  aiosqlite

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
