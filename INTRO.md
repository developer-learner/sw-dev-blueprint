# INTRO.md — the friendly first hour

> Read this first if you're new. It builds the mental model in plain English
> before any command line. When it's done, go to `QUICKSTART.md` to actually
> run the thing, and `README.md` / `BLUEPRINT.md` when you want the reference.

---

## What sw-dev-blueprint is

A template for building software with AI assistance that doesn't collapse the
moment the AI gets creative. You describe an app in plain English; a small
team of AI seats plans it, writes it, and tests it against a spec that gets
frozen before any code is written. Your job is approving what the plan claims
and eyeballing the finished app — never reading diffs, never marking things
done on the AI's word.

The bet: **AI is generative; correctness needs to be mechanical.** The
template holds that line at every step.

---

## The five things involved

Get these five in your head and everything else falls out of them.

**You (the CEO).** You describe intent. You open the finished app and try it.
You don't run scripts by hand and you don't read code. You approve nothing
mechanically: the freeze auto-applies on green preflights (D-121) and the
full-suite is an on-demand regression check (D-112).

**A frontier LLM (the TPM seat).** The CEO assigns who holds the seat per
session (D-139) — a web chat like Claude.ai or ChatGPT, a scoped repo agent,
or the same LLM already on the job. You
paste your app description here and it writes back four documents: a product
description, the technical shape, an API contract, and the test suite that
will decide "is it done." This chat lives outside the pipeline; it's just a
web browser tab.

**LM Studio (or any OpenAI-compatible local server).** Runs on your Mac.
Serves two AI seats — the **EM** (mid-strength model that plans work) and the
**coder** (local model that writes one file at a time). Both are called over
HTTP; neither has any tools, filesystem access, or memory of prior calls.

**Lima (a Linux VM on your Mac).** The pipeline scripts refuse to run on
macOS directly — they need Linux. Lima gives you a Linux box that lives on
your Mac. The pipeline runs inside it. LM Studio stays on the Mac so it can
use the GPU; the pipeline reaches out to it over the network.

**Podman (containers inside Lima).** When tests run, they run inside a
Podman container: no network, your files mounted read-only, thrown away
after. This is the actual safety line — even if the AI writes malicious code,
it can't reach your data or the internet.

Two AI seats you don't install: the **TPM** — the LLM the CEO assigns to the
spec seat per session (D-139: a web chat, a scoped repo agent, or the same
LLM already on the job) — and
the **conductor** — the chat agent you're talking to right now — which drives
the shell scripts, reads output back to you, and never touches trusted files
itself.

---

## What runs where

Picture three nested layers:

