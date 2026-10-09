# TESTING.md — Testing Strategy

> Strategy and conventions, not results.
> The frozen suite in `tests/` is TPM-authored and hash-pinned (INV-1) —
> it is not written or edited by any agent, ever. This file describes the
> STYLE the TPM works in when authoring that suite, plus how to run and
> read results.

---

## Who writes the tests

The TPM (the CEO-assigned spec seat, D-139 — web chat, scoped agent, or the
same LLM already on the job) authors the frozen suite alongside
the ERD/contracts, at spec time, **before the implementation exists**
(INV-1, D-31). They enter the repo only via `scripts/refreeze.sh` — which
auto-applies once every mechanical preflight is green (D-121) — and are
hash-pinned in
`scripts/.approved/frozen-manifest`. No agent — coder, EM, or conductor
— may create or modify a file under `tests/`. See `docs/TPM-ROLE.md`
for the top tier's job description and `docs/ESCALATION.md` for how
test-suite errors are corrected (spec delta round-trip, never a direct
edit).

---

## Philosophy

- Test behavior, not implementation
- Tests should read like documentation
- If it's hard to test, the design is wrong — fix the design (revised
  ERD, refreeze) rather than tolerate untestable code
- Coverage target: 80% on business logic, not on route boilerplate — the
  ratchet may drift per project (Rule 3)
- **Parsimony is a spec property.** One test per acceptance criterion is
  the default; a second test earns its place only by exercising a
  different surface (unit vs API vs UI) or a distinct failure class. When
  a unit test and an API test would assert the same fact, one is carrying
  the other — write the one that reads better as documentation.
- **Suite size is a review item at every freeze.** A diff that grows
  `tests/` without a corresponding PRD acceptance-criterion change is a
  smell, and it belongs in the freeze review. The suite is the oracle, but
  it is also collected, parsed, and diffed on every run — weight is debt
  with a hash.

## Test retirement (spec-delta only)

A test that has never failed is not evidence that it is useless — a good
regression test is SUPPOSED to stay green (D-209). Silence alone never makes
a retirement candidate. A frozen test becomes a candidate only on positive
evidence, judged by the TPM:

- **Relevance:** it no longer maps to a current acceptance criterion or
  locked surface (the requirement changed or was removed).
- **Redundancy:** another frozen test checks the same behavior at least as
  strictly.
- **Discrimination:** a mutation pass (`scripts/mutation-pass.sh`) shows it
  kills no mutant that the rest of the suite does not also kill.
- **Cost:** it is slow, flaky, or brittle enough that its upkeep outweighs
  what only it catches.

A candidate leaves through the same `refreeze.sh` delta path as any other
spec change — never by direct edit. This is advisory TPM guidance, not a
mechanical gate. The standing question at every freeze: if a test could not
fail under any plausible regression, it is ceremony, not coverage — and the
way to show that is a mutation pass, not a quiet history.

---

## Test Types (style guidance for the TPM)

Layout mirrors the project's file inventory; every frozen test file must
observe the system only through `contracts.entry_points` + `contracts.routes`
(INV-4, checked by `scripts/check-test-surface.py` at freeze time).

| Type | Typical location | Tool | Style note |
|------|------------------|------|------------|
| Unit | `tests/services/`, `tests/utils/` | pytest | One file per source file; every acceptance criterion in the ERD has at least one test |
| Integration | `tests/integration/` | pytest | For flows that touch DB or external services; externals require a captured probe (D-56) |
| API | `tests/api/` | pytest + httpx (`TestClient`, in-process) | Every locked route in `contracts.routes` gets tests; no real sockets (sandbox has `--network none`) |

---

## Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=src --cov-report=term-missing

# Specific file
pytest tests/services/test_project_service.py

# Specific test
pytest tests/services/test_project_service.py::test_create_project_returns_id

# Verbose
pytest -v

# Stop on first failure
pytest -x

# Template control-plane validation (runs even before src/ exists)
ruff check --isolated --select E4,E7,E9,F scripts/
pytest scripts/selftest/selftest_gates.py -q
pytest scripts/selftest/selftest_plane_snapshot.py -q
pytest scripts/selftest/selftest_mutation_pass.py -q

