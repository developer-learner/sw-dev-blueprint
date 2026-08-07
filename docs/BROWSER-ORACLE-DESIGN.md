# Handoff: Browser Oracle — the frozen suite learns to see the frontend (2026-07-07)

> Template milestone spec. Status: **spike PASSED (2026-07-07) — build can
> proceed.** Validation vehicle: testchat M7 (see Acceptance). Companion
> fixes already landed: D-57 (mechanized regression bucket), SMOKE_MAX_TIME,
> MAX_PLAN_REVISIONS=2, refreeze D-56 visibility.
>
> **Spike results (constraint 5 discharged):** arm64 chromium + Playwright
> ran green inside the real sandbox contract (repo RO, `--network none`,
> `--cap-drop=ALL`, no-new-privileges, keep-id, tmpfs HOME) on first
> attempt, no workarounds. Warm test 0.68s including uvicorn + browser
> launch. Measured image delta: **+1.2 GB** (1.92 GB vs 717 MB base —
> `playwright install --with-deps chromium` alone is 1.35 GB), not the
> ~400–500 MB constraint 4 estimated. Accepted; if it ever matters,
> `playwright install --only-shell` plus a hand-picked dep list (instead of
> `--with-deps`, which pulls xvfb/mesa/fonts/X11 a headless run may not
> need) would reclaim a chunk.

## Motivation (evidence, not theory)

Two consecutive testchat milestones "succeeded" green and were actually
finished by hand, with identical anatomy:

- **M5:** 58/58 frozen tests green; app broken (spec imagined the LM Studio
  API shape). Fixed by D-56 captures — spec-vs-world, TPM tier.
- **M6:** 60/60 green; app broken. Committed `index.html` at `[success]`
  **discarded think-events entirely** (`replyText += ''`) — silently
  regressing M5's think-streaming — and implemented the model lock as one
  global flag, failing AC-23 (per-thread lock). Both invisible to pytest:
  the defects live in browser-executed JS, and the milestone's single task
  carried only 2 mapped tests (static-serving checks) against 58 regression
  tests. The oracle had near-zero power over the milestone's actual content.

The consequence chain (CEO's own diagnosis, 2026-07-07): the frozen-test
oracle is weaker than the goal → the real acceptance oracle is the human,
post-hoc → hand-fixes land outside the pipeline → nothing defends them →
the next milestone's full-file rewrite regresses them (the think-toggle has
now broken twice). **Tracked metric: hand-fix commits after `[success]`**
(M5: 4 + a debug session; M6: 2 dirty src files). This milestone's goal is
to drive that metric to zero by making frontend ACs mechanically checkable.

## Core idea

The TPM authors browser-level tests (Playwright for Python) as ordinary
members of the frozen suite. The PRD's acceptance criteria are already
written in Playwright's vocabulary ("WHEN the user clicks a thread, THE
SYSTEM SHALL display that thread's history") — today they are hand-executed
by the CEO in the demo; after this milestone they are also executed by the
pipeline, per task and per run, forever. A frontend regression then fails
*inside* the loop, where the escalation ladder can route it, instead of at
the demo, where the only path is a hand-fix.

INV-1 is untouched: the tests still derive from the spec, written before
the implementation, by a tier that never sees it.

## Architecture

```
Sandbox container (unchanged contract: repo RO, lanes RW, --network none)
├─ chromium + playwright-python  — baked into the image at BUILD time
│    (network exists at build; content-hash rebuild D-50 picks up the
│     Containerfile/requirements change automatically)
├─ uvicorn app under test        — started by a pytest fixture, loopback only
└─ pytest                        — one suite, backend + UI node-ids alike
```

- UI tests are plain pytest node-ids. Refreeze collection, `test-nodeids`,
  `validate-plan.py` mapping, the D-57 regression split, and the final
  full-suite verdict all apply **unchanged**. No second test framework, no
  second runner, no new gate scripts in the run loop.
- `--network none` holds: app and browser share the container; the fixture
  binds loopback. Nothing reaches out; generated code still has no
  exfiltration path.
- Backend externals inside UI tests are mocked **from D-56 captures**, same
  law as everywhere else.

## Design constraints (decided — reopen only with evidence)

