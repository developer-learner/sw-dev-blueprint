#!/bin/bash
# bootstrap.sh — Run once when starting a new project from this template
#
# Usage: ./scripts/bootstrap.sh <project-name>
#
# What it does:
#   1. Renames placeholders throughout docs
#   2. Creates Python virtual environment
#   3. Installs base dependencies
#   4. Initializes git (if not already)
#   5. Prints next steps
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

# --- Python virtual environment ---
echo "🐍 Creating virtual environment..."
python3.12 -m venv .venv
source .venv/bin/activate

# --- Base dependencies (DEFAULT STACK — edit for your project, Rule 3) ---
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

# Save to requirements files
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
echo "  3. Update CLAUDE.md with your project description and tech stack"
echo "  4. Update docs/PRODUCT.md with your product context"
echo "  5. Write your first task in tasks/CURRENT.md (be specific!)"
echo "  6. Run Pre-Flight Check (BLUEPRINT.md Step 0)"
echo "  7. Start LM Studio, load the non-thinking model"
echo "  8. Run: aider --architect src/"
echo ""
echo "Happy building 🛠"