```
┌─── your Mac ────────────────────────────────────────┐
│   LM Studio  +  loaded model  (uses the GPU)        │
│   Your chat with the conductor                      │
│                                                     │
│   ┌─── Lima VM (Linux) ─────────────────────────┐   │
│   │   The pipeline scripts (orchestrate, etc.)  │   │
│   │   The project files                         │   │
│   │                                             │   │
│   │   ┌─── Podman container ──────────────┐     │   │
│   │   │   pytest runs the tests           │     │   │
│   │   │   No network, no writes to repo   │     │   │
│   │   │   Thrown away after each run      │     │   │
│   │   └───────────────────────────────────┘     │   │
│   │                                             │   │
│   │   pipeline reaches out to LM Studio ────────┼───┼──▶ (host.lima.internal)
│   └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

Model on your Mac. Pipeline in Lima. Tests in Podman. On bare Linux, Lima
disappears — you'd only need Podman.

---

## The linear process, from your brief to a working app

Every milestone follows this shape.

**Stage 1 — You describe the app.**
Tell the TPM seat — the LLM you name for this session (D-139) — what you
want built.

**Stage 2 — TPM authors the spec.**
It writes back the product description, the technical shape, the API
contract, and the test suite. Nothing is checked yet — it's a proposal.

**Stage 3 — Freeze.**
You paste those four back into your conductor. Running `refreeze.sh` scans
them (ruff lints the tests, gates check the tests only touch declared APIs
and are internally consistent), then hashes every file and locks the spec.
When every mechanical preflight is green the freeze applies automatically —
there is no human approval step (D-121). From this moment nothing — no AI,
no script — can change what "done" means; the diff preview is read-only
until you request it, and a green preflight is what releases the lock.

**Stage 4 — Pre-flight.**
Running `orchestrate.sh` first checks the world is sane: is LM Studio
reachable? Working tree clean? Right model loaded? A "reply with OK" probe
catches a thinking model in two seconds instead of fifteen minutes in.

**Stage 5 — EM plans the work.**
The EM AI reads the spec and produces a task list — one file per task, under
150 lines each, with a dependency graph. A validator rejects the plan if
tasks are too big, if the dependency graph has cycles, if a test isn't
mapped to a task, or if the coder is being asked to touch a file the spec
declared unchanged.

**Stage 6 — Coder writes, one task at a time.**
For each task: the coder AI produces one file's worth of text, the shell
parses it and writes it to disk (the AI never touches your filesystem),
then pytest runs the mapped tests inside a Podman container. Fail once,
retry. Fail twice, the EM gets called to diagnose. Diagnosis routes to a
revised brief, a new plan, or a bundle back to you for the TPM.

**Stage 7 — Delta-mapped verdict.**
When every task passes its mapped tests, the run checks the acceptance
criteria the delta touched (D-112) — the full frozen suite is an on-demand
regression check (`--full-suite`), not the milestone gate. Green → the
pipeline creates a `[success]` commit.

**Stage 8 — You open the app.**
Green tests are necessary, never sufficient. You open the running app in a
real browser and try the golden path. If it looks or feels wrong, that's
still a fail — and a new test gets added so the pipeline never misses that
class of bug again.

**Loops when things fail:**
- Task retry (up to 2 tries per task)
- EM diagnosis → new plan or revised brief
- Spec defect → bundle back to Stage 1 for the TPM to fix, re-freeze, resume

---

## Why this actually works

The design assumes the AI will lie, drift, or hallucinate — and puts a
physical barrier at every place it could cause damage.

- **Tests are written before the code, by a different AI that never sees the
  code.** The coder can't move the goalposts because it never sees them.
- **Tests are hash-locked.** Change one byte and the pipeline halts.
- **The AI never touches your files.** It produces text; the shell writes.
- **Every task is one small file.** Small failures instead of big mysteries.
- **Tests run in a network-off, read-only sandbox.** Blast radius is zero.
- **The AI cannot mark itself done.** pytest says pass/fail. The AI has no say.
- **Failures escalate, never disappear.** No silent retry until it happens to pass.
- **You are the last check.** Green isn't enough; human eyes are the final oracle.

---

## Beyond a single milestone

A few things run at the template level, between or outside milestones:

**Pulling improvements from the blueprint.** The blueprint itself keeps
getting new gates and fixes. `check-drift.sh` tells you how far behind
you are. `update-template.sh` pulls them in — with a plain-language summary
you approve before anything changes. Your project files are never touched;
only template-owned files update.

**Housekeeping.** `status.sh` gives you a read-only view (VM state, LM Studio
port, container count, disk usage) — good end-of-day check. `teardown.sh`
reclaims resources when you want them back, always with a dry-run first.
Neither runs automatically — the design treats a warm VM and loaded model as
*state you chose*, not leaks to clean up.

**The template protects itself.** Critical files are hashed. If you or an AI
edit one, the next commit is blocked until you consciously regenerate the
hash list. The blueprint's own test suite runs in CI so a broken template
never reaches your project via `update-template.sh`.

Nothing is on a timer. Every template action is human-triggered — the design
assumes you want to *choose* when the ground under you moves.

---

## How the system remembers

Five artifacts accumulate durable memory across runs. Three are automatic:

- **Escalation bundles** — generated the moment the pipeline hits a wall,
  packaged for you to hand to the TPM.
- **Flake and completion ledgers** — the pipeline remembers between runs.
  A test that flakes N times stops being written off. A task validated done
  in one run isn't redone in the next.
- **EM archive** — every EM call captured verbatim for later replay and
  benchmarking.

Two require human discipline:

- **Decisions ledger** (`docs/DECISIONS.md`) — every rule in the pipeline
  exists because something broke. Each entry names the failure and the guard.
  Someone has to write the entry when a design call gets made.
- **LLM Correction Log** (in `CLAUDE.md`) — when the AI is corrected in a
  novel way, someone has to add a row so the next session doesn't repeat it.

The machine catches what the machine can see. The docs catch what the human
notices. The docs are as good as the discipline behind them.

---

## Naming quick-reference

You'll see these terms everywhere. First-time gloss:

- **CEO** — you. Business intent and final acceptance.
- **TPM** — the LLM in the CEO-assigned spec seat (D-139: a web chat, a
  scoped repo agent, or the same LLM already on the job). Writes the spec.
- **Conductor** — the chat agent you talk to that runs the scripts.
- **EM** — the mid-strength AI that plans work.
- **Coder** — the local AI that writes one file per task.
- **PRD** — the product description (what to build, for whom).
- **ERD** — the technical shape (files, routes, data models).
- **Contracts** — the machine-readable API surface.
- **Freeze / refreeze** — locking a spec by hash so nothing can move
  goalposts. Named `refreeze` because after milestone 1 every freeze
  replaces the previous one.

---

## Where to go next

- **`QUICKSTART.md`** — run the pipeline end-to-end on a bundled example
  in ~30 minutes. Do this before reading anything else.
- **`README.md`** — reference layout of files and roles, once you've seen
  the pipeline work.
- **`BLUEPRINT.md`** — the master document. Read on demand: the section
  you need, not front-to-back.
- **`docs/TPM-ROLE.md`** — when you're ready to write your own spec.
- **`docs/ESCALATION.md`** — the first time a run exits with an escalation.
- **`docs/DECISIONS.md`** — 100+ dated entries. Read each as you hit its
  subject in practice, not as reading material.

---

*The pipeline is stricter than it looks and gentler than it sounds. The
strictness is why it works when the AI drifts; the gentleness is that you
never have to babysit — you set intent, approve claims, and open the app.*
