# ENGINEERING-CONSTITUTION.md — the canonical source

> **Single source of truth for the engineering principles.** Blueprint-owned
> reference (not a runtime channel — no seat reads this file at runtime). The
> per-seat guidance is **hand-derived, self-contained projections** of this doc,
> inlined into each seat's real channel; this file is where a maintainer keeps
> them coherent. Adopted D-172 (canonical-parent trigger met at three consumers:
> coder, EM, TPM). Mechanical auto-slicing is deliberately deferred until
> hand-sync demonstrably fails.
>
> Apply proportionately. These are decision guides, not a license to add
> abstraction, and **not** a checklist to recite — do not invoke a principle by
> name without naming the concrete risk it prevents in the change at hand.

---

## Decision priority (resolves every conflict)

1. Correctness, safety, required behavior.
2. Explicit invariants and public contracts.
3. Simplicity and readability.
4. Change isolation and testability.
5. Reuse and extensibility.
6. Performance — only when a measurement makes it a requirement.

A change that buys #5/#6 by spending #1/#2 is a reject.

## The principles (condensed)

- **Correctness before cleverness; KISS; YAGNI; DRY with restraint; SOLID;
  separation of concerns; composition over inheritance; least surprise.**
- **Correctness/reliability:** make invalid states hard to represent; explicit
  contracts (inputs/outputs/transitions/side-effects/errors/ownership); fail
  fast at boundaries; fail safe on destructive/ownership-uncertain actions;
  idempotency where retries happen; atomic check-then-act; determinism under
  controlled inputs.
- **Maintainability:** local reasoning; high cohesion / low coupling;
  information hiding; dependency direction inward (policy free of
  framework/DB/net); one source of truth; no speculative refactoring; leave
  unrelated code alone.
- **Testing:** assert observable behavior not implementation; the test must
  discriminate a wrong implementation; right level; hermetic; cover failure
  paths; verification proportional to risk.
- **Ops/security:** observability; least privilege; secure defaults; never
  silently swallow failures; bound external work (timeouts/limits); backward
  compatibility is deliberate.

## Authority by seat — who decides what, and where the projection lives

Principles are decided at the capability level that owns them; guidance reaches
only the seats that make decisions, bounded by their authority. (Seat reality
verified in D-172: the pipeline assigns LLMs to **EM and Coder only**; TPM is a
CEO-assigned chat/agent seat; there is **no reviewer** and the conductor is
process-only, possibly a bare shell.)

| Seat | Owns (decides) | Projection lives in | Reaches |
|---|---|---|---|
| **TPM** | "What correct means": contracts, invariants, valid/invalid states, failure behavior + user errors, retry/idempotency, concurrency/atomicity, backward-compat, discriminating tests incl. negatives, non-goals + prohibited abstractions | `docs/TPM-ROLE.md` | chat (tpm-pack slice), agent (`tpm-agent.sh`), view (`tpm-view.sh`) |
| **EM** | Decomposition into one-file tasks, responsibility boundaries, dependency direction, whether an abstraction is justified (constrained compiler — never re-architects) | `.opencode/prompts/em-plan.md` (+ `em.md` core) | pipeline system prompt |
| **Coder** | Local implementation of one specified task: focused functions, precise types, boundary validation, error handling, restrained reuse, narrow scope | `.opencode/prompts/coder.md` | pipeline system prompt |
| **Conductor** | Nothing about the code — runs the process, reports, escalates | (process obligations only, `CONDUCTOR-ROLE.md`) | — |
| ~~Reviewer~~ | **Does not exist.** App-code "review" = frozen discriminating tests + mechanical gates + live CEO acceptance (D-44) | — | — |

**Caveat (D-172):** tests/gates/acceptance verify *behavior*, not SOLID/cohesion.
With no reviewer seat, those qualities rest entirely on the TPM/EM/coder
projections being coherent — which is why this canonical source exists.

## Where each principle is actually enforced (map, not aspiration)

- **Structural (cannot be violated):** scope containment + one-file atomicity
  (`phase-gate` INV-2, `validate-plan`); least-privilege/bounded work for the
  test run (`sandbox-run.sh`); test-observes-locked-surface (INV-4).
- **Mechanically checked:** bare-except (ruff E722); silent-swallow
  (`check-swallowed-errors.py`, D-68); coverage floor; spec additivity/contract
  pins (refreeze gates).
- **Measured, not gated:** suite discrimination (`mutation-pass.sh`, freeze
  cadence, report-only, D-161).
- **Projection-only (guidance, no gate — by design):** most of SOLID, KISS,
  YAGNI, cohesion, fail-fast/fail-safe, idempotency-in-product-code,
  invalid-states-unrepresentable, backward-compat. **No gate per principle** —
  crude static checks cause false positives and cargo-cult code. A new gate
  requires all four: a concrete recurring defect, a reliable machine-detectable
  signal, acceptable false-positive cost, and a behavioral test of real wiring
  (D-115). Schemas tighten only when repeated failures show prose insufficient.

## Projections (kept in sync with this source by hand)

- **Coder** → `.opencode/prompts/coder.md` — implementation conventions + habits.
- **EM** → `.opencode/prompts/em-plan.md` — the constrained-compiler rules (most
  already present as mechanical plan requirements; the constitution adds the
  explicit "don't invent abstractions absent from the ERD; preserve declared
  dependency direction" framing).
- **TPM** → `docs/TPM-ROLE.md` — the spec-decision checklist (specify the fields
  above so weaker downstream models cannot misinterpret).

Delivery of each projection is pinned by a selftest so a dangling reference
cannot recur.
