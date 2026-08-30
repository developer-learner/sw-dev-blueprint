#!/usr/bin/env bash
# llm-call.sh — D-53: the pipeline speaks to models over bare HTTP.
#
# One completion per call, no harness: the shell owns all procedure, files,
# and state; the model only ever answers one question. This replaces the
# containerized `opencode run` path (D-40/D-52), whose seams — attach
# protocol, agent modes, version pins, config mounts — produced every
# failure of the first three supervised runs and zero of the catches.
#
# Usage: llm-call.sh <role> <system-prompt-file> [--schema <json-schema-file>]
#                    [--max-time <seconds>]
#   - user prompt is read from STDIN
#   - the model's content is printed on STDOUT (markdown fences stripped)
#   - --schema constrains the response to a JSON schema (LM Studio
#     structured output); best-effort — if the server rejects the schema,
#     the call retries unconstrained and the downstream gate still validates.
#
# Model mapping (D-41, unchanged in spirit): never recorded in this repo.
# The CEO maps roles to models in ~/.config/sw-dev-blueprint/models.env:
#     SWBP_EM_MODEL=<id as served by the local endpoint>
#     SWBP_CODER_MODEL=<id>
# Environment variables of the same names override the file.
# No mapping for the requested role = hard halt (D-52: no silent fallback).
set -euo pipefail

ROLE="${1:?usage: llm-call.sh <role> <system-prompt-file> [--schema f] [--max-time s] [--expect-model id]}"
SYS_FILE="${2:?system prompt file required}"
shift 2
SCHEMA=""
MAX_TIME=1800
EXPECT_MODEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --schema)   SCHEMA="${2:?}"; shift 2 ;;
    --max-time) MAX_TIME="${2:?}"; shift 2 ;;
    --expect-model) EXPECT_MODEL="${2:?}"; shift 2 ;;
    *) echo "llm-call: unknown arg $1" >&2; exit 2 ;;
  esac
done
[ -f "$SYS_FILE" ] || { echo "llm-call FAIL: system prompt not found: $SYS_FILE" >&2; exit 1; }
[ -z "$SCHEMA" ] || [ -f "$SCHEMA" ] || { echo "llm-call FAIL: schema not found: $SCHEMA" >&2; exit 1; }

CFG="$HOME/.config/sw-dev-blueprint/models.env"
VAR="SWBP_$(printf '%s' "$ROLE" | tr '[:lower:]' '[:upper:]')_MODEL"
_PRE_HOST="${SANDBOX_LLM_HOST:-}"
_PRE_PORT="${SANDBOX_LLM_PORT:-}"
if [ -z "${!VAR:-}" ] && [ -f "$CFG" ]; then
  # shellcheck disable=SC1090
  . "$CFG"
fi
[ -n "$_PRE_HOST" ] && SANDBOX_LLM_HOST="$_PRE_HOST"
[ -n "$_PRE_PORT" ] && SANDBOX_LLM_PORT="$_PRE_PORT"
MODEL="${!VAR:-}"
[ -n "$MODEL" ] || {
  echo "llm-call FAIL: no model mapped for role '$ROLE' — set $VAR in $CFG (or export it). No silent fallback (D-52/D-53)." >&2
  exit 1
}

: "${SANDBOX_LLM_HOST:=localhost}"
: "${SANDBOX_LLM_PORT:=1234}"
URL="http://$SANDBOX_LLM_HOST:$SANDBOX_LLM_PORT/v1/chat/completions"

# Read user prompt from stdin into a tempfile BEFORE the heredoc — stdin and
# heredoc both compete for fd 0, so the piped content must be captured first.
# Linux caps a single env-var string at ~128 KB; large contexts (all frozen
# tests, a big ERD) would die on E2BIG. Passing via file removes the ceiling.
USER_FILE="$(mktemp -t swbp-user-XXXXXX)"
trap 'rm -f "$USER_FILE"' EXIT
cat > "$USER_FILE"

PROFILES="$HOME/.config/sw-dev-blueprint/model-profiles.toml"

SWBP_LLM_URL="$URL" SWBP_LLM_MODEL="$MODEL" SWBP_LLM_SYS="$SYS_FILE" \
SWBP_LLM_SCHEMA="$SCHEMA" SWBP_LLM_MAXTIME="$MAX_TIME" SWBP_LLM_ROLE="$ROLE" \
SWBP_LLM_USER_FILE="$USER_FILE" SWBP_LLM_PROFILES="$PROFILES" \
SWBP_LLM_EXPECT_MODEL="$EXPECT_MODEL" \
python3 - <<'PYEOF'
import json
import os
import re
import sys
import urllib.error
import urllib.request

url = os.environ["SWBP_LLM_URL"]
model = os.environ["SWBP_LLM_MODEL"]
role = os.environ["SWBP_LLM_ROLE"]
max_time = int(os.environ["SWBP_LLM_MAXTIME"])
system = open(os.environ["SWBP_LLM_SYS"]).read()
schema_path = os.environ.get("SWBP_LLM_SCHEMA") or ""
user = open(os.environ["SWBP_LLM_USER_FILE"]).read()
profiles_path = os.environ.get("SWBP_LLM_PROFILES") or ""

# Load model profile (settings from model-profiles.toml override defaults)
profile: dict = {}
if profiles_path and os.path.isfile(profiles_path):
    try:
        import tomllib
        with open(profiles_path, "rb") as f:
            all_profiles = tomllib.load(f)
        profile = all_profiles.get(model, {})
        if profile:
            print(f"llm-call: loaded profile for '{model}'", file=sys.stderr)
    except Exception as e:
        print(f"llm-call: warning: could not read {profiles_path}: {e}",
              file=sys.stderr)

