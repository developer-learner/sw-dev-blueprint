# Handoff: Linux Dev VM for Zero-Prompt Agent Operation (2026-07-05)

> Supersedes `HANDOFF-outer-sandbox.md` (wrapper design, removed). The core
> idea changed: instead of wrapping `orchestrate.sh` in an outer sandbox on
> the host, the **conductors themselves move inside a persistent Linux VM**.
> The pipeline runs directly in the VM; no wrapper script exists.

## Motivation (evidence, not theory)

The testchat M4 supervised run (see CLAUDE.md correction log, 2026-07-04):
a frontier conductor under goal pressure crossed every advisory lane —
hand-wrote `src/`, authored test fixes, added unspecced features, skipped
the escalation ladder — while every structural gate held. Conductor
constraints must be structural. A VM boundary makes them structural, and as
a bonus eliminates permission-prompt babysitting entirely: conductors run
with permissions bypassed *because the VM is the boundary*.

## Architecture

```
Mac host
├─ LM Studio / model server (:1234) — stays on host for GPU access
└─ Lima VM (Linux, persistent, headless)
     ├─ Claude Code, OpenCode, Kilo Code (via VS Code Remote-SSH)
     │    — all run with permissions bypassed / full-auto
     ├─ git repo (shared with host via virtiofs mount;
     │    VM is the PRIMARY working-tree home — host side is read-mostly
     │    to avoid dual-edit conflicts)
     ├─ Podman (native — D-30 inner sandbox runs unchanged)
     └─ scripts/orchestrate.sh — runs directly, no wrapper
```

Two boundaries, two jobs:
- **VM** protects the host from the agents (conductor seat included).
- **D-30 Podman lanes** (inside the VM, unchanged) protect the control
  plane — tests, gates, frozen spec — from generated code.

No VM-in-VM concern: Podman on macOS already runs inside a hidden Linux VM
(`podman machine`) today. This swaps the hidden VM for a visible one the
conductors also live in. Same nesting depth as now — arguably less, since
Podman becomes native.

## Design constraints (decided — do not reopen)

1. **Backend: Lima.** OrbStack ruled out (shared-kernel model,
   insufficient isolation for skip-permissions agents). Persistent,
   headless, interacted with from the Mac terminal / VS Code Remote-SSH.
2. **First task: prove the inner sandbox inside the VM.** Before
   installing any conductor, verify `scripts/sandbox-run.sh` works
   unchanged under native Podman in the Lima guest (RO repo mount,
   `--rw` lanes, `--network none`, image auto-rebuild). If this fails,
   stop and report — do NOT shortcut to running pytest directly in the
   VM with the repo RW; that silently kills the D-30 guarantee.
3. **No host execution path remains.** The old handoff's "hard-halt, no
   unsandboxed fallback" translates to: `orchestrate.sh` gains a
   pre-flight check that refuses to run on a macOS host (mechanism:
   implementer's choice — `uname` check or a VM marker file; must be a
   `die`, not a warning). The conductor's host-side job shrinks to zero;
   the CEO talks to conductors that live in the VM.
4. **Model server stays on the host (GPU).** The VM reaches it via the
   Lima host-gateway address (`host.lima.internal:1234`). This requires
   parameterizing the endpoint host in `llm-call.sh`/`orchestrate.sh`
   (today they hardcode `http://localhost:$SANDBOX_LLM_PORT`) — e.g.
   `SANDBOX_LLM_HOST`, default `localhost`, set to `host.lima.internal`
   in the VM's environment.
5. **Cross-boundary model access = deliberate D-53 partial reversal.**
   D-53 moved LLM calls host-local precisely because cross-boundary port
   wiring caused the failures of the first three supervised runs.
   Reintroducing it is accepted as the cost of the VM boundary — but it
   MUST get its own DECISIONS.md entry, and orchestrate pre-flight MUST
   include a round-trip `llm-call.sh` smoke test (trivial prompt through
   the mapped model, assert non-empty reply). This also discharges the
   smoke-test debt in the correction log (2026-07-03) — plumbing bugs in
   the model path are invisible to static review; only a live round-trip
   catches them.
6. **Live shared repo, no copy-in/out.** virtiofs mount preserves
   `.pipeline-state` crash checkpointing (D-24) and git continuity.
   Host-side results are visible immediately.

## What NOT to change

- `sandbox-run.sh` and the gate/lane enforcement — inner layer, unchanged.
- `orchestrate.sh` internals beyond the two pre-flight additions
  (host-refusal check, llm-call round-trip) and the endpoint-host
  parameterization.
- Derived-project (testchat/spark) files — template + host setup only.

## Genuinely project-specific work items

1. Lima VM config (CPU/RAM/disk, virtiofs mount of the dev directory,
   host-gateway networking) — written up as a reproducible provisioning
   spec, not a hand-built snowflake.
2. Podman inside the VM + constraint-2 verification.
3. `llm-call.sh`/`orchestrate.sh` endpoint-host parameterization +
   round-trip smoke pre-flight + DECISIONS.md entry (constraints 4–5).
4. `orchestrate.sh` host-refusal pre-flight (constraint 3).
5. OSC 52 clipboard shim (`pbcopy`/`pbpaste` equivalents in the guest)
   so the TPM shuttle scripts (`tpm-pack.sh` copy-paste flow) work from
   inside a headless VM.
6. Install/configure the three conductors inside (Claude Code, OpenCode,
   Kilo Code via VS Code Remote-SSH), each in skip-permissions mode.

## Prior art (reusable starting points, verified to exist)

- [mattolson/agent-sandbox](https://github.com/mattolson/agent-sandbox) —
  closest drop-in Lima template for this exact pattern.
- [Sandboxing AI coding agents with Lima](https://bogoyavlensky.com/blog/sandboxing-ai-coding-agents-with-lima/)
  — walkthrough of the Lima + skip-permissions setup.
- [INNOQ dev-sandbox writeup](https://www.innoq.com/en/blog/2025/12/dev-sandbox/)
  — Lima + gateway networking notes.
- Anthropic's devcontainer / Docker Sandboxes: considered, don't fit —
  Docker-in-Docker conflicts with D-30 Podman lanes; Docker Sandboxes is
  per-agent/ephemeral, not a persistent shared dev home.
- mlx-serve's Virtualization.framework agent sandbox: existence proof
  only; internal to its own app, not wrappable. Do not install.

## Acceptance

- A fresh `lima start <config>` + documented setup steps yields a VM where
  all of the following hold, with **zero permission prompts** end to end:
  - `sandbox-run.sh` lanes verified working (constraint 2).
  - `llm-call.sh` round-trip to host LM Studio passes from inside the VM
    and from inside the inner Podman sandbox.
  - A derived project's `orchestrate.sh` runs a full milestone
    unattended.
  - `orchestrate.sh` on the macOS host refuses to run (constraint 3).
  - TPM shuttle copy/paste works via OSC 52 from the Mac terminal.
- New DECISIONS.md entry recording the D-53 partial reversal.
- Host filesystem outside the shared mount untouched by anything in the VM.
