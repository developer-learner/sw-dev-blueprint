# T7 — Model-specific Git provenance (decision note)

> **CEO ruling 2026-09-01: Option 3 approved as staged. M1 is authorized
> and IMPLEMENTED (this Blueprint, D-174); M2 (signing + verifier) is
> authorized only after the three M2 prerequisites below land.**
>
> This note records the problem, the current evidence situation, the
> design (the trusted commit broker), the options, the ruling, and the
> blind-test plan. The implementation lives upstream in the Blueprint and
> is adopted by Vortex/Testchat through their own `update-template.sh`
> pull step — never a push from the Blueprint.
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
  sanitized observed model id (lowercase, non-`[a-z0-9._-]` → `-`,
  ≤64 chars — the email local-part limit) or the literal `unset` when
  nothing was observed — never fabricated. The observed id is the
  **provider-returned** model (the response envelope's `model` field,
  exposed by llm-call.sh's `SWBP_LLM_META_OUT` sidecar — the same field
  the D-62 seat check treats as the server's claim) when the server
  reports one, else the role's mapped model (`SWBP_EM_MODEL` /
  `SWBP_CODER_MODEL`), else `unset`.
- **Committer** = always the ambient human identity (Arc Elixir). The
  committer is the principal accountable for the repo; the author is the
  provenance label.

### 2. Provenance trailers (added at commit time, one trailer block)

| Trailer | Carried by | Value source |
|---|---|---|
| `Swbp-Role:` | all | the site's role |
| `Swbp-Model:` | all | observed model id or `unset` |
| `Swbp-Run:` | `[plan]` `[task]` `[success]` | run id, generated at run start (`<UTC compact>-<6 hex>`, e.g. `20260901T143022Z-a1b2c3`), persisted in `.pipeline-state/run-id` as `<id> spec=<v>` so a resume with the same spec keeps the same run; a new spec version (post-refreeze) starts a new one; the file dies with the success teardown, so the id lifecycle is exactly one milestone attempt sequence |
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

### M2 prerequisites (CEO ruling 2026-09-01 — signing is NOT authorized until these are designed to completion)

1. **Durable trust anchor.** A public key stored only in the repo it
   verifies is insufficient by itself (a compromised pipeline can re-pin
   its own key). M2 must add a pinned key fingerprint + rotation and
   revocation rules, published out-of-band of the verified repo (e.g.
   the CEO's playbook / a separate pinned location); the verifier checks
   the signing key's fingerprint against the pinned anchor, not merely
   "verifies with the in-repo public key". Rotation = new key +
   documented re-pin procedure; revocation = a fingerprint blocklist.
2. **Durable evidence storage.** A trailer hash is unreverifiable later
   if the corresponding archived bytes are deleted (the archives are
   self-ignoring and CWD-local — they do not survive a push or a machine
   loss). M2 must make the milestone's prompt/reply bytes durable —
   e.g. committed under a per-run evidence path bound to the run id,
   hash-verified against the trailers — so `Swbp-Prompt-SHA256` /
   `Swbp-Reply-SHA256` are re-verifiable from the repo alone.
3. **Attestation semantics, stated for the record.** Signing attests
   what the TRUSTED PIPELINE RECORDED (the broker's trailer values), not
   independently which model generated the response. Only the pipeline's
   own call path (llm-call.sh, D-62 seat check) can make that claim. M2
   documentation and the verifier output must say exactly this. Provider-
   returned model/run identifiers are preferred over environment
   variables when available — M1 already does this for the model id
   (meta sidecar); M2 extends the same preference to any run identifier
   the provider returns.

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

## Recommendation → Ruling

**Recommended:** Option 3, staged M1 → M2. The pain the filing names is
attribution (M1 fixes it); the "trusted" in "trusted commit broker" is
the signature (M2 earns it). If the CEO wanted the smallest coherent
step, option 2 is self-sufficient — it is M1 exactly; M2 is the add-on.

**Ruling (2026-09-01):** Option 3 approved as staged, **M1 authorized
now**; M2 authorized after the trust-anchor and evidence-retention
details (prerequisites above) are added. M1 landed as D-174.

## M1 implementation record (D-174, 2026-09-01)

- `scripts/git-provenance.sh` — `swbp_commit`, `swbp_run_id`,
  `swbp_model_slug` (sourced library; fail-closed source in
  orchestrate.sh preflight).
- Sites wired: orchestrate [plan]/[task]/[success]; refreeze [refreeze
  vN] (role=tpm, `SWBP_TPM_MODEL` default `human`); update-template ×4,
  link-template, bootstrap (role=human, ambient author).
- llm-call.sh: `SWBP_LLM_META_OUT` sidecar (`model=`, `call_id=` from the
  response envelope) — opt-in, no-op for existing callers.
- Coder prompt capture: `tee` to `$LOG_DIR/<id>-a<attempt>.prompt`,
  archived as `.coder-archive/<v>.<task>.<rev>.<attempt>.prompt` (+`.meta`).
- Selftests: `scripts/selftest/selftest_provenance.py` (10 tests, blind
  fixture repo driving the REAL broker; full suite 548 green).
- Manifest: `git-provenance.sh` added to `.manifest-template` (76
  entries); modified scripts re-pinned.

## Blind-test plan (freeze-first, house style)

Authored before implementation, against a fixture repo. M1 items landed
in `selftest_provenance.py`; M2 items land with M2.

1. ✅ Broker commit carries the expected author name/email, the ambient
   committer, and the exact trailer set/values.
2. ✅ (hash half) Planted prompt/reply bytes → trailer hashes equal
   their sha256; absent bytes → trailer omitted. ⏳ (M2) the verifier
   detects a tampered archive.
3. ⏳ (M2) Signed commit verifies against the pinned trust anchor; a
   wrong-key commit fails verification.
4. ✅ `SWBP_EM_MODEL` absent → `Swbp-Model: unset` (never fabricated);
   ✅ provider-returned model preferred over the mapped env var.
5. ✅ Source-shape: all pipeline commit sites route through the broker
   (a bare `git commit` at a pipeline site fails the suite).
6. ⏳ (M2) Verifier names a non-broker commit planted in a fixture
   history (gate mode fails; report mode warns).
7. ✅ Resume keeps the same `Swbp-Run` id (same spec reuses; a new spec
   version generates a new one).

## Adoption path

Blueprint implements and publishes → Vortex and Testchat advance their
pins via their own `update-template.sh` (their LLMs pull; the Blueprint
never pushes). The first post-adoption run is the live validation — the
`[success]` subject plus trailers self-document, the same way D-168's
plane SHA does.

## Open questions (resolved by default at the 2026-09-01 ruling)

- Author email domain: `@swbp.invalid` (RFC 6761 reserved — never
  routable) — **default taken**.
- `SWBP_TPM_MODEL` best-effort env for `[refreeze]`, default `human` —
  **default taken**.
- Signing key: GPG (portable, `git commit -S` native) over SSH —
  **default taken** (M2).