1. **The locked surface extends to the DOM (INV-4).** `contracts.json`
   gains a `ui` array: locked selectors, `data-testid` values only, each
   `{id, testid, description}`. `check-test-surface.py` learns: a test file
   that imports playwright may locate elements only via locked testids
   (`get_by_test_id` / `[data-testid=...]` literals) — arbitrary CSS/XPath
   selection is rejected at freeze time. Same principle as routes/entry
   points: tests observe only what the spec locks, so the coder is free to
   restructure everything else. The testids also become part of the coder's
   brief material (they live in contracts, which the coder already gets).
2. **Determinism is TPM law, mechanically assisted.** TPM-ROLE.md addendum:
   rely on Playwright auto-waiting; no `sleep`/timeout-tuned assertions; no
   animation-dependent checks; fixed viewport. Enforcement where cheap:
   refreeze grep-rejects `time.sleep` and `wait_for_timeout` in staged UI
   tests. **Flake policy: zero retries** — a flaky frozen test is a spec
   defect and goes back to the TPM like any other; retry-on-flake would
   quietly convert the oracle into a suggestion.
3. **The CEO demo script and the UI test set are one artifact.** Every AC
   describing a user-visible behavior must map to at least one frozen UI
   node-id, or carry an explicit `manual-only:` waiver in the PRD with a
   reason. The CEO demo remains (D-44 — built-right vs built-as-specified),
   but it stops being the only oracle for the frontend.
4. **Image weight is accepted.** Chromium adds roughly 400–500 MB to the
   sandbox image, once, hash-tagged like today. Do not add a second
   "light" image variant — two images is drift surface.
5. **arm64 reality check comes first.** The Lima VM is aarch64; Playwright
   ships linux-arm64 chromium builds. Constraint-1 style: before any
   template change, prove `sandbox-run.sh -- pytest <trivial playwright
   test>` green inside the VM. If arm64 chromium fails in the container,
   stop and report — do not fall back to running the browser outside the
   sandbox (that re-opens the exact hole this milestone closes).
6. **Time budget:** UI tests are slower (~1–5 s each). The per-task loop
   already runs only mapped tests; keep UI node-ids mapped to the tasks
   that own their behavior so the cost lands where the work is. If a full
   suite crosses ~5 min, that is a TPM sizing signal (D-46), not a reason
   to skip tests.

## What NOT to change

- **D-53:** no harness, no tools for EM/coder. The browser runs in the
  *test* path, not the model path.
- **One task = one file.** If frontend files grow past comfortable
  full-file regeneration (M6: ~600 lines, 8.5 min per coder call), the fix
  is the TPM splitting the frontend into more files in the ERD inventory
  (index.html + app.js + style.css) — an ERD choice that needs no template
  change — never diff-based coder output (evaluated 2026-07-07, rejected:
  trades a speed problem for a correctness problem on local non-thinking
  models).
- **refreeze flow:** UI tests enter like every other frozen artifact —
  staged, diffed, auto-applied on green preflights (D-121), hash-pinned.

## Acceptance (this template milestone is done when)

1. **Spike green:** a trivial FastAPI page + one Playwright test runs green
   via `sandbox-run.sh` inside the VM, `--network none`, repo RO.
   ✅ DONE 2026-07-07 — see spike results in the header.
2. **Surface gate:** `check-test-surface.py` rejects a staged UI test using
   a raw CSS selector; accepts the same test via a locked testid.
   Selftests cover both directions (same pattern as the route selftests).
3. **Determinism gate:** refreeze rejects staged UI tests containing
   `time.sleep` / `wait_for_timeout`.
4. **Docs:** TPM-ROLE.md authoring rules; contracts.schema.json `ui` entry;
   D-58 logged (the decision entry for this design).
5. **Validation vehicle — testchat M7:** first freeze retrofits UI tests
   for the M5/M6 ACs that broke (think-toggle rendering, per-thread model
   lock, thread switching). Proof criterion: those tests must **fail**
   against the committed `9bfc21a` tree and **pass** after the hand-fixes —
   demonstrating the oracle now sees exactly what the CEO saw at the demo.
   Then M7 proper builds a real feature through the pipeline with the
   browser oracle live, and the hand-fix count after `[success]` is the
   metric that judges the milestone.

## Rough size

Medium-large: Containerfile + requirements (small), check-test-surface
extension + selftests (the real work), TPM-ROLE/schema/docs (small),
spike + M7 validation (process). No orchestrate.sh changes expected.
