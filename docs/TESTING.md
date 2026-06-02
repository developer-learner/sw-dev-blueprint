# TESTING.md — Testing Strategy

> Strategy and conventions, not results.
> CI handles pass/fail tracking. This file tells the LLM how we test.

---

## Philosophy

- Test behavior, not implementation
- Tests should read like documentation
- If it's hard to test, the design is wrong — fix the design
- Coverage target: 80% on business logic (services/), not on route boilerplate

---

## Test Types

| Type | Location | Tool | When to write |
|------|----------|------|---------------|
| Unit | `tests/services/`, `tests/utils/` | pytest | Always — alongside new functions |
| Integration | `tests/integration/` | pytest | For flows that touch DB or external services |
| API | `tests/api/` | pytest + httpx | For every route |

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
```

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

## Mocking Policy

- Mock external HTTP calls (use `respx` for httpx)
- Mock email sending
- **Do not mock the database** — use a real test DB with transactions
- **Do not mock your own services** — if you need to mock it, split the dependency
