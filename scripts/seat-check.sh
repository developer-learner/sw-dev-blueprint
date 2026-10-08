#!/usr/bin/env bash
# seat-check.sh — the Rule 1 admission test for a model seat (D-209).
#
# A model/backend combination may hold the EM or coder seat only if it
# reliably returns a COMPLETE, PARSEABLE artifact in the reply's content
# within its configured budget. Reasoning ("thinking") models are fine when
# the backend still delivers the final answer as content; what is refused is
# an empty, reasoning-only, truncated, or unparseable reply. This runs the
# seat through the pipeline's own llm-call.sh (same mapping, profile, budget)
# with a small representative task, so a pass means the real call path works.
#
#   scripts/seat-check.sh coder   # create-mode file reply, must compile
#   scripts/seat-check.sh em      # schema-bound JSON diagnosis, must validate
#
# Uses the same seat resolution as a run (SWBP_<ROLE>_MODEL, models.env,
# SANDBOX_LLM_HOST/PORT). Exit 0 = admitted, 1 = refused (reason printed).
set -uo pipefail

ROLE="${1:-}"
case "$ROLE" in em|coder) ;; *) echo "usage: seat-check.sh <em|coder>" >&2; exit 2 ;; esac
PLANE="$(cd "$(dirname "$0")/.." && pwd -P)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/seat-check.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
refuse() { echo "seat-check $ROLE: REFUSED — $*"; exit 1; }

if [ "$ROLE" = coder ]; then
  cat > "$TMP/prompt" <<'EOF'
Create src/seat_check_probe.py: define `def add(a: int, b: int) -> int` that returns a + b. Nothing else.

Write EXACTLY one file: src/seat_check_probe.py — the gate rejects any other change.

Reply with ONLY this, nothing before or after it:
=== FILE: src/seat_check_probe.py ===
<the complete file content>
=== END FILE ===
EOF
  bash "$PLANE/scripts/llm-call.sh" coder "$PLANE/.opencode/prompts/coder.md" \
    < "$TMP/prompt" > "$TMP/reply" 2> "$TMP/log" \
    || refuse "llm-call failed: $(tail -2 "$TMP/log" | tr '\n' ' ')"
  grep -q "finish_reason=stop" "$TMP/log" \
    || refuse "reply did not finish naturally ($(grep -o 'finish_reason=[a-z_]*' "$TMP/log" || echo 'no finish_reason')) — budget too small or truncated"
  python3 - "$TMP/reply" <<'PY' || refuse "reply is not a complete, compilable file block"
import ast, re, sys
text = open(sys.argv[1]).read()
m = re.search(r"=== FILE: src/seat_check_probe.py ===\n(.*)\n=== END FILE ===", text, re.S)
if not m:
    sys.exit("no complete file block")
tree = ast.parse(m.group(1))
if not any(isinstance(n, ast.FunctionDef) and n.name == "add" for n in tree.body):
    sys.exit("file does not define add()")
PY
else
  cat > "$TMP/prompt" <<'EOF'
Task T1 (src/app.py) failed twice: the frozen test expects HTTP 201 from POST /items, the coder's file returns 200 because the brief never states the status code. Diagnose the single likeliest cause and reply with ONLY the JSON verdict.
EOF
  bash "$PLANE/scripts/llm-call.sh" em "$PLANE/.opencode/prompts/em.md" \
    --schema "$PLANE/scripts/schemas/diagnosis.schema.json" \
    < "$TMP/prompt" > "$TMP/reply" 2> "$TMP/log" \
    || refuse "llm-call failed: $(tail -2 "$TMP/log" | tr '\n' ' ')"
  grep -q "finish_reason=stop" "$TMP/log" \
    || refuse "reply did not finish naturally ($(grep -o 'finish_reason=[a-z_]*' "$TMP/log" || echo 'no finish_reason')) — budget too small or truncated"
  python3 - "$TMP/reply" <<'PY' || refuse "reply is not a valid diagnosis JSON"
import json, sys
d = json.load(open(sys.argv[1]))
allowed = {"brief_wrong", "decomposition_wrong", "contract_or_test_wrong", "transient_or_environmental"}
if d.get("verdict") not in allowed or not str(d.get("reason", "")).strip():
    sys.exit("missing or unknown verdict/reason")
PY
fi
echo "seat-check $ROLE: ADMITTED — complete, parseable artifact in content, finished within budget"
