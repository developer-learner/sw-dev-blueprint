# PROVENANCE.md — Git provenance: public tier (D-174 M1, D-184 M2a)

> Public tier: what a third party can verify, with what, and how the
> key lifecycle works. Machine tier (the private key, the pin file)
> never leaves the operator's machine.

## What is attested

Every pipeline commit (plan / task / success) is made by the trusted
commit broker (`scripts/git-provenance.sh` → `swbp_commit`), which:

1. **Authors** the commit as the model identity
   (`swbp-<role>-<model> <…@swbp.invalid>`) and **commits** as the
   ambient human identity — author ≠ committer is the model-specific
   split (D-174).
2. **Records trailers** on the commit: `Swbp-Role`, `Swbp-Model`,
   `Swbp-Run`, `Swbp-Plane`, `Swbp-Task`, `Swbp-Call-Id` (the LLM call's
   meta sidecar id), and `Swbp-Prompt-SHA256` / `Swbp-Reply-SHA256`.
3. **Commits the evidence in-tree**: the actual prompt, raw reply, and
   call metadata land at `.swbp-evidence/<run>/<entry>/` in the SAME
   commit — the signature covers the evidence.
4. **Signs** the commit with the provenance key (M2a). A commit without
   a signature is an M1-era commit: reported as `pre-m2`, out of gate
   scope.

## What a third party verifies

`scripts/check-provenance.py <range> [--gate]` — no network, no trust in
the machine:

- **Signature**: the commit's GPG signature is valid against the repo's
  public bundle `scripts/.provenance/pub.asc` (both the legacy trailing
  `gpgsig` block and the modern `gpgsig` header are read).
- **Pin**: the signing fingerprint is in the pinned list and NOT in the
  revocation list. **Revocation beats pinning** and is permanent.
- **The hole**: a pipeline-shaped subject (`[plan]` / `[task …]` /
  `[success …]`) with no `Swbp-Role` trailer is a non-broker pipeline
  commit — a failure by construction.
- **Trailers**: well-formed `Swbp-Role` / `Swbp-Model` / `Swbp-Run`.
- **Evidence**: the `Swbp-Prompt-SHA256` / `Swbp-Reply-SHA256` trailers
  recompute from the commit's OWN tree, and no later commit may modify
  the evidence paths (tamper check).

**In-scope boundary**: the first SIGNED broker commit (inclusive).
Earlier commits are `pre-m2`; non-pipeline commits are out of scope.
Report mode (default) always exits 0 and names every failure; `--gate`
exits 1 on any in-scope failure (the T1 flip, M2b).

## The key

- **Type**: Ed25519, sign-only, no passphrase (headless broker), 2-year
  expiry.
- **Home**: `~/.swbp/provenance/gnupg` (dedicated; never the user's
  `~/.gnupg`). Private backup: `~/.swbp/provenance/provenance-key.gpg`
  (mode 600).
- **Current anchor** (as of 2026-09-04, init):
  - uid: `swbp-provenance-20260904T023818Z-16274@swbp.invalid`
  - fingerprint: 346C7C0F2D471E68576CF9166E87DD78A1461240
  - expires: 2028-09-03
  - **Authoritative anchor**: `scripts/.provenance/pub.asc` in each repo
    (the bundle; it grows on rotation). This section is a convenience
    copy — the bundle is the truth.
- **Pin file** (machine tier, CEO-only writer):
  `~/.swbp/provenance/pinned-fingerprints`. Revocation list:
  `~/.swbp/provenance/revoked-fingerprints`.

## Lifecycle procedure

All commands: `scripts/git-provenance.sh <cmd>` (run on the machine that
makes pipeline commits).

| Command | Effect |
|---|---|
| `init` | Create the key, pin it, print the public bundle (commit it to `scripts/.provenance/pub.asc` in every repo that runs the pipeline). |
| `active` | Show the active fingerprint. |
| `rotate` | Create a NEW key (unique uid), make it active, pin it, back up the old private key. **Overlap**: both keys verify until the old one is retired — commit the GROWN bundle (old + new) to every repo. |
| `revoke <fpr>` | Move a fingerprint to the permanent revocation list (beats pinning). Use for compromise. |
| `retire <fpr>` | Same mechanism, benign marker — use after a clean cycle on the successor key. |

**Rotation discipline**: rotate → commit the grown bundle everywhere →
run one clean cycle on the new key → `retire` the old fingerprint.
Commits made by the old key during the overlap still verify (it is
pinned, not revoked).

## What this is NOT

- Not model-side signing (D-127 stands: models get no git access).
- Not a keyserver / no network in verification.
- Not retroactive: pre-M2 history is `pre-m2`, never re-attested.
- Not a replacement for the release gate: provenance verifies WHO/WHAT
  made a pipeline commit; the release gate verifies the SUITE is green.
