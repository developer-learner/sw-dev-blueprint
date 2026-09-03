#!/usr/bin/env bash
# new-project.sh — create a new project from the sw-dev-blueprint template
#
# Two modes:
#
#   1. Copy-seed (classic — run from INSIDE a fresh clone of this template,
#      produced by `gh repo create --template` + git clone):
#        scripts/new-project.sh <project-name>
#      It invokes ./scripts/bootstrap.sh in the current directory, so the
#      "target" is the CWD, not a subdirectory of it.
#
#   2. Born-linked (D-183 — blueprint given by --from, defaulting to this
#      script's own checkout):
#        scripts/new-project.sh --linked <project-name> [--from <blueprint>] [--skip-bootstrap]
#      Creates <project-name> as a SIBLING of the blueprint checkout, seeds
#      the child-owned files, and immediately links every plane file as a
#      symlink into the blueprint. The child is born in the linked state —
#      no copy-seeded plane residue is ever left behind.
#      --skip-bootstrap: fixture/CI mode — skip the LLM preflight and the
#      venv/dependency bootstrap (seed + link still run).
set -euo pipefail

LINKED=0
SKIP_BOOTSTRAP=0
BLUEPRINT_OVERRIDE=""
if [ "${1:-}" = "--linked" ]; then
  LINKED=1
  shift
  PROJECT_NAME="${1:?usage: scripts/new-project.sh --linked <project-name> [--from <blueprint>] [--skip-bootstrap]}"
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --from) BLUEPRINT_OVERRIDE="${2:?--from needs a path}"; shift 2 ;;
      --skip-bootstrap) SKIP_BOOTSTRAP=1; shift ;;
      *) echo "ERROR: unknown option for --linked mode: $1" >&2; exit 1 ;;
    esac
  done
elif [ -n "${1:-}" ]; then
  PROJECT_NAME="$1"
else
  echo "usage: scripts/new-project.sh <project-name> | scripts/new-project.sh --linked <project-name> [--from <blueprint>] [--skip-bootstrap]" >&2
  exit 1
fi

TARGET_DIR="$(pwd -P)"
LLM_PORT="${SANDBOX_LLM_PORT:-1234}"
LLM_HOST="${LLM_HOST:-localhost}"
LLM_URL="http://$LLM_HOST:$LLM_PORT/v1/chat/completions"

die() { echo "ERROR: $*" >&2; exit 1; }
step() { echo "--- $* ---"; }

# Cross-platform sed in-place (macOS/BSD needs '' arg; GNU/Linux does not)
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(sed -i)        # GNU sed (Linux, CI)
else
  SED_INPLACE=(sed -i '')     # BSD sed (macOS)
fi

# Step 0: Pre-flight check (Hard Rule 1 & 4) — shared by both modes.
# Model-agnostic: probe whatever model the CEO has loaded — never hardcode one.
llm_preflight() {
  step "Pre-flight: checking local LLM at $LLM_URL ..."
  LOADED_MODELS="$(curl -s --max-time 10 "http://$LLM_HOST:$LLM_PORT/v1/models" \
    | python3 -c 'import sys,json
try:
    for m in json.load(sys.stdin)["data"]:
        print(m["id"])
except Exception:
    pass' || true)"
  [ -n "$LOADED_MODELS" ] || die "no model loaded in LM Studio. Load one (any non-thinking model) and retry."
  LOADED_MODEL="$(printf '%s\n' "$LOADED_MODELS" | head -1)"
  if [ "$(printf '%s\n' "$LOADED_MODELS" | wc -l | tr -d ' ')" -gt 1 ]; then
    echo "  WARNING: multiple models loaded — probing the first:"
    printf '%s\n' "$LOADED_MODELS" | sed 's/^/    /'
    echo "  (make sure your OpenCode global config maps agents to the intended ones)"
  fi
  echo "  probing model: $LOADED_MODEL"

  PREFLIGHT_RAW="$(curl -s --max-time 30 "$LLM_URL" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$LOADED_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"max_tokens\":5,\"temperature\":0}" \
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
}

