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
# Image tag = content hash of what defines it (D-50): a requirements.txt or
# Containerfile change yields a new tag, forcing a rebuild automatically —
# the stale-image failure (TPM picks a new stack, sandbox still has the old
# one, pytest "collects no tests") becomes structurally impossible.
STACK_HASH="$(cat "$REPO/Containerfile" "$REPO/requirements.txt" 2>/dev/null | sha256sum | cut -c1-12)"
IMAGE="swbp-sandbox:$STACK_HASH"
TIMEOUT="${SANDBOX_TIMEOUT:-1800}"

# LLM host address — staging step 0 proves which address reaches the host LLM
# from inside the container. On Linux: host.containers.internal. On macOS
# (via podman machine VM), verify reachability explicitly — don't assume.
# Port defaults to LM Studio's; override for any other OpenAI-compatible server.
: "${SANDBOX_LLM_HOST:=host.containers.internal}"
: "${SANDBOX_LLM_PORT:=1234}"

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

# D-52: the CEO's agent→model mapping (D-41) lives in the HOST global config;
# the container's ephemeral HOME (/tmp) would otherwise lose it, and OpenCode
# silently substitutes a remote default model — pipeline work leaving the
# machine with nobody deciding that. Mount the mapping (and auth, if present)
# read-only into the container HOME, rewriting localhost to the address that
# reaches the host from inside the container. The no-silent-fallback halt
# itself lives in orchestrate.sh, which verifies the agent ran as invoked.
GLOBAL_MOUNTS=()
OC_CONFIG_TMP=""
trap '[ -n "$OC_CONFIG_TMP" ] && rm -f "$OC_CONFIG_TMP"' EXIT
if [ -f "$HOME/.config/opencode/opencode.json" ]; then
  OC_CONFIG_TMP="$(mktemp)"
  sed -e "s/127\.0\.0\.1/$SANDBOX_LLM_HOST/g" -e "s/localhost/$SANDBOX_LLM_HOST/g" \
    "$HOME/.config/opencode/opencode.json" > "$OC_CONFIG_TMP"
  GLOBAL_MOUNTS+=(-v "$OC_CONFIG_TMP:/tmp/.config/opencode/opencode.json:ro,Z")
fi
[ -f "$HOME/.local/share/opencode/auth.json" ] \
  && GLOBAL_MOUNTS+=(-v "$HOME/.local/share/opencode/auth.json:/tmp/.local/share/opencode/auth.json:ro,Z")

podman info >/dev/null 2>&1 \
  || { echo "sandbox-run: podman is not running — start it (podman machine start). The sandbox is mandatory (D-30); there is no unsandboxed fallback." >&2; exit 1; }
podman image exists "$IMAGE" || {
  echo "sandbox-run: building sandbox image $IMAGE (first run or stack changed)..." >&2
  podman build -t "$IMAGE" -f "$REPO/Containerfile" "$REPO" >&2
}

# HOME on a tmpfs: the agent user needs a writable home for OpenCode/pip
# session data, and it must not be the (read-only) repo. Ephemeral by design.
podman run --rm --timeout "$TIMEOUT" \
  --userns=keep-id \
  -v "$REPO:/work:ro,Z" \
  ${RW_MOUNTS[@]+"${RW_MOUNTS[@]}"} \
  --tmpfs /tmp:rw,size=256m \
  ${GLOBAL_MOUNTS[@]+"${GLOBAL_MOUNTS[@]}"} \
  --env HOME=/tmp \
  -w /work \
  --network slirp4netns \
  --add-host "$SANDBOX_LLM_HOST:host-gateway" \
  --env OPENAI_API_BASE="http://$SANDBOX_LLM_HOST:$SANDBOX_LLM_PORT/v1" \
  --env PYTHONPATH=/work \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --memory=4g --cpus=2 \
  --cap-drop=ALL --security-opt no-new-privileges \
  "$IMAGE" "$@"
