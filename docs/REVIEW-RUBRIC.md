# REVIEW-RUBRIC.md — DRAFT checklist for the cold-review seat

> **Status: untracked draft. Not wired to anything.** Delivery is the gating
> question, not the content:
> - **The review seat is the cold adversarial reviewer of `update-template.sh
>   --review`** — not the conductor. The conductor is "a dispatcher and a
>   reporter, not a developer" (`CONDUCTOR-ROLE.md`); pointing it at a rubric
>   would silently widen its lane. The `--review` bundle is **self-contained**
>   (claims + diff + embedded reviewer instructions, hash-bound to what gets
>   applied), so for this rubric to govern that reviewer it must be **included
>   in the bundle** (or the reviewer explicitly granted repo access). No wiring
>   exists yet — see the ownership decision below.
> - **Ownership: Blueprint-only (decided 2026-08-30).** Manifest membership is
>   about distribution, not blast radius (D-115 does not answer it). This rubric
>   stays **out of `.manifest-template`**; it governs only Blueprint's own
>   control-plane reviews (the `--review` seat), and copied/linked children do
>   not receive it. **Promotion trigger:** when a child gains an app-code review
>   seat, revisit fleet-wide (template-owned + drift-guarded).
> - **EM and web-chat TPM are out of scope.** Tool-less / air-gapped; their
>   prompt context (`em.md`/`em-plan.md`) and `tpm-pack.sh` view do not include
>   this file. Not consumers unless the content is inlined into prompt/bundle —
>   deferred.
>
> Where this sits among the real layers: the mechanical gates
> (`phase-gate.sh`, `validate-plan.py`, CI, hooks) carry structural
> enforcement; **live CEO acceptance (D-44) is the completion check** — the
> frozen suite is binding automated *evidence*, not ground truth (D-161). This
> rubric is a **human/frontier review aid** that sits beside those, for the
> judgment a gate can't make. It is not an enforcement layer and must not be
> described as one.
>
> Usage rule (from the source constitution): **do not cite a principle by name
> without naming the concrete failure it prevents in *this* change.** A finding
> with no failure scenario is not a finding.

---

## 0. Decision priority — read first, use to resolve every conflict

When two items below pull in opposite directions, this order decides. Most
review disagreements are really disagreements about this ordering.

1. **Correctness, safety, required behavior.**
2. **Explicit invariants and public contracts** — frozen spec, `contracts.json`,
   persisted-data shape, documented API.
3. **Simplicity and readability.**
4. **Change isolation and testability.**
5. **Reuse and extensibility.**
6. **Performance** — only when a measurement, not a hunch, makes it a
   requirement.

A change that buys #5 or #6 by spending #1 or #2 is a reject, always.

---

## 1. Correctness & reliability

- [ ] **Invalid states are hard to represent**, not just currently unreached.
  *Risk: the guard gets removed and nothing catches the now-legal bad state.*
- [ ] **Contracts are explicit and matched** — inputs, outputs, transitions,
  side effects, errors, ownership. *Risk: a caller relies on undocumented
  behavior a later change breaks.*
- [ ] **Fails fast at boundaries.** *Risk: corrupt data travels far from its
  source; the trace points at the wrong place.*
- [ ] **Fails safe on destructive/ownership-uncertain actions.** *Risk: an
  ambiguous request destroys or leaks the wrong data.*
- [ ] **Idempotent where retries can happen.** *Risk: an at-least-once path
  (queue, webhook, double-click) creates duplicates.*
- [ ] **Check-then-act is atomic.** *Risk: two concurrent runs both pass the
  check.*
- [ ] **Deterministic under controlled inputs** — time/randomness/ordering
  injected. *Risk: green until the clock or map-order changes; flaky forever.*

## 2. Maintainability

- [ ] **Local reasoning** — understandable without loading the whole system.
- [ ] **Cohesion / coupling / separated concerns** — name the two layers that
  are entangled, and the change that would force edits across both.
- [ ] **Information hiding** — callers see need, not representation.
- [ ] **Dependency direction inward** — core policy free of framework/DB/net
  types.
- [ ] **One source of truth** — one owner per rule/id/state. *We have been
  burned by exactly this: DECISIONS-ledger divergence.*
- [ ] **No speculative refactoring; unrelated code left alone.** *Risk: an
  incidental rewrite hides the real change and widens the blast radius past
  what the gate and reviewer can trace.*

## 3. Testing & verification — read against the *current* machinery

- [ ] **Tests assert observable behavior, not implementation.** *Risk: tests
  that pin internals block the refactors they should permit.*
- [ ] **Does the test plausibly discriminate a wrong implementation?** Judge
  this **by reading the test** — the reviewer's eye is the only per-change
  signal that exists. Be accurate about what the machinery does and does not do:
  - suite discrimination is measured only at **freeze cadence**, by
    `scripts/mutation-pass.sh` — **one-shot, report-only, not a gate, not
    per-change** (D-161; per-run/emptied-`src` mutation testing was
    **rejected** at D-75 and reaffirmed rejected — do not invoke it as a review
    step);
  - **spec-clause → test mapping is UNBUILT** (D-161 alt (c)) — do not treat
    "test count vs clause count" as an available check;
  - `red-before-green` at freeze (D-75) is **warn-only**, not a pass/fail.
  So: flag a test that would pass against an obviously-wrong body, but frame it
  as a review judgment, never as a gate the pipeline enforces.
- [ ] **Right level** — unit by default, contract/integration at real
  boundaries, e2e kept narrow.
- [ ] **Hermetic** — time/fs/network/subprocess controlled. *Risk: green on
  CI, red on a dev host with a real server up (the non-hermetic class we've hit).*
- [ ] **Failure paths and boundaries covered**, not just the happy path.
- [ ] **Verification proportional to risk** — a control-plane or destructive
  change earns more than one happy-path test.

## 4. Operations & security

- [ ] **Observable** — stdlib `logging` for diagnostics, structured errors,
  correlation ids; `print` used as application logging is the defect, while
  deliberate CLI/user-facing stdout is fine. *Risk: a production failure with
  nothing to diagnose it by.*
- [ ] **Least privilege / secure defaults** — no scope broadened "to make it
  work." *Risk: a wildcard grant (the `safe.directory '*'` near-miss).*
- [ ] **No silently swallowed failure** — never `|| true` over an unknown error
  class. *Risk: one benign case's suppression hides every other failure of that
  command (the git-identity no-op incident).*
- [ ] **External work is bounded** — explicit timeout/limit on every call,
  subprocess, retry, wait.
- [ ] **Backward compatibility is deliberate** — public API / persisted data /
  documented behavior change only on purpose, called out in the diff.

---

## How to score

Walk §1→§4 in order; resolve tension via §0; rank findings by the priority tier
they touch. Report the true severity distribution, not a problem list. Two
standing cautions from this repo's own rules:

- **"Detected nothing" ≠ "green."** An untriggered check is inconclusive
  (Rule 6). Keep standalone-result and live-run claims separate.
- **Enforcement that can be mechanized belongs in a gate, not this rubric** —
  *but only when it clears the admission bar* (concrete failure class,
  proportionate blast radius, acceptable false-positive cost, a test of the
  real wiring; D-115). "This principle is currently review-only" is not by
  itself a reason to build a gate. When a check does clear that bar, say so —
  that is the highest-leverage outcome a review produces.
