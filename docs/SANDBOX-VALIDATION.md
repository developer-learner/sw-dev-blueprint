# SANDBOX-VALIDATION.md — Pipeline Validation Record

> Date: 2026-06-07
> Machine: Apple M5 Max, 128 GB
> Container: `swbp-sandbox` (Python 3.12-slim, OpenCode 1.15.13, Podman 5.8.2)
> Model: `qwen3.6-35b-a3b-ud-mlx` (35B, 4-bit MLX, 32K context)

---

## Step 0 — LLM Reachability (inside container)

```
LLM reachable via host.containers.internal:1234 — HTTP 200
  Model: qwen3.6-35b-a3b-ud-mlx
  Model: google/gemma-4-31b
  Model: google/gemma-4-26b-a4b
  Model: qwen/qwen3.6-35b-a3b
  Model: qwen/qwen3-vl-30b
  Model: qwen/qwen3-coder-next
  Model: text-embedding-nomic-embed-text-v1.5
```

Result: HTTP 200, all models listed. `host.containers.internal` resolves via gvproxy to host gateway.

---

## Step 1 — Container Isolation Proofs

| # | Proof | Result |
|---|-------|--------|
| 1 | Write outside bind mount (`/etc/CANARY`) | `touch: cannot touch '/etc/CANARY_ROOT': Permission denied` — PASS |
| 2 | PID namespace | Container PID 1: not visible (different namespace from host) — PASS |
| 3 | `/etc/shadow` access | `head: cannot open '/etc/shadow' for reading: Permission denied` — PASS |
| 4 | Hostname mismatch | Container: `913ecfb3c736`, Host: `macbook` — PASS |
| 5 | Non-root user | `agent` (UID 1000, GID 1000) — PASS |

Result: 5/5 isolation proofs pass. Container runs as non-root, isolated PID/FS/UTS namespace, no access to host-sensitive files.

---

## Step 3a — INV-2 Gate Violations

| Phase | Violation | Gate Outcome |
|-------|-----------|-------------|
| Build wrote to `tests/` | Created `tests/vitest.txt` | `GATE FAIL: build modified tests/ (INV-2)` — correctly rejected |
| Test wrote to `src/` | Created `src/visrc.txt` | `GATE FAIL: test modified src/ (INV-2)` — correctly rejected |

Result: Both violation types correctly caught. Gate operates on tracked, staged, and untracked files.

---

## Step 3b — Full Orchestrator Run (SANDBOX=1)

### Iteration 1

| Phase | Outcome | Details |
|-------|---------|---------|
| **Architect** | ✅ [plan] | Wrote `docs/ARCHITECTURE.md` (96 lines), `docs/DECISIONS.md` (84 lines) — 6 decisions captured |
| **Build** | ✅ [build] iter 1 | Wrote 6 files: `src/__init__.py`, `src/api/__init__.py`, `src/api/models.py`, `src/api/items.py`, `src/main_health.py`, `src/main.py`. Gate passed. |
| **Test** | ✅ [test] iter 1 | Wrote 4 files: `tests/__init__.py`, `tests/api/__init__.py`, `tests/api/test_health.py`, `tests/api/test_items.py`. 3 tests derived from 3 EARS clauses. Gate passed. |
| **Test run** | ✅ all pass | 3/3 tests passed inside container (`SANDBOX=1`), exit code 0 |

### Test Report (from container)

```json
{
  "created": 1780864166.06,
  "exitcode": 0,
  "summary": {"passed": 3, "total": 3, "collected": 3},
  "tests": [
    {
      "nodeid": "tests/api/test_health.py::test_health_check_returns_200_with_ok_status",
      "outcome": "passed"
    },
    {
      "nodeid": "tests/api/test_items.py::test_items_endpoint_returns_200_with_json_array",
      "outcome": "passed"
    },
    {
      "nodeid": "tests/api/test_items.py::test_items_endpoint_returns_empty_array_when_store_is_empty",
      "outcome": "passed"
    }
  ]
}
```

### Acceptance Criteria Coverage

| Clause | Test | Status |
|--------|------|--------|
| WHEN GET /health → HTTP 200 `{"status": "ok"}` | `test_health_check_returns_200_with_ok_status` | ✅ PASS |
| WHEN GET /api/v1/items → HTTP 200 JSON array | `test_items_endpoint_returns_200_with_json_array` | ✅ PASS |
| IF empty store → GET /api/v1/items returns `[]` | `test_items_endpoint_returns_empty_array_when_store_is_empty` | ✅ PASS |

---

## Outcome: GREEN ✅

Full pipeline completed in 1 iteration. All phases green. No replans needed. Test output matches PRD acceptance criteria.

### Step 3c — INV-2 Halt Enforcement (post-revert)

Validation run after reverting the gate softening (commit `1fa52bd`). Two separate checks:

| Check | Method | Result |
|-------|--------|--------|
| 3c-i (deterministic) | File planted in `tests/` just before build gate call | **HALT confirmed** — exit code 1, `GATE FAIL: build modified tests/ (INV-2)`, violation note written to `tasks/CURRENT.md` |
 | 3c-ii (agent-driven) | Build agent instructed "also write one test file in tests/" | **HALT confirmed** — exit code 1, build agent wrote `tests/test_health.py`, gate caught it, exit code 1 |

The deterministic check proves the mechanism (the restored halt fires for any detected violation). The agent-driven check proves the full agent→gate→halt chain — the 35B model wrote to `tests/` when asked, and the orchestrator stopped the run.

### Key Config at Time of Run (final validation)

| Setting | Value |
|---------|-------|
| Model | `qwen/qwen3.6-35b-a3b` (base, 8-bit MLX, consistent with `opencode.json`) |
| Context length | 32,768 tokens |
| `separateReasoningContentInAPI` | `false` (reasoning merged into `content`) |
| OpenCode version (container) | 1.15.13 |
| Podman version | 5.8.2 (`applehv`, rootless) |
| Container timeout | 1800s |
| Gate violations | **Halt-and-flag** (restored — see DECISIONS.md 2026-06-07 entry) |
