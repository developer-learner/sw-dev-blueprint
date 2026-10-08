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
     ├─ per-run project clones on the VM's own disk
     │    (~/swbp-runs/<project>/<run>/ws) — copied in from the host's
     │    committed HEAD, returned only as checked commits (D-205)
     ├─ sw-dev-blueprint mounted READ-ONLY (swbp + helpers)
     ├─ Podman (native — D-30 inner sandbox runs unchanged)
     └─ scripts/orchestrate.sh — runs directly, no wrapper
```

Two boundaries, two jobs:
- **VM** protects the host from the agents (conductor seat included).
- **D-30 Podman lanes** (inside the VM, unchanged) protect the control
  plane — tests, gates, frozen spec — from generated code.

### Getting work into and out of the VM (D-205)

The VM mounts no host project. Every run goes through `scripts/vm-sync`,
run **on the Mac**:

```bash
scripts/vm-sync start ~/dev/vortex                 # prints a run id + the VM path
scripts/vm-sync exec  ~/dev/vortex <run> -- <cmd>  # or work in that path inside the VM
scripts/vm-sync land  ~/dev/vortex <run>           # bring the run's commits back
scripts/vm-sync list  ~/dev/vortex
scripts/vm-sync discard ~/dev/vortex <run>
```

- `start` clones the current branch's **committed** HEAD onto the VM's disk.
  Uncommitted and ignored host files (`.env`, drafts) do not go across unless
  named with `--copy-file`, and a copied file never comes back.
- Inside the VM the run is an ordinary checkout on branch `swbp-run`; run the
  pipeline there as before (`swbp orchestrate --app <that path>`). An
  interrupted run stays on the VM's disk and can simply continue.
- `land` pulls back ONE bundle holding only the run's new commits and
  `scripts/vm_land.py` checks it before anything on the host changes: linear
  history on top of the recorded base; no symlinks, submodules, `.git`/`..`
  paths or host-ignored files; the host branch has not moved; no uncommitted
  host edits to the touched files. The base and branch come from the host's
  own record in `.git/swbp-vm/`, never from the VM. Anything else is
  refused with the host untouched.
- The VM can never push to the host. Landing is always a host-side action.

The guest needs a Git identity for its commits (`git config --global
user.name/user.email` inside the VM); the clones are VM-owned, so the old
`dubious ownership` workaround for shared checkouts no longer applies to
projects.

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
   D-114 extends this boundary to refreeze: node-id collection and the
   red-before-green check use only the inner Podman sandbox. Run operational
   refreezes in the VM; there is no macOS pytest fallback.
4. **Model server stays on the host (GPU).** The VM reaches it via the
   Lima host-gateway address (`host.lima.internal:1234`). The endpoint is
   resolved from explicit `SANDBOX_LLM_HOST`/`SANDBOX_LLM_PORT` values first,
   then `~/.config/sw-dev-blueprint/models.env`, with `localhost:1234` as the
   fallback (D-180). Lima sets `SANDBOX_LLM_HOST=host.lima.internal` in the
   VM environment, so that per-run authority wins over a host-side default.
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
6. **Copy-in / copy-out, no writable host mounts (D-205, supersedes D-196's
   four-project mount).** The only mount is `~/dev/sw-dev-blueprint`,
   read-only, so `swbp`, its helpers and `lima/splash-relay.py` run in the
   VM. Projects come in through `scripts/vm-sync start` and go back only
   through `scripts/vm-sync land` (see "Getting work into and out of the VM").
   Crash checkpointing (D-24) still works: `.pipeline-state` lives in the
   run's VM-disk clone, which survives a VM restart.

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
   The smoke test has two parts: (a) trivial prompt, assert non-empty
   reply (plumbing); (b) for the coder role, a sentinel-format
   micro-task — assert the reply contains a well-formed
   `=== FILE: ... === / === END FILE ===` block (M4: a coder model that
   cannot comply with the output convention burns both strikes before
   anyone learns it; catch that before the pipeline starts).
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

> Bookkept 2026-08-22 against recorded evidence; rows without evidence stay
> honestly open rather than being marked done by optimism.

- [x] A fresh `lima start <config>` + documented setup steps yields a VM
      where the criteria below hold, with **zero permission prompts** end
      to end — satisfied in operation by Vortex's unattended milestone runs.
- [x] `sandbox-run.sh` lanes verified working (constraint 2) — testchat
      sessions drove mapped pytest through the lanes and probed the
      isolation surface directly (`sandbox-run.sh -- sh -c 'id -u'` → uid
      1000, empty CapEff, no-new-privileges; testchat `tasks/CURRENT.md`
      session notes).
- [x] Container process cap holds at runtime — `scripts/selftest/verify-sandbox-in-vm.sh`
      check [7] reads `pids.max` inside the sandbox and expects
      `${SANDBOX_PIDS_LIMIT:-1024}`. Verified in the VM on 2026-10-06 at
      `bd36d47`: 12/12 checks passed, `pids.max is 1024`. Real workload
      (2026-10-07): testchat's 69 Playwright tests passed in the sandbox,
      peak 99 processes against the 1024 cap (D-206).
- [x] `llm-call.sh` round-trip to the host model server passes from inside
      the VM — exercised by every milestone's pre-flight smoke since D-55,
      including Vortex's three `[success]` runs (v1 `a6f6ec6`, v2
      `af7a157`, v3 `891042d`). *Inner-Podman leg:* no distinct recorded
      round-trip from inside the container itself — the lanes carry
      network-restricted pytest, not LLM calls; stated-but-unexercised
      until a lane genuinely needs model access.
- [x] A derived project's `orchestrate.sh` runs a full milestone
      unattended — Vortex v2/v3 completed end-to-end inside the dev VM
      with zero permission prompts (`[success] spec v2` = `af7a157`,
      `[success] spec v3` = `891042d`).
- [x] `orchestrate.sh` on the macOS host refuses to run (constraint 3) —
      mechanism in the `orchestrate.sh` pre-flight (`uname -s` Darwin
      check, hard `die`); live-probed 2026-08-22 on the macOS host: fails
      closed with the constraint-3 message before any other work.
- [ ] TPM shuttle copy/paste works via OSC 52 from the Mac terminal —
      **still open**: no recorded session has exercised the clipboard shim
      from the headless guest; TPM bundles so far traveled by conductor
      relay instead.
- [x] New DECISIONS.md entry recording the D-53 partial reversal — D-55
      (2026-07-05) records the cross-boundary model-access reversal and
      the round-trip smoke that guards it.
- [x] No host project writable from the VM (D-205) — verified live on
      2026-10-06: the only virtiofs mount is `~/dev/sw-dev-blueprint` and a
      write to it is refused; no other project is visible. Through the real
      VM, a `vm-sync` round trip landed one commit on the recorded base
      (the VM never saw the host's `.env`); a symlink commit was refused with
      the host byte-identical; landing with the VM stopped failed with the
      host byte-identical and no quarantine ref; after restart the same run
      landed. `swbp tpm-view` ran from the read-only builder against a
      VM-disk clone of vortex.
