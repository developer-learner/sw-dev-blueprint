# QUICKSTART.md — zero to a green frozen suite, one Linux box

> Prove the pipeline on your machine before you learn its theory: build the
> bundled example spec — a real bookmarks API, 21 frozen tests, built by this
> exact pipeline on 2026-07-16 — end to end. Roughly 30 minutes of commands
> plus a ~10-minute one-time container build. No GitHub account, no spec
> authoring, no VM split.
>
> **macOS:** the build step hard-requires Linux; set up the Lima VM first
> (`docs/DEV-VM-SETUP.md`), then run the steps below inside it. On a bare
> Linux box everything runs in one place — this page assumes that.

## Step 0 — what you need

| Need | Verify | Notes |
|------|--------|-------|
| git with identity | `git config user.name && git config user.email` | both non-empty, else `git config --global` them — the pipeline's own commits silently no-op without an identity, so pre-flight fails closed on it |
| Python 3.12+ | `python3 --version` | — |
| Podman | `podman info` | the frozen suite runs sandboxed (`--network none`, repo read-only); there is no unsandboxed fallback (D-30) |
| ruff | `ruff --version` | the freeze gate lints staged tests and fails closed without it (D-67) |
| A local LLM server | `curl -s http://localhost:1234/v1/models` | LM Studio, llama.cpp server, vLLM — anything OpenAI-compatible. Port 1234 assumed below; override with `SANDBOX_LLM_PORT` |
| `gh` CLI (optional) | `gh auth status` | only used to stamp the template birth SHA; bootstrap warns and continues without it |

The model matters more than the server: a **~27B-class dense, non-thinking
model with 32K context** is the proven floor here — smaller or heavily-MoE
models failed real task work in this repo's own history (D-12/D-14/D-66),
and a thinking model breaks reply parsing outright (Rule 1). Verify
non-thinking in 20 seconds:

```bash
MODEL=$(curl -s http://localhost:1234/v1/models | python3 -c \
  'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])')
curl -s http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with just OK\"}],\"max_tokens\":5}"
```

PASS: `content` says OK and `reasoning_content` is absent or empty. If it is
the other way around, a thinking model is loaded — swap it before going on.

## Step 1 — create a project

```bash
git clone https://github.com/developer-learner/sw-dev-blueprint myproj
cd myproj
./scripts/bootstrap.sh myproj
git add -A && git commit -m "chore: instantiate myproj from sw-dev-blueprint"
```

Bootstrap fills placeholders, builds the venv, enables the pre-commit gate
(`core.hooksPath=.githooks`), and stamps `.template-version`. The commit
matters: the orchestrator refuses a dirty tree (pre-flight, fail-closed).

(The durable path for real projects is GitHub's "Use this template" — see
README "Starting a new project". Not needed today.)

## Step 2 — map the model seats

```bash
mkdir -p ~/.config/sw-dev-blueprint
cat > ~/.config/sw-dev-blueprint/models.env <<'EOF'
SWBP_EM_MODEL=your-model-id-as-served
SWBP_CODER_MODEL=your-model-id-as-served
EOF
```

Use the exact id `/v1/models` returned; the same model in both seats is fine
to start. No mapping is a hard halt, never a silent substitution (D-53).

## Step 3 — pre-warm the sandbox (one-time, ~10 min)

```bash
scripts/sandbox-run.sh -- true
```

Builds the container image the frozen tests run in. Do it now so the freeze
and the build don't eat the image build inside their own timeouts.

## Step 4 — stage the example spec

```bash
mkdir -p scripts/.approved/incoming/tests
cp examples/minimal-spec/PRD.md examples/minimal-spec/ERD.md \
   examples/minimal-spec/contracts.json scripts/.approved/incoming/
cp examples/minimal-spec/tests/storage_tests.py scripts/.approved/incoming/tests/test_storage.py
cp examples/minimal-spec/tests/api_tests.py     scripts/.approved/incoming/tests/test_api.py
```

These four artifacts — PRD, ERD, contracts, frozen tests — are what the TPM
(a frontier chat you operate) authors for every real milestone. Today they
are pre-written; `examples/minimal-spec/README.md` explains each one.

## Step 5 — freeze it

```bash
scripts/refreeze.sh
```

Read the diff it shows, answer y. The spec is now version-stamped and
hash-pinned under `scripts/.approved/` + `tests/` — from here on, no agent
can change what "done" means. This human diff-review is THE approval gate of
the whole system.

## Step 6 — build it

```bash
scripts/orchestrate.sh
```

What you'll watch: pre-flight (including an LLM round-trip smoke test) → the
EM decomposes the ERD into a validated 2-task plan → the coder writes
`src/storage.py` and its mapped tests run sandboxed → same for `src/api.py` →
full frozen suite → `21 passed` → a `[success]` commit. Most of the elapsed
time is model inference.

The green suite is the proof, but the app is real: serve it with
`.venv/bin/uvicorn src.api:app` and exercise the routes the frozen ERD in
`scripts/.approved/` names.

## If it halts

| Symptom | Meaning | Move |
|---------|---------|------|
| pre-flight: no LLM reachable | server down or wrong port | start it, or `SANDBOX_LLM_PORT=8000 scripts/orchestrate.sh` |
| empty smoke reply / JSON parse errors | thinking model loaded | Rule 1 — swap to non-thinking, re-run the Step 0 probe |
| pre-flight: working tree not clean | uncommitted changes | commit or stash, re-run |
| hard halt: role has no model mapping | models.env missing or typo'd | Step 2 — the id must match `/v1/models` exactly |
| exit 2 + `.pipeline-state/escalations/BATCH.md` | the pipeline says the SPEC is wrong | the TPM escalation loop — `docs/ESCALATION.md`. You won't hit it on the example spec. |

Two retries on the same error and still stuck: stop and read the matching
doc — that discipline (Rule 2) is the system, not a suggestion.

## What you just proved, and where depth lives

You ran the entire trust chain: a human-approved frozen spec, a shell that
owns all procedure, model seats with no filesystem access, and a sandboxed
frozen suite as the only definition of done.

Go deeper strictly on demand:

- **Your own project (milestone 1):** a frontier web chat authors the four
  artifacts — read `docs/TPM-ROLE.md` (how to run that chat) and
  `docs/CEO-PLAYBOOK.md` (the operator rhythm), then repeat Steps 4–6 with
  its output.
- **The first time a run exits 2:** read `docs/ESCALATION.md` — the failure
  ladder and the TPM bundle round-trip. Not before.
- **Several projects from this template:** now the fleet tools matter —
  `scripts/check-drift.sh` and `scripts/update-template.sh` (BLUEPRINT.md
  "Staying Current with the Template").
- **Why it is built this way:** `docs/DECISIONS.md` — 80+ dated decisions,
  each traceable to a failure. Read entries as you hit their subject, not
  front to back.
