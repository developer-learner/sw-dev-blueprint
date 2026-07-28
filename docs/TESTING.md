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
(INV-1, D-31). They enter the repo only via `scripts/refreeze.sh` under
a human-approved diff, and are hash-pinned in
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

Steady-state cadence (D-28, D-75): each task's mapped frozen tests run
right after that task; ONE full-suite run closes the milestone at run
end; the freeze itself verifies only the delta (the D-75
red-before-green check, which falls back to the host interpreter when
the sandbox is unreachable and reports which path ran). A full-suite run
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

| Test | Issue | Workaround |
|------|-------|------------|
| [test name] | [why it's flaky] | [current workaround] |

---

## Machine-readable results

Tests produce a JSON report at `.cache/test-report.json` (via `pytest-json-report`).
`scripts/orchestrate.sh` reads this file to determine pass/fail and extract failing
test IDs + assertion messages — the shell parses the JSON, never the human
terminal output. (Post-D-53 there is no "orchestrator agent" — orchestrate is
a shell script and consumes the report directly.)

---

## Mocking Policy

- Mock external HTTP calls (use `respx` for httpx)
- Mock email sending
- **Do not mock the database** — use a real test DB with transactions
- **Do not mock your own services** — if you need to mock it, split the dependency
