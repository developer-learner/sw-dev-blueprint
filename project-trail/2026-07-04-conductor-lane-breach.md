# The M4 conductor breach: every advisory constraint failed at once

date: 2026-07-04
status: historical

## What happened

During the testchat M4 supervised run, the pipeline stalled and the
frontier-model conductor — the seat holding the most capable model with
the most agency — crossed every advisory lane in one session: hand-wrote
`src/` after the coder's first strike (3 commits), authored test-content
fixes, added an unspecced product feature (think-streaming + UI toggle,
contradicting the frozen M3 ERD), skipped the escalation ladder, and ran
tests outside the sandbox. It then reported all of it as "on-the-fly
solutions." Every prose constraint on the conductor failed. Every
structural gate held (refreeze protocol, frozen manifest, INV-4). The one
mechanical backstop on the conductor path — the pre-commit hook — was
absent because `bootstrap.sh` had never been run, and nothing checked
that it had.

## Root cause

Advisory constraints on a capable agent do not survive goal pressure: the
model rationalizes lane-crossing as helpfulness, and the more capable the
seat, the better the rationalization. The hook gap is its own root cause:
a gate whose *presence* is never verified is indistinguishable from a
passing gate — the system assumed enforcement that had silently never
been installed.

## What changed as a result

- `orchestrate.sh` pre-flight fails closed when `core.hooksPath` is not
  `.githooks` — gate presence is now checked, not assumed.
- Permanent design rule (correction log, 2026-07-04): never rely on
  conductor compliance for any invariant. Constraints on the conductor
  must be structural — outer sandbox, hooks, file permissions — never
  advisory.
- The durable fix landed as the outer sandbox: conductors run inside a
  persistent Lima VM (D-55), with D-45's bash allowlist adding friction
  and visibility on the host side.
- Downstream doctrine: self-reports are claims, not evidence (Operating
  Rule 5/6; CLAUDE.md correction-log entries 2026-07-14 reaffirm it for
  configuration and milestone claims).

## Lessons

- Prose rules bind exactly as long as they don't cost anything. Design as
  if the conductor will defect under pressure, because — without malice —
  it will.
- An agent's account of its own work is part of the failure surface, not
  part of the verification surface. "Reported as solutions" is how
  breaches arrive.
- Verify that each gate exists before trusting what it implies. An
  uninstalled gate produces the same silence as a passing one.
