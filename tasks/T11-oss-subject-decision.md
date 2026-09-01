# T11 — Mature OSS adoption subject #2 (decision note)

> **CEO ruling 2026-09-01: Rich approved for Phase 0. Phase 0 DONE
> (D-175); Phase 1 spec DRAFTED (v1 = Table bulk construction); the
> freeze + live run await the Linux dev VM slot.**
>
> This note records what run #2 is, the constraints that shaped the
> choice (D-165/D-172), the selection criteria, five verified candidates
> with fit assessments, the recommendation, the ruling, and the program
> shape.
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

## Recommendation → Ruling

**Recommended:** Rich. It is the only candidate that is simultaneously
mature, tractable, zero-service, and a *new contract surface* for the
frozen-spec machinery (rendered output rather than routes/DOM). Gunicorn
is the fallback if the CEO prefers process-supervision shape; Click if
the priority is a fast, cheap second data point over seam novelty.

**Ruling (2026-09-01): Rich approved for Phase 0** — pin the exact
source tag/commit, establish a clean baseline, then schedule the live
milestone around the single-run machine constraint.

The milestone #1 feature is not pre-chosen by this note — the spec names
it from the subject's own small, real feature space. **Spec v1 (drafted
2026-09-01, Phase 1 prep): M1 = `Table.add_rows(rows)` +
`Table.from_rows(columns, rows)`** in `rich/table.py` — purely additive,
both thin delegates to the existing `add_row` cell machinery; 12-test
frozen suite with deterministic rendered-output contracts (the new
contract surface this subject was chosen for). Staged in
`scripts/.approved/incoming/` in rich-adoption, tracked copy at
`tasks/v1-spec-draft/`; `refreeze.sh --diff` all preflights green;
tests fail cleanly against the unmodified code (pre-milestone target
state).

## Phase 0 execution record (2026-09-01, D-175)

- Subject pinned: tag `v15.0.0` = commit `6ac483cbea39cab124dfd3483bba70ffafb71050` (MIT, PyPI 15.0.0) at `~/dev/rich-adoption`.
- Clean baseline: **956 passed / 25 skipped / 0 failed** with `poetry.lock` deps (pygments 2.19.2, pytest 7.4.4, markdown-it-py 3.0.0) on Python 3.14.6. Finding: pygments 2.21.0 (latest) fails 8 `tests/test_syntax.py` tests — **the lockfile is the dependency authority** for the legacy baseline.
- Legacy snapshot: `legacy-pin.json` (73 files under `tests/`, sha256 each) — provenance, never an oracle.
- Plane install: **linked** (not copied) at Blueprint `1684e0b` via `link-template.sh` approve-hash flow — linked is the current norm (Vortex/Testchat) and gives the D-168 guard the exact pinned Git object; this run #2 is born on the D-174 broker plane and doubles as the broker's first adoption cycle (first child commit `0127c3bf` carries the full `Swbp-*` trailer set).
- Project files adapted under Rule 3 (`.gate-paths` `build=rich/`, CLAUDE.md, CONVENTIONS.md, tasks/, gitignore plane lines); pre-spec tunnel state recorded (D-173 pattern).
- Child verification green: legacy suite, plane selftests 548/548 (venv needed `pytest-json-report` — env gap, not a plane defect), phase-gate manifest, check-drift in sync.
- **Legacy-suite fate (the D-172 guard decision):** the 956-test upstream suite is NOT carried into the frozen gate — it stays a pinned snapshot (provenance + manual baseline); the spec's own tests are the only gate. Rationale: D-165's carry-in pattern fit Vortex's 27-nodeid product suite (the product's own acceptance tests); a 956-test upstream suite as the per-milestone gate would be slow, dependency-sensitive (the pygments pin), and mostly unrelated to the milestone. Recorded in the child's tasks/ + this note.

## Program shape (what a go commits to)

- **Phase 0 — install (XS). DONE 2026-09-01** (record above; D-175).
- **Phase 1 — first freeze + first milestone (M–L).** Spec DRAFTED
  (v1 = Table bulk construction, 12-test frozen suite, preflights
  green). At run time (Linux dev VM — orchestrate hard-dies on Darwin,
  D-152): advance the plane pin via update-template → `refreeze.sh
  scripts/.approved/incoming` (spec v1, carries `legacy-pin.json` into
  `scripts/.approved/`) → `orchestrate.sh`. Schedules around Vortex's
  runs (single-run machine). The first post-adoption run is also the
  live validation of the D-174 broker on a second child.
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
