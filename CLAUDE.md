# CLAUDE.md — Master LLM Context File

> OpenCode and Claude Code can read this file via their file tools. You are
> expected to read it at the start of every session, and to consult it again
> before any action that touches the document layer (`BLUEPRINT.md`,
> `CONVENTIONS.md`, `docs/DECISIONS.md`, `docs/ENGINEERING-CONSTITUTION.md`,
> `docs/CORRECTION-LOG.md`).
> Keep it current. Every correction you make to the LLM should be recorded here
> so the mistake never happens again.

---

## Project Overview

**Name:** [PROJECT_NAME]
**What it does:** [One paragraph. What does this do, who is it for, what problem does it solve.]
**Status:** [Planning | In Development | Production]

---

## Tech Stack

> Default template stack shown below. ADAPT to this project's real stack
> before first commit (see BLUEPRINT.md Rule 3).

```
Language:     Python 3.12+
Framework:    [e.g. FastAPI / Django / Flask]
Database:     [e.g. PostgreSQL / SQLite / MongoDB]
Auth:         [e.g. Clerk / JWT / OAuth]
Hosting:      [e.g. Railway / Fly.io / AWS]
CI/CD:        GitHub Actions
Testing:      pytest
```

---

## Project Structure

```
[PROJECT_NAME]/
├── src/                  # application source
│   ├── api/              # route handlers
│   ├── models/           # data models
│   ├── services/         # business logic
│   └── utils/            # shared utilities
├── tests/                # TPM-authored frozen suite (INV-1); changes only via refreeze.sh
├── docs/                 # architecture, engineering constitution, decisions, product, TPM role, escalation
├── tasks/                # EM write lane (plan.json) + session notes + backlog
│   └── CURRENT.md        # session notes — active work, halt notes (the PRD lives in scripts/.approved/)
├── scripts/
│   ├── bootstrap.sh / new-project.sh
│   │                         # one-time setup (core.hooksPath, .template-version stamp); template-owned, kept after setup (manifest gate fails on a missing file)
│   ├── orchestrate.sh        # shell-driven task-DAG conductor (owns ALL procedure)
│   ├── llm-call.sh           # ONE bare HTTP completion per call, no harness (D-53)
│   ├── phase-gate.sh         # lane + integrity gate (INV-2, frozen spec; portable sha256)
│   ├── validate-plan.py      # plan.json gate (atomicity, DAG, coverage, mapping)
│   ├── apply-edit-blocks.py  # fail-closed anchored SEARCH/REPLACE applier (D-59)
│   ├── sandbox-run.sh        # podman wrapper: read-only repo, --network none
│   ├── refreeze.sh           # ONLY path frozen TPM artifacts change (auto-applies on green preflights, D-121)
│   │                           + its freeze-door gates: refreeze_delta.py,
│   │                           check-spec-delta.py, check-prd-additive.py,
│   │                           check-ac-postconditions.py, check-swallowed-errors.py,
│   │                           check-test-direction.py, check-test-surface.py (INV-4),
│   │                           extract-test-functions.py, context-budget.py,
│   │                           standing-summary.py
│   ├── contracts-delta.py / contracts-merge.py / spec_artifacts.py
│   │                         # contract slicing/merging + shared artifact helpers
│   ├── completion-ledger.py / flake-ledger.py / metrics-report.py
│   │                         # durable cross-run bookkeeping (.measurement/, D-108/D-111/D-126)
│   ├── update-template.sh / link-template.sh / check-drift.sh / regen-manifest.sh /
│   │   manifest-drift-guard.sh / doc-consistency.sh
│   │                         # fleet sync + doc guards (D-33/D-34/D-115 class)
│   ├── tpm-pack.sh / tpm-unpack.sh / tpm-view.sh / tpm-agent.sh (+ *-settings.json)
│   │                         # TPM shuttle: verbatim relay, scoped agent (D-49/D-139)
│   ├── teardown.sh / status.sh / em-bench.sh / feature-summary.py
│   │                         # housekeeping, status, EM benchmarking, milestone summary
│   ├── selftest/             # control-plane selftests — run after ANY control-plane change
│   ├── schemas/              # plan / diagnosis / contracts schemas
│   └── .approved/            # frozen TPM spec: PRD, ERD, contracts, VERSION, hashes
├── .opencode/
│   └── prompts/          # agent role definitions (em/coder)
├── .githooks/            # pre-commit gate for the interactive/human path
├── .gate-paths           # configurable directories for INV-2 enforcement
├── CLAUDE.md             # this file
└── CONVENTIONS.md        # code style rules
```

