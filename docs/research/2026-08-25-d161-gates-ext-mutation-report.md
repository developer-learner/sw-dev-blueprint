# D-161 mutation-pass — 2b-ext (the remaining 34 gates)

- source: `sw-dev-blueprint@2cd9c72` (isolated exact-HEAD clone, `--no-local --no-checkout`)
- baseline: green (full suite)
- suite (oracle): `python3 -m pytest scripts/selftest/selftest_*.py -q`
- mutants: 68 authored (2 per gate × 34 gates) — see `2026-08-25-d161-gates-ext-mutants.tsv`
- raw per-mutant results: `2026-08-25-d161-gates-ext-results.tsv`
- enforcement: **report-only.** Survivors are evidence for oracle improvement, never a build gate (D-161).

## Bottom line

**68 mutants: 45 killed, 23 survived.**

The 3 core gates from 2b were 6/6 killed — strong oracles, because they got the 2a fixture focus. The 34 ext gates survive at a much higher rate: **their selftest coverage is thinner than the audit's "TEETH" label suggested.** The 23 survivors are a map of exactly where the oracle is weak.

Per-gate outcome:

| outcome | gates | count |
|---|---|---|
| **proven** — both mutants killed | apply-edit-blocks, check-prd-additive, check-spec-delta, check-swallowed-errors, context-budget, contracts-delta, contracts-merge, doc-consistency, manifest-drift-guard, orchestrate, phase-gate, refreeze, regen-manifest, spec-artifacts, standing-summary, tpm-pack, tpm-unpack, tpm-view, validate-plan | 19 |
| **partial** — one killed, one survived | bootstrap, extract-test-functions, link-template, metrics-report, mutation-pass, refreeze-delta, teardown | 7 |
| **unproven** — both survived | check-drift, feature-summary, llm-call, new-project, sandbox-run, status, tpm-agent, update-template | 8 |

A "partial" gate has **demonstrated real teeth** (it caught one mutation); the survivor is an oracle gap to close, not proof the gate is dead. An "unproven" gate's oracle caught neither mutation — its teeth are unverified.

## The 23 survivors (oracle-gap map)

Each survivor is a real mutation the suite failed to catch. The "gap type" is my reading of the selftest coverage, not a measured fact — it names what to add.

**Unexercised branch** — the mutated code path is never reached in the selftest fixture (11):
- `new-project.sh` — thinking-model pre-flight guard removed (Hard Rule 1 die → pass)
- `check-drift.sh` — sync condition inverted (matching flagged, divergent reported IN_SYNC)
- `sandbox-run.sh` — control-plane write blocklist narrowed (.git/.githooks become agent-writable)
- `sandbox-run.sh` — escape check inverted (paths outside repo root accepted as writable)
- `link-template.sh` — approval-hash check inverted (correct rejected, mismatch accepted)
- `bootstrap.sh` — dubious-ownership fix trusts the wrong path (git still refuses)
- `llm-call.sh` — thinking-model detection inverted (reasoning-only pass, normal die)
- `llm-call.sh` — seat-mismatch check inverted (correct model fails, wrong passes)
- `tpm-agent.sh` — view-mode branch inverted (--view launches plain agent, default launches view)
- `tpm-agent.sh` — agent launched with a non-existent settings file
- `update-template.sh` — approval-hash check inverted (correct rejected, mismatch applies diff)

**Fixture no-op** — the fixture's stubs make the path a no-op, so the change is unobservable (2):
- `status.sh` — podman section condition inverted (stubs make podman a no-op)
- `teardown.sh` — teardown starts the VM instead of stopping it (limactl stubbed)

**Unasserted output / exit** — the code runs, but the specific output or exit code isn't asserted (10):
- `new-project.sh` — bootstrap pre-check message changed
- `extract-test-functions.py` — leading-comment inclusion inverted
- `check-drift.sh` — BEHIND now fails (rc=1) instead of exiting 2
- `mutation-pass.sh` — baseline loses PYTHONDONTWRITEBYTECODE=1 (stale-.pyc vacuity returns)
- `status.sh` — LLM port probe moved off the documented default port
- `feature-summary.py` — archive time window inverted (old EM calls counted, recent skipped)
- `feature-summary.py` — outcome parsing inverted
- `metrics-report.py` — waste counting inverted (successes counted as waste, failures not)
- `update-template.sh` — no-change detection inverted ("nothing to review" when changes exist)
- `refreeze_delta.py` — D-140 notice condition inverted (behavioral freezes get the no-work notice)

## Scope note

`check-test-surface.py` was **not** swept. The audit's pass-2 omitted it (and `completion-ledger.py`) from the TEETH classification — the audit's own arithmetic correction (line 446) notes the TEETH list is 35, not the 38 the header claims. `check-test-surface.py` is a real hard gate with a dedicated selftest section (selftest_gates.py:1416), so its teeth are fixture-verified but **not mutation-proven**. It is a known gap for a follow-up, not a silent omission. `completion-ledger.py` is a tool (n/a for tiering), not a gate.

## Artifact note

The raw results report one "authoring error": it is the mutants-TSV **header line** (`file / find / replacement / reason`) being counted as a mutant, because the header did not start with `#`. It is not a real mutant. The header is now commented so future runs skip it. Real count: 68 mutants, 45 killed, 23 survived.

## How this feeds tiering (D-170)

The mutation status now populates the gate inventory's teeth column, which `gate-tiering.py` combines with the catch ledger and per-gate cost:
- **proven / partial** → demonstrated teeth → T1 (hard) / T2 (soft)
- **unproven** + zero in-the-wild catches → the prime **T3 review** candidates (check-drift, feature-summary, llm-call, new-project, sandbox-run, status, tpm-agent, update-template)

T3 names a gate for human examination; it is not a retirement decision. Silence alone cannot distinguish dead from dormant (D-170).
