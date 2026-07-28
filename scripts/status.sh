#!/usr/bin/env bash
# status.sh — read-only report on what pipeline resources are resident (D-97).
#
# Reports: Lima dev-vm state + uptime, LLM servers on the ports llm-call.sh
# defaults to (LM Studio 1234, mtplx 8001, mlx-serve 11234), orphan podman
# containers inside the VM, pipeline state directory sizes, disk free on
# repo and VM. Never writes; safe to run at any moment. The companion
# `teardown.sh` is the reclamation tool; this one is the "what's up right
# now" tool. Design: exit 0 unless a command itself fails — the report is
# informational, and a stopped VM is not an error condition.
set -u

cd "$(cd "$(dirname "$0")/.." && pwd -P)"

# --- section formatting ------------------------------------------------------
hdr() { printf '\n== %s ==\n' "$1"; }
kv()  { printf '  %-24s %s\n' "$1:" "$2"; }
note(){ printf '  %s\n' "$1"; }

echo "pipeline status @ $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "repo: $(pwd)"

# --- Lima dev-vm ------------------------------------------------------------
hdr "Lima dev-vm"
if ! command -v limactl >/dev/null 2>&1; then
  note "limactl not on PATH — Lima not installed here (D-55 macOS host path)"
else
  STATUS=$(limactl list --format '{{.Status}}' dev-vm 2>/dev/null || echo "MISSING")
  kv "state" "$STATUS"
  if [ "$STATUS" = "Running" ]; then
    # `uptime` inside the VM: portable, doesn't need extra packages.
    UP=$(limactl shell dev-vm -- uptime 2>/dev/null | sed 's/^ *//' || echo "?")
    kv "uptime" "$UP"
    MEM=$(limactl shell dev-vm -- sh -c "free -h 2>/dev/null | awk '/^Mem:/ {print \$3 \" used / \" \$2 \" total (\" \$7 \" available)\"}'" 2>/dev/null || echo "?")
    kv "memory" "$MEM"
    DF=$(limactl shell dev-vm -- df -h / 2>/dev/null | awk 'NR==2 {print $3 " used / " $2 " (" $5 " full, " $4 " free)"}' || echo "?")
    kv "vm disk /" "$DF"
  fi
fi

# --- LLM servers on the ports llm-call.sh knows about -----------------------
# Doesn't hit /v1/models (that would load a model on some servers); a bare
# TCP probe is enough to report "something is listening on this port."
hdr "LLM servers (host ports)"
if ! command -v nc >/dev/null 2>&1; then
  note "nc (netcat) not on PATH — cannot probe LLM ports"
else
  probe() {  # $1 label  $2 port
    if nc -z 127.0.0.1 "$2" 2>/dev/null; then
      kv "$1 :$2" "listening"
    else
      kv "$1 :$2" "not reachable"
    fi
  }
  probe "LM Studio (default)" 1234
  probe "mtplx"               8001
  probe "mlx-serve"           11234
fi

# --- podman containers inside the VM (D-30 inner lanes) ---------------------
hdr "podman containers (inside dev-vm)"
if [ "${STATUS:-}" = "Running" ]; then
  COUNT=$(limactl shell dev-vm -- podman ps -q 2>/dev/null | wc -l | tr -d ' ')
  kv "running" "$COUNT"
  if [ "$COUNT" -gt 0 ] 2>/dev/null; then
    limactl shell dev-vm -- podman ps --format '  {{.ID}}  {{.Image}}  up {{.RunningFor}}  ({{.Names}})' 2>/dev/null || true
  fi
  STOPPED=$(limactl shell dev-vm -- podman ps -aq --filter status=exited 2>/dev/null | wc -l | tr -d ' ')
  kv "stopped (reclaimable)" "$STOPPED"
else
  note "VM not running — skipped"
fi

# --- pipeline state on the repo's disk --------------------------------------
hdr "pipeline state (this repo)"
size() {  # $1 path label  $2 path
  if [ -e "$2" ]; then
    kv "$1" "$(du -sh "$2" 2>/dev/null | cut -f1) ($2)"
  fi
}
size ".pipeline-state"    .pipeline-state
size ".em-archive"        .em-archive
size ".cache"             .cache
size "tests/__pycache__"  tests/__pycache__
size "src/__pycache__"    src/__pycache__

# --- repo disk --------------------------------------------------------------
hdr "repo disk"
DF=$(df -h . | awk 'NR==2 {print $3 " used / " $2 " (" $5 " full, " $4 " free) on " $1}')
kv "df ." "$DF"

echo ""
echo "read-only report — no state changed. reclamation: scripts/teardown.sh --help"