---

## Code Conventions

- Always use type hints on function signatures
- Prefer functions over classes unless persistent state is needed
- Use `logging` from the standard library — never `print()`
- One responsibility per function — if it needs a comment explaining what it does, split it
- Tests live in `tests/` mirroring `src/` structure (e.g. `src/services/user.py` → `tests/services/test_user.py`)
- Tests are TPM-authored and land via `scripts/refreeze.sh` BEFORE the code they gate — never written after the fact to match an implementation
- Use `pydantic` for data validation and serialization
- Environment variables via `python-dotenv` — never hardcode secrets

---

## What NOT To Do

> These are guardrails. Do not override them without explicit human instruction.

**Code guardrails:**
- **Do not add dependencies** without asking first
- **Do not refactor files** unrelated to the current task
- **Do not change the database schema** without explicit instruction
- **Do not remove error handling** to simplify code
- **Do not use `Any` type** — be specific
- **Do not write `TODO` comments** — either implement it or raise it as a task
- **Do not use `time.sleep()`** in production code — use proper async patterns
- **Do not commit secrets** — use `.env` and ensure `.gitignore` covers it

**Pipeline guardrails (Rules 6-7, see BLUEPRINT.md; ladder details in DECISIONS.md D-26..D-32):**
- **No agent authors or edits tests** — the suite is TPM-authored, installed only via `scripts/refreeze.sh`, and hash-pinned in `scripts/.approved/frozen-manifest` (INV-1, now structural: tests are written before the code exists, by a tier that never sees the implementation).
- **Do not cross role boundaries** — Coder writes exactly the one file its task names (`phase-gate.sh task`); EM writes `tasks/` only (`phase-gate.sh em`). Post-D-53 enforcement is shell-owned: the model reply never touches the filesystem — the shell parses it and writes to exactly the task's declared path. `scripts/phase-gate.sh` re-verifies the working tree after every phase and fails closed on any out-of-lane change (INV-2).
- **Tests observe only the locked surface** — imports from `contracts.entry_points`, routes from `contracts.routes` (INV-4, checked at freeze time by `scripts/check-test-surface.py`).
- **Do not skip escalation** — retry → EM consult → brief/plan revision (bounded) → batched TPM bundle → re-freeze (gate-approved: refreeze auto-applies on green preflights, D-121). All counters shell-owned. See `docs/ESCALATION.md`.
- **Sync the stack before every freeze (D-50).** The TPM chooses the tech stack at spec time. Before running `refreeze.sh`, check the staged tests' imports against `requirements.txt` and add anything missing (this edit is in the conductor's lane). The sandbox image rebuilds itself when `requirements.txt` or `Containerfile` change — never manually delete or rebuild images.
- **TPM shuttle is a verbatim relay (D-49).** When the CEO asks for the TPM prompt/briefing: run `scripts/tpm-pack.sh` and reproduce its ENTIRE stdout in your reply, unabridged — never summarize it, never point the CEO at repo files (the bundle is assembled from several sources; it cannot be hand-collected), never claim it is "in the clipboard." When the CEO pastes a TPM reply back: write it to a temp file unmodified and run `scripts/tpm-unpack.sh <file>` — do not re-type or edit it.
- **TPM/milestone runs are inform-first (D-139).** Diagnosing a fix as needing a TPM round-trip or a milestone (orchestrate) run is NOT a launch: stop and ask the CEO — including who will take the TPM seat. The seat may be a web-chat model, a `scripts/tpm-agent.sh` agent, or the same LLM already on the job, by the CEO's assignment; never assume "the TPM is someone else" or that the run proceeds on an agent's judgment alone.

