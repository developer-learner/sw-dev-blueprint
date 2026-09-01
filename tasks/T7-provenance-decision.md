# T7 — Model-specific Git provenance (decision note)

> Milestone kickoff, awaiting the CEO's build/no-build call. This note
> records the problem, the current evidence situation, a concrete design
> (the trusted commit broker), the options, a recommendation, and the
> blind-test plan. The go/no-go and scope are the CEO's; if approved, the
> implementation lands upstream in the Blueprint and is adopted by
> Vortex/Testchat through their own `update-template.sh` pull step —
> never a push from the Blueprint.
>
> Source: vortex backlog item 13 (filed 2026-08-22, Codex (GPT-5)).

## Problem

Every commit in the child repos shares the Arc Elixir Git/GitHub identity.
The pipeline's commits — `[plan]`, `[task]`, `[success]`, `[refreeze]`,
`[template-*]` — are all authored and committed as the human principal, so
a change can only be **inferred** to have come from a particular model
call, not **attributed** to it.

## What already holds (and what doesn't)

**Already true — the model never runs git.** Every pipeline commit is made
by the trusted shell, at exactly these sites:

| Site | Subject | Producer of the content |
|---|---|---|
| `orchestrate.sh:1527` | `[plan] validated against spec vN` | EM plan call |
| `orchestrate.sh:2201` | `[task <id>] attempt N` | coder call for that attempt |
| `orchestrate.sh:2535` | `[success] spec vN (plane <sha12>)` | the shell's own bookkeeping |
| `refreeze.sh:968` | `[refreeze vN]` | TPM delta, human-approved |
| `update-template.sh:121/290/301/358`, `link-template.sh:169`, `bootstrap.sh:146` | `[template-*]`, bootstrap | operator-driven adoption |

The sandbox already refuses `.git` writes (D-127 blocklist), so "the
trusted orchestrator — not the model — owns the commits" is the existing
trust boundary. What is missing is that the commits **carry** no
model/role/session evidence at all.

**Evidence that exists today, but outside Git:**

- `.em-archive/<ts>_<kind>/` — `prompt.txt`, `reply.json`, `meta.txt`
  (carries `em_model=` from `SWBP_EM_MODEL` since `09aec03`), verdicts.
- `.coder-archive/<v>.<task>.<rev>.<attempt>.raw/.log` — raw replies +
  call log. **The coder prompt is not archived byte-for-byte today**
  (it is constructed inline and piped straight to `llm-call.sh`).
- `.measurement/counters` — terminal rows with `fault_role=`, `plane=`,
  `spec=`; the `[success]` subject carries the plane SHA (D-168).

These are CWD-local, self-ignoring, and partially wiped at success
teardown — they do not survive a push, and nothing ties a specific commit
to a specific model call. Attribution today is correlation by timestamp,
which is exactly the inference the filing rejects.

## Design — the trusted commit broker

A single plane helper (`scripts/git-provenance.sh`, function
`swbp_commit`) becomes the only path by which a pipeline commit is made.
Every site above routes through it. It does three things:

### 1. Author/committer separation

- **Author** = the machine that produced the content:
  `swbp-<role>-<modelslug>` / `swbp-<role>-<modelslug>@swbp.invalid`, set
  via `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` on the single commit
  invocation. `role` ∈ `em|coder|tpm|pipeline|human`; `modelslug` is the
  sanitized observed model id (`SWBP_EM_MODEL` / `SWBP_CODER_MODEL`;
  lowercase, non-alphanumeric → `-`, ≤32 chars) or the literal `unset`
  when the env var is absent — never fabricated.
- **Committer** = always the ambient human identity (Arc Elixir). The
  committer is the principal accountable for the repo; the author is the
  provenance label.

### 2. Provenance trailers (added at commit time, one trailer block)

| Trailer | Carried by | Value source |
|---|---|---|
| `Swbp-Role:` | all | the site's role |
| `Swbp-Model:` | all | observed model id or `unset` |
| `Swbp-Run:` | `[plan]` `[task]` `[success]` | run id, generated at run start (`<UTC ts>-v<spec>-p<plane sha12>`), persisted in `.pipeline-state/run-id` so a resume keeps the same run |
| `Swbp-Task:` | `[task]` | task id |
| `Swbp-Plane:` | all pipeline sites | D-168 pinned plane SHA |
| `Swbp-Prompt-SHA256:` | `[plan]` `[task]` | sha256 of the exact archived prompt bytes |
| `Swbp-Reply-SHA256:` | `[plan]` `[task]` | sha256 of the exact archived raw reply |

