# CEO Playbook — how to operate the pipeline

> You are the CEO. You make two kinds of decisions: **what to build**, and
> **whether the spec says what you asked for**. Everything else runs without you.
> You run **no commands** (D-40): your interface is a conductor chat —
> Claude Code, OpenCode's built-in Build agent, or any similar tool you
> prefer (D-53: the choice is a preference, not an architecture decision,
> since EM/coder never go through it) — which runs every script below and
> reports back in plain language. You never approve a freeze: the refreeze
> auto-applies on green preflights and there is no approval prompt (D-121).
>
> (Operator runbook for the D-38..D-42 machinery — not the Quick Reference
> Card that D-01 pruned; nothing here restates BLUEPRINT.md rules.)

## Who talks to whom (read once)

You talk to the **conductor** (for operations) and the **TPM** (for what to
build). You never brief the EM or the coder — the orchestrator briefs them
mechanically from the frozen spec. There is no prompt to carry from the TPM
to the EM; the frozen spec IS that handoff. If you ever find yourself
copy-pasting instructions to the EM, something is being done wrong.

```
you ⇄ TPM (agent or web chat)  →  .tpm/outbox
you ⇄ conductor (any chat agent) → refreeze --diff → you read the preview
        → auto-applies on green preflights (D-121) → orchestrate.sh ⇄ EM/coder
                                            (one HTTP completion each, D-53)
                                                        │
you ←── stuck? conductor reports; TPM reads BATCH.md ───┘
```

## One-time: create a project

Tell the conductor: "instantiate a project called X from the
sw-dev-blueprint template and adapt the stack per Rule 3." It runs
`scripts/new-project.sh` (which pre-flights whatever model you've loaded in
LM Studio — no specific model required, D-41) and `scripts/bootstrap.sh`.

## Each milestone

1. **Start the TPM.** Ask the conductor to launch `scripts/tpm-agent.sh`
   (or use a web chat — see Fallback). It's a frontier agent already scoped
   to its lane (reads the repo except `src/`, writes only its outbox, runs
   nothing) and briefed on its role.
2. **State business outcomes in plain language.** For iterative builds:
   *"Break this into milestones. Spec milestone 1 only — design its
   interfaces so later milestones add to them without changing them."*
   Push back until the acceptance criteria say what you actually mean.
   The TPM reads the current frozen spec itself; you paste nothing.
3. **Verify.** When the TPM says the outbox is ready, the conductor runs
   `scripts/refreeze.sh --diff .tpm/outbox` to preview the delta and its
   hash, then applies it once preflight-green (D-121, auto-apply — no
   approval flag exists). You are
   **not** expected to review code (D-44) — the machines
   already checked structure (INV-4, contracts schema) before you see
   anything. Your answer to one question matters: *"is this a change I asked
   for?"* Check the TPM's plain-language summary of WHAT the delta does
   against what you requested; if it isn't what you asked for, tell the TPM
   before the outbox is installed. Your real quality
   gate comes at step 5, not here.
4. **Build.** The conductor runs `SANDBOX=1 scripts/orchestrate.sh` and
   reports. The pipeline plans (EM), builds (coder), tests, retries, and
   escalates internally.
   - **Exit 0** — every frozen test passes. A measurement, not an opinion.
     This means "built as specified" — NOT yet "milestone done" (D-44).
   - **Exit 2** — it's stuck and has written a briefing. Tell the TPM:
     *"read .pipeline-state/escalations/BATCH.md and fix the spec."*
     Then step 3 again (install its delta), and the conductor reruns
     orchestrate. Only affected work re-runs; finished tasks stay finished.
5. **Try it — the milestone gate (D-44).** Ask the conductor to run the
   app and give you the URL (or command output). Use it the way a real
   user would; check it does what you meant, not what the spec said. This
   is YOUR test suite — outcomes, not code. A milestone closes only when
   both are true: the delta's mapped verdict green (D-112) AND you've accepted the prototype.
   If it passes tests but isn't what you meant, that's not a bug — the
   spec is wrong: back to the TPM (step 2) for the next delta.
   - **Record the hand-fix ledger at close-out (D-82).** Have the
     conductor count the live-fix commits made after `[success]`
     (`git log --oneline --grep='live-fix' <success-commit>..HEAD`) and
     record the number in `tasks/CURRENT.md`'s Results. Zero is the norm
     (testchat held it from M7 to M27). The count is your honest measure
     of what leaked past the frozen ACs: a spike (M28: eleven) means the
     spec under-pinned interaction detail — name that to the TPM at the
     next intake, don't just absorb the fixes.
