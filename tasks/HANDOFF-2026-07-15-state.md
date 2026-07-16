# HANDOFF — sw-dev-blueprint state, 2026-07-15

> Template-repo session handoff (not a child project's). Verify every claim
> against the tree before repeating it: `git log`, `pytest
> scripts/selftest/selftest_gates.py -q`, and the child's own history.

## Where the template stands

- HEAD `41491d9`, pushed to origin, working tree clean.
- 61 selftests green. Decisions through **D-70**.
- Landed this round (2026-07-14/15), one concern per commit:
  - `015e17e` ci.yml: `mypy --explicit-package-bases` (bare mypy exits 2 on
    duplicate module basenames before checking anything).
  - `ada440e` **D-67** refreeze lint gate: staged tests must pass ruff at the
    freeze door; fail-closed on missing ruff.
  - `3093bdb` **D-68** swallowed-error gate: comment-less `except: pass` /
    empty JS `.catch()`/`catch{}` in coder output = task strike, both apply
    modes (`scripts/check-swallowed-errors.py`); TPM-ROLE law: every
    side-effect needs a failure-visibility AC.
  - `be53cb4` ci.yml test step made actually runnable: PYTHONPATH, Playwright
    chromium install (skips cleanly for no-playwright projects), `.cache` dir.
  - `883bf99` **D-69** run wall-clock budget + phase-timing log (other session).
  - `41491d9` **D-70** MAX_TASK_STRIKES defaults to 2 — ladder armed (CEO
    directive; other session).

## Gate validation ledger (Rule 6: untriggered ≠ working)

Live-fire status as of testchat M23 (`[success] spec v44`, CEO-accepted):

| Gate | Live fire | Evidence |
|------|-----------|----------|
| D-65 no_edit_files | ✅ | 4 no-op tasks skipped coder, acceptance ran (M23 T3–T6) |
| D-67 refreeze lint | ✅ | green at 4 freezes; die() live-triggered via lint-bait staging in `--diff` mode |
| D-68 swallowed-error | ◐ | flagged the real `threads.js:25` standalone; passed clean coder output in production; has never yet FAILED a live coder attempt |
| D-69 run budget | ❌ | never breached (M23 runs were short); timing table works |
| Ladder: retry rung | ✅ | T7 strike 1→2, failure appended to retry brief |
| Ladder: EM consult | ✅ | fired after strike 2 |
| Ladder: diagnosis schema gate | ✅ | refused schema-invalid diagnosis (empty task_id), halted correctly |
| Ladder: verdict routing (brief_wrong / decomposition_wrong / spec-wrong) | ❌ | **unexercised — no production EM diagnosis has ever validated** |
| Ladder: TPM escalation bundle | ❌ | never emitted in production |

## Top open template work

1. **EM diagnosis hardening (highest value).** The MTPLX 27b plans cleanly
   (3rd plan valid at M23) but its consult diagnosis came back
   schema-invalid — same mid-tier weakness as the 122B ("weak on live
   consult", D-66 family). Candidates, pick one and selftest it:
   (a) one schema-retry with the validation error appended (mirror the
   plan-revision pattern); (b) diagnosis prompt carries an inline literal
   example of a valid reply; (c) shrink the reply surface to a verdict enum +
   free-text reason, shell fills the rest. Until fixed, every 2-strike task
   dead-ends at the diagnosis gate.
2. **Exercise the unexercised rungs** — verdict routing and bundle emission
   have never run. Cheapest path: a scratch child with a deliberately
   caps-exhausted task; watch BATCH.md get written and a verdict route.
3. **ci.yml never syncs** (`.manifest-project`): the two CI fixes reach
   existing children only by hand (testchat: done, `6ba8cc2` + `f79f0d2`).
   New children inherit via clone. Remember for any other child revived.
4. Standing backlog: fast-path declined (`128dfcd`, CEO); coverage default
   stays 80 in the template (testchat runs 75 as a project adaptation —
   platform-variance: mac-only code paths measure lower on Linux runners);
   EM-collapse experiment, TurboQuant bench (icebox); cheap-tier publish
   decision (CEO's, still open).

## Serving/config facts that bit people before

- **MTPLX endpoint proven in production** (testchat M23, both seats):
  `mtplx-qwen36-27b-optimized-quality` at 32K ctx, reasoning off via server
  CLI flags — immune to the LM Studio reload-drift problem; 36–57 tok/s.
  From inside the VM the host endpoint is `host.lima.internal:8000`.
- `models.env` + `model-profiles.toml` are **CEO-owned**; the pipeline reads
  the **VM copy** (`llm-call.sh` sources models.env, including
  `SANDBOX_LLM_HOST/PORT`). Any seat change: apply in the VM, then verify by
  a real round-trip probe through `llm-call.sh` per role — a config edit is a
  claim, not evidence.
- Verify every template→child sync **by content** (`cmp` against the
  template), never by exit code (the D-59 silent no-op sync).
- `docs/` never syncs to children — child-facing TPM guidance must ride
  `.opencode/prompts/` or be hand-copied (D-68's TPM-ROLE law was
  hand-copied to testchat).
- Any control-plane edit: regenerate BOTH manifests in the same commit.

## Child status (one line each)

- **testchat**: spec v44, M14–M23 all CEO-accepted, CI green
  (first in its history, 2026-07-15), feature-complete → maintenance mode.
  Its `tasks/CURRENT.md` carries the full M23 chronicle + TPM lessons.
- **spark / sparkv2**: pre-capability-ladder; do NOT run update-template.sh
  on them — migration is a separate human decision.