# --- Born-linked mode (D-183) -------------------------------------------------
# The child is created as a sibling of the blueprint checkout and converted to
# the linked state in the same run:
#   commit 1 — seed: child-owned files + a copy-seeded plane skeleton (a valid
#               D-34 state, so the commit is gate-consistent and the link
#               step's git-add pathspecs all resolve)
#   commit 2 — [template-link]: every plane file replaced by a symlink into
#               the blueprint, .template-link written, manifests re-pinned
#   commit 3 — bootstrap artifacts (venv/deps/hooks), unless --skip-bootstrap
born_linked() {
  local name="$1" blueprint="$2" skip_bootstrap="$3"
  local target birth_sha plan_sha preview f wf p

  [ -f "$blueprint/scripts/.manifest-template" ] || die "not a blueprint checkout: $blueprint"
  [ -f "$blueprint/.template-version" ] || die "blueprint missing .template-version: $blueprint"
  [ -f "$blueprint/CLAUDE.md" ] || die "blueprint missing CLAUDE.md — cannot seed: $blueprint"
  git var GIT_AUTHOR_IDENT >/dev/null 2>&1 \
    || die "git identity missing — set user.name/user.email (or GIT_AUTHOR_*/GIT_COMMITTER_* env)"
  target="$(cd "$blueprint/.." && pwd -P)/$name"
  [ -e "$target" ] && die "target already exists: $target"

  echo "🧬 Born-linked seeding: $name"
  echo "   blueprint: $blueprint"
  echo "   target:    $target"
  echo ""

  if [ "$skip_bootstrap" = 0 ]; then
    llm_preflight
    echo ""
  fi

  # --- 1a. Seed the child-owned files (the plane is handled in 1b) ----------
  mkdir -p "$target/.github/workflows" "$target/scripts" "$target/docs" "$target/tasks"
  for f in CLAUDE.md CONVENTIONS.md README.md .gitignore .gate-paths opencode.json \
           Containerfile requirements.txt .dockerignore .env.example; do
    [ -f "$blueprint/$f" ] && cp "$blueprint/$f" "$target/$f"
  done
  for wf in "$blueprint"/.github/workflows/*.yml; do
    [ -f "$wf" ] || continue
    # check-drift.yml is the plane exception — the link step installs it as a
    # real file from the blueprint; don't seed a copy the link would replace.
    [ "$(basename "$wf")" = "check-drift.yml" ] && continue
    cp "$wf" "$target/.github/workflows/$(basename "$wf")"
  done
  # AGENTS.md → CLAUDE.md (bootstrap would create it; creating it now lets the
  # link step's manifest re-pin hash it).
  ln -s CLAUDE.md "$target/AGENTS.md"

  # --- 1b. Seed the plane as a copy-seeded skeleton --------------------------
  # Copied whole so commit 1 is a valid D-34 (copied) state: the plane
  # manifest's hashes match the tree, and the link step's explicit git-add
  # pathspecs all resolve. Step 3 converts every one of these into a symlink.
  # (The plane manifest itself is copied explicitly — it is the link step's
  # precondition and is listed in the real blueprint's manifest anyway.)
  mkdir -p "$target/scripts"
  cp "$blueprint/scripts/.manifest-template" "$target/scripts/.manifest-template"
  while IFS='  ' read -r _hash p; do
    [ -z "$p" ] && continue
    mkdir -p "$target/$(dirname "$p")"
    cp "$blueprint/$p" "$target/$p"
  done < "$blueprint/scripts/.manifest-template"

  # Rename placeholders in the child-owned files (the plane copies are
  # replaced by the link anyway; bootstrap's rename stays for the copy-seed
  # flow and is a no-op here).
  find "$target" -type f \( -name "*.md" -o -name "*.yml" -o -name "*.yaml" \) \
    -not -path "$target/.git/*" \
    -exec "${SED_INPLACE[@]}" "s/\[PROJECT_NAME\]/$name/g" {} +

  # --- 1c. Identity + child-owned inventory ----------------------------------
  # .template-version — pre-stamped with the LOCAL blueprint HEAD: in linked
  # mode the plane is this checkout, so the local ref is the truth (no gh api
  # — GitHub's HEAD may be behind the local checkout the symlinks resolve to).
  birth_sha="$(git -C "$blueprint" rev-parse HEAD)"
  sed "s/^ref=.*/ref=$birth_sha/" "$blueprint/.template-version" > "$target/.template-version"

  # scripts/.manifest-project — the child-owned inventory (PENDING; the link
  # step's regen fills the hashes). Every listed file exists at that point.
  {
    echo "PENDING  .template-version"
    for f in CLAUDE.md CONVENTIONS.md README.md .gitignore .gate-paths opencode.json \
             Containerfile requirements.txt .dockerignore .env.example AGENTS.md \
             docs/DECISIONS.md tasks/CURRENT.md tasks/BACKLOG.md; do
      [ -f "$target/$f" ] && echo "PENDING  $f"
    done
    for wf in "$target"/.github/workflows/*.yml; do
      [ -f "$wf" ] && echo "PENDING  .github/workflows/$(basename "$wf")"
    done
  } > "$target/scripts/.manifest-project"

  # Minimal child-owned docs/tasks — fresh logs, NOT the blueprint's.
  cat > "$target/docs/DECISIONS.md" <<'EOF'
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
EOF
  cat > "$target/tasks/CURRENT.md" <<EOF
# CURRENT — $name

No active milestone yet. First milestone: author the frozen spec
(PRD/ERD/contracts/tests) with your TPM, stage it under
scripts/.approved/incoming/, run scripts/refreeze.sh, then
scripts/orchestrate.sh.
EOF
  cat > "$target/tasks/BACKLOG.md" <<'EOF'
# BACKLOG

(quiet — nothing queued)
EOF

  # --- 2. Seed commit (hooks not yet enabled — the baseline is exempt) -------
  (
    cd "$target"
    git init -q -b main
    git add -A
    git commit -q -m "chore: seed $name (born-linked from sw-dev-blueprint @ ${birth_sha:0:12})"
  )

  # --- 3. Link: every plane file becomes a symlink into the blueprint --------
  # The same two-step approval as a manual link: dry-run → PLAN-SHA → approve.
  echo "🔗 Linking plane into the blueprint..."
  preview="$(cd "$target" && "$blueprint/scripts/link-template.sh" --from "$blueprint" --dry-run)" \
    || die "link dry-run failed"
  plan_sha="$(printf '%s\n' "$preview" | grep -o 'PLAN-SHA: [0-9a-f]\{64\}' | awk '{print $2}' || true)"
  [ -n "$plan_sha" ] || die "link dry-run produced no PLAN-SHA"
  (cd "$target" && "$blueprint/scripts/link-template.sh" --from "$blueprint" --approve "$plan_sha")

  # --- 4. Bootstrap (venv, deps, hooks, .env) — unless --skip-bootstrap ------
  if [ "$skip_bootstrap" = 0 ]; then
    echo ""
    step "Running bootstrap..."
    (cd "$target" && "$blueprint/scripts/bootstrap.sh" "$name")
    (
      cd "$target"
      # bootstrap rewrites requirements.txt (pip freeze) — re-pin before the
      # final commit so the (now-enabled) pre-commit gate passes.
      bash scripts/regen-manifest.sh scripts/.manifest-project
      git add -A
      if ! git diff --cached --quiet; then
        git commit -q -m "chore: bootstrap $name (venv, deps, hooks)"
      fi
    )
  fi

  echo ""
  echo "✅ $name is born-linked at $target"
  echo "   plane: symlinks into the blueprint (pinned at ${birth_sha:0:12})"
  echo "   next: cd $target && scripts/orchestrate.sh"
}

if [ "$LINKED" = 1 ]; then
  BLUEPRINT_DIR="${BLUEPRINT_OVERRIDE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
  BLUEPRINT_DIR="$(cd "$BLUEPRINT_DIR" && pwd -P)"
  born_linked "$PROJECT_NAME" "$BLUEPRINT_DIR" "$SKIP_BOOTSTRAP"
  exit 0
fi

llm_preflight

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
3. Adapt stack if needed (Rule 3): edit ci.yml / requirements if not FastAPI+SQLite
4. Load one or two non-thinking models in LM Studio (your choice — D-41: the
   repo never names a model) and map roles in ~/.config/sw-dev-blueprint/models.env
   (SWBP_EM_MODEL=<name>, SWBP_CODER_MODEL=<name>).
5. Author the frozen spec (PRD/ERD/contracts/tests) with your TPM chat, stage
   under scripts/.approved/incoming/, run scripts/refreeze.sh.
6. scripts/orchestrate.sh — the shell drives EM and coder over HTTP
   directly (D-53), no agent harness needed. A conductor (Claude Code,
   OpenCode, anything) is optional for CEO ergonomics only.

Tests are binding automated completion evidence (Rule 5).
Two strikes on the same error then stop (Rule 2).
DONE
