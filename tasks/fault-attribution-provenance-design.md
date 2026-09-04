# Fault-attribution provenance — endorsed design

> **Status: CEO-endorsed 2026-09-04 (design).** Implementation not yet
> scheduled. Endorsed *as the Software Development Blueprint approach*, with
> the four refinements below binding. Recorded as D-185 and queued in
> `tasks/BACKLOG.md`; implementation remains unscheduled.
>
> Supersedes nothing; extends T7 (`tasks/T7-provenance-decision.md`,
> `tasks/T7-m2-design.md`). T7 builds **authorship/integrity**; this builds
> **fault attribution** on the same evidence substrate.

---

## 1. The two provenance goals (kept separate on purpose)

- **Authorship / integrity (T7, M1+M2):** tamper-evidently *prove which actor
  made a change*. Signature-backed. Largely built (see §3).
- **Fault attribution (this note):** *when something breaks, trace it back* to
  the responsible tier (coder / EM / TPM) and the specific LLM, from durable
  evidence, after ship.

These are different goals with different failure modes. They share one
substrate (the committed task evidence) but must not be conflated: a valid
signature says nothing about whether the code is correct.

## 2. Core architecture (agreed)

1. **Separate authorship/integrity from fault attribution** — two consumers of
   one evidence store, never one claim doing both jobs.
2. **The durable source of truth is committed, content-addressed *task
   evidence* — not Git authorship.** A commit's author field is erased by any
   re-commit / squash / cherry-pick; content-addressed evidence recognizes the
   work by its bytes and survives that.
3. **Each task's evidence records:** the produced **diff**, the **tier**, the
   **model**, the **prompt(s)**, the **reply(ies)**, and the **diagnosis**.
4. **Post-ship adjudication is a first-class path.** A green-but-wrong bug (the
   frozen test itself was wrong — a spec/TPM fault) carries *no* automatic
   fault at ship time, because the run succeeded. Attribution for it is
   performed later, by re-running the same adjudication against durable
   evidence. This is judgment, not automation, and the design says so.

## 3. As-is (verified in the tree, 2026-09-04)

**Built:**
- **Authorship trail (M1/M2a):** broker with author≠committer; trailers
  (role/model/run/task/plane/prompt-hash/reply-hash); GPG signing + trust
  anchor; `prompt`/`reply`/`meta` committed under `.swbp-evidence/<run>/<task>/`
  (hash-bound); verifier `check-provenance.py` in **advisory (warn-only)** mode.
  Enforcement flip (M2b) awaits one live run — machine-gated, lane-owned.
- **Fault taxonomy:** `FAULT_ROLE` ∈ `coder | em | tpm | environment |
  pipeline | none`, set at the real halt sites in `orchestrate.sh`, written to
  the run exit row.
- **Live diagnosis verdict:** `brief_wrong | decomposition_wrong |
  contract_or_test_wrong | transient_or_environmental` (EM consult).
- **Coder model + EM model** captured.

**Gaps for fault attribution specifically:**
- Fault detection fires **only when a run fails** — not for bugs that shipped
  green.
- The fault verdict + `FAULT_ROLE` + the `.em-archive`/`.coder-archive` records
  are **self-ignoring, CWD-local, wiped at success teardown** — NOT durable.
  Only `.swbp-evidence/` is committed, and it lacks the verdict and the diff.
- **No per-task diff** is stored in evidence.
- **No backward-trace tool** (the verifier does integrity only).
- **TPM model** is usually `human` (the TPM runs in chat; not observable).
- **Direct/hand-written fixes** carry no provenance at all.

## 4. The four binding refinements (CEO, 2026-09-04)

1. **Fault verdicts are revisable events, not permanent facts.** Store each
   verdict as an event carrying: the evidence it rests on, the **adjudicator**
   (human / EM / a model id), the **taxonomy version**, a **confidence**, and
   any **later corrections** (an event may supersede an earlier one). The
   current fault is *computed* by folding the un-superseded events; the history
   is kept. **These events do NOT live inside `.swbp-evidence/`** — see §6a for
   why (immutability conflict) and where they live instead.