# Standalone harness form (same checks, no pytest required)
python3 scripts/selftest/selftest_plane_snapshot.py
```

> **Collect vs standalone.** Every selftest module must expose at least one
> pytest-collectable `test_*` entry point, even if its scenarios live behind a
> `main()` harness. A module that only runs under `if __name__ == "__main__"`
> is invisible to CI collection — the D-168 snapshot suite shipped that way and
> a launch-breaking regression passed locally while 47 of 469 suite checks
> failed against real source. Slice-level extraction tests prove the slice;
> only whole-file execution from the real entry point proves the composition.

> **Oracle-strength measurement (D-161).** At freeze cadence—not on every
> run—curate a small TSV of plausible one-line defects and run
> `scripts/mutation-pass.sh --repo <child> --mutants <file> --out <report>`.
> The runner clones the exact child HEAD and never edits its checkout. A
> survivor is evidence that the frozen suite does not discriminate that defect;
> record it for the TPM, but do not fail the build or weaken D-44's live check.

---

## When the full suite runs

Steady-state cadence (D-28, D-75, D-112): each task's mapped frozen tests
run right after that task; the delta's verdict run closes the milestone at
run end — the mapped tests plus every DEPENDENT frozen test (its file
reaches, directly or transitively through the import graph, a module the
milestone created or modified, or sits under a modified conftest.py's
directory, D-188/D-191) (the full frozen suite is an on-demand `--full-suite`
regression check); the freeze itself verifies only the delta (the D-75
red-before-green check, which is confined to the Linux sandbox and halts
if it cannot obtain a readable report). A full-suite run
at freeze time is **catch-up only** — for freezes where `src/` changed
outside the pipeline (the testchat v65 case). A steady-state freeze that
re-runs the whole suite is duplicating the run's own closing gate, not
adding safety.

The dependent set is computed by `validate-plan.py --dependent-ids` from the
plan, the frozen node-ids, and the actual tree. When that selection is
UNCERTAIN — a frozen test file missing from the tree, a plan task file
missing, or an unparseable file in the import graph — the command exits 1
and the verdict block falls back to the full frozen suite (D-191). It never
silently narrows to the mapped union: the silent exclusion of unparseable
inputs is exactly how vortex v43 reached [success] with the full suite red.

Every collected frozen test must finish with an ordinary `passed` outcome.
Skipped, xfailed, xpassed, and xfail-marked passes are red acceptance results
(D-103): pytest's process-level success policy does not override the frozen
suite's role as the behavioral oracle.

---

## Test Database

```bash
# Tests use a separate test database
# Set in .env.test:
DATABASE_URL=postgresql://localhost/myapp_test

# Fixtures handle setup/teardown — never test against production DB
```

---

## Fixtures

```python
# conftest.py at tests/ root
# Standard fixtures available in all tests:

@pytest.fixture
def db_session():
    """Rolls back after each test."""
    ...

@pytest.fixture
def test_user():
    """A standard user for auth tests."""
    ...

@pytest.fixture
def auth_headers(test_user):
    """Authorization headers for API tests."""
    ...
