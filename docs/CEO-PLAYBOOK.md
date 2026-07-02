# CEO Playbook — how to operate the pipeline

> You are the CEO. You make two kinds of decisions: **what to build**, and
> **whether to approve a spec change**. Everything else runs without you.
> This page is the complete operator's manual for those two jobs. It assumes
> nothing technical beyond copy, paste, and running a command you're told.
>
> (This is an operator runbook for the D-38 shuttle scripts — not the
> Quick Reference Card that D-01 pruned; nothing here restates rules or
> diagrams from BLUEPRINT.md.)

## The loop at a glance

```
you state intent  →  TPM writes spec+tests  →  you approve (y/N)
      ↑                                              ↓
      └──── stuck? BATCH.md back to TPM ←──── pipeline builds until green
```

Your two commands: `scripts/tpm-pack.sh` (brief the TPM) and
`scripts/tpm-unpack.sh` (bank its reply). Everything between them is chat.

## Start a milestone

1. **Pack the briefing.** Run `scripts/tpm-pack.sh`. The full TPM briefing —
   job description, schema, and the current frozen spec if one exists — lands
   on your clipboard. You never pick files by hand.
2. **Open a FRESH chat** with a top-tier LLM and paste. One paste; that chat
   is now your TPM for this milestone. (Fresh chat every milestone — chat
   memory drifts; the pack bundle carries the real state.)
3. **State your intent in business terms.** Plain language. For iterative
   builds, say so explicitly, e.g.: *"Break this product into milestones.
   Spec milestone 1 only — design its interfaces so later milestones can add
   to them without changing them."* Answer the TPM's clarifying questions;
   push back until the acceptance criteria say what you actually mean.
4. **Bank the reply.** When the TPM delivers the spec (files wrapped in
   `=== FILE: ... ===` blocks), copy its whole reply, then run
   `scripts/tpm-unpack.sh` (reads your clipboard; `--force` replaces
   leftovers from a previous round). It stages everything and rejects
   anything malformed — if it complains, tell the TPM to resend in the
   mandatory format.
5. **Approve — this is your real power.** Run `scripts/refreeze.sh`. It shows
   you the complete diff and asks y/N. **Read it before you say y.** This
   y/N is the only door into the frozen spec; everything downstream trusts
   what you approve here.

## Run the build

6. Run `SANDBOX=1 scripts/orchestrate.sh` and walk away. It plans, builds,
   tests, retries, and escalates internally without you.
   - **Exit 0** — milestone done: every frozen test passes. Not an AI's
     opinion; a measurement.
   - **Exit 2** — the pipeline is stuck and has written you a briefing:
     paste `.pipeline-state/escalations/BATCH.md` into the SAME TPM chat,
     in one message. The TPM returns a fix as `=== FILE: ... ===` blocks →
     `tpm-unpack.sh` → `refreeze.sh` (y/N again) → rerun
     `scripts/orchestrate.sh`. Only affected work re-runs; finished tasks
     stay finished.

## Next milestone

7. Go back to step 1. `tpm-pack.sh` now automatically includes the frozen
   spec from the last milestone, so the new TPM chat designs its delta
   against ground truth.

## Rules that keep you safe

- **Never paste source code (`src/`) into the TPM chat.** The tests are
  trustworthy precisely because their author has never seen the
  implementation. If the TPM says it needs the code to write tests, the
  contracts are incomplete — ask it to enrich `contracts.json` instead.
- **Freeze only the current milestone.** Keep the roadmap as conversation;
  approve contracts and tests one milestone at a time. What you freeze is
  locked; what you learn in milestone 1 should be free to improve milestone 2.
- **The diff prompt is not a formality.** Everything the TPM produces enters
  through your y at `refreeze.sh`. Skim every diff; actually read the
  acceptance criteria and anything that *changes* a previously frozen file.
- **Don't negotiate with the pipeline.** If a run fails, the answer is never
  to edit tests or gates by hand — that's the "advisory safety" failure this
  whole system exists to prevent. Failures have exactly one exit: the
  escalation bundle, through the TPM, through your y/N.
