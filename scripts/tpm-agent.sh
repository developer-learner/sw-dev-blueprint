#!/usr/bin/env bash
# tpm-agent.sh — launch the TPM as a scoped repo agent (D-39).
#
# D-38 kept the TPM chat-side with an air gap; D-39 promotes it to a repo
# agent on the CEO's explicit decision, with the containment D-38(b) recorded:
#
#   WRITE lane   .tpm/outbox/ only (harness-allowed; everything protected is
#                harness-denied; anything else prompts the operator). Nothing
#                installs from the outbox except through the human y/N in
#                scripts/refreeze.sh — same door as ever, hash-pinned after.
#   READ wall    src/ is harness-denied and Bash is denied entirely (no
#                `cat src/...` bypass). Oracle independence (INV-1): the TPM
#                authors tests without ever seeing the implementation.
#   NO PROCEDURE the TPM triggers nothing — orchestrate.sh, refreeze.sh, EM
#                and coder runs are all operator- or shell-initiated.
#
# Honest layer statement: the read wall is harness-enforced (softer than the
# chat air gap — that fallback remains: tpm-pack.sh/tpm-unpack.sh, D-38).
# The write wall is layered and hard: harness deny + operator ask-prompts +
# hash-pinned manifests failing closed + the interactive refreeze gate.
#
# Usage: tpm-agent.sh   (from the project root; requires the `claude` CLI)
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd -P)"

command -v claude >/dev/null 2>&1 \
  || { echo "tpm-agent: 'claude' CLI not found — install Claude Code, or use the chat-side TPM (scripts/tpm-pack.sh)" >&2; exit 1; }

mkdir -p .tpm/outbox

exec claude --settings scripts/tpm-agent-settings.json \
  "You are the TPM for this project, running in AGENT MODE. Before anything else, read docs/TPM-ROLE.md in full — it is your job description and its Agent mode section governs where you write. Summary of your lane: read the repo freely EXCEPT src/ (never attempt it — oracle independence is the point of your role); write spec artifacts (PRD.md, ERD.md, contracts.json, tests/*.py) ONLY under .tpm/outbox/ with paths preserved; escalation bundles are at .pipeline-state/escalations/BATCH.md — read them yourself, no one will paste them. You run nothing: the operator installs your outbox via scripts/refreeze.sh and drives the pipeline. When ready, tell the CEO you are and ask for the business intent."