6. **Next milestone:** fresh TPM session (step 1). Continuity lives in the
   frozen artifacts, not the conversation.

## Wrapping up (end of day, or before switching workloads)

The Lima dev-VM and warm LM Studio models are meant to stay resident
between runs (D-55, D-72) — cold Lima boot is ~60s and a cold model load
~120s, so auto-teardown after every pipeline run costs real seconds every
run for no gain. Nothing self-cleans automatically. Two operator-invoked
tools handle the moments where you want the resources back (D-97):

- `scripts/status.sh` — read-only report of what's resident (Lima state,
  LLM ports, podman containers, pipeline-state sizes, disk). Run any time.
- `scripts/teardown.sh` — reclaim per explicit flags. Bare invocation
  prints help; `--dry-run` shows the plan without touching anything.
  Common flows:
  - end of day, freeing everything you can:
    `scripts/teardown.sh --all --lima` (adds Lima stop — opt-in outside
    `--all` because it's the biggest cost to reverse)
  - between milestones, keeping the VM and models warm:
    `scripts/teardown.sh --state --caches --containers`
  - `--em-archive` is opt-in even under `--all` — the corpus feeds the
    EM-diagnosis A/B backlog item; only wipe it when you know.

## Fallback: TPM without repo access

If you'd rather run the TPM in a plain web chat (or don't have the agent
CLI): the conductor runs `scripts/tpm-pack.sh` and gives you the briefing
for one paste into the chat; you paste the TPM's reply back to the
conductor, which stages it via `scripts/tpm-unpack.sh`; then step 3 as
usual. Same trust model — you copy text between two chats, nothing more.

## Rules that keep you safe

- **The TPM must never see `src/`.** The tests are trustworthy precisely
  because their author has never seen the implementation. The harness
  blocks it, but back the machine up: never paste source into the TPM
  session, and if it claims it needs code to write tests, the contracts
  are incomplete — have it enrich `contracts.json` instead.
- **Freeze only the current milestone.** Keep the roadmap as conversation;
  contracts and tests freeze one milestone at a time. What you freeze is
  locked; what you learn in milestone 1 should be free to improve
  milestone 2.
- **Make sure it's what you asked for.** You don't read code; you match the
  TPM's plain-language description of the delta against your own request.
  If a delta appears that you didn't ask for, tell the TPM to rewrite
  before the next freeze. Your
  technical protection is the gates; your product protection is step 5.
- **Watch for permission prompts.** There is no refreeze approval prompt —
  refreeze applies once preflight-green (D-121). Any permission prompt
  asking you to authorize a refreeze/apply/update involving `tests/`, `scripts/`, `src/`, or the control plane — IS the
  alarm going off: deny it and ask the agent what it was trying to do.
- **Don't negotiate with the pipeline.** If a run fails, the answer is
  never to hand-edit tests or gates — that's the "advisory safety" failure
  this system exists to prevent. Failures have one exit: the escalation
  bundle, through the TPM, back through the refreeze preflights (D-95:
  the material verdict is the gates passing, not a keystroke after).
- **A new milestone's spec is next-session work by default.** Both
  defect-bearing M28 freezes (v51 23:34, v52 23:49) were authored minutes
  after closing the prior milestone (22:50), at the end of a long session,
  across a pause/resume and model changes. Spec authoring is the highest
  blast-radius activity in the system (Rule 9); it deserves a fresh head.
  If you must freeze same-session, at minimum pause and re-read the contracts
  from scratch — fatigue-authored specs cost more to fix downstream than the
  session-end urgency saves. The old freeze-time D-83 freshness note was retired
  (D-115): it fired ~0.04s per freeze but never once changed a freezing
  behavior, and the failure mode it targeted — fatigue-authored specs — is
  caught by the Rule 9 statement above, not by a script timing the last
  `[success]`.
