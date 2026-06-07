#!/usr/bin/env bash
# sandbox-run.sh — run a command inside a disposable Podman container over the repo only.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
IMAGE="swbp-sandbox"
TIMEOUT="${SANDBOX_TIMEOUT:-1800}"

# LLM host address — staging step 0 proves which address reaches the host LLM
# from inside the container. On Linux: host.containers.internal. On macOS
# (via podman machine VM), verify reachability explicitly — don't assume.
SANDBOX_LLM_HOST="${SANDBOX_LLM_HOST:-host.containers.internal}"

podman image exists "$IMAGE" || podman build -t "$IMAGE" -f "$REPO/Containerfile" "$REPO"

podman run --rm --timeout "$TIMEOUT" \
  --userns=keep-id \
  -v "$REPO:/work:Z" \
  -w /work \
  --network slirp4netns \
  --add-host "$SANDBOX_LLM_HOST:host-gateway" \
  --env OPENAI_API_BASE="http://$SANDBOX_LLM_HOST:1234/v1" \
  --memory=4g --cpus=2 \
  --cap-drop=ALL --security-opt no-new-privileges \
  "$IMAGE" "$@"