```

---

## What We Don't Test

- FastAPI route boilerplate (the framework is already tested)
- Database migration scripts (tested by running them)
- Third-party library internals

---

## Known Issues / Flaky Tests

The flake ledger — `.pipeline-flakes.json` (D-111), local to each project —
is the machine-readable record of accepted flakes; it is never populated by
hand. `orchestrate.sh` reads it for D-77 triage and the D-111 recurring
threshold. A flaky test belongs in the ledger via the pipeline's own triage
or goes back to the TPM as a spec defect (D-58) — never in a prose table
that nothing reads.

---

## Machine-readable results

Tests produce a JSON report at `.cache/test-report.json` (via `pytest-json-report`).
The report is untrusted input: it is written by the pytest process, which runs
application code inside a sandbox whose `.cache` is writable. The only consumer
is `scripts/test-verdict.py`, a host-side tool that never runs in the sandbox:

- `prepare` — refuses a symlinked `.cache` and unlinks the previous report
  without following links.
- `<runner-status> [selector...]` — opens the report without following
  symlinks (regular file, single link, ≤ 64 MiB), then checks consistency:
  the report's `exitcode` must equal the runner status the host observed;
  summary counts must equal the per-record counts; the reported node IDs must
  cover exactly the frozen `scripts/.approved/test-nodeids` set (or the
  selected subset); every phase must be an ordinary pass. Exit 0 = pass,
  1 = failed acceptance (failing IDs + bounded detail on stdout),
  3 = unavailable or inconsistent evidence. 3 is never a green.
- `copy <dest>` — copies the report to a host-owned destination (the
  escalation bundle) without following symlinks.
- `prepare-redcheck` / `redcheck` — use the same safe cache access for the
  freeze preflight's advisory report. Its marker is written only under
  host-owned `.pipeline-state`, never into the sandbox's writable cache.

(Post-D-53 there is no "orchestrator agent" — orchestrate is a shell script
and consumes the verdict, never the human terminal output.)

The control-plane suite generates reports with the real plugin and passes them
through the production parser (D-110); synthetic reports remain for malformed
and rare outcome shapes. Accepted D-77 flakes are stored by node and successful
spec version in `.pipeline-flakes.json`. The third occurrence by default keeps
the suite red and creates a TPM bundle instead of granting another bypass
(D-111; threshold override: `SWBP_FLAKE_ESCALATION_THRESHOLD`).

The sandbox image is built from a cold cache on packaging changes and weekly,
then inspected for an absent project tree (D-123). This complements the static
Dockerfile/context tests; it does not replace them.

### Remaining limits (in-process pytest)

The verdict is a consistency check, **not** an attestation. Application code
runs inside the same pytest process that writes the report, and `.cache` is
writable from inside the sandbox. A sufficiently hostile in-process actor can,
after `pytest-json-report` has written the honest report at session end,
overwrite `.cache/test-report.json` with a fully consistent forged green
report (all-pass records, matching summary, `exitcode: 0`) and force
`session.exitstatus = 0` so the runner exits 0 — indistinguishable from a
genuine green run. The `exitcode`-equality check defeats the naive forgery
(a forged all-pass report while pytest actually exited non-zero is rejected);
closing the residual requires separating application execution from the
trusted test oracle and its observations. Moving only the JSON writer to the
host or another process does not establish that isolation: an untrusted
pytest process could still send fabricated results. That boundary redesign
is future work, not a claimed guarantee (D-189).

The constrained actors are the tool-free coder's reply and application code
executing inside the sandbox. They do not have write access to the host's
control plane, frozen node IDs, or `.pipeline-state`; the sandbox-writable
cache and all pytest process state remain untrusted. A compromised host,
container runtime, or human with checkout write access is outside this boundary.

**Accepted residuals (security plan, 2026-10-01).** The working threat model is
a *buggy* local model, not a hostile one. Under it, two known gaps are accepted
on purpose rather than fixed:

- the in-process report forgery above (closing it needs the isolation
  redesign, not more consistency checks);
- forged `Swbp-Role:` trailers: the app guard (D-192) reads the role from an
  unsigned commit trailer, so a commit can claim `tpm`. Signature-checked
  roles (`check-provenance.py --gate`) are deferred until an untrusted model
  or an outside contributor appears.

Both are listed so nobody reads the gates as stronger than they are.

### Source destination containment

The plan validator and coder appliers share `scripts/source_paths.py`
(D-190). Task paths must be canonical relative descendants of the configured
build lane: absolute paths, `.`/`..`, empty segments, and symlinked files or
ancestors are refused. The coder checks before calling the model and again
when applying its reply. Reads and writes walk directory descriptors without
following links; writes replace a temporary file atomically, preserving an
existing file's permissions while avoiding writes through hard links.

Control-plane regressions exercise rejected plans, direct edits, create
tasks, late symlink insertion, hard links, and normal nested custom lanes.
These are local filesystem and stubbed-runner checks, not a live VM milestone.

Completion-ledger coverage includes the success-cleanup boundary (D-113): with
runtime `spec_version` gone and newer freezes installed, the exact resolver,
range builder, restore, and reset blocks from `orchestrate.sh` must recover the
prior successful spec, include every intervening delta, restore exact matches,
and return delta-hit tasks to pending. Malformed/noncanonical history and a
missing intervening delta must halt; neither can be treated as empty history.
The same regression leaves a stale runtime version beside an empty task
checkpoint and proves the ledger remains authoritative; reset and edit scope
reuse one affected-task result so a second computation cannot fail open. The
baseline persists across same-spec retries, and both in-process decomposition
revision sites recompute and reapply scope before work continues.

---

## Mocking Policy

- Mock external HTTP calls (use `respx` for httpx)
- Mock email sending
- **Do not mock the database** — use a real test DB with transactions
- **Do not mock your own services** — if you need to mock it, split the dependency

## Existing-suite regression evidence (D-212)

An adopted project (D-165) keeps its pre-existing tests as a hash-pinned
snapshot, `legacy-pin.json` (at `scripts/.approved/` or the project root;
optional `known_failing` nodeid list). Those tests are not an oracle and
never gate acceptance — they were written with the implementation in view.
But a test of existing behavior that turns red is real evidence, so when a
milestone succeeds `orchestrate.sh` runs the pinned test files once in the
sandbox (`scripts/legacy-regression.py`) and records:

- the result in `.measurement/legacy-v<N>.json` — counts, `regressions`
  (failing tests not in `known_failing`), pinned files whose bytes changed
  since adoption, or why the suite could not run;
- one line in the milestone's `## Results` entry in `tasks/CURRENT.md`
  (committed with `[success]`), naming up to five regressions;
- the regression count in the `legacy_regressions` metrics column.

It is report-only: a regression never fails or blocks the milestone. A
suite that could not run says `NOT RUN`, never "no regressions". Projects
without a pin skip it entirely. Rich's 956-test suite takes about 4 seconds.

## End-to-end simulation and gate teeth (D-208)

- `scripts/selftest/e2e-sim.sh` runs one full milestone through the real
  pipeline in the dev VM with scripted models (`e2e_fake_llm.py`) and checks
  that the gates fire, the catch ledger comes home, and a coder spec report
  reaches the EM. Run it after changing orchestrate, refreeze, vm-sync or the
  gates: it needs the VM running and takes a few minutes. It proves the
  plumbing, not model quality.
- `docs/mutation/<gate>.tsv` holds the curated mutants that prove each
  run-time gate's tests catch a planted defect. Re-run one with
  `scripts/mutation-pass.sh --repo . --mutants docs/mutation/<gate>.tsv --suite "<pytest command>"`.