**Operating guardrails (from hard-won failures — see BLUEPRINT.md):**
- **Do not set a thinking model as the active model.** Thinking models leave `content` empty and put output in `reasoning_content`, which breaks parsing. The model must be non-thinking local OR frontier.
- **CARDINAL RULE — an EM/coder failure is never re-run blind.** If an EM or coder call fails, stop and troubleshoot the root cause — read the failure message, fix the harness/context/spec — never re-run the same call expecting the model to succeed next time. One attempt per run per call; a re-run is legitimate ONLY after a root-cause fix (then exactly one clean run). Measure and test through the pipeline's own machinery (`llm-call.sh` + schema + profile budget), never a hand-rolled copy of it.
- **Do not trust your own "it works" — only passing tests confirm success.** Run `pytest`. The tests are binding automated completion evidence, not your assessment. Do not mark a task done on self-judgment.
- **Do not proceed past an unreachable LM Studio or a missing service** — halt and report.
- **Do not invent product or architecture decisions to fill an ambiguous spec** — that is the human's job. Halt and ask.
- **Do not run destructive commands** (`rm -rf`, `git push --force`, drop tables, delete files outside the project) — halt and ask.

---

## Current Focus

The frozen spec (PRD/ERD/contracts + version) lives in `scripts/.approved/`;
`tasks/CURRENT.md` holds session notes and halt notes. New features start in
the TPM web chat (see `docs/TPM-ROLE.md`) and enter via `scripts/refreeze.sh`.

---

## Capability Ladder (D-27)

