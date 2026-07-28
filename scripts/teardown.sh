#!/usr/bin/env bash
# teardown.sh — explicit, operator-invoked reclamation of pipeline resources (D-97).
#
# Never called by orchestrate.sh — the persistent Lima VM and warm LM Studio
# models are DESIGN (D-55, model cold-start ~120s), not leaks; auto-tearing
# them down after every run would cost real seconds every run for no gain.
# This tool exists for the moments where the operator wants the resources
# back: end of day, before a reboot, before switching to a heavy other app,
# when `status.sh` shows something surprising.
#
# Flags compose. Nothing defaults to destructive: bare `teardown.sh` prints
# help and exits 0. Every action prints what it would do BEFORE doing it,
# and `--dry-run` runs the whole plan without side effects.
#
# Flags:
#   --containers   remove stopped/exited podman containers inside dev-vm
#                  (D-30 lanes should self-clean via --rm; this catches
#                  the cases they didn't)
#   --state        prune this repo's .pipeline-state/ (transient orchestrator
#                  scratch — no artifact worth keeping between runs)
#   --caches       remove __pycache__/ + .pytest_cache/ under tests/ and src/
#   --lm-studio    kill LM Studio (frees model VRAM; next run pays cold load)
#   --lima         `limactl stop dev-vm` (frees VM memory; next run pays boot)
#   --all          all of the above except --lima (Lima stop is the biggest
#                  cost to reverse — opt in explicitly)
#   --em-archive   ALSO remove .em-archive/ (default: KEEP — corpus for the
#                  M28 diagnosis-brief A/B; only prune when you know)
#   --dry-run      show the plan; do nothing
set -u

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

show_help() {
  # Print the header comment block (up to the first blank line after `set`).
  awk 'NR>1 && /^set -u$/ {exit} NR>1 {sub(/^# ?/, ""); print}' "$0"
  echo ""
  echo "Companion: scripts/status.sh (read-only report of what is resident)"
}

CONTAINERS=0; STATE=0; CACHES=0; LM_STUDIO=0; LIMA=0
EM_ARCHIVE=0; DRY=0

if [ $# -eq 0 ]; then show_help; exit 0; fi

while [ $# -gt 0 ]; do
  case "$1" in
    --containers) CONTAINERS=1; shift ;;
    --state)      STATE=1; shift ;;
    --caches)     CACHES=1; shift ;;
    --lm-studio)  LM_STUDIO=1; shift ;;
    --lima)       LIMA=1; shift ;;
    --em-archive) EM_ARCHIVE=1; shift ;;
    --all)        CONTAINERS=1; STATE=1; CACHES=1; LM_STUDIO=1; shift ;;
    --dry-run)    DRY=1; shift ;;
    -h|--help)    show_help; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
done

do_or_say() {  # print, then run (or skip when DRY)
  printf '  $ %s\n' "$*"
  [ "$DRY" = "1" ] || eval "$@"
}

BANNER=""
[ "$DRY" = "1" ] && BANNER="  (DRY RUN — no side effects)"
echo "teardown plan:$BANNER"

# --- podman container reclamation (inside dev-vm) ----------------------------
if [ "$CONTAINERS" = "1" ]; then
  echo ""
  echo "[--containers] remove stopped/exited podman containers"
  if ! command -v limactl >/dev/null 2>&1; then
    echo "  limactl not installed — skipped"
  elif ! limactl list --format '{{.Status}}' dev-vm 2>/dev/null | grep -qx Running; then
    echo "  dev-vm not running — skipped (nothing to reach)"
  else
    do_or_say "limactl shell dev-vm -- podman container prune -f"
  fi
fi

# --- .pipeline-state/ --------------------------------------------------------
if [ "$STATE" = "1" ]; then
  echo ""
  echo "[--state] prune .pipeline-state/ (orchestrator scratch)"
  if [ -d .pipeline-state ]; then
    SZ=$(du -sh .pipeline-state 2>/dev/null | cut -f1)
    echo "  size before: $SZ"
    do_or_say "rm -rf .pipeline-state"
  else
    echo "  not present — skipped"
  fi
fi

# --- __pycache__ + .pytest_cache under tests/ and src/ -----------------------
if [ "$CACHES" = "1" ]; then
  echo ""
  echo "[--caches] remove __pycache__/ + .pytest_cache/"
  # find | xargs pattern that survives no-matches on macOS/BSD find
  for d in tests src; do
    [ -d "$d" ] || continue
    HITS=$(find "$d" -type d \( -name __pycache__ -o -name .pytest_cache \) 2>/dev/null)
    if [ -z "$HITS" ]; then
      echo "  $d/: nothing to remove"
    else
      COUNT=$(printf '%s\n' "$HITS" | wc -l | tr -d ' ')
      echo "  $d/: removing $COUNT cache dir(s)"
      [ "$DRY" = "1" ] || printf '%s\n' "$HITS" | xargs rm -rf
    fi
  done
fi

# --- LM Studio ---------------------------------------------------------------
if [ "$LM_STUDIO" = "1" ]; then
  echo ""
  echo "[--lm-studio] stop LM Studio (frees model VRAM; next run pays cold load)"
  # LM Studio's CLI is `lms`; graceful stop where available, then fall back
  # to matching by process name.
  if command -v lms >/dev/null 2>&1; then
    do_or_say "lms server stop"
  else
    echo "  lms CLI not on PATH; falling back to pkill by app name"
    do_or_say "pkill -f 'LM Studio' || true"
  fi
fi

# --- Lima VM (biggest cost to reverse — opt-in only, not in --all) -----------
if [ "$LIMA" = "1" ]; then
  echo ""
  echo "[--lima] limactl stop dev-vm (frees VM memory; next run pays boot ~60s)"
  if ! command -v limactl >/dev/null 2>&1; then
    echo "  limactl not installed — skipped"
  elif ! limactl list --format '{{.Status}}' dev-vm 2>/dev/null | grep -qx Running; then
    echo "  dev-vm not running — skipped"
  else
    do_or_say "limactl stop dev-vm"
  fi
fi

# --- .em-archive/ (default KEEP — opt-in only) -------------------------------
if [ "$EM_ARCHIVE" = "1" ]; then
  echo ""
  echo "[--em-archive] remove .em-archive/ (M28 diagnosis-brief A/B corpus)"
  if [ -d .em-archive ]; then
    SZ=$(du -sh .em-archive 2>/dev/null | cut -f1)
    COUNT=$(find .em-archive -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "  size before: $SZ ($COUNT files)"
    do_or_say "rm -rf .em-archive"
  else
    echo "  not present — skipped"
  fi
fi

echo ""
[ "$DRY" = "1" ] && echo "dry run complete — nothing changed." || echo "teardown complete."
