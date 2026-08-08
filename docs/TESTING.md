# TESTING.md — Testing Strategy

> Strategy and conventions, not results.
> The frozen suite in `tests/` is TPM-authored and hash-pinned (INV-1) —
> it is not written or edited by any agent, ever. This file describes the
> STYLE the TPM works in when authoring that suite, plus how to run and
> read results.

---

## Who writes the tests

The TPM (frontier LLM in a web chat) authors the frozen suite alongside
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

A frozen test that has not failed for five consecutive milestones, or that
no longer maps to a current acceptance criterion or locked surface, is a
retirement candidate: the TPM flags it at the next refreeze, and it leaves
through the same `refreeze.sh` delta path as any other spec change — never
by direct edit. This is advisory TPM guidance, not a mechanical gate: the
per-node failure history that would mechanize it is not yet tracked, and a
check with no consumer is decoration (D-85). The standing question at every
freeze: if a test could not fail under any plausible regression, it is
ceremony, not coverage.

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
```

---

## When the full suite runs

Steady-state cadence (D-28, D-75, D-112): each task's mapped frozen tests
run right after that task; the delta's mapped verdict run closes the
milestone at run end (the full frozen suite is an on-demand `--full-suite`
regression check); the freeze itself verifies only the delta (the D-75
red-before-green check, which is confined to the Linux sandbox and halts
if it cannot obtain a readable report). A full-suite run
at freeze time is **catch-up only** — for freezes where `src/` changed
outside the pipeline (the testchat v65 case). A steady-state freeze that
re-runs the whole suite is duplicating the run's own closing gate, not
adding safety.

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
`scripts/orchestrate.sh` reads this file to determine pass/fail and extract failing
test IDs + assertion messages — the shell parses the JSON, never the human
terminal output. (Post-D-53 there is no "orchestrator agent" — orchestrate is
a shell script and consumes the report directly.)

The control-plane suite generates reports with the real plugin and passes them
through the production parser (D-110); synthetic reports remain for malformed
and rare outcome shapes. Accepted D-77 flakes are stored by node and successful
spec version in `.pipeline-flakes.json`. The third occurrence by default keeps
the suite red and creates a TPM bundle instead of granting another bypass
(D-111; threshold override: `SWBP_FLAKE_ESCALATION_THRESHOLD`).

The sandbox image is built from a cold cache on packaging changes and weekly,
then inspected for an absent project tree (D-112). This complements the static
Dockerfile/context tests; it does not replace them.

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
