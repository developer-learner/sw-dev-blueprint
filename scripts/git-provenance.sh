#!/usr/bin/env bash
# git-provenance.sh — T7 M1 (D-174): the trusted commit broker.
#
# The model never runs git (D-127 sandbox blocklist). Every pipeline commit
# routes through swbp_commit — the single place where pipeline commits get
# their author identity and Swbp-* provenance trailers. There is no other
# pipeline commit path; the source-shape selftest (selftest_provenance.py)
# fails the suite if a bare `git commit` reappears at a pipeline site.
#
# Sourced, not executed:
#     source "$PLANE_DIR/scripts/git-provenance.sh"   # orchestrate.sh (D-168 snapshot)
#     source scripts/git-provenance.sh                # refreeze/update-template/link/bootstrap
#
# Identity model (author/committer separation):
#   author    = who produced the content
#               em/coder/tpm/pipeline: swbp-<role>-<modelslug>@swbp.invalid
#               human:                the ambient identity (no override)
#   committer = always the ambient identity (the machine's git user)
#
# Attestation semantics (stated for the record, M2 signing will attest the
# same values): the trailers record what the TRUSTED PIPELINE RECORDED —
# the model id it observed (provider-returned when the server reports one,
# else the role's mapped model, else "unset"). They do not independently
# prove which model generated a reply; only the pipeline's own call path
# (llm-call.sh seat check, D-62) can make that claim.
#
# Trailers (last paragraph of the commit message, git interpret-trailers
# format):
#   Swbp-Role:            em | coder | tpm | pipeline | human
#   Swbp-Model:           provider-returned model id (SWBP_PROV_MODEL) when
#                         available, else the role's mapped model
#                         (SWBP_EM_MODEL / SWBP_CODER_MODEL / SWBP_TPM_MODEL),
#                         else "unset" — never fabricated
#   Swbp-Run:             the run id (stable across resumes; see
#                         swbp_run_id), or "n/a" for human/tpm commits
#   Swbp-Task:            task id — [task] commits only (SWBP_PROV_TASK)
#   Swbp-Plane:           $SWBP_PLANE_SHA (D-168) when set, else the child's
#                         pinned .template-version ref, else "n/a"
#   Swbp-Prompt-SHA256 /  sha256 of the archived prompt/reply bytes, present
#   Swbp-Reply-SHA256:    only when SWBP_PROV_PROMPT_FILE /
#                         SWBP_PROV_REPLY_FILE point at existing files
#
# Failure contract: swbp_commit returns non-zero WITHOUT committing when the
# role is invalid, there is nothing to commit, or git itself fails. Callers
# keep their own fatal-vs-guarded semantics (the [success] site swallows,
# the refreeze site dies) — the broker adds no new failure mode.

# --- swbp_model_slug <model-id> — sanitize into an email-local-part slug.
# Lowercase; anything outside [a-z0-9._-] becomes '-'; leading/trailing '-'
# trimmed; capped at 64 chars (email local-part limit). Empty -> "unset".
swbp_model_slug() {
  local m="${1:-}"
  [ -n "$m" ] || { echo "unset"; return 0; }
  printf '%s' "$m" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9._-]/-/g; s/^-+//; s/-+$//' \
    | cut -c1-64
}

# --- swbp_run_id <spec-version> — the run id for this spec version.
# Generated once (UTC stamp + 6 hex from /dev/urandom) and stored in
# .pipeline-state/run-id as "<id> spec=<v>". A later call with the SAME spec
# version reuses the stored id (resume stability); a DIFFERENT spec version
# generates a new one (a refreeze starts a new attempt sequence). The file
# dies with .pipeline-state on success teardown, so the id lifecycle is
# exactly one milestone attempt sequence.
swbp_run_id() {
  local spec="${1:-unknown}" f=".pipeline-state/run-id"
  if [ -f "$f" ]; then
    local prev_id prev_spec
    prev_id="$(awk '{print $1}' "$f" 2>/dev/null || true)"
    prev_spec="$(awk '{print $2}' "$f" 2>/dev/null | sed 's/^spec=//' || true)"
    if [ -n "$prev_id" ] && [ "$prev_spec" = "$spec" ]; then
      echo "$prev_id"
      return 0
    fi
  fi
  mkdir -p .pipeline-state
  local id
  id="$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"
  echo "$id spec=$spec" > "$f"
  echo "$id"
}