| Tier | Where it runs | Produces | Writes |
|------|---------------|----------|--------|
| **CEO** (human) | conversation with the conductor | business intent | — (runs no commands, D-40) |
| **TPM** (CEO-assigned seat, D-139) | web chat (D-38), scoped repo agent via `scripts/tpm-agent.sh` (D-39), or the same LLM already on the job — the CEO names the holder per session | PRD, ERD + `contracts.json`, the test suite | nothing directly — installed via `scripts/refreeze.sh` (auto-applies on green preflights, D-121), frozen in `scripts/.approved/` + `tests/` |
| **Conductor** | any chat agent the CEO chooses (Claude Code, OpenCode's Build, or a plain shell) | status reports, script invocations | docs/session notes; denied on `tests/`, `scripts/`, `src/`, control plane (D-40) |
| **EM** (mid-tier LLM) | one HTTP completion via `scripts/llm-call.sh` (D-53) | `tasks/plan.json` (decomposition), `tasks/diagnosis.json` (consults) — the shell writes both, not the model | `tasks/**` only |
| **Coder** (local LLM) | one HTTP completion via `scripts/llm-call.sh` (D-53) | one file per task, sentinel-wrapped in the reply | that one file only (gate-enforced) |

Model identity never lives in this repo: roles map to models in
`~/.config/sw-dev-blueprint/models.env` (CEO-owned, D-53). Model *class*
is constrained (frontier / mid / local non-thinking), never identity; no
mapping for a role is a hard halt, never a silent substitution.

The shell owns ALL procedure: `scripts/orchestrate.sh` validates the plan,
walks the DAG, runs gates and acceptance, and owns every escalation counter
(D-26). EM and coder are one bare HTTP completion each — no tools, no
filesystem access; the shell writes every artifact from their replies
(D-53). Tests are run by the shell; there is no test agent.

Loop, failure paths, freeze mechanics: BLUEPRINT.md ("The System in One
Diagram", "Hard Rules") and `docs/ESCALATION.md`. In short: refreeze
auto-applies on green preflights (D-95/D-121) → orchestrate → plan gate →
one task per coder call, mapped frozen tests after each → delta-mapped
verdict green = done (D-112).

---

## Reporting

When summarizing work since the last PM review (status reports, commit scoping, progress updates):

1. Read `docs/.pm-last-review` to get the last reviewed ref:
   ```
   LAST=$(cat docs/.pm-last-review 2>/dev/null || git rev-list --max-parents=0 HEAD)
   ```
2. Derive the commit list from the tree, not memory:
   ```
   git log "$LAST"..HEAD --oneline
   ```
3. State the scope explicitly in the report: "N new commits since reviewed ref `$LAST`".
4. Never write or advance `docs/.pm-last-review` — PM-owned.
5. If the file is missing (fresh checkout), the `git rev-list` fallback uses the initial commit — the scope becomes the entire history, which is correct for a first report.

---

## Operating Rules

> A rule that cannot be enforced mechanically is a suggestion, not a rule. Document the enforcement mechanism alongside every rule — and where there is none, say so explicitly.

Seven rules for agents working in this repo, derived from failures in prior sessions. Rules 2–7 are advisory — they rely on PM review for enforcement. Rule 1 has a mechanical backstop (see footnote).

1. **Report against the tree, never memory.** Derive your commit list from `LAST=$(cat docs/.pm-last-review); git log "$LAST"..HEAD --oneline`. State the range. A report that disagrees with `git log` is a defect regardless of the underlying work. *(Mechanical backstop: `docs/.pm-last-review` + PM source-side reconciliation.)*

2. **One commit, one concern.** Any change to a gate, invariant (INV-1/INV-2), permission, or model choice gets its own isolated commit whose message names it as such. Never bundle a constraint change with unrelated edits.

3. **A change to what a rule does is stop-and-ask.** Improving how a gate detects — fix freely. Changing what happens on a violation, or relaxing any constraint — stop and ask the PM first, even mid-run, even if the rule is what's slowing you down. The rule slowing you down is usually it working.

4. **Conditionals are checkpoints.** "Only do X if Y fails" means: when you reach that point, report whether Y failed and what you chose. If Y didn't fail, say so — don't silently act.

5. **Read the artifact, not the summary.** Report from committed files, never from another agent's summary or your own memory of a run. When source and summary disagree, source wins.

6. **"Detected" ≠ "enforced"; "nothing went wrong" ≠ "safeguard works."** Keep standalone-test results and live-run results as separate claims. An untriggered safeguard is inconclusive, not green.

7. **Decide trivial calls; escalate only contested principles.** If the PM has stated the governing principle ("put it where process docs live"), execute — don't re-ask for confirmation or surface options for a low-stakes choice. Escalate only when the principle itself is unclear, or when correctness is genuinely at stake (then asking is correct, not a failure).

---

## Documentation Impact Sweep

> Recording a decision is not propagating it. `docs/DECISIONS.md` says WHY the
> system changed; the guides below must then teach it AS IT NOW WORKS. Run this
> sweep IN THE SAME CHANGE as the code/decision — the doc drift this repo has
> accumulated (stale exit-0 criterion, an un-indexed canonical doc, a quickstart
> whose first commit could not pass) all came from recording without sweeping.

For every meaningful change, ask — and update wherever the answer is yes:

- [ ] Human behavior changed → `README.md` / `QUICKSTART.md` / `docs/CEO-PLAYBOOK.md`
- [ ] Milestone procedure changed → `BLUEPRINT.md` / `docs/ESCALATION.md` / `docs/TESTING.md`
- [ ] LLM responsibility changed → this file / role docs / `.opencode/prompts/*` (mirror the rule, never fork it)
- [ ] Architecture changed → `docs/ARCHITECTURE.md` decision map + `docs/ENGINEERING-CONSTITUTION.md`
- [ ] Current status changed → `tasks/CURRENT.md` (status) / `tasks/BACKLOG.md` (queue)
- [ ] Decision made → `docs/DECISIONS.md`
- [ ] A gate or flag was removed → grep EVERY guide for the retired token; `scripts/doc-consistency.sh` only warns on a fixed enumerated list, so it will not catch a new one
- [ ] Major incident or lesson → `docs/CORRECTION-LOG.md` (+ a `project-trail/` narrative for the ones worth a story)
- [ ] A design/spike doc reached its end state → mark it historical

One canonical source per rule: entry points and role docs POINT at it, they do
not restate it. When you touch a manifest-owned doc (anything in
`scripts/.manifest-project` or `.manifest-template`), regenerate the manifest in
the same change (`scripts/regen-manifest.sh <manifest>`).

---

## Key Contacts / Roles

| Role | Name |
|------|------|
| Product owner | [NAME] |
| Lead dev | [NAME] |

---

## LLM Correction Log

> The log moved out of this file's hot path on 2026-09-03 (it had reached ~67 KB, ~80% of this file, loaded every session). It now lives in **[`docs/CORRECTION-LOG.md`](docs/CORRECTION-LOG.md)**.
>
> **When the LLM makes a mistake and you correct it, add a row there** — newest at the top — and **read it before any control-plane, gate, or document-layer change.** It is still the most valuable guardrail in the system; it is now one hop away instead of in every prompt. A rich log means the system is working.
