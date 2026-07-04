# Handoff: Outer Sandbox for the Orchestrator (revised 2026-07-04)

> Supersedes the earlier "Blueprint Sandbox Isolation" handoff, which was
> written against a stale picture of the repo. Read this whole document
> before touching anything — especially "What already exists."

## What already exists (do not rebuild)

The template already has an **inner sandbox**: `scripts/sandbox-run.sh`
(Podman, D-30/D-50/D-53). It runs pytest and smoke checks over a
**read-only** repo mount with per-lane `--rw` grants, `--network none`,
resource caps, and a content-hashed auto-rebuilding image
(`Containerfile` + `requirements.txt` at repo root). Lane violations by
generated code are *preventively* impossible in-loop; `phase-gate.sh` is
the backstop for the human/interactive path. It is called from
`orchestrate.sh` at lines ~192 (frozen suite) and ~461 (smoke).

Do not weaken, bypass, or duplicate it. This handoff adds an **outer**
boundary around it.

## Problem (the actual remaining gap)

`orchestrate.sh` itself runs on the host: git, state writes under
`.pipeline-state/`, coder-output file writes, and `llm-call.sh` HTTP
calls. The conductor (Claude Code) therefore prompts for these host side
effects, requiring human babysitting per run or broad host permissions.
CEO directive: one command, one permission prompt; everything inside runs
freely; host protected.

## Deliverable

`scripts/orchestrate-sandboxed.sh` — an outer wrapper the conductor
invokes instead of `scripts/orchestrate.sh` directly.

(Name deliberately not `sandbox.sh`: it would collide conceptually with
the existing `sandbox-run.sh`.)

## Design constraints (decided — do not reopen)

1. **Backend: one, VM-class.** The inner sandbox needs Podman *inside*
   the outer boundary (nested). A Linux VM runs Podman natively — cleaner
   than today's `podman machine` hop. Candidates: Apple `container`
   (per-container Virtualization.framework VM, can likely reuse the
   existing Containerfile pattern) or a lightweight Linux VM (lima/krunkit
   class). Podman-in-Podman on the host is NOT acceptable: if it proves
   fragile and the implementer shortcuts to running pytest directly in the
   outer sandbox with the repo mounted RW, the D-30 guarantee silently
   dies. First task of the thread: prove `sandbox-run.sh` works unchanged
   inside the chosen backend before building anything else.
2. **No unsandboxed fallback — hard-halt.** Matches the existing policy
   verbatim ("The sandbox is mandatory (D-30); there is no unsandboxed
   fallback"). If the backend is unavailable, exit non-zero with a clear
   message.
3. **Live project mount, read-write, into the outer sandbox.** No
   copy-in/copy-out: it would break `.pipeline-state` crash checkpointing
   (D-24) and git continuity. The RW outer mount is safe *only because*
   the inner RO-lane sandbox still runs inside it (constraint 1).
4. **Model server access = deliberate D-53 partial reversal.** Forward /
   NAT the host model port (default 1234; roles mapped in
   `~/.config/sw-dev-blueprint/models.env`) so `llm-call.sh` works
   unchanged from inside. D-53 moved LLM calls to the host precisely
   because cross-boundary port wiring caused the failures of the first
   three supervised runs (D-50/D-52 class). Reintroducing it is accepted
   as the cost of a single boundary — but it MUST get its own
   DECISIONS.md entry, and the wrapper MUST pre-flight a round-trip
   `llm-call.sh` smoke test from inside the sandbox before starting the
   pipeline (this also discharges the smoke-test debt logged in the
   CLAUDE.md correction log, 2026-07-03).
5. **Outer image needs the orchestrator's toolchain**: bash, python3,
   git, curl/jq (whatever `llm-call.sh` uses), plus Podman. The existing
   `Containerfile` is scoped to the test lane; do not overload it — give
   the outer environment its own definition with the same content-hash
   rebuild trick (D-50).

## What NOT to change

- `orchestrate.sh` internals — the wrapper wraps it.
- `sandbox-run.sh` and gate/lane enforcement — they remain the inner layer.
- `llm-call.sh` — must work unchanged via the forwarded port.
- Any derived-project (testchat/spark) files — template-only.

## Prior art (reference only, not a dependency)

mlx-serve (mlxserve.com, github.com/ddalcu/mlx-serve) ships an agent
sandbox using Virtualization.framework with port forwarding — existence
proof that this isolation pattern needs no special entitlements. Its
sandbox is internal to its own app and cannot wrap arbitrary scripts;
do not install it as part of this work.

## Stopgap already available (not part of this work)

A conductor allowlist entry for `Bash(scripts/orchestrate.sh*)` gives
"one prompt" today but zero host isolation — acceptable while the outer
sandbox is built, insufficient as the end state per the CEO directive.

## Acceptance

- Conductor runs `scripts/orchestrate-sandboxed.sh` as one command; no
  further prompts for anything the pipeline does.
- Inner `sandbox-run.sh` lanes verified working inside the outer boundary
  (RO repo, `--rw` lanes, no network).
- `llm-call.sh` pre-flight round-trip passes from inside.
- Results visible on the host immediately via the live mount.
- Hard-halt (non-zero, clear message) when the backend is missing.
- New DECISIONS.md entry recording the D-53 partial reversal.
