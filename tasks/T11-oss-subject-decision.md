# T11 — Mature OSS adoption subject #2 (decision note)

> The subject choice is the CEO's. This note records what run #2 is, the
> constraints that shape the choice (D-165/D-172), the selection
> criteria, five verified candidates with fit assessments, a
> recommendation, and the program shape a "go" commits to.
>
> Source: vortex backlog item 18.

## What run #2 is

A second brownfield adoption of the control plane onto a **mature
open-source project** — the CEO's own words in D-172: "any future
representative brownfield subject is mature open-source software, run
#2." Run #1 was Vortex (D-172, 2026-08-15): the plane installed verbatim
from Blueprint HEAD, the legacy suite pinned as a byte-hash snapshot
(never an oracle), the first milestone producing the first freeze, and
the findings ledgered (D-173 pre-spec tunnel gate-clean; D-174
live-walkthrough findings became the first milestone backlog).

The point of run #2 is **seam discovery**: D-165 records that adoption is
*snapshot-plus-go-forward* theory, "unvalidated by any run, and the
framework's own history shows every new seam class is discovered by
incident, not design." A second subject — ideally a different shape —
tests whether the theory generalizes, and finds the seam classes run #1
was too close to its own domain to expose.

## Constraints (mechanical, from D-165/D-172)

1. **Python + pytest.** The oracle machinery is pytest + `--json-report`
   + Python-validator bound (D-110). Non-Python/non-pytest stacks are a
   fatal class — the framework does not exist for them without a new
   oracle adapter.
2. **Mature OSS.** Established project, stable releases, real feature
   history. Not a toy, not pre-1.0 churn, not the CEO's live project
   (testchat is hands-off by ruling).
3. **Tractable size.** The EM/coder inventory must be enumerable and the
   first milestone reviewable. Rule of thumb: ≲150 source files, test
   suite ≲10 min on this machine.
4. **Runs locally.** No external services for the test suite; the Lima
   VM + local models must be able to drive a real milestone.
5. **Different shape from run #1.** Vortex was a FastAPI server + web UI
   + async model-process lifecycle. A second web app would mostly
   re-prove what run #1 already proved; a different shape maximizes new
   seam classes.
6. **Permissive license, public clone.** The experiment runs on a local
   clone; nothing is ever pushed upstream.

## Candidates (verified 2026-09-01 against PyPI)

| Subject | Latest | License | Shape | Fit |
|---|---|---|---|---|
| **Rich** (Textualize/rich) | 15.0.0 | MIT | terminal rendering library | **Recommended.** New contract surface: rendered output. The framework has frozen HTTP routes + DOM (browser oracle) but never "output shape" — Rich's own suite pins rendered text, so the first freeze exercises a genuinely new seam (contracts over rendered strings). Medium size (~40 modules), fast suite, zero services, py≥3.9. |
| **Gunicorn** (pallets/gunicorn) | 26.2.0 | MIT | WSGI server / process supervision | Strong runner-up. Arbiter/workers/signals shape differs from Vortex's model lifecycle — but is thematically adjacent (long-lived process management), so it cross-validates the lifecycle class where the framework's strongest evidence lives (v22–v26). Stdlib-only, ~30 files, tiny suite. |
| **Click** (pallets/click) | 8.5.0 | BSD-3 | CLI framework | Cheapest, fastest run. CLI shape (no server, no UI) is new to the framework; contract surface is small (options/exit codes). Risk: too easy to stress the pipeline — the milestone may be over before the ladder ever sees a second strike. |
| **Uvicorn** (encode/uvicorn) | 0.52.4 | BSD-3 | ASGI server | Mature and small, but async-server shape is close to Vortex's own domain — lowest seam novelty of the five. |
| **Scrapy** (scrapy/scrapy) | 2.18.0 | BSD-3 | crawler engine + middleware | Highest seam novelty (plugin/middleware architecture, downloader, spider API) but the heaviest: ~100+ files, twisted reactor in the stack, slower suite. D-165's "workable-but-heavy" path at its heaviest; the first freeze's inventory is a project in itself. |

## Recommendation

**Rich.** It is the only candidate that is simultaneously mature,
tractable, zero-service, and a *new contract surface* for the
frozen-spec machinery (rendered output rather than routes/DOM). Gunicorn
is the fallback if the CEO prefers process-supervision shape; Click if
the priority is a fast, cheap second data point over seam novelty.

The milestone #1 feature is **not** pre-chosen here — the TPM names it at
spec time from the subject's own small, real feature space (the house
rule: the spec is the TPM's; this note only fixes the subject).

## Program shape (what a go commits to)

- **Phase 0 — install (XS).** Clone the subject to a local experiment
  repo; install the plane verbatim from Blueprint HEAD (hash-verified
  against `scripts/.manifest-template`); adapt project-owned files under
  Rule 3 and re-pin in `scripts/.manifest-project`; pin the legacy suite
  as a byte-hash snapshot (`legacy-pin.json` pattern, D-172); record the
  pre-spec tunnel state (D-173).
- **Phase 1 — first freeze + first milestone (M–L).** The first freeze
  decides the legacy suite's fate (carried or retired — D-172's guard);
  one real small milestone runs TPM → refreeze → orchestrate on the Lima
  VM with local models. This is the live validation of D-165's
  snapshot-plus-go-forward theory on a second subject.
- **Phase 2 — findings (S).** Ledger the adoption findings as DECISIONS
  entries (the D-173/D-174 pattern); write the findings doc (seam
  classes discovered, gate hits, what the framework got wrong); verdict
  on whether the theory generalizes.

**Excluded by ruling:** no brownfield adoption tooling (D-165 forbids it
until generalization is a named feature); no upstream push; the legacy
snapshot is never an oracle; the CEO's live projects stay hands-off.

**Cost:** L per the register (Phase 0 XS + Phase 1 M–L + Phase 2 S).
Phase 1 is the only part that contends for the machine's single
live-run slot (cross-cutting rule 2) — it schedules around Vortex's
runs.
