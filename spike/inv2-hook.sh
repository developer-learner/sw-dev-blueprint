#!/bin/bash
# INV-2 PreToolUse hook for OpenHands.
# Reads stdin JSON, checks file path against .gate-paths + phase marker.
# Only blocks write operations (create/edit), allows view.
# Exit 2 = BLOCK the operation. Exit 0 = ALLOW.

PHASE_FILE="/tmp/inv2-spike/PHASE"
GATE_PATHS="/tmp/inv2-spike/test-project/.gate-paths"

phase=$(cat "$PHASE_FILE" 2>/dev/null || echo "")

tool_input_command=$(python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('tool_input', {}).get('command', ''))
print(data.get('tool_input', {}).get('path', ''))
" 2>/dev/null || echo "")
command=$(echo "$tool_input_command" | sed -n '1p')
file_path=$(echo "$tool_input_command" | sed -n '2p')

[ -z "$phase" ] && exit 0
[ -z "$file_path" ] && exit 0

# Only block write operations (create, edit), allow view
[ "$command" = "view" ] && exit 0

allowed=$(grep "^$phase=" "$GATE_PATHS" 2>/dev/null | cut -d= -f2)
[ -z "$allowed" ] && exit 0

case "$file_path" in
  */"$allowed"*) exit 0 ;;
  */"${allowed%/}"/*) exit 0 ;;
  "$allowed"*) exit 0 ;;
  "${allowed%/}"/*) exit 0 ;;
esac

echo "INV-2 GATE BLOCKED: $phase phase attempted to write $file_path (allowed: $allowed)"
exit 2