def call(body: dict) -> dict:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=max_time) as r:
        return json.load(r)

body = {
    "model": model,
    "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ],
    "temperature": profile.get("temperature", 0.2),
    "stream": False,
    "enable_thinking": profile.get("enable_thinking", False),
    # Output budget (found via testchat M11a): with no cap, a runaway
    # generation's only ceiling is the context window — a 70-line file task
    # ran 23 minutes into a 32K window. Chat users ARE the cap; the pipeline
    # must set its own. Override per model via max_output_tokens in the
    # profile, or per CALL via SWBP_MAX_OUTPUT (testchat M17: edit-block
    # replies are legitimately small — a tighter edit-mode budget halves
    # the wall-clock cost of every failed attempt, since a local model
    # generates its whole allowance before the applier can reject it).
    # `or 0`, not a .get() default: orchestrate.sh legitimately exports
    # SWBP_MAX_OUTPUT="" for create-mode ("no per-call override"), and
    # int('') raises — which killed every create-mode coder call from the
    # M17 budget change until the 2026-07-16 ladder drill exposed it.
    "max_tokens": int(os.environ.get("SWBP_MAX_OUTPUT") or 0)
                  or profile.get("max_output_tokens", 8192),
}
if profile.get("extra_body"):
    body.update(profile["extra_body"])
if schema_path:
    body["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "output", "strict": True,
                        "schema": json.load(open(schema_path))},
    }

try:
    resp = call(body)
except urllib.error.HTTPError as e:
    err_body = e.read()[:500].decode(errors='replace')
    if schema_path:
        print(f"llm-call: schema-constrained request rejected by server "
              f"({e.code}: {err_body}); retrying unconstrained — downstream "
              f"gate still validates", file=sys.stderr)
        body.pop("response_format", None)
        try:
            resp = call(body)
        except urllib.error.HTTPError as e2:
            sys.exit(f"llm-call FAIL: unconstrained retry also rejected — "
                     f"HTTP {e2.code} from {url}: "
                     f"{e2.read()[:500].decode(errors='replace')}")
    else:
        sys.exit(f"llm-call FAIL: HTTP {e.code} from {url}: {err_body}")
except urllib.error.URLError as e:
    sys.exit(f"llm-call FAIL: cannot reach {url} ({e.reason}) — is the local "
             f"LLM server running? Halting, not proceeding (Hard Rule 4).")

msg = resp["choices"][0]["message"]
# Surface WHY generation ended on stderr (lands in the caller's log file):
# 'stop' = the model finished naturally, 'length' = cut off by the token
# budget. Downstream parsers use this to distinguish "complete reply that
# merely forgot a trailing sentinel" from a truncated one (testchat M7 T3).
print(f"llm-call: finish_reason={resp['choices'][0].get('finish_reason', 'unknown')}",
      file=sys.stderr)
content = (msg.get("content") or "").strip()
reasoning = (msg.get("reasoning_content") or "").strip()
if not content and reasoning:
    sys.exit(f"llm-call FAIL: model '{model}' for role '{role}' returned "
             f"reasoning but no content — thinking model loaded (Hard Rule 1).")
if not content:
    sys.exit(f"llm-call FAIL: empty content from model '{model}'.")

# Seat verification (--expect-model): when the caller names the model the
# seat must answer with, the server's own "model" field is the claim to
# check. A mismatch means the mapped seat model is NOT the one serving —
# e.g. the server reloaded a different default (D-62 drift) or the mapping
# points at an id the server aliases. Fail closed: proceeding on the wrong
# seat is how mid-run confusion starts. A server that does not report a
# model id cannot be verified — warn and continue (the reply checks above
# still run).
expect_model = os.environ.get("SWBP_LLM_EXPECT_MODEL")
if expect_model:
    served = resp.get("model")
    if not served:
        print(f"llm-call: warning: cannot verify seat model — server did "
              f"not report 'model'; expected {expect_model}", file=sys.stderr)
    elif served != expect_model:
        sys.exit(f"llm-call FAIL: seat mismatch — server answered with model "
                 f"'{served}', expected '{expect_model}' for role '{role}'. "
                 f"The mapped seat model is not the one serving; check the "
                 f"loaded model / model mapping before proceeding.")

if profile.get("strip_think_tags", True):
    # LEADING block only — that is the shape of leaked reasoning. A global
    # strip corrupts replies whose CODE legitimately contains think-tag
    # literals (D-59, found via testchat M7: edit blocks quoting frontend
    # think-handling were eaten mid-anchor).
    content = re.sub(r"\A\s*<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
    if not content:
        sys.exit(f"llm-call FAIL: content was only a <think> block from model '{model}'.")

# Strip a single wrapping markdown fence if present (local models add them).
# Anchored ^...$ matching missed replies wrapped in prose ("Here is the
# plan:") — but a global strip would corrupt replies whose content
# legitimately contains fence literals (the D-59 think-tag class), so strip
# only when the reply carries exactly one fence pair, anywhere in it.
if content.count("```") == 2:
    m = re.search(r"```[a-zA-Z0-9_-]*\n(.*?)\n```", content, re.DOTALL)
    if m:
        content = m.group(1)
sys.stdout.write(content)
PYEOF
