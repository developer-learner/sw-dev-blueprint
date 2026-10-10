#!/usr/bin/env bash
# new-project.sh — create a new builder-targeted app (D-186)
#
#   scripts/new-project.sh [--targeted] <project-name> [--from <blueprint>] [--skip-bootstrap]
#
# Creates <project-name> as a sibling of the blueprint checkout with NO control
# plane: child-owned files, app CI + swbp-guard workflows, and a `.swbp` pin to
# the blueprint's HEAD. The pipeline runs from the builder:
# `scripts/swbp <cmd> --app <project>`. --skip-bootstrap skips only the LLM
# preflight. (`--targeted` is accepted for compatibility; it is the only mode.
# The copy-seed and born-linked modes were retired with the sync layer at
# stage F, D-218.)
set -euo pipefail

SKIP_BOOTSTRAP=0
BLUEPRINT_OVERRIDE=""
[ "${1:-}" = "--targeted" ] && shift
case "${1:-}" in
  --linked) echo "ERROR: --linked was retired at stage F (D-218) — apps are builder-targeted; run without it" >&2; exit 1 ;;
  ""|-*) echo "usage: scripts/new-project.sh [--targeted] <project-name> [--from <blueprint>] [--skip-bootstrap]" >&2; exit 1 ;;
esac
PROJECT_NAME="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --from) BLUEPRINT_OVERRIDE="${2:?--from needs a path}"; shift 2 ;;
    --skip-bootstrap) SKIP_BOOTSTRAP=1; shift ;;
    *) echo "ERROR: unknown option: $1" >&2; exit 1 ;;
  esac
done

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

# --- D-186: builder-targeted birth -------------------------------------------
# The app is born with no control plane. One seed commit, made through the
# provenance broker (`swbp commit`), so the app guard sees a clean history.
born_targeted() {
  local name="$1" blueprint="$2" skip_bootstrap="$3"
  local target birth_sha f wf

  [ -x "$blueprint/scripts/swbp" ] || die "not a builder checkout (no scripts/swbp): $blueprint"
  [ -d "$blueprint/app-template" ] || die "builder missing app-template/: $blueprint"
  [ -f "$blueprint/CLAUDE.md" ] || die "blueprint missing CLAUDE.md — cannot seed: $blueprint"
  git var GIT_AUTHOR_IDENT >/dev/null 2>&1 \
    || die "git identity missing — set user.name/user.email (or GIT_AUTHOR_*/GIT_COMMITTER_* env)"
  target="$(cd "$blueprint/.." && pwd -P)/$name"
  [ -e "$target" ] && die "target already exists: $target"
  birth_sha="$(git -C "$blueprint" rev-parse HEAD)"
  git -C "$blueprint" cat-file -e "$birth_sha:scripts/swbp" 2>/dev/null \
    || die "builder HEAD $birth_sha has no committed scripts/swbp — commit it first"

  echo "🧬 Builder-targeted seeding: $name"
  echo "   builder: $blueprint @ ${birth_sha:0:12}"
  echo "   target:  $target"
  echo ""
  if [ "$skip_bootstrap" = 0 ]; then llm_preflight; echo ""; fi

  mkdir -p "$target/.github/workflows" "$target/docs" "$target/tasks"
  for f in CLAUDE.md CONVENTIONS.md README.md .gitignore .gate-paths opencode.json \
           Containerfile requirements.txt .dockerignore .env.example; do
    [ -f "$blueprint/$f" ] && cp "$blueprint/$f" "$target/$f"
  done
  for wf in "$blueprint"/app-template/.github/workflows/*.yml; do
    cp "$wf" "$target/.github/workflows/$(basename "$wf")"
  done
  [ -f "$blueprint/.github/workflows/container-build.yml" ] \
    && cp "$blueprint/.github/workflows/container-build.yml" "$target/.github/workflows/"
  ln -s CLAUDE.md "$target/AGENTS.md"
  printf 'repo=developer-learner/sw-dev-blueprint\nref=%s\n' "$birth_sha" > "$target/.swbp"

  find "$target" -type f \( -name "*.md" -o -name "*.yml" -o -name "*.yaml" \) \
    -exec "${SED_INPLACE[@]}" "s/\[PROJECT_NAME\]/$name/g" {} +
  python3 - "$target/CLAUDE.md" "$blueprint" "$target" <<'PY'
import sys
from pathlib import Path
path, builder, app = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
note = f"""> **D-186 — builder-targeted app.** This repo carries no control plane.
> Every `scripts/<name>.sh` named below means
> `{builder}/scripts/swbp <name> --app {app} [-- args]`. The builder version
> is pinned in `.swbp`; change it only between milestones. A person's change
> to tests, the frozen spec, or pipeline adaptations goes through
> `swbp commit --app {app} -- "<subject>" <files>`.

"""
head, _, rest = path.read_text().partition("\n")
path.write_text(head + "\n\n" + note + rest)
PY

  cat > "$target/docs/DECISIONS.md" <<'DOC'
# DECISIONS.md — Architectural Decision Log

> Every non-obvious technical decision goes here with the reasoning.
> Format: date, decision, why, what not to suggest.

---
DOC
  cat > "$target/tasks/CURRENT.md" <<DOC
# CURRENT — $name

No active milestone yet. First milestone: author the frozen spec
(PRD/ERD/contracts/tests) with your TPM, stage it under
scripts/.approved/incoming/, then from the builder:
  $blueprint/scripts/swbp refreeze --app $target -- scripts/.approved/incoming
  $blueprint/scripts/swbp orchestrate --app $target
DOC
  printf '# BACKLOG\n\n(quiet — nothing queued)\n' > "$target/tasks/BACKLOG.md"

  git init -q -b main "$target"
  "$blueprint/scripts/swbp" commit --app "$target" -- \
    "chore: seed $name (builder-targeted, sw-dev-blueprint @ ${birth_sha:0:12})" -A \
    || die "seed commit failed"

  echo ""
  echo "✅ $name is born builder-targeted at $target (no control plane)"
  echo "   builder pin: ${birth_sha:0:12} (.swbp)"
  echo "   next: map the model seats in ~/.config/sw-dev-blueprint/models.env"
  echo "         (SWBP_EM_MODEL=<name>, SWBP_CODER_MODEL=<name>) and check each with"
  echo "         $blueprint/scripts/seat-check.sh em|coder (Rule 1, D-209);"
  echo "         create a venv, author the spec, then $blueprint/scripts/swbp refreeze --app $target"
}

BLUEPRINT_DIR="${BLUEPRINT_OVERRIDE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
BLUEPRINT_DIR="$(cd "$BLUEPRINT_DIR" && pwd -P)"
born_targeted "$PROJECT_NAME" "$BLUEPRINT_DIR" "$SKIP_BOOTSTRAP"
