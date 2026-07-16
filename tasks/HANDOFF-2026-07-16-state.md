# HANDOFF — sw-dev-blueprint state, 2026-07-16

> Template-repo session handoff (not a child project's). Supersedes
> HANDOFF-2026-07-15-state.md. Verify every claim against the tree before
> repeating it: `git log`, `pytest scripts/selftest/selftest_gates.py -q`,
> and the children's own histories.

## Where the template stands

- HEAD `e2077f7`, pushed to origin, working tree clean, CI green.
- **66 selftests green** (was 61). Decisions through **D-71**.
- Landed this session (2026-07-16), one concern per commit:
  - `959a663` **D-71** EM diagnosis hardened: `task_id` removed from the
    reply surface (the shell stamps it — the M23 empty-task_id failure is
    structurally impossible), inline literal example in the consult prompt,
    one retry carrying the validator's errors before the halt. First
    selftests for `consult_em` (`scripts/selftest/drive-consult.sh` extracts
    the REAL functions from orchestrate.sh and drives them against a
    scripted fake EM — never a copy).
  - `cbd9285` fix: every create-mode (new-file) coder call had been dead
    since the M17 edit-budget change — orchestrate exports
    `SWBP_MAX_OUTPUT=""` for create mode and `int(os.environ.get(v, 0))`
    raises on empty (default covers unset, not empty). Now `int(... or 0)`.
  - `b24c335` fix: pre-flight fails closed on missing git identity — the
    `[plan]`/`[task]` commits swallow failures on purpose (nothing-to-commit
    is normal), which also swallowed "no user.email", so every pipeline
    commit in the dev VM silently no-op'd.
  - `8e35ef0` / `9bd98bc` / `e2077f7` — handoff/ledger bookkeeping.

## Gate validation ledger (Rule 6: untriggered ≠ working)

Live-fire status after the **scratch-rung ladder drill** (2026-07-16):
a disposable child (since deleted on CEO directive) whose ERD said
`double(n) = n*2` while its frozen test demanded `double(2) == 5` — the
contradiction lived only in the PRD, which EM/coder never see. Two runs,
both halting exit 2 with a self-contained bundle.

Plus the **scratch-decomp drill** (2026-07-16, later same day): a second
disposable child (`~/dev/scratch-decomp`, kept for now) with a clean
two-file spec (`api.compute` must delegate to `helpers.scale`) and a
rigged plan — T1 (`src/api.py`) with `depends_on: []` so the frozen
delegation test fails on the missing helper. One run, exit 0.

| Gate | Live fire | Evidence |
|------|-----------|----------|
| Ladder: retry rung (strike 1→2) | ✅ | both drill runs + testchat M23 |
| Ladder: EM consult | ✅ | 4 consults: 3 across the scratch-rung runs + 1 in scratch-decomp |
| Ladder: D-71 diagnosis validation | ✅ | **3/3 observed diagnoses schema-valid first-try**; run 2's was factually perfect (named the node-id, quoted the 4≠5 contradiction). The scratch-decomp diagnosis was valid (route fired) but its stdout didn't survive, so first-try vs D-71-retry is unknown for that one |
| Ladder: D-71 retry rung | ◐ | 5 selftests + live probes green; never OBSERVED needed live (all observed diagnoses passed first-try) |
| Verdict routing: `brief_wrong` | ✅ | run 1 — revision applied, strikes reset, re-ran |
| Verdict routing: `contract_or_test_wrong` | ✅ | run 2 — routed straight to spec-wrong escalation |
| Verdict routing: `decomposition_wrong` | ✅ | scratch-decomp drill — EM re-emitted plan v2 (T1 gained `depends_on: ["T2"]`, child `4ff5faa`), re-validated, strikes reset, run finished green (`66c6b9b`, 6/6 frozen tests) |
| TPM bundle + BATCH.md + exit 2 | ✅ | both kinds: caps-exhausted (run 1), spec-wrong (run 2); bundles self-contained with embedded diagnosis |
| D-65 no_edit_files | ✅ | testchat M23 (4 no-op tasks skipped coder) |
| D-67 refreeze lint | ✅ | live-triggered via lint-bait (2026-07-15) |
| D-68 swallowed-error | ◐ | has never yet FAILED a live coder attempt |
| D-69 run budget | ❌ | never breached; timing table works |
| b24c335 git-identity pre-flight | ◐ | selftest-free one-liner; will live-fire on any identity-less clone |

## Top open template work

1. **Opportunistic rung** — a live D-71 retry (`decomposition_wrong` closed
   via the scratch-decomp drill). Selftest-covered; not forceable
   deterministically — all live diagnoses so far have been schema-valid
   first-try. When a real child consult produces one, capture it here.
2. **ci.yml never syncs to children** (`.manifest-project`): hand-apply CI
   fixes to existing children (testchat: done, `6ba8cc2` + `f79f0d2`). New
   children inherit via clone.
3. Standing backlog: coverage ratchet after CI measures testchat's suite;
   cheap-tier publish decision (CEO's, still open); EM-collapse experiment
   and TurboQuant bench (icebox); LM Studio housekeeping (delete
   `unsloth/qwen3.6-27b-mlx`, benched strictly worse).

## Running the pipeline — facts that cost time this session

- **Split-brain execution model:** the freeze ceremony (`refreeze.sh`) runs
  on the **macOS host** (homebrew ruff + podman; start the machine first:
  `podman machine start`). `orchestrate.sh` runs **only inside dev-vm**
  (hard die on Darwin). Sandbox images are per-side — host podman and VM
  podman are separate stores; a cold build is ~10 min of pip install.
  Pre-warm with `scripts/sandbox-run.sh -- true` on BOTH sides before a
  first run, or refreeze/orchestrate will eat the build inside a timeout.
- **VM run invocation** (from the child dir; the host `~/dev` mount is
  writable in the VM):
  `limactl shell dev-vm -- bash -c 'SANDBOX_LLM_HOST=host.lima.internal SANDBOX_LLM_PORT=8000 bash scripts/orchestrate.sh'`
  — orchestrate's pre-flight curl does NOT read models.env; without those
  exports it probes localhost:1234 and dies.
- **Model seating:** VM `~/.config/sw-dev-blueprint/models.env` maps both
  seats to `mtplx-qwen36-27b-optimized-quality` @ host.lima.internal:8000
  (verified live this session). The VM copy is the one the pipeline reads;
  the host copy (`qwen/qwen3.6-27b` @ 1234) serves host-side probes only.
  CEO-owned — see the models.env rules in CLAUDE.md's correction log.
- **VM git identity is now set** (`pipeline@dev-vm.local` / `swbp-pipeline`,
  global) and pre-flight enforces it (`b24c335`).
- **Children cloned from the local template** need `git pull --no-rebase`
  (no pull.rebase default configured) and their own git identity.
- **A deliberate full-ladder run needs a bigger budget**: it has more phases
  than a healthy run by design — `SWBP_RUN_BUDGET=2400` worked; the default
  1200 is for healthy runs.
- docs/ and ci.yml never sync to children; verify syncs by content not exit
  code; both manifests regen in the same commit; probe after every seat
  change.

## Child status (one line each)

- **testchat**: spec v45, M24 CEO-accepted (`ab0f983`), main == origin,
  maintenance mode, CI green. Its `tasks/CURRENT.md` carries the milestone
  chronicle + TPM lessons.
- **spark / sparkv2**: pre-capability-ladder, untouched by design — never
  run `update-template.sh` on them.
- **scratch-rung**: deleted 2026-07-16 post-drill (CEO directive). Its
  evidence lives in the ledger above, the two fix commits, and CLAUDE.md's
  correction log — not in the child.
