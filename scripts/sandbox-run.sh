#!/usr/bin/env bash
# sandbox-run.sh — run a command inside a disposable Podman container over the repo.
#
# D-30: the repo is mounted READ-ONLY; write access is granted per-lane with
# --rw. Lane violations and gate-tampering are therefore physically impossible
# in-loop, not merely detected — phase-gate.sh remains as the backstop for the
# interactive/human path. The control-plane manifest and the frozen spec get
# their out-of-band anchor for free: no agent can write the gate that polices
# it, nor the manifest, nor the frozen tests.
#
# Usage: sandbox-run.sh [--rw <relpath>]... [--] <command...>
#   --rw src        mount $REPO/src read-write (created if missing)
#   --rw .cache     e.g. for the pytest JSON report
# No --rw flags = fully read-only repo (test runs, smoke checks).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
IMAGE="swbp-sandbox"
TIMEOUT="${SANDBOX_TIMEOUT:-1800}"

# LLM host address — staging step 0 proves which address reaches the host LLM
# from inside the container. On Linux: host.containers.internal. On macOS
# (via podman machine VM), verify reachability explicitly — don't assume.
: "${SANDBOX_LLM_HOST:=host.containers.internal}"

RW_MOUNTS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rw)
      rel="${2:?--rw needs a repo-relative path}"
      rel="${rel#./}"; rel="${rel%/}"
      case "$rel" in
        ""|.|..*|/*) echo "sandbox-run: refusing --rw '$2' (must be a repo-relative subdir)" >&2; exit 2 ;;
        scripts|scripts/*|.git|.git/*|.githooks|.githooks/*)
          echo "sandbox-run: refusing --rw '$2' (control plane is never agent-writable)" >&2; exit 2 ;;
      esac
      mkdir -p "$REPO/$rel"
      RW_MOUNTS+=(-v "$REPO/$rel:/work/$rel:Z")
      shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done

podman image exists "$IMAGE" || podman build -t "$IMAGE" -f "$REPO/Containerfile" "$REPO"

# HOME on a tmpfs: the agent user needs a writable home for OpenCode/pip
# session data, and it must not be the (read-only) repo. Ephemeral by design.
podman run --rm --timeout "$TIMEOUT" \
  --userns=keep-id \
  -v "$REPO:/work:ro,Z" \
  ${RW_MOUNTS[@]+"${RW_MOUNTS[@]}"} \
  --tmpfs /tmp:rw,size=256m \
  --env HOME=/tmp \
  -w /work \
  --network slirp4netns \
  --add-host "$SANDBOX_LLM_HOST:host-gateway" \
  --env OPENAI_API_BASE="http://$SANDBOX_LLM_HOST:1234/v1" \
  --env PYTHONPATH=/work \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --memory=4g --cpus=2 \
  --cap-drop=ALL --security-opt no-new-privileges \
  "$IMAGE" "$@"
