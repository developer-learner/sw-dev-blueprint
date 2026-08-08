# examples/minimal-spec — a complete frozen spec, linkbox-sized

This is a **real, working example** of the four artifacts the TPM (your
frontier chat) authors before the pipeline builds anything. This exact spec
was frozen and built end-to-end by the pipeline on 2026-07-16: two tasks,
two source files, 21 frozen tests, full suite green on the second run, and
the result was a working personal bookmarks API.

Read it to answer the question the docs alone can't: *what do the TPM's
artifacts actually look like?*

## The four artifacts

| File | What it is | Who reads it |
|------|-----------|--------------|
| `PRD.md` | Product intent in plain language — the problem, the scope, what's deliberately out | The human + the TPM (for later milestones) |
| `ERD.md` | The engineering design: file inventory in DAG order, exact signatures, table DDL, route behaviors | The EM derives task briefs from this — precision here is what makes a local model succeed |
| `contracts.json` | The machine-readable locked surface: file inventory, importable entry points, HTTP routes, error shapes (schema: `scripts/schemas/contracts.schema.json`) | `validate-plan.py` gates the EM's plan against it; `check-test-surface.py` gates the tests (INV-4) |
| `tests/*_tests.py` | The frozen suite — written **before the implementation exists**, by a tier that never sees it (INV-1) | The shell runs it in the sandbox; the delta-mapped verdict green = done (D-112) |

> The example test files are named `storage_tests.py` / `api_tests.py`
> (not `test_*.py`) so a bare `pytest` run in a child never collects them —
> the same convention `scripts/selftest/selftest_gates.py` uses. You rename
> them to `test_*.py` when staging (step below); frozen suites in real
> projects use normal pytest names.

## How you'd use it

From a bootstrapped child project (see BLUEPRINT.md → Bootstrap Sequence):

```bash
mkdir -p scripts/.approved/incoming/tests
cp examples/minimal-spec/{PRD.md,ERD.md,contracts.json} scripts/.approved/incoming/
cp examples/minimal-spec/tests/storage_tests.py scripts/.approved/incoming/tests/test_storage.py
cp examples/minimal-spec/tests/api_tests.py     scripts/.approved/incoming/tests/test_api.py
scripts/refreeze.sh scripts/.approved/incoming    # auto-applies on green preflights → frozen v1 (D-121)
scripts/orchestrate.sh                            # (inside the Linux VM) builds it
```

The pipeline will: have the EM decompose the ERD into a validated 2-task
plan, call the coder once per file, run the mapped frozen tests in the
sandbox after each task, and finish when all 21 tests pass.

## What to notice

- **The ERD prescribes exact shapes** — signatures, the table DDL, the JSON
  record layout, even "read the DB path per call, never cache it at import
  time." A ~27B local coder succeeds when the design decisions are already
  made; it fails when asked to make them (Rule 8, D-60).
- **Tests observe only the locked surface** — every import in the tests
  appears in `contracts.entry_points`, every route hit appears in
  `contracts.routes` (INV-4).
- **One file per task, one task per file** — the `files` array has two
  entries; the EM's plan must have exactly two tasks (structural atomicity,
  D-26).
- **No model names anywhere** — which LLM plays which seat is your
  `~/.config/sw-dev-blueprint/models.env`, never the spec (D-41).