# --- swbp_commit <role> <subject> [file...] — the broker.
# Adds the given files (or commits what is already staged when none given),
# then commits with the role's author identity and the Swbp-* trailers.
# Returns non-zero without committing on: bad role, nothing staged, git fail.
swbp_commit() {
  local role="${1:-}" subject="${2:-}"
  [ -n "$role" ] && [ -n "$subject" ] || {
    echo "swbp_commit: usage: swbp_commit <role> <subject> [file...]" >&2
    return 2
  }
  shift 2
  case "$role" in
    em|coder|tpm|pipeline|human) ;;
    *) echo "swbp_commit: bad role '$role' (em|coder|tpm|pipeline|human)" >&2
       return 2 ;;
  esac

  if [ $# -gt 0 ]; then
    git add "$@" || return 1
  fi
  # Nothing staged -> nothing to commit. Callers that pre-check (the [plan]
  # and [task] sites) never reach this; the [success] site relies on it.
  git diff --cached --quiet && return 1

  # Model resolution: provider-returned id first (SWBP_PROV_MODEL, read by
  # the caller from llm-call's meta sidecar), then the role's mapped model,
  # then "unset". tpm defaults to "human" (a refreeze is human-driven unless
  # SWBP_TPM_MODEL names the model that produced the delta).
  local model_raw=""
  case "$role" in
    em)     model_raw="${SWBP_PROV_MODEL:-${SWBP_EM_MODEL:-}}" ;;
    coder)  model_raw="${SWBP_PROV_MODEL:-${SWBP_CODER_MODEL:-}}" ;;
    tpm)    model_raw="${SWBP_TPM_MODEL:-human}" ;;
    pipeline) model_raw="" ;;
    human)  model_raw="" ;;
  esac
  local model_slug
  model_slug="$(swbp_model_slug "$model_raw")"

  local author_name="" author_email=""
  if [ "$role" != "human" ]; then
    author_name="swbp-$role-$model_slug"
    author_email="$author_name@swbp.invalid"
  fi

  local run_id
  case "$role" in
    em|coder|pipeline) run_id="${SWBP_RUN_ID:-n/a}" ;;
    human|tpm)         run_id="n/a" ;;
  esac

  local plane="${SWBP_PLANE_SHA:-}"
  if [ -z "$plane" ] && [ -f .template-version ]; then
    plane="$(sed -n 's/^ref=//p' .template-version 2>/dev/null | head -1)"
  fi
  [ -n "$plane" ] || plane="n/a"

  local trailers="Swbp-Role: $role
Swbp-Model: $model_slug
Swbp-Run: $run_id
Swbp-Plane: $plane"
  if [ -n "${SWBP_PROV_TASK:-}" ]; then
    trailers="$trailers
Swbp-Task: $SWBP_PROV_TASK"
  fi
  if [ -n "${SWBP_PROV_PROMPT_FILE:-}" ] && [ -f "${SWBP_PROV_PROMPT_FILE:-}" ]; then
    trailers="$trailers
Swbp-Prompt-SHA256: $(sha256sum "$SWBP_PROV_PROMPT_FILE" | awk '{print $1}')"
  fi
  if [ -n "${SWBP_PROV_REPLY_FILE:-}" ] && [ -f "${SWBP_PROV_REPLY_FILE:-}" ]; then
    trailers="$trailers
Swbp-Reply-SHA256: $(sha256sum "$SWBP_PROV_REPLY_FILE" | awk '{print $1}')"
  fi

  if [ -n "$author_name" ]; then
    GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
      git commit -m "$subject" -m "$trailers"
  else
    git commit -m "$subject" -m "$trailers"
  fi
}
