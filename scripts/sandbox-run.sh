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
# D-53: this sandbox now runs ONLY pytest and smoke_check — the model calls
# that used to happen inside it (via containerized OpenCode) now happen on
# the host, before any container starts (scripts/llm-call.sh). Nothing in
# here talks to an LLM, so there is no LLM host/port wiring and no config to
# mount — that entire class of failure (D-52's stale mapping, D-50's
# version-pin drift) no longer has a place to occur. Network is fully
# disabled: the frozen suite exercises the app in-process (TestClient/ASGI
# transport, no real sockets), so untrusted generated code gets no
# exfiltration path. A project whose tests genuinely need network is a
# reason to revisit this, not a reason to assume it quietly.
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

podman info >/dev/null 2>&1 \
  || { echo "sandbox-run: podman is not running — start it (podman machine start). The sandbox is mandatory (D-30); there is no unsandboxed fallback." >&2; exit 1; }
podman image exists "$IMAGE" || {
  echo "sandbox-run: building sandbox image $IMAGE (first run or stack changed)..." >&2
  podman build -t "$IMAGE" -f "$REPO/Containerfile" "$REPO" >&2
}

# HOME on a tmpfs: pip/pytest need a writable home for cache/session data,
# and it must not be the (read-only) repo. Ephemeral by design.
podman run --rm --timeout "$TIMEOUT" \
  --userns=keep-id \
  -v "$REPO:/work:ro,Z" \
  ${RW_MOUNTS[@]+"${RW_MOUNTS[@]}"} \
  --tmpfs /tmp:rw,size=256m \
  --env HOME=/tmp \
  -w /work \
  --network none \
  --env PYTHONPATH=/work \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --memory=4g --cpus=2 \
  --cap-drop=ALL --security-opt no-new-privileges \
  "$IMAGE" "$@"