2. **Shared causality is representable.** A defect may involve an ambiguous TPM
   contract *and* a weak EM decomposition *and* a coder mistake. Record a
   **primary tier plus contributing tiers**, never a single blamed seat.
3. **Do not overclaim content matching.** Exact diff provenance survives
   squashes and re-commits, but **not** substantial edits or refactors. The
   trace tool returns **confidence levels** (e.g. exact / partial / none) and
   says **"unknown"** rather than guessing when the code has diverged from any
   recorded diff.
4. **Precise attestation language, everywhere.** A signature proves *what the
   pipeline recorded*; it does **not** independently prove which model
   generated the bytes. Every artifact (verifier output, docs, trace-tool
   output) states this ceiling.

**Explicit boundaries (CEO):** attribution is **not** singular, **not**
infallible, **not** permanently settled. Any design element implying otherwise
is out of contract.

## 5. Additional requirements (CEO, 2026-09-04)

- **Capture the exact model id/version AND the execution configuration** (not
  just a model slug) — enough to reproduce/interpret the call.
- **Protect prompts that may contain secrets.** Evidence is committed and
  pushed to remotes; prompts must be scrubbed/redacted (or the secret-bearing
  portion excluded with a marker) before they land in `.swbp-evidence/`. A
  hash over the *original* bytes may still be kept for integrity while the
  stored copy is redacted — the redaction policy is part of the schema.
  **Redaction is deterministic and fail-closed** (pattern/entropy rules, not an
  LLM). Do **not** put an LLM-based secret scanner on the per-task path — it
  adds latency, cost, and another uncertain actor; a deterministic rule that
  errs toward over-redaction is the contract.
- **The evidence schema is versioned.** Every record carries its
  `schema_version`; the trace tool and verifier read the version and adapt.
- **Verification is incremental.** The verifier/trace never rescans full repo
  history per commit — it operates on the push/commit range (existing
  `check-provenance.py` default `HEAD~50..HEAD`, CI passes the push range). A
  full-history rescan is an occasional audit, never a per-operation tax.
- **Ad-hoc fixes get an escape hatch, not a prohibition.** A captured fix (via
  the lightweight command, §7.5) is traceable; an ordinary direct commit is
  **allowed** and simply reported as `unknown/unattributed`. Forcing every
  emergency fix through capture (or the full milestone pipeline) would make the
  feature operationally expensive and drive people to bypass it.

## 6. Evidence record — shape (versioned)