`[success]` carries run/plane but no prompt/reply hashes (the shell's own
bookkeeping — there is no single reply to hash). `[refreeze]` carries
`role=tpm` and `Swbp-Model:` from an optional operator-set
`SWBP_TPM_MODEL` (default `human` — the TPM runs in the CEO's chat; its
model id is not mechanically visible to `refreeze.sh`, and the approval
is the human's either way). `[template-*]`/bootstrap carry `role=human`.

M1 also adds coder-prompt capture (tee the constructed prompt to
`$LOG_DIR/<id>-a<attempt>.prompt` and archive it alongside `.raw`/`.log`)
so the `[task]` prompt hash is computable.

### 3. Pipeline attestation (the strong-evidence layer)

The broker signs each commit with a pipeline-owned key:

- `swbp-provenance init` generates a GPG keypair on first use; the
  private key lives at `~/.swbp/provenance/` (0600, outside the repo,
  outside the sandbox — the model cannot read or use it); the public key
  is committed to the repo (`scripts/.provenance/pubring.asc`).
- `git commit -S` with that key → the signature is **inside the commit
  object**; anyone with the public key can verify "the pipeline broker
  made this commit" with no sidecar file and no chain to maintain.
- A verifier (`scripts/check-provenance.py`) walks a commit range and
  checks, per pipeline commit: (1) valid pipeline signature, (2) trailer
  consistency (role/model/plane/run well-formed; hashes match the
  archived bytes when the archive is present), (3) no pipeline-subject
  commit in range lacking a signature.

What this does **not** do: no `Co-authored-by` (the filing explicitly
rejects it as execution provenance); no model-side git access (already
blocked); no change to what gets committed or to any gate's verdict.
Within the host+sandbox trust boundary the attribution is mechanical;
outside it, the signature still binds the commit to the pipeline key —
which is the "pipeline-owned attestation" the filing asks for. An author
label alone remains spoofable by a host-level actor; the signature is
what closes that.

## Options

1. **Decline** — keep the shared identity; the archives + metrics remain
   the provenance record; the limitation is documented. (T7 closes as
   explicitly declined.)
2. **Broker + trailers only** (no signing) — closes the attribution gap
   (commit → model/role/run/plane/prompt/reply becomes mechanical, not
   inferred). Smallest step; trailers remain spoofable by a host-level
   actor, which the current trust boundary already excludes.
3. **Full: broker + trailers + signing + verifier** — the filing's full
   bar (T7's "Done when" names pipeline attestation). Staged as two
   milestones: **M1** broker + author/committer + trailers + run-id +
   coder-prompt capture + selftests (S/M); **M2** signing + verifier +
   CI wiring (report-only first, hard gate after one clean adoption
   cycle — the house pattern: advisory teeth, then real teeth) +
   Vortex/Testchat adoption (M).

## Recommendation

**Option 3, staged M1 → M2.** The pain the filing names is attribution
(M1 fixes it); the "trusted" in "trusted commit broker" is the signature
(M2 earns it). If the CEO wants the smallest coherent step, option 2 is
self-sufficient — it is M1 exactly; M2 is the add-on.

## Blind-test plan (freeze-first, house style)

Authored before implementation, against a fixture repo:

1. Broker commit carries the expected author name/email, the ambient
   committer, and the exact trailer set/values.
2. Planted prompt/reply bytes → trailer hashes equal their sha256; the
   verifier detects a tampered archive.
3. Signed commit verifies against the committed public key; a wrong-key
   commit fails verification.
4. `SWBP_EM_MODEL` absent → `Swbp-Model: unset` (never fabricated).
5. Source-shape: all pipeline commit sites route through the broker
   (the group-1 oracle-gap pattern — assert the call, not just the
   helper).
6. Verifier names a non-broker commit planted in a fixture history (gate
   mode fails; report mode warns).
7. Resume keeps the same `Swbp-Run` id across a halted/resumed
   milestone.

## Adoption path

Blueprint implements and publishes → Vortex and Testchat advance their
pins via their own `update-template.sh` (their LLMs pull; the Blueprint
never pushes). The first post-adoption run is the live validation — the
`[success]` subject plus trailers self-document, the same way D-168's
plane SHA does.

## Open questions (decide at go, or take the defaults)

- Author email domain: `@swbp.invalid` (RFC 6761 reserved — never
  routable) — default.
- `SWBP_TPM_MODEL` best-effort env for `[refreeze]`, default `human` —
  default.
- Signing key: GPG (portable, `git commit -S` native) over SSH —
  default.
