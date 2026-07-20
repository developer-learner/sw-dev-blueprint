#!/usr/bin/env bash
# em-bench.sh — replay archived EM diagnosis calls with variant briefs.
#
# Replays the prompt from an .em-archive/ entry through the live EM using a
# (possibly alternate) system prompt and scores the reply. Designed for A/B
# testing diagnosis brief variants against a corpus of real consults
# (backlog item 6). Two scoring modes, chosen per entry from its meta:
#
#   compare — the capture succeeded (meta has verdict=): replay and report
#             MATCH/MISMATCH against the recorded verdict (stability).
#   fix     — the capture FAILED (outcome=invalid_json, or
#             validation=schema_invalid): replay and report FIXED (reply now
#             passes the diagnosis validator) or STILL_INVALID. These are the
#             entries the brief-variant work exists for.
#
# Plan entries (…_plan) carry plan_gate metadata for manual analysis but are
# not replayed here — scoring a plan needs the child's full frozen context.
#
# Usage:
#   em-bench.sh <archive-entry>                    # replay one entry
#   em-bench.sh --all                              # replay every diagnosis entry
#   em-bench.sh <entry> --brief alt-em-prompt.md   # test a variant brief
#
# Requires: a running LLM server, models.env configured for the em role.
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

BRIEF=".opencode/prompts/em.md"
ALL=0
ENTRIES=()

while [ $# -gt 0 ]; do
  case "$1" in
    --brief) BRIEF="${2:?--brief needs a file}"; shift 2 ;;
    --all)   ALL=1; shift ;;
    -*)      echo "em-bench: unknown flag $1" >&2; exit 2 ;;
    *)       ENTRIES+=("$1"); shift ;;
  esac
done

[ -f "$BRIEF" ] || { echo "em-bench: brief not found: $BRIEF" >&2; exit 1; }
[ -x scripts/llm-call.sh ] || { echo "em-bench: scripts/llm-call.sh missing" >&2; exit 1; }

# A diagnosis entry is replayable if it succeeded (verdict=) or failed in a
# way the bench can score a fix for (invalid_json / schema_invalid).
replayable() {
  grep -q '^out=tasks/diagnosis.json' "$1/meta.txt" || return 1
  grep -qE '^(verdict=|outcome=invalid_json|validation=schema_invalid)' "$1/meta.txt"
}

if [ "$ALL" = "1" ]; then
  for d in .em-archive/*; do
    [ -d "$d" ] && [ -f "$d/meta.txt" ] && replayable "$d" && ENTRIES+=("$d")
  done
  [ "${#ENTRIES[@]}" -gt 0 ] \
    || { echo "em-bench: no replayable diagnosis entries in .em-archive/" >&2; exit 1; }
fi

[ "${#ENTRIES[@]}" -gt 0 ] \
  || { echo "usage: em-bench.sh <archive-entry> [--brief <file>] | --all" >&2; exit 2; }

match=0 mismatch=0 fixed=0 still_invalid=0 errors=0

for ENTRY in "${ENTRIES[@]}"; do
  [ -f "$ENTRY/prompt.txt" ] || { echo "SKIP $ENTRY (no prompt.txt)"; continue; }
  [ -f "$ENTRY/meta.txt" ]   || { echo "SKIP $ENTRY (no meta.txt)"; continue; }

  recorded_verdict=$(grep -m1 '^verdict=' "$ENTRY/meta.txt" | cut -d= -f2- || true)
  task_id=$(grep -m1 '^task_id=' "$ENTRY/meta.txt" | cut -d= -f2- || true)
  mode="fix"; [ -n "$recorded_verdict" ] && mode="compare"

  echo "--- $(basename "$ENTRY") [$mode] ---"
  echo "  brief: $BRIEF"
  [ -n "$recorded_verdict" ] && echo "  recorded: $recorded_verdict" \
    || echo "  recorded: FAILED ($(grep -m1 -E '^(outcome=invalid_json|validation=schema_invalid)' "$ENTRY/meta.txt"))"

  replay_dir="$ENTRY/replays/$(date '+%Y-%m-%d_%H%M%S')_$(basename "$BRIEF" .md)"
  mkdir -p "$replay_dir"
  cp "$BRIEF" "$replay_dir/brief-used.md"

  if ! timeout 300 scripts/llm-call.sh em "$BRIEF" \
        --schema scripts/schemas/diagnosis.schema.json --max-time 300 \
      < "$ENTRY/prompt.txt" \
      > "$replay_dir/reply.json" 2> "$replay_dir/stderr.log"; then
    echo "  RESULT: call_failed"
    errors=$((errors + 1))
    continue
  fi

  # Stamp task_id the way the orchestrator does (D-71: it is never the
  # model's to echo), then validate. Any failure from here scores the reply.
  if replay_verdict=$(python3 - "$replay_dir" "${task_id:-BENCH}" <<'PYEOF'
import json, subprocess, sys
rd, tid = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(f"{rd}/reply.json"))
except Exception:
    sys.exit(1)
if isinstance(d, dict):
    d["task_id"] = tid
json.dump(d, open(f"{rd}/reply-stamped.json", "w"), indent=2)
r = subprocess.run(
    [sys.executable, "scripts/validate-plan.py", "--diagnosis", f"{rd}/reply-stamped.json"],
    capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(1)
print(r.stdout.strip())
PYEOF
  ); then
    replay_valid=1
  else
    replay_valid=0 replay_verdict=""
  fi

  if [ "$mode" = "compare" ]; then
    echo "  replay:   ${replay_verdict:-INVALID}"
    if [ "$replay_valid" = "1" ] && [ "$replay_verdict" = "$recorded_verdict" ]; then
      echo "  RESULT: MATCH"; match=$((match + 1)); score="match"
    else
      echo "  RESULT: MISMATCH"; mismatch=$((mismatch + 1)); score="mismatch"
    fi
  else
    if [ "$replay_valid" = "1" ]; then
      echo "  replay:   $replay_verdict"
      echo "  RESULT: FIXED"; fixed=$((fixed + 1)); score="fixed"
    else
      echo "  RESULT: STILL_INVALID"; still_invalid=$((still_invalid + 1)); score="still_invalid"
    fi
  fi
  printf 'mode=%s\nreplay_verdict=%s\nrecorded_verdict=%s\nscore=%s\n' \
    "$mode" "$replay_verdict" "$recorded_verdict" "$score" > "$replay_dir/score.txt"
done

if [ "${#ENTRIES[@]}" -gt 1 ]; then
  echo ""
  echo "=== Summary ==="
  echo "  entries: ${#ENTRIES[@]}  match: $match  mismatch: $mismatch  fixed: $fixed  still_invalid: $still_invalid  errors: $errors"
fi
