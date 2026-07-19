# ARCHITECTURE.md — System Design

> Living document. Update when structure changes.
> LLMs read this to understand how the system fits together.

---

## System Overview

[One paragraph describing the overall system — what it does, how it's structured at a high level.]

---

## Data Models

> Define every entity, its fields, and relationships.
> Keep this updated — the LLM uses this to avoid inventing schema.

### [ModelName]

| Field | Type | Notes |
|-------|------|-------|
| id | int | primary key, auto-increment |
| created_at | datetime | set on insert |
| updated_at | datetime | set on update |

**Relationships:**
- has many [OtherModel]
- belongs to [AnotherModel]

---

## API Structure

```
GET    /api/v1/[resource]           list
POST   /api/v1/[resource]           create
GET    /api/v1/[resource]/:id       get one
PUT    /api/v1/[resource]/:id       update
DELETE /api/v1/[resource]/:id       delete
```

---

## Key Flows

> Describe the important user journeys as numbered steps.
> These prevent the LLM from misunderstanding how pieces connect.

### [Flow Name]

1. User does X
2. System checks Y
3. If Y passes → Z happens
4. Response returned

---

## External Services

| Service | Purpose | Notes |
|---------|---------|-------|
| [Service] | [What it does] | [Auth method, rate limits, etc.] |

---

## Infrastructure

```
[Environment]
├── App server:    [e.g. Railway, single instance]
├── Database:      [e.g. Postgres 15, managed]
├── Cache:         [e.g. Redis, optional]
├── File storage:  [e.g. S3 / Cloudflare R2]
└── CDN:           [e.g. Cloudflare]
```

---

## Known Constraints

> Things the LLM should know to avoid bad suggestions.

- [e.g. "Database is read-heavy — optimize for reads over writes"]
- [e.g. "No background job queue yet — everything is synchronous"]
- [e.g. "Single-tenant for now — no multi-tenancy logic needed"]

---

## Pipeline Decisions Index (template)

> **Not for child projects to edit.** This section indexes the template's own
> pipeline decisions — see `docs/DECISIONS.md` for the full entries with
> reasons, alternatives, and "do not suggest." INV-3 (the `architect`-phase
> traceability gate in `scripts/phase-gate.sh`) requires every
> non-documentation-only D-entry to appear here.
>
> If your child project has never touched the pipeline, you can leave this
> section alone. The sections *above* this line are the template skeleton
> for describing YOUR project's architecture.

### Capability ladder & tiering

- **D-05**: Code-driven orchestration loop (the shell owns procedure)
- **D-07**: Four-role PRD→Plan→Build→Test pipeline
- **D-11**: Agent permission model, no catch-all deny
- **D-12**: Local model tier chosen for coder/test at that time
- **D-14**: Context-window ceiling measurement and fix
- **D-16**: Local coder model pinned as the default
- **D-18**: 32K context as pinned default for the local model
- **D-27**: Capability ladder — TPM (frontier chat) / EM (mid-tier) / coder (local); test-runner agent deleted
- **D-40**: OpenCode Build agent as conductor; em/coder become subagents
- **D-41**: Model identity leaves the repo — the blueprint is model-agnostic
- **D-43**: Flat hierarchy under the shell; `em`/`coder` denied the task tool
- **D-46**: Milestone sizing is TPM judgment against a fixed balance; no formula
- **D-48**: Conductor denied the task tool — no agent in this repo can spawn another
- **D-52**: em/coder back to primary mode; no silent agent/model substitution
- **D-53**: Retire the agent harness — EM/coder called over bare HTTP, shell writes every artifact
- **D-55**: Linux dev VM boundary; D-53 partial reversal for cross-boundary model access
- **D-60**: Task sizing governed by the coder's measured bare-completion capability
- **D-66**: The EM seat is precision-transcription work; dense models preferred

### Sandbox & untrusted-code execution

- **D-08**: AC9 compliance — mandatory sandbox + freeze-trap closure
- **D-09**: Sandbox wiring in the orchestrator
- **D-10**: macOS compatibility fixes for sandbox scripts
- **D-13**: Pipeline robustness — container deps, PYTHONPATH, gate recovery
- **D-17**: Template deps baked into `Containerfile`
- **D-30**: Sandbox flip — read-only repo + per-lane rw mounts; pre-commit hook for the human path
- **D-50**: Stack drift killed mechanically — content-hashed sandbox image, podman preflight
- **D-62**: LM Studio drift probe in orchestrate.sh pre-flight

### Frozen spec & TPM shuttle

- **D-06**: EARS format for acceptance criteria
- **D-26**: Schema-validated artifact handoffs; plan.json validation gate
- **D-31**: Versioned re-freeze — frozen spec changes only via human-approved delta
- **D-32**: INV-4 — test-visible surface ⊆ ERD-locked surface
- **D-38**: TPM shuttle scripts (`tpm-pack.sh`/`tpm-unpack.sh`)
- **D-39**: Agent-mode TPM — scoped repo access via `tpm-agent.sh`
- **D-42**: Refreeze approval without a terminal — `--diff`/`--approve <hash>`
- **D-49**: `tpm-pack.sh` defaults to stdout; conductor relays the bundle verbatim
- **D-51**: Initial freeze collects node-ids statically
- **D-54**: Spec-drift policy — test surface is binding; ERD prose is advisory
- **D-56**: External interfaces enter the spec only as captured reality
- **D-58**: Browser oracle — locked surface extends to the DOM (`contracts.ui`)
- **D-61**: Template updates gain hash-bound approval
- **D-63**: Ratify milestones — catching up the spec after outside-band work
- **D-64**: Browser-test mapping enforced mechanically in `validate-plan.py`
- **D-67**: `refreeze` lints staged tests
- **D-75**: Red-before-green — a refreeze runs the delta's tests pre-implementation, warns on early passes

### Escalation ladder & failure paths

- **D-15**: INV-2 gate — halt, not cleanup
- **D-22**: INV-2 gate — halt, not auto-clean (reaffirmed)
- **D-24**: File-based pipeline state persistence
- **D-28**: Oracle projection — EM schedules frozen TPM tests, authors nothing
- **D-29**: Escalation ladder with batched, filesystem-only TPM round-trips
- **D-44**: The CEO gate is outcome acceptance, not diff review
- **D-57**: Carried-forward regression bucket computed by the shell
- **D-65**: `no_edit_files` — spec-declared no-op tasks never reach the coder
- **D-68**: Silent error swallows are a task failure; failure paths are spec surface
- **D-69**: Run wall-clock budget + phase-timing log
- **D-70**: The escalation ladder is armed — `MAX_TASK_STRIKES` defaults to 2
- **D-71**: EM diagnosis hardened — shrunken reply surface + one validator-fed retry
- **D-73**: Failure detail from the test report reaches retry briefs and consults
- **D-74**: Coder output linted per task, fail-closed, before acceptance

### Gates, lanes & governance

- **D-19**: `docs/.pm-last-review` — PM-owned ref marker
- **D-25**: INV-3 — decision-traceability gate (this section satisfies it)
- **D-33**: Fleet drift — birth-SHA identity, ownership-split manifests
- **D-34**: Template propagation — `update-template.sh` applies the refreeze pattern to the control plane
- **D-36**: Gate-script self-tests (`scripts/selftest/`)
- **D-37**: `build_extra`/`test_extra` exact-file lane exceptions in `.gate-paths`
- **D-45**: Conductor bash allowlist — pipeline scripts + read-only git; everything else asks
- **D-47**: External TPM review of D-40..D-46 adjudicated
- **D-59**: The coder edits existing files through anchored blocks
- **D-76**: `postmortems/` incident archive — unauthoritative, human-authored, zero pipeline dependency
