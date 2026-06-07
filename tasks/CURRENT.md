# CURRENT.md — Active Task

> This is the session-level spec. Update before every coding session.
> The LLM reads this to know exactly what to build — and what to leave alone.
> When done, move to BACKLOG.md and write the next task here.

---

## Task: [TASK_NAME]

**Status:** [Not started | In progress | In review | Done]
**Branch:** `[feature/task-name]`
**Estimated effort:** [Small / Medium / Large]

---

## What

[One paragraph. What should exist when this task is complete that doesn't exist now.]

---

## Acceptance Criteria

> Write each criterion in EARS form so it maps one-to-one to a test (sharpens INV-1).
> <!-- EARS forms:
>      THE SYSTEM SHALL <behavior>                      (always)
>      WHEN <trigger>, THE SYSTEM SHALL <response>       (event)
>      WHILE <state>, THE SYSTEM SHALL <behavior>        (during a state)
>      IF <condition>, THEN THE SYSTEM SHALL <response>  (error/edge)
>      WHERE <feature>, THE SYSTEM SHALL <behavior>      (optional feature)
>      One clause = one test. Attach a concrete I/O example where useful. -->

- [ ] WHEN <trigger>, THE SYSTEM SHALL <observable response>
- [ ] IF <invalid input>, THEN THE SYSTEM SHALL <error response>
- [ ] THE SYSTEM SHALL <invariant that always holds>
- [ ] Tests pass for the above; no existing tests broken

---

## Out of Scope

> Explicit. Prevents the LLM from building things you don't want yet.

- [Thing that sounds related but isn't this task]
- [Future feature that will come later]

---

## Files Likely Involved

> Give the LLM a map so it edits the right files.

```
src/services/[relevant_service].py   # main logic here
src/api/[relevant_router].py         # route handler
src/models/[relevant_model].py       # if schema changes
tests/services/test_[service].py     # unit tests
tests/api/test_[router].py           # API tests
```

---

## Notes / Context

[Anything the LLM needs to know that isn't in ARCHITECTURE.md or DECISIONS.md.
Temporary context for this task only.]

---

---

## Flagged Assumptions

> Where the casual instruction was ambiguous, the PM picked a reading. List each pick here.
> This is the human's review surface — they scan only this + Acceptance Criteria.

- [Ambiguity] → [Assumption taken]. e.g. "share reports" → assumed view-only links, not collab editing.

---

## Approval

**Status:** Draft | Approved
**Approved by:** [human reviewer]

> Build does NOT start until Status: Approved. Once Approved, Acceptance Criteria are FROZEN —
> no agent may edit them. Changes require a new Draft cycle and re-approval.

---

## Definition of Done

- [ ] Acceptance criteria all checked
- [ ] Tests written and passing
- [ ] `docs/ARCHITECTURE.md` updated if structure changed
- [ ] `docs/DECISIONS.md` updated if non-obvious choice was made
- [ ] No linter errors (`ruff check src/`)
- [ ] Branch merged to main
