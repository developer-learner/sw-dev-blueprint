# DECISIONS.md — Architectural Decision Log

> Every non-obvious technical decision goes here with the reasoning.
> This prevents the LLM from "helpfully" undoing choices you already made.
> Format: date, decision, why, what not to suggest.

---

## Template

```
## YYYY-MM-DD — [Decision title]

**Decision:** [What was decided]
**Alternatives considered:** [What else was evaluated]
**Reason:** [Why this choice was made]
**Do not suggest:** [What the LLM should not propose as a "fix"]
```

---

## Decisions

## [DATE] — [Your first decision here]

**Decision:** [e.g. Using raw SQL over ORM]
**Alternatives considered:** [e.g. SQLAlchemy, Tortoise ORM]
**Reason:** [e.g. Query complexity made ORM unreadable for our join-heavy patterns]
**Do not suggest:** Switching to an ORM. This was deliberate.

---

## [DATE] — Monorepo structure

**Decision:** Single repository for all services.
**Alternatives considered:** Separate repos per service.
**Reason:** Team size doesn't justify the overhead of managing multiple repos. Shared code is easier to refactor.
**Do not suggest:** Splitting into microservices repos until team grows past 5 engineers.

---

> Add new decisions above this line, newest first.
