# CEO Playbook — how to operate the pipeline

> You are the CEO. You make two kinds of decisions: **what to build**, and
> **whether to approve a spec change**. Everything else runs without you.
> This page is the complete operator's manual. It assumes nothing technical
> beyond talking to an AI and running a command you're told.
>
> (Operator runbook for the D-38/D-39 machinery — not the Quick Reference
> Card that D-01 pruned; nothing here restates BLUEPRINT.md rules.)

## Who talks to whom (read once)

You talk to the **TPM only**. You never brief the EM or the coder — the
orchestrator briefs them mechanically from the frozen spec. There is no
prompt to carry from the TPM to the EM; the frozen spec IS that handoff.
If you ever find yourself copy-pasting instructions to the EM, something
is being done wrong.

```
you ⇄ TPM (agent)  →  .tpm/outbox  →  your y/N  →  orchestrate.sh ⇄ EM/coder
                                                        │
you ←──────────── stuck? BATCH.md (TPM reads it itself) ┘
```

## One-time: create a project

Run `scripts/new-project.sh <name>` from the template (it pre-flights your
local LLM first), or tell any capable agent: "instantiate a project called
X from the sw-dev-blueprint template and adapt the stack per Rule 3."
Then `scripts/bootstrap.sh` inside the new project.

## Each milestone

1. **Start the TPM.** Run `scripts/tpm-agent.sh`. It launches a frontier
   agent already scoped to its lane (reads the repo except `src/`, writes
   only its outbox, runs nothing) and briefed on its role.
2. **State business outcomes in plain language.** For iterative builds:
   *"Break this into milestones. Spec milestone 1 only — design its
   interfaces so later milestones add to them without changing them."*
   Push back until the acceptance criteria say what you actually mean.
   The TPM reads the current frozen spec itself; you paste nothing.
3. **Approve.** When the TPM says the outbox is ready, run
   `scripts/refreeze.sh .tpm/outbox`. It shows you the complete diff and
   asks y/N. **Read it before you say y** — this is your real control
   point; everything downstream trusts what you approve here.
4. **Build.** Run `SANDBOX=1 scripts/orchestrate.sh` and walk away. It
   plans (EM), builds (coder), tests, retries, and escalates internally.
   - **Exit 0** — milestone done: every frozen test passes. A measurement,
     not an opinion.
   - **Exit 2** — it's stuck and has written a briefing. Tell the TPM:
     *"read .pipeline-state/escalations/BATCH.md and fix the spec."*
     Then step 3 again (approve its delta), and rerun orchestrate. Only
     affected work re-runs; finished tasks stay finished.
5. **Next milestone:** fresh TPM session (step 1). Continuity lives in the
   frozen artifacts, not the conversation.

## Fallback: TPM without repo access

If you'd rather run the TPM in a plain web chat (or don't have the agent
CLI): `scripts/tpm-pack.sh` puts the full briefing on your clipboard for
one paste; copy the TPM's reply and `scripts/tpm-unpack.sh` stages it;
then `scripts/refreeze.sh` as usual. Same trust model, one paste each way.

## Rules that keep you safe

- **The TPM must never see `src/`.** The tests are trustworthy precisely
  because their author has never seen the implementation. The harness
  blocks it, but back the machine up: never paste source into the TPM
  session, and if it claims it needs code to write tests, the contracts
  are incomplete — have it enrich `contracts.json` instead.
- **Freeze only the current milestone.** Keep the roadmap as conversation;
  approve contracts and tests one milestone at a time. What you freeze is
  locked; what you learn in milestone 1 should be free to improve
  milestone 2.
- **The diff prompt is not a formality.** Skim every diff; actually read
  the acceptance criteria and anything that *changes* a previously frozen
  file.
- **Watch for permission prompts during a TPM session.** The TPM's lane is
  pre-approved; if the harness asks you to approve a read or write outside
  it, that IS the alarm going off — deny it and ask the TPM what it was
  trying to do.
- **Don't negotiate with the pipeline.** If a run fails, the answer is
  never to hand-edit tests or gates — that's the "advisory safety" failure
  this system exists to prevent. Failures have one exit: the escalation
  bundle, through the TPM, through your y/N.
