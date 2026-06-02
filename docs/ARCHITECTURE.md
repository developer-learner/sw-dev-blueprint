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
