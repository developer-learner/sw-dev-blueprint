#!/usr/bin/env bash
# em-bench.sh — replay archived EM diagnosis calls with variant briefs.
#
# Replays the prompt from an .em-archive/ entry through the live EM using a
# (possibly alternate) system prompt, validates the reply against the diagnosis
# schema, and compares the verdict to the one recorded at capture time.
# Designed for A/B testing diagnosis brief variants against a corpus of real
# consults (backlog item 6).
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

if [ "$ALL" = "1" ]; then
  for d in .em-archive/*; do
    [ -d "$d" ] && [ -f "$d/meta.txt" ] && grep -q '^verdict=' "$d/meta.txt" \
      && ENTRIES+=("$d")
  done
  [ "${#ENTRIES[@]}" -gt 0 ] \
    || { echo "em-bench: no diagnosis entries in .em-archive/" >&2; exit 1; }
fi

[ "${#ENTRIES[@]}" -gt 0 ] \
  || { echo "usage: em-bench.sh <archive-entry> [--brief <file>] | --all" >&2; exit 2; }

match=0 mismatch=0 errors=0

for ENTRY in "${ENTRIES[@]}"; do
  [ -f "$ENTRY/prompt.txt" ] || { echo "SKIP $ENTRY (no prompt.txt)"; continue; }
  [ -f "$ENTRY/meta.txt" ]   || { echo "SKIP $ENTRY (no meta.txt)"; continue; }

  recorded_verdict=$(grep '^verdict=' "$ENTRY/meta.txt" | cut -d= -f2- || true)
  [ -n "$recorded_verdict" ] || { echo "SKIP $ENTRY (no recorded verdict)"; continue; }

  echo "--- $(basename "$ENTRY") ---"
  echo "  brief: $BRIEF"
  echo "  recorded: $recorded_verdict"

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

  if ! python3 -c "import json; json.load(open('$replay_dir/reply.json'))" 2>/dev/null; then
    echo "  RESULT: invalid_json"
    errors=$((errors + 1))
    continue
  fi

  replay_verdict=$(python3 -c "
import json, sys
print(json.load(open(sys.argv[1])).get('verdict',''))
" "$replay_dir/reply.json")
  echo "  replay:   $replay_verdict"

  if [ "$replay_verdict" = "$recorded_verdict" ]; then
    echo "  RESULT: MATCH"
    match=$((match + 1))
  else
    echo "  RESULT: MISMATCH"
    mismatch=$((mismatch + 1))
  fi
  printf 'replay_verdict=%s\nrecorded_verdict=%s\nmatch=%s\n' \
    "$replay_verdict" "$recorded_verdict" \
    "$([ "$replay_verdict" = "$recorded_verdict" ] && echo yes || echo no)" \
    > "$replay_dir/score.txt"
done

if [ "${#ENTRIES[@]}" -gt 1 ]; then
  echo ""
  echo "=== Summary ==="
  echo "  entries: ${#ENTRIES[@]}  match: $match  mismatch: $mismatch  errors: $errors"
fi
