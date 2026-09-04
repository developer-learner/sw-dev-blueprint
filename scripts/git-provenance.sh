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
#   Swbp-Call-Id:         the provider's own call receipt (the response
#                         envelope's id field, read by the caller from the
#                         meta sidecar into SWBP_PROV_CALL_ID) — present only
#                         when the server reported one; never fabricated
#
# T7 M2 (D-184) additions:
#   Signing:              when a provenance key exists in
#                         ~/.swbp/provenance/gnupg (created by
#                         `git-provenance.sh init`), every broker commit is
#                         GPG-signed (Ed25519, no passphrase, dedicated
#                         homedir — the key never touches the user's
#                         keyring). No key -> unsigned (M2a is advisory;
#                         the verifier reports "missing", the M2b gate flip
#                         makes it a failure).
#   Evidence:             when SWBP_PROV_ENTRY is set (the [plan]/[task]
#                         sites) and the prompt/reply files exist, the exact
#                         bytes are committed atomically with the commit at
#                         .swbp-evidence/<run-id>/<entry>/{prompt.txt,
#                         reply.raw,meta.txt} — the trailer hashes are
#                         computed over exactly these bytes. A 5MB-per-file
#                         guard fails closed BEFORE anything is staged
#                         (a truncated byte stream would make the hashes a
#                         lie). .swbp-evidence/ is NOT git-ignored: the
#                         committed copy is the durable record (the CWD
#                         archives stay git-ignored, for between-run
#                         debugging only).
#
# Failure contract: swbp_commit returns non-zero WITHOUT committing when the
# role is invalid, there is nothing to commit, an evidence file exceeds the
# size guard, or git itself fails. Callers keep their own fatal-vs-guarded
# semantics (the [success] site swallows, the refreeze site dies) — the
# broker adds no new failure mode.
#
# Executed (not sourced) it is the key-management CLI:
#   git-provenance.sh init          create the pipeline key (2y expiry),
#                                   pin it (machine tier), print the public
#                                   key (commit it to scripts/.provenance/pub.asc)
#   git-provenance.sh rotate        new key, same uid; old key preserved,
#                                   new fingerprint printed for pinning
#   git-provenance.sh revoke <fpr>  move a fingerprint to the revoked list
#                                   (permanent; revocation beats pinning)
#   git-provenance.sh retire <fpr>  end-of-rotation revocation (marked
#                                   "retired" for audit clarity)
#   git-provenance.sh active        show the active key (fingerprint/expiry)

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
# then commits with the role's author identity, the Swbp-* trailers, the
# durable evidence (M2), and the GPG signature (M2, when a key exists).
# Returns non-zero without committing on: bad role, nothing staged,
# evidence size-guard trip, git fail.
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

  # --- T7 M2 (D-184): durable evidence, staged BEFORE anything else.
  # The exact prompt/reply/meta bytes are committed atomically with the
  # [plan]/[task] commit; the trailer hashes are computed over exactly
  # these bytes. Size guard first — fail closed, nothing staged.
  local evidence_files=()
  local pf="${SWBP_PROV_PROMPT_FILE:-}" rf="${SWBP_PROV_REPLY_FILE:-}"
  if [ -n "${SWBP_PROV_ENTRY:-}" ] && [ "$run_id" != "n/a" ] \
     && [ -n "$pf" ] && [ -f "$pf" ] && [ -n "$rf" ] && [ -f "$rf" ]; then
    local f sz
    for f in "$pf" "$rf" "${SWBP_PROV_META_FILE:-}"; do
      [ -n "$f" ] && [ -f "$f" ] || continue
      sz="$(wc -c < "$f" | tr -d ' ')"
      if [ "$sz" -gt 5242880 ]; then
        echo "swbp_commit: evidence file exceeds 5MB ($(basename "$f"): ${sz} bytes) — refusing to commit (fail-closed; never truncate)" >&2
        return 1
      fi
    done
    local evidence_dir=".swbp-evidence/$run_id/$SWBP_PROV_ENTRY"
    mkdir -p "$evidence_dir" || return 1
    cp "$pf" "$evidence_dir/prompt.txt" || return 1
    cp "$rf" "$evidence_dir/reply.raw" || return 1
    if [ -n "${SWBP_PROV_META_FILE:-}" ] && [ -f "${SWBP_PROV_META_FILE:-}" ]; then
      cp "$SWBP_PROV_META_FILE" "$evidence_dir/meta.txt" || return 1
    else
      : > "$evidence_dir/meta.txt" || return 1
    fi
    printf 'ts=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$evidence_dir/meta.txt"
    evidence_files=("$evidence_dir/prompt.txt" "$evidence_dir/reply.raw" "$evidence_dir/meta.txt")
  fi

  if [ $# -gt 0 ]; then
    git add "$@" || return 1
  fi
  if [ ${#evidence_files[@]} -gt 0 ]; then
    git add "${evidence_files[@]}" || return 1
  fi
  # Nothing staged -> nothing to commit. Callers that pre-check (the [plan]
  # and [task] sites) never reach this; the [success] site relies on it.
  git diff --cached --quiet && return 1

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
  if [ -n "${SWBP_PROV_CALL_ID:-}" ]; then
    trailers="$trailers
Swbp-Call-Id: $SWBP_PROV_CALL_ID"
  fi

  # --- T7 M2 (D-184): signing. Dedicated homedir (the key never touches
  # the user's keyring); batch/loopback wrapper (no passphrase prompts —
  # the key has none by design). No key -> unsigned (M2a advisory).
  local sign_args=() gpg_wrap=""
  local prov_home
  prov_home="$HOME/.swbp/provenance"
  local gpg_home="$prov_home/gnupg"
  if [ -d "$gpg_home" ] && command -v gpg >/dev/null 2>&1; then
    local fpr=""
    if [ -f "$prov_home/active" ]; then
      fpr="$(head -1 "$prov_home/active" 2>/dev/null | tr -d '[:space:]')"
    fi
    if [ -z "$fpr" ]; then
      fpr="$(gpg --homedir "$gpg_home" --batch --list-keys --with-colons 2>/dev/null \
              | awk -F: '$1=="fpr"{print $10; exit}')"
    fi
    if [ -n "$fpr" ]; then
      gpg_wrap="$(mktemp "${TMPDIR:-/tmp}/swbp-gpg.XXXXXX" 2>/dev/null)" || gpg_wrap=""
      if [ -n "$gpg_wrap" ]; then
        printf '#!/bin/sh\nexec gpg --homedir %q --batch --yes --pinentry-mode loopback --passphrase "" "$@"\n' \
          "$gpg_home" > "$gpg_wrap"
        chmod +x "$gpg_wrap"
        sign_args=(-c "gpg.program=$gpg_wrap" -c "user.signingkey=$fpr")
      fi
    fi
  fi

  local rc=0
  if [ -n "$author_name" ]; then
    if [ ${#sign_args[@]} -gt 0 ]; then
      GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
        git "${sign_args[@]}" commit -S -m "$subject" -m "$trailers" || rc=$?
    else
      GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email" \
        git commit -m "$subject" -m "$trailers" || rc=$?
    fi
  else
    if [ ${#sign_args[@]} -gt 0 ]; then
      git "${sign_args[@]}" commit -S -m "$subject" -m "$trailers" || rc=$?
    else
      git commit -m "$subject" -m "$trailers" || rc=$?
    fi
  fi
  [ -n "$gpg_wrap" ] && rm -f "$gpg_wrap"
  return $rc
}

# =====================================================================
# T7 M2 (D-184): key management CLI (executed, not sourced).
#
# Security model: file location + permissions, not a passphrase prompt.
# The key lives in a DEDICATED gpg homedir under ~/.swbp/provenance/ —
# outside the repo, outside the user's keyring, outside the model's
# filesystem view (the sandbox CWD is the project root; D-127 already
# blocks .git writes, this extends the same boundary to the key).
# The machine-tier pin file (pinned-fingerprints) is the gate's trust
# anchor; the CEO (or an operator with the CEO's authorization) is its
# only writer. Revocation beats pinning; revocation is permanent.
# =====================================================================

_swbp_prov_base() { echo "$HOME/.swbp/provenance"; }
_swbp_prov_gpg_home() { echo "$HOME/.swbp/provenance/gnupg"; }

# _swbp_prov_gen_key <expiry> — generate an Ed25519 signing key in the
# dedicated homedir; print its fingerprint.
_swbp_prov_gen_key() {
  local expiry="${1:-2y}"
  local home uid
  home="$(_swbp_prov_gpg_home)"
  mkdir -p "$home" && chmod 700 "$home"
  # unique uid per key: gpg refuses a second key with the same uid
  # (the fingerprint is the identity; the uid is only a label)
  uid="swbp-provenance-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM@swbp.invalid"
  # capture the NEW key's fpr from gpg's own status (gpg >= 2.4:
  # KEY_CREATED P <fpr>; older: GEN_KEY <fpr> <created> <expires>) —
  # listing the homedir would return the FIRST key, which is the wrong
  # one once a rotation adds a second key.
  local out fpr
  out="$(gpg --homedir "$home" --batch --pinentry-mode loopback \
      --passphrase '' --status-fd 1 \
      --quick-generate-key "$uid" ed25519 sign "$expiry" 2>/dev/null)" \
    || return 1
  fpr="$(printf '%s\n' "$out" | awk '
    /^\[GNUPG:\] GEN_KEY/      { print $3; exit }
    /^\[GNUPG:\] KEY_CREATED/  { print $NF; exit }')"
  [ -n "$fpr" ] || return 1
  printf '%s' "$fpr"
}

# _swbp_prov_has_key — 0 when the homedir holds at least one key.
_swbp_prov_has_key() {
  local home
  home="$(_swbp_prov_gpg_home)"
  [ -d "$home" ] && gpg --homedir "$home" --batch --list-keys 2>/dev/null | grep -q "^pub"
}

# _swbp_prov_pin <fpr> <note> — append to the machine-tier pin file
# (the caller — init/rotate, run by the CEO/operator — is the writer).
_swbp_prov_pin() {
  local fpr="$1" note="$2"
  local base pinned
  base="$(_swbp_prov_base)"
  pinned="$base/pinned-fingerprints"
  if [ ! -s "$pinned" ]; then
    echo "# swbp provenance pinned fingerprints — machine tier (CEO-only writer)" > "$pinned"
  fi
  grep -q "^$fpr" "$pinned" 2>/dev/null || echo "$fpr  # $note" >> "$pinned"
}

_swbp_prov_init() {
  command -v gpg >/dev/null 2>&1 || { echo "git-provenance: gpg not found" >&2; return 1; }
  if _swbp_prov_has_key; then
    echo "git-provenance: key already exists (use 'active' to inspect, 'rotate' to replace)" >&2
    return 1
  fi
  local base fpr
  base="$(_swbp_prov_base)"
  mkdir -p "$base" && chmod 700 "$base"
  fpr="$(_swbp_prov_gen_key 2y)" || { echo "git-provenance: key generation failed" >&2; return 1; }
  [ -n "$fpr" ] || { echo "git-provenance: key generation failed (no fingerprint)" >&2; return 1; }
  # private-key backup at the design's path (the operational key lives in
  # the dedicated homedir; this file is the rotation/restore artifact)
  gpg --homedir "$(_swbp_prov_gpg_home)" --batch --pinentry-mode loopback --passphrase '' \
      --armor --export-secret-keys > "$base/provenance-key.gpg" 2>/dev/null
  chmod 600 "$base/provenance-key.gpg"
  _swbp_prov_pin "$fpr" "pinned $(date -u +%F) by swbp-provenance init"
  gpg --homedir "$(_swbp_prov_gpg_home)" --armor --export
  echo "git-provenance: key created (fingerprint $fpr). Public key on stdout — commit it to scripts/.provenance/pub.asc" >&2
}

_swbp_prov_active() {
  if ! _swbp_prov_has_key; then
    echo "git-provenance: no provenance key (run: scripts/git-provenance.sh init)"
    return 0
  fi
  local base fpr=""
  base="$(_swbp_prov_base)"
  if [ -f "$base/active" ]; then
    fpr="$(head -1 "$base/active" 2>/dev/null | tr -d '[:space:]')"
  fi
  [ -n "$fpr" ] || fpr="$(gpg --homedir "$(_swbp_prov_gpg_home)" --batch --list-keys --with-colons 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')"
  echo "active fingerprint: $fpr"
  gpg --homedir "$(_swbp_prov_gpg_home)" --batch --list-keys --with-colons 2>/dev/null \
    | awk -F: -v f="$fpr" '$1=="pub" && index($10,f)==1 {print "uid: swbp-provenance@swbp.invalid"; print "expires: " ($7 ? $7 : "never"); print "algo: " $4}'
}

_swbp_prov_rotate() {
  _swbp_prov_has_key || { echo "git-provenance: no existing key to rotate" >&2; return 1; }
  local base old_fpr new_fpr
  base="$(_swbp_prov_base)"
  old_fpr="$(gpg --homedir "$(_swbp_prov_gpg_home)" --batch --list-keys --with-colons 2>/dev/null | awk -F: '$1=="fpr"{print $10; exit}')"
  # preserve the old private key (rotation overlap: both keys verify)
  gpg --homedir "$(_swbp_prov_gpg_home)" --batch --pinentry-mode loopback --passphrase '' \
      --armor --export-secret-keys "$old_fpr" > "$base/provenance-key-${old_fpr:0:8}.gpg" 2>/dev/null
  chmod 600 "$base/provenance-key-${old_fpr:0:8}.gpg"
  new_fpr="$(_swbp_prov_gen_key 2y)" || { echo "git-provenance: rotation failed" >&2; return 1; }
  [ -n "$new_fpr" ] || { echo "git-provenance: rotation failed (no fingerprint)" >&2; return 1; }
  echo "$new_fpr" > "$base/active"
  _swbp_prov_pin "$new_fpr" "pinned $(date -u +%F) by swbp-provenance rotate (overlap with ${old_fpr:0:8})"
  # the homedir now holds BOTH keys — the export is the bundle
  gpg --homedir "$(_swbp_prov_gpg_home)" --armor --export
  echo "git-provenance: rotated — new key $new_fpr is active; old key ${old_fpr:0:8} preserved. Commit the bundled public key (signed by the OLD key), pin the new fingerprint out-of-band, and retire the old one after one clean cycle on the new key." >&2
}

# _swbp_prov_revoke <fpr> <marker> — move a fingerprint from pinned to
# revoked. Revocation takes precedence over pinning and is permanent.
_swbp_prov_revoke() {
  local fpr="${1:-}" marker="${2:-revoked}"
  [ -n "$fpr" ] || { echo "usage: git-provenance.sh $marker <fingerprint>" >&2; return 2; }
  local base pinned revoked
  base="$(_swbp_prov_base)"
  pinned="$base/pinned-fingerprints"
  revoked="$base/revoked-fingerprints"
  if [ -f "$pinned" ]; then
    grep -v "^$fpr" "$pinned" > "$pinned.tmp" && mv "$pinned.tmp" "$pinned"
  fi
  if [ ! -s "$revoked" ]; then
    echo "# swbp provenance revoked fingerprints — permanent; revocation beats pinning" > "$revoked"
  fi
  grep -q "^$fpr" "$revoked" 2>/dev/null || echo "$fpr  # $marker $(date -u +%F)" >> "$revoked"
  chmod 600 "$revoked"
  echo "git-provenance: $fpr $marker"
}

# --- CLI dispatch: only when executed directly, never when sourced.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-}" in
    init)   _swbp_prov_init; exit $? ;;
    active) _swbp_prov_active; exit $? ;;
    rotate) _swbp_prov_rotate; exit $? ;;
    revoke) shift; _swbp_prov_revoke "${1:-}" "revoked"; exit $? ;;
    retire) shift; _swbp_prov_revoke "${1:-}" "retired"; exit $? ;;
    *) echo "usage: git-provenance.sh {init|rotate|revoke <fpr>|retire <fpr>|active}" >&2; exit 2 ;;
  esac
fi