Per task (extending today's `.swbp-evidence/<run>/<task>/`):

- `schema_version`
- `prompt` (redacted per §5), `reply`, and their hashes over original bytes
- **`diff`** (the patch this task produced) — NEW
- `meta`: exact model id **+ version**, execution config, role/tier, run, task,
  call-id, timestamps

The evidence record is committed with the task (atomic, content-addressed) and
is **permanently immutable** — M2's verifier treats any later change to
`.swbp-evidence/<run>/<task>/` as tampering. **No verdict log lives here.**

## 6a. Adjudication events — the revisable layer (separate, immutable-per-event)

The immutability of §6 is exactly why revisable verdicts cannot be appended
into the evidence record. Instead:

- **`.swbp-evidence/` stays permanently immutable** (the as-produced record).
- Each adjudication or correction is a **new, signed, immutable event**, e.g.
  `.swbp-adjudications/<case>/<event>.json`, carrying:
  `{ id, ts, adjudicator, taxonomy_version, primary_tier, contributing_tiers[],
     confidence, evidence_refs (original evidence hashes), supersedes? }`.
- An event **references the original evidence by hash** and optionally
  **supersedes** an earlier event. Nothing rewrites history.
- **The current verdict is computed** by folding the un-superseded events for a
  case — never by mutating a stored fact.

So both immutability contracts hold: evidence is never touched after creation,
and each adjudication event is itself immutable; revision happens by *adding*
a superseding event, not editing one.

## 6b. Failure-evidence sink (a real gap)

Today only a **successful task commit** carries evidence. Failed attempts and
their diagnoses (the `.em-archive`/`.coder-archive` records) have **no
committing vehicle** and are wiped locally — yet they are exactly the material
a `coder`/`em` fault verdict rests on. The implementation needs an **explicit
failure-evidence commit at halt** (or another durable, signed sink) so a failed
milestone's prompts/replies/diagnosis become durable evidence too, not just the
green path's.

## 7. Concrete deltas (implementation shape — small-to-medium)

1. **Promote to durable storage:** record `fault_role`/diagnosis as the first
   signed **adjudication event** (§6a) — NOT appended into the immutable
   evidence record (today these die locally).
1a. **Failure-evidence commit at halt (§6b):** on a failed milestone, commit
   the failed attempts' prompts/replies/diagnosis as durable signed evidence
   (they have no successful-task commit to ride).
2. **Capture the per-task diff** into evidence.
3. **Capture the TPM seat's model** at freeze (name the seat), so a
   spec-authoring fault names a specific LLM, not `human`.
4. **Trace tool** (`buggy line → task → tier → model`): reads the durable
   evidence, matches by content, returns the tier(s), model(s), verdict
   history, and a **match confidence** (exact / partial / unknown).
5. **Lightweight ad-hoc capture command:** a broker command that records a
   direct fix — who/which model produced it, the request/reason, before/after
   diff, tests run, model config, and whether it was subsequently human-edited
   — auto-deriving everything derivable (≈one command, 10–60 s of workflow). It
   does **not** launch a milestone/EM/TPM. Paired with the escape hatch (§5):
   uncaptured direct commits stay allowed, reported `unknown/unattributed`.
6. **Secret-redaction step** on prompt capture (deterministic, fail-closed);
   **schema versioning** on all records.

## 7a. Cost profile (CEO analysis, 2026-09-04)

Marginal cost is low for milestone runs, moderate (workflow, not compute) for
ad-hoc fixes, and mostly operational/governance rather than inference.

| Area | Marginal cost |
|---|---|
| Successful milestone run | **No extra LLM call**; ~1–3 s hashing, diff capture, signing, bounded verify |
| Failed milestone | Reuses the existing diagnosis call; **one added failure-evidence commit at halt** (§6b) + a few seconds of verification |
| Evidence storage | T7 baseline ≈ 1–2 MB / 20-attempt milestone; fault fields add ≈ 0.2–0.6 MB pre-compression |
| Ad-hoc fix | <1 s mechanically; ≈10–60 s of workflow if routed through the capture command |
| Later bug investigation | Provenance lookup: seconds; fault adjudication: ~15–60 min human/model review |
| One-time build | ≈10–15 engineer-days hardened; **4–7 days for a milestone-only MVP** |

Key points: the normal milestone path incurs **essentially zero added
inference** (prompt/reply/model/task/commit already exist). Repo growth ≈
100–200 MB per repo per 100 substantial milestones (mostly the existing T7
evidence; fault fields are a minority). Post-ship adjudication cost already
exists during incident analysis — the feature makes the evidence available, so
it should *reduce* total investigation time. Storage anchor:
`tasks/T7-m2-design.md` (20-attempt ≈ 1–2 MB).

## 7b. Build order (CEO recommendation, 2026-09-04)

1. **Milestone** diff capture + model/config capture + versioned records +
   **exact-match** trace. (Keeps the normal-run tax negligible.)
2. **Append-only, revisable fault events** (§4.1).
3. **Lightweight ad-hoc-fix capture command** (§7.5) + escape hatch.
4. **Partial/fuzzy matching only after exact-match has real usage evidence** —
   do not build fuzzy matching speculatively.

The feature becomes expensive only if SWBP tries to (a) make every attribution
automatic, (b) force every emergency fix through capture/the full pipeline, or
(c) rescan full history per operation. The endorsed design requires none of
these.

## 8. Open items / dependencies

- The M2b enforcement flip (authorship track) is an independent prerequisite
  for trusting the signed layer; it is machine-gated and lane-owned.
- Redaction policy needs a concrete rule (what counts as a secret; marker
  format) before prompt evidence is trusted to be push-safe.
- Direct/hand-written fixes remain unattributed unless routed through an
  evidence-logging path — out of scope for the first cut, noted as a known
  limit.
