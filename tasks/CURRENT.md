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

> Written as checkboxes. Each one is testable.

- [ ] [Specific, observable outcome 1]
- [ ] [Specific, observable outcome 2]
- [ ] [Tests pass for the above]
- [ ] [No existing tests broken]

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

## Definition of Done

- [ ] Acceptance criteria all checked
- [ ] Tests written and passing
- [ ] `docs/ARCHITECTURE.md` updated if structure changed
- [ ] `docs/DECISIONS.md` updated if non-obvious choice was made
- [ ] No linter errors (`ruff check src/`)
- [ ] Branch merged to main
