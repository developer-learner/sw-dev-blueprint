# DECISIONS.md — Architectural Decision Log

> Every non-obvious technical decision goes here with the reasoning.
> This prevents the LLM from "helpfully" undoing choices you already made.
> Format: date, decision, why, what not to suggest.

---

## Template

```
## YYYY-MM-DD — [Decision title]

**Decision:** [What was decided]
**Alternatives considered:** [What else was evaluated]
**Reason:** [Why this choice was made]
**Do not suggest:** [What the LLM should not propose as a "fix"]
```

---

## Decisions

## D-61 — 2026-07-11 — Template updates gain hash-bound approval (`--approve <DIFF-SHA>`): the D-42 refreeze pattern applied to the second protected-artifact class

**Decision:** `update-template.sh` gains `--approve <sha>`, mirroring refreeze's D-42 flow: `--dry-run` (and `--review`) print the `DIFF-SHA` — sha256 of the exact aggregate diff text — and `--approve <sha>` recomputes it and applies only on a byte-exact match, no tty required. Any change to the template or the child between review and approval changes the hash and fails closed. The interactive y/N path is unchanged and remains the default.

**Found by:** the 2026-07-11 session: the CEO authorized a reviewed template pull in chat, but the script's only non-interactive options were `--dry-run` (read-only) — so the conductor answered the y/N prompt itself through a pty wrapper (`expect`). That apply was correct and disclosed, but it is exactly the honor-string approval D-42 rejected: nothing bound what the CEO read to what got applied. The gap was structural — D-34 explicitly rejected generalizing refreeze into one engine and accepted "a shared pattern with two small tools," but only one of the two tools ever got the pattern's non-interactive half.

**Alternatives considered:** keep tty-only and forbid conductor-driven pulls (rejected — the CEO runs no commands, D-40; every real pull would either need the human at a terminal or the pty workaround this exists to retire); `--yes` flag (rejected for the same reason as refreeze — it approves whatever is true at run time, not what was reviewed); generalizing refreeze and update-template into one approve-delta engine (still rejected per D-34 — this change is ~15 lines precisely because the pattern is shared and the tools are not).

**Honest caveat (same as D-42):** the CEO sees the diff through the conductor's relay; a misreporting conductor could show doctored text beside the true hash of different content. The raw diff is deterministic and re-printable at any time, the terminal path remains for structural updates, and the blast radius is one control-plane update caught by the template's selftests and the next run's gates. Accident-class threat, accepted; not zero.

**Do not suggest:** adding `--yes`/`--force`; approving on a stale hash after either side moved; retiring the interactive path.

---

## D-60 — 2026-07-09 — Task sizing is governed by the coder's measured bare-completion capability, encoded where the tiers read it

**Decision:** The coder-capability profile (one concern per brief; new files well under ~150 lines; existing files touched via at most two tightly-related edits; brief must fit the model's working memory — no tools, no retries) is LAW in the prompts the planning tiers actually read: em.md (task decomposition) and TPM-ROLE.md (milestone/ERD cutting). External benchmark claims (SWE-bench, 256K contexts) do not transfer — they assume agent scaffolds with tools and retries, which D-53 deliberately forbids; only the project's own bench and run evidence updates this profile.

**Found by:** CEO directive after M7 ("we have known from the start the 27b needs atomic tasks... the control plane seems to have drifted on this"). The knowledge lived in bench notes and conductor memory, not in any prompt a planning tier reads — so M7's ERD bundled three concerns into one brief twice, and nothing mechanical objected.

**Do not suggest:** relaxing sizing because a bigger context window ships; importing external agent-benchmark numbers as capability evidence; moving the sizing law to docs the EM never sees.

---

## D-59 — 2026-07-09 — The coder edits existing files through anchored blocks; it never retypes them

**Decision:** For a task whose file already exists, the coder's reply contract is anchored edit blocks (`<<<<<<< SEARCH` exact-verbatim existing lines `=======` replacement `>>>>>>> REPLACE`), applied by `scripts/apply-edit-blocks.py` — fail-closed: every anchor must match the target exactly once; a missing/ambiguous anchor or truncated block writes nothing. `=== NO CHANGES ===` is a legal no-op reply (mapped tests still gate). New files keep the full-file sentinel contract. Companion rules from live corruption incidents: anchors must not include lines containing think-tag literals, new code constructs such strings by concatenation, and `llm-call.sh` strips only a LEADING think block (a global strip eats code that legitimately mentions the tags).

**Found by:** testchat M5..M7. The full-file contract asked a local coder to faithfully retype hundreds of lines it wasn't changing; it deleted 99 lines (v10, 638-line file) and 119 lines (v14, 347-line file, 16K ctx) of working logic — proving the failure is the output format, not file size or context. Controlled CEO-run experiments with edit blocks on the identical tasks: 11/11 anchors verbatim-exact across three replies, both behavior fixes correct, 67/67 frozen tests green including the browser suite. The model consistently aced the thinking and flunked the typing; this contract removes the typing.

**Alternatives considered:** unified diffs (rejected — line-number arithmetic is precisely what local models get wrong); rejecting edit output entirely, per the 2026-07-07 evaluation (overturned — that evaluation weighed diff-apply risk against full-file regeneration assumed safe; the deletion evidence reverses the risk comparison, and fail-closed anchoring converts apply-risk into a loud halt instead of silent corruption); larger/frontier coder models (still available via escalation, but the format fix makes the bench-chosen local coder sufficient).

**Do not suggest:** "simplifying" back to full-file replies for existing files; fuzzy/whitespace-tolerant anchor matching (exactness is the safety property); letting the applier skip unmatched blocks and apply the rest (all-or-nothing, fail-closed); global think-tag stripping in llm-call.sh.

---

## D-58 — 2026-07-08 — Browser oracle: the frozen suite sees the frontend; the locked surface extends to the DOM (contracts.ui)

**Decision:** The TPM authors browser-level tests (Playwright for Python) as ordinary members of the frozen suite — plain pytest node-ids, entering via `refreeze.sh`, collected into `test-nodeids`, mapped by the EM, run by the shell; no second framework, runner, or gate script. Chromium + playwright are baked into the sandbox image at build time (network exists at build; the run keeps `--network none` — app and browser share the container over loopback). The locked surface extends to the DOM: `contracts.json` gains a `ui` array of `{id, testid, description}`; `check-test-surface.py` rejects, in any playwright-importing test file, element location that is not a locked `data-testid` (role/text/label locators and raw CSS/XPath selection fail at freeze time). `refreeze.sh` grep-rejects `time.sleep`/`wait_for_timeout` in staged UI tests. Flake policy: zero retries — a flaky frozen test is a spec defect and goes back to the TPM. Every AC describing user-visible behavior maps to at least one frozen UI node-id or carries an explicit `manual-only:` waiver in the PRD.

**Found by:** testchat M5 and M6, identical anatomy: full green suite, broken app, finished by hand. M6's committed `index.html` discarded think-events entirely (`replyText += ''`) and locked the model selector globally (failing AC-23) — invisible to pytest because the defects live in browser-executed JS the suite never runs. The consequence chain: oracle weaker than the goal → the human is the real acceptance oracle, post-hoc → hand-fixes land outside the pipeline → nothing defends them → the next full-file rewrite regresses them (think-toggle broke twice). Tracked metric: hand-fix commits after `[success]` (M5: 4 + debug session; M6: 2 dirty src files + hotfix).

**Alternatives considered:** Screenshot/visual-diff oracle (rejected — non-deterministic, locks pixels instead of behavior); a separate UI test runner outside the frozen suite (rejected — a second oracle with its own gates is drift surface, and its verdicts would compete with the frozen one); letting UI tests use arbitrary selectors (rejected — whatever tests observe is thereby locked, INV-4; arbitrary selectors would freeze the coder's entire DOM by accident); a second browser-free "light" image (rejected — two images is drift surface, constraint 4); running the browser outside the sandbox (rejected — reopens the exfiltration hole the sandbox closes).

**Do not suggest:** retry-on-flake for UI tests (converts the oracle into a suggestion); `wait_for_timeout`-based synchronization (auto-waiting is the law); giving the coder or EM a browser (D-53 — the browser lives in the test path, not the model path); diff-based coder output to offset larger frontend files (evaluated and rejected 2026-07-07 — the ERD splitting the frontend into more files is the sanctioned fix).

---

## D-57 — 2026-07-07 — The carried-forward regression bucket is computed by the shell, never emitted by the EM

**Decision:** `plan.regression` is retired. `validate-plan.py` now computes the carried-forward split itself, from the ownership signals its reachability gates already extract: an unmapped frozen node-id whose test file imports a task-owned module at module level, or whose test body makes an AST-visible call to a route some task claims, belongs to this delta and MUST be mapped (decomposition incomplete, named per node-id); every other unmapped node-id is a carried-forward regression test, auto-assigned, with the final full-suite run as its acceptance point. A plan carrying a `regression` key is rejected outright (same class as status fields — orchestrator bookkeeping is never the EM's to emit). The plan schema drops the field, so schema-constrained generation cannot produce it. Fail-open by construction: a dynamic import or built-up path hides the ownership signal, which can only move a test INTO regression — it still gates the run at the end, just not per-task. Mapped-but-unownable node-ids remain legal (the EM may know a relationship the AST cannot see).

**Found by:** testchat M6 (2026-07-07). The EM (a 122B model) failed twice to transcribe the 58-element regression array into valid JSON, and the conductor hand-wrote `tasks/plan.json` on CEO order — a lane violation by fiat in the first milestone where the conductor otherwise stayed in-lane. The bucket's definition ("node-ids testing files not in this delta's inventory") requires no judgment; asking the least reliable tier to do derivable bookkeeping was the pipeline outsourcing its own job.

**Alternatives considered:** keeping EM-emitted regression with more revisions (rejected — bench data shows the EM task is structured output, not intelligence; the failure mode is transcription volume, which grows with every milestone as the suite accretes); auto-bucketing ALL unmapped node-ids with no ownership check (rejected — a lazy or degenerate EM could map nothing and every test would silently drift to end-of-run acceptance; the ownership signal keeps per-task early failure detection mechanically demanded exactly where it is mechanically derivable).

**Do not suggest:** Re-adding a regression field to the plan schema "for EM transparency"; making mapped-but-unownable node-ids an error (the AST signal is deliberately fail-open); pre-filtering test-nodeids out of the EM's context based on ownership — the EM still needs the full list to map from.

---

## D-56 — 2026-07-06 — External interfaces enter the spec only as captured reality (contracts.externals + frozen captures)

**Decision:** `contracts.json` gains an optional `externals` array: every external interface the spec makes assumptions about (third-party APIs, model output/streaming formats, wire protocols) is declared as `{id, probe, capture}`. The `probe` is the exact command the operator ran against the real dependency; the `capture` is its raw recorded output, staged under `captures/` and installed to `scripts/.approved/captures/`, hash-pinned in the frozen manifest like every other frozen artifact. `refreeze.sh` fails closed if a declared capture is missing (or is invalid JSON for `.json` captures), and rejects staged captures no external references. The TPM authors mocks and tests from captures, never from memory of how the dependency probably behaves; the probe-first loop (TPM requests probes → operator runs them → pastes raw output) happens before spec authoring.

**Reason:** testchat M5 shipped a fully green frozen suite over an app that didn't work. Every post-success hand-fix was a spec-vs-reality mismatch: the real LM Studio models endpoint is `/api/v1/models` returning `{"models":[{"key":...}]}` (spec assumed OpenAI-style `/v1/models` + `data[].id`), and the real model streams thinking as `delta.reasoning_content` (spec assumed inline `<think>` tags). Mocked tests are a fixed-point check — they verify code-matches-spec, and cannot verify spec-matches-world. The gap was structural: no gate required the TPM's external-interface assumptions to be grounded in anything. Same failure tier as the v6 no-oracle incident: TPM, not EM/coder.

**Alternatives considered:** live integration tests in the frozen suite (rejected — the sandbox is offline by design, and live tests make the gate flaky and environment-dependent); prose-only rule in TPM-ROLE.md (rejected — advisory rules on LLM tiers are suggestions; every hard-won guard here is mechanical); a separate contract-check script in the run loop (rejected — heavier, and the run loop is the wrong place: the error is made at freeze time, so the gate belongs at freeze time).

**Cost accepted:** one extra loop at spec time (probe → paste → author). Captures can go stale when the upstream changes; the recorded `probe` makes re-verification a one-liner, and staleness surfaces at CEO acceptance (D-44) exactly as before — this narrows the gap, it does not claim to close it.

**Do not suggest:** letting the TPM skip captures for "well-known" APIs (the M5 miss WAS a well-known API shape); making captures advisory; running probes from inside the sandbox at test time.

---

## D-55 — 2026-07-05 — Linux dev VM boundary; D-53 partial reversal for cross-boundary model access

**Decision:** Conductors move inside a persistent Lima VM (Ubuntu 24.04, virtiofs mount of `~/dev`). The VM is the structural boundary that replaces advisory conductor constraints; agents run with permissions bypassed because the VM is the containment. `orchestrate.sh` refuses to run on macOS (`uname -s` check, hard halt). D-30 Podman lanes run unchanged inside the VM as native rootless containers — same nesting depth as the previous `podman machine` arrangement on the host.

**D-53 partial reversal (cross-boundary model access):** D-53 moved LLM calls host-local precisely because cross-boundary port wiring caused the failures of the first three supervised runs. The VM boundary reintroduces cross-boundary access: `SANDBOX_LLM_HOST` (default `localhost`, set to `host.lima.internal` in the VM) parameterizes the endpoint in `llm-call.sh` and `orchestrate.sh`. This is accepted as the cost of the VM boundary. A round-trip smoke test (`llm-call.sh` with a trivial prompt, assert non-empty reply) runs in `orchestrate.sh` pre-flight to catch plumbing bugs — the class of failure that was invisible to static review and caused the misdiagnosed "model hallucinations" in early runs (correction log 2026-07-03).

**Alternatives considered:** keeping conductors on the host with advisory constraints (failed — testchat M4 proved frontier conductors cross every advisory lane under goal pressure); Docker/devcontainer (rejected — Docker-in-Docker conflicts with D-30 Podman lanes); OrbStack (rejected — shared-kernel model, insufficient isolation for skip-permissions agents); ephemeral VMs per session (rejected — destroys `.pipeline-state` crash checkpointing D-24 and git continuity).

**Deferred:** a coder sentinel-format micro-check (send a prompt that should produce `=== FILE: ... === END FILE ===` wrapping and verify the format parses) — the current smoke test only asserts non-empty reply, which catches plumbing failures but not format mismatches between llm-call.sh and the coder extraction logic. Low urgency: the extraction already hard-fails on bad format during real tasks, so it's caught one call later.

**Do not suggest:** Running `orchestrate.sh` directly on the macOS host. Removing the `uname` pre-flight check. Using Docker instead of Podman inside the VM. Hardcoding `localhost` instead of `SANDBOX_LLM_HOST`. Skipping the round-trip smoke test.

---

## D-54 — 2026-07-05 — Spec-drift policy: the test surface is the binding spec; ERD prose is advisory design intent

**Decision:** Only what is mechanically checkable at freeze or run time is binding: the frozen test suite, `contracts.json` (entry points, routes, schemas, smoke_checks), and the gates that enforce them. ERD prose — implementation constraints, library choices, internal design notes — is advisory design intent. Code that passes the full frozen suite is conformant by definition, even where it deviates from ERD prose. Consequences: (1) the TPM must express every MUST-HOLD constraint as something observable at the locked surface — a test, a contracts entry, or a smoke_check — or accept that it is guidance, not law; (2) deviating from advisory ERD prose is not a violation, but it MUST be reported to the CEO in the run summary (silent drift is still a reporting defect under Operating Rule 4); (3) when drift accumulates enough that the ERD misleads the next milestone's TPM, the fix is a refreeze that re-trues the prose — bookkeeping, not rollback.

**Found by:** the testchat M3/M4 supervised runs (2026-07-04): shipped code replaced httpx with raw urllib reads and streamed think-content to the frontend, both contradicting frozen ERD prose (C-4, think-stripping) — with the full suite green throughout. The tests observe only the locked surface, so prose-level constraints were undetectably violated. Nothing in the pipeline can catch this class of drift, and pretending otherwise mislabels a suggestion as a rule.

**Alternatives considered:** a post-success conformance review step, human or LLM, diffing implementation against ERD prose (rejected — it is an advisory review by exactly the class of agent that the M4 incident proved ignores advisory constraints under goal pressure; it adds a cycle per milestone without a mechanical guarantee, and its failure mode is silent, which is the problem it claims to solve); making ERD prose binding by policy alone (rejected — restates the repo's founding axiom in reverse: a rule that cannot be enforced mechanically is a suggestion).

**Do not suggest:** Failing or re-running a green milestone because the implementation deviates from ERD prose. Adding a conformance-review gate without new evidence that reported-but-tolerated drift caused a real defect. Moving constraints into tests retroactively to "win" a disagreement — that is a TPM spec change and goes through refreeze like any other.

---

## D-53 — 2026-07-03 — Retire the agent harness from the execution loop: EM/coder called over bare HTTP, no tools, shell writes every artifact

**Decision:** `scripts/orchestrate.sh` no longer runs `opencode serve` or invokes agents via `opencode run --attach --agent <name>`. Instead: (1) `scripts/llm-call.sh` sends ONE completion per call directly to the local OpenAI-compatible endpoint (LM Studio) — no harness, no filesystem/tool access for the model, no memory between calls. It reads a CEO-owned role→model mapping (`~/.config/sw-dev-blueprint/models.env`, successor to the `opencode.json` agent mapping, D-41 spirit unchanged) and hard-halts on an unmapped role — never a silent substitution. It supports LM Studio's `response_format: json_schema` for schema-constrained generation, with graceful fallback to unconstrained if the server rejects it. (2) The orchestrator now gathers whatever context a call needs (ERD, contracts, test-nodeids, the prior plan, relevant failing test source) into the prompt itself and writes the model's reply to disk itself: JSON straight to `tasks/plan.json`/`diagnosis.json` for the EM, and for the coder, a sentinel-wrapped block (`=== FILE: path === ... === END FILE ===`, the same convention the TPM shuttle already uses) parsed and written to exactly the task's named path — a reply naming a different path or missing the block is a coder FAILURE (retry/consult evidence), never written. (3) `sandbox-run.sh` and the `Containerfile` drop everything OpenCode-related (the D-52 config-mount, the version-pinned install) since nothing inside the sandbox talks to a model anymore — it now runs `pytest`/`smoke_check` only, with `--network none` (no LLM to reach, so no reason for the container to have network at all — untrusted generated code gets no exfiltration path either). `opencode.json` is stripped to the conductor's own permission config (the `em`/`coder` agent blocks are deleted — nothing invokes them); it is now entirely optional, relevant only if the CEO happens to pick OpenCode as their conductor.

**Found by:** the first two supervised POC runs on the wordcount instance (2026-07-02/03). Every failure across both runs was a harness seam, never the actual pipeline logic: `opencode run --agent em` silently fell back to a default agent on a remote free-tier model when `em` was `mode: subagent` (D-52 fixed the mode, but the failure recurred); the container's pinned OpenCode build (1.15.13) had drifted from the host (1.17.12), and the version mismatch is the prime suspect for the server dropping the `--agent` selection even after D-52's mode fix; the remote fallback then hit provider rate limits. Zero of these failures were about the actual gates, lanes, or escalation ladder — every one of those fired correctly across three runs. The seam was always the harness sitting between the shell and the model, never the trust boundary itself.

**Alternatives considered:** keep tuning the OpenCode attach/agent-mode path (rejected — three consecutive fix attempts, D-40/D-52/this incident, each patched one seam and surfaced another; the pattern is the mechanism, not the configuration); swap OpenCode for a different CLI agent harness inside the sandbox (rejected — same class of seams: any harness between the shell and the model is a version to pin, a config to lose, a fallback to silently take); give EM/coder real tool access so they read files themselves (rejected — the entire value of the capability ladder is that the shell owns procedure and knows exactly what changed; tool-using agents reintroduce the "did it actually only touch its lane" question that sandboxing was built to make moot, for zero capability gain since every prompt in this pipeline is a single, boundedly-scoped question).

**Reason:** The shell already read every file these agents needed and validated every artifact they produced (`validate-plan.py`, `phase-gate.sh`, INV-4) — the harness was never load-bearing for trust, only for convenience, and it was the only thing that ever broke. A model that receives a full prompt and returns one answer needs no tools to do its job in this design; every "read X" instruction to the old agents is mechanically equivalent to pasting X into the prompt, and the shell can do that pasting without an intermediary that has its own versions, configs, and failure modes.

**Do not suggest:** Re-introducing an agent CLI/harness into the EM or coder invocation path for "richer" tool use — if a future task genuinely needs the model to explore rather than answer one bounded question, that is a signal the task decomposition (EM's job) is wrong, not that the execution tier needs tools. Hardcoding a model name anywhere to avoid the models.env mapping (violates D-41). Re-enabling sandbox network access "just in case" without a concrete test that needs it — add it deliberately, with a reason, if that day comes.

---

## D-52 — 2026-07-02 — em/coder back to primary mode; model mapping mounted into the sandbox; no silent agent/model substitution

**Decision:** Three coupled fixes from the first orchestrate run. (1) `em`/`coder` return to `mode: "primary"` in `opencode.json` — `opencode run --agent <name>` refuses subagent-mode agents ("not a primary agent"), so D-40's flip broke the orchestrator's only invocation path. Impersonation protection does not regress: the sandbox lane mounts (D-30) physically bound what each agent can write regardless of mode, and both agents keep `task: false` (D-43/D-48). (2) `sandbox-run.sh` mounts the host's global `~/.config/opencode/opencode.json` (the D-41 agent→model mapping) read-only into the container HOME, rewriting `localhost`/`127.0.0.1` to `$SANDBOX_LLM_HOST` so a mapping that points at the host LLM still resolves from inside the container; auth.json rides along if present. (3) `orchestrate.sh` hard-halts if the run log shows OpenCode substituted the default agent — before this, it silently proceeded as `build` on a default REMOTE free-tier model.

**Found by:** the first supervised POC run (wordcount): the plan phase logged `agent "em" is a subagent, not a primary agent. Falling back to default agent` and ran as `build · mimo-v2.5-free`. Nothing was running on the CEO's mapped local models; the CEO noticed and aborted.

**Reason:** The silent fallback is the worst half: pipeline work left the machine on an unchosen remote model with no actor deciding that. Halting is the only honest behavior when the invoked agent is not the one that runs.

**Do not suggest:** Re-flipping em/coder to subagent mode to hide them from the CEO's TUI (cosmetic benefit, breaks the pipeline); baking a model ID into the repo to avoid the mount (violates D-41); downgrading the substitution halt to a warning.

---

## D-51 — 2026-07-02 — Initial freeze collects node-ids statically: the v1 suite cannot import src/ that doesn't exist yet

**Decision:** `refreeze.sh` falls back to static AST-based node-id derivation (module-level `test*` functions and `Test*` class methods in `tests/**/test_*.py` / `*_test.py`) when dynamic collection yields nothing AND the failure is `No module named 'src…'`. Parametrized ids are not expanded by the fallback; the first refreeze after `src/` exists re-collects dynamically. Additionally, collection diagnostics now capture and grep BOTH streams — pytest reports collection errors on stdout, which D-50's stderr-only capture missed, leaving the exact misleading "no tests" message D-50 claimed to have retired.

**Found by:** the first supervised POC run (wordcount instance): the very first v1 freeze in template history failed at collection. This is structural, not incidental — INV-1 requires the TPM suite to exist before any implementation, so at v1 every test module's `import src.…` must fail. The initial-freeze path could never have worked; every prior instance was either migrated mid-history or hand-patched.

**Alternatives considered:** stub `src/` files at freeze time (violates lanes — no actor may write src/ outside a coder task); deferring node-id collection until after the first build (the EM's plan gate needs the ids before any coder runs); having the TPM hand-author the node-id list (unverifiable, drifts from the actual suite).

**Reason:** Static derivation is exact for the accident class the template constrains anyway (frontier-TPM-authored plain pytest functions), and self-heals to dynamic collection at the next freeze. Known limit: a v1 suite relying on parametrize-expanded ids maps them unexpanded until the v2 freeze.

**Do not suggest:** Making the AST fallback the primary collector (dynamic collection is ground truth whenever imports resolve); relaxing the "no nodeids = fail" rule — a freeze without a suite still cannot gate anything.

---

## D-50 — 2026-07-02 — Stack drift killed mechanically: content-hashed sandbox image, podman preflight, honest collection errors

**Decision:** Three fixes for the sparkv2-Issue-9 failure family (TPM picks a stack at spec time; the sandbox doesn't have it; the gate reports a misleading "pytest collected no tests"). (1) `sandbox-run.sh` tags the image with a hash of `Containerfile`+`requirements.txt` — any stack change produces a new tag and an automatic rebuild; a stale image is now structurally impossible, and manual `podman image rm` ceremony is retired. (2) `sandbox-run.sh` checks podman is actually running before anything else and says exactly what to do if not — previously it failed downstream with unrelated-looking errors. (3) `refreeze.sh` captures collection stderr instead of discarding it (`2>/dev/null` was hiding `ModuleNotFoundError` since the beginning), prints it on failure, and names the requirements.txt fix when the cause is an import error. Plus a conductor guardrail in CLAUDE.md: check staged test imports against `requirements.txt` before every freeze.

**Found by:** the second live run — the TPM chose FastAPI+httpx while the sandbox carried the previous project's stack, re-creating sparkv2's Issue 9 exactly. The first occurrence was hand-fixed in the instance and logged but never ported to the template as machinery; recurrence was guaranteed.

**Reason:** An error message that misdescribes the failure ("no tests" when the truth is "can't import") costs a debugging session per occurrence. Discarded stderr is the root sin. And rebuild-on-change must be mechanical because the actor who changes the stack (TPM, via spec) is not the actor who maintains the image (operator) — a handoff that relied on someone remembering.

**Do not suggest:** Pinning the stack in the template to avoid drift (the TPM must be free to choose per project, D-41 spirit); pruning old image tags aggressively (cheap disk, and old tags let an interrupted migration fall back).

---

## D-49 — 2026-07-02 — tpm-pack.sh defaults to stdout; conductor must relay the bundle verbatim (first live-run bug)

**Decision:** `tpm-pack.sh` now writes the bundle to stdout by default; clipboard copy is opt-in via `--clipboard` (`--stdout` kept as a no-op for compatibility). CLAUDE.md gains a conductor guardrail: when the CEO asks for the TPM briefing, run the script and reproduce its entire stdout verbatim — no summarizing, no pointing at repo files (the bundle is assembled, not hand-collectable), no "it's in the clipboard"; TPM replies pasted back go to a temp file unmodified, then `tpm-unpack.sh <file>`.

**Found by:** the first live conductor session (CEO asked for the TPM prompt; got a file reference in one attempt and a false "copied to clipboard" in another). Root cause: the script's TTY auto-detection (`[ -t 1 ]`) was built for a human at a terminal, but agent harnesses may allocate a pty — the check fired inside the subprocess, the bundle went to a clipboard call the CEO never received, and nothing instructed the conductor to relay output rather than report about it.

**Reason:** In the conductor-operated design (D-40) the primary caller of this script is an agent, not a human — defaults must serve the common caller. Auto-detection that guesses the caller's context is exactly the class of cleverness that fails silently; an explicit flag cannot misfire. The instruction-layer half exists because the script fix alone doesn't stop an agent from summarizing captured output.

**Do not suggest:** Restoring TTY auto-detection; having the conductor paraphrase or trim the bundle ("the CEO only needs the gist" — the TPM needs every byte, and the sentinel footer is load-bearing for tpm-unpack.sh). Conductor denied the task tool: no agent in this repo can spawn another

**Decision:** The built-in Build agent gets `"tools": { "task": false }` in the project `opencode.json`, completing D-43. No agent — conductor, em, or coder — can spawn any agent. The only inter-agent invocation path in the entire system is `orchestrate.sh` calling `opencode run --agent` inside the sandbox. CEO-surfaced gap: "Build hands to the orchestrator" was doc-advisory while Build held the task tool — it could have dispatched coder directly, skipping sandbox mounts and per-task gates. Residual soft path: Build running `opencode run --agent coder` via bash is not allowlisted, so it falls to the ask-prompt (= CEO alarm), subject to the D-45 glob caveat.

**Alternatives considered:** Leaving Build the task tool for utility subagents (explore-style) — rejected: the pipeline never needs it, and the utility doesn't justify keeping open the one bypass around the shell's procedural monopoly.

**Reason:** "The shell is the only actor with procedural authority" (D-26) is now enforced by configuration at every seat, not by prompt discipline. Rules that can be mechanical must be (CLAUDE.md operating-rules preamble).

**Do not suggest:** Re-enabling task for Build to "parallelize" or "speed up" anything; the orchestrator is the parallelism boundary.

---

## D-47 — 2026-07-02 — External TPM review of D-40..D-46 adjudicated: pytest/conftest hole closed, permissions hardened, honest-layer statements added

**Decision:** A frontier-LLM review of the conductor redesign produced five findings; all were verified against the tree before acting (none taken on the reviewer's word). Actions: **(1) CONFIRMED+FIXED** — `"pytest*": "allow"` plus undenied root `conftest.py` gave the conductor a zero-prompt arbitrary-code-execution path (write `./conftest.py`, run bare `pytest` unsandboxed), also loadable inside sandboxed suite runs where `.cache/` is writable (test-report forgery path). Removed `pytest*` from the allowlist (suite runs go through `sandbox-run.sh`; bare pytest now asks) and denied edits to root pytest-config files (`conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg`, `tox.ini`) for the conductor AND the coder. **(2) OPEN** — OpenCode glob-vs-compound-command matching is untested; caveat recorded in D-45, probe scheduled for first live session. **(3) FIXED** — D-42's conductor-relayed-diff weakening now stated in its entry. **(4) CONFIRMED+FIXED** — coder's `"**": "allow"` could override global control-plane denies depending on merge semantics; denies mirrored into the coder block, and `em` got an explicit `"**": "deny"` terminal rule (fail closed regardless of merge semantics). **(5) FIXED** — `new-project.sh` warns when multiple models are loaded and respects `SANDBOX_LLM_PORT`; stale y/N-only comments in `refreeze.sh` header and CLAUDE.md structure tree updated.

**Reason:** The pipeline's own doctrine applied to its own control plane: external review, source-verified adjudication, fixes committed per concern. Finding 1 was the exact class D-45 claims to prevent (unprompted write→execute), found by an actor who never saw this session — the review layer works.

**Do not suggest:** Re-adding `pytest*` to the conductor allowlist "for quick checks" — `scripts/sandbox-run.sh -- pytest ...` is the allowed, sandboxed way to run tests.

---

## D-46 — 2026-07-02 — Milestone sizing is TPM judgment against a fixed balance; no formula

**Decision:** Milestone cutting is the TPM's call, made per project, documented briefly in each PRD. The optimization target is fixed and two-sided: small enough that the CEO's acceptance check (D-44) catches errors before they compound — one bad milestone is the maximum blast radius; big enough to use a full freeze→build cycle well — no fragment milestones that spend a freeze/accept round-trip on trivia. No arc, ordering, or size unit is prescribed to the TPM — not even as an example: an example in role instructions anchors an LLM and becomes a de-facto formula (the CEO's own sketch — engine → connector/frontend → MVP → features — lives only here, as history, deliberately outside `TPM-ROLE.md`). Corollary: every milestone must end CEO-checkable, with acceptance depth scaling to what exists — live demo with real inputs for pre-UI milestones, hands-on prototype use once any UI exists. A milestone whose CEO check can't be described is cut wrong.

**Alternatives considered:** (a) A sizing formula (N tasks / N files / N tests per milestone) — rejected: project-dependent; a formula would be gamed or fought rather than judged. (b) CEO cuts milestones — rejected: sizing requires estimating what the pipeline can deliver in one spec, which is technical judgment; the CEO states outcomes and accepts results.

**Reason:** CEO-stated doctrine (2026-07-02): balance early error detection by human user-testing against per-cycle throughput; "a TPM can intelligently figure this out; there is no formula ideally, and it depends on project." Resolves the D-44 tension for backend-only milestones (nothing hands-on to test) via scaled acceptance instead of forbidding them.

**Do not suggest:** Adding numeric sizing thresholds to gates or schemas; milestones that end at internal refactors with no CEO-observable behavior.

---

## D-45 — 2026-07-02 — Conductor bash allowlist: pipeline scripts + read-only git; everything else asks

**Decision:** The Build (conductor) session's bash permission in `opencode.json` becomes an allowlist — the pipeline scripts (orchestrate, bootstrap, new-project, tpm-pack/unpack/agent, sandbox-run, check-drift), read-only git (`status`/`log`/`diff`/`show`), pytest, and read-only file commands are allowed; `refreeze.sh` stays `ask` (D-42); **everything else falls to `ask`**. Combined with the playbook rule, this gives the non-technical CEO a decision procedure requiring zero code judgment: the only prompt you expect is refreeze-approve; any other prompt = alarm = deny and ask the conductor what it wanted.

**Alternatives considered:** (a) Default-allow bash (previous state) — rejected: bash bypasses `permission.edit`, so a conductor could `sed -i` protected files without any prompt. (b) Default-deny — rejected: the conductor legitimately needs incidental commands (installing a dep the CEO approved, starting the app for UAT); `ask` keeps those possible with the human in the loop.

**Reason:** Closes the routine accident surface of D-40's honest caveat (conductor bash outside the sandbox) while keeping fail-closed backstops (hooks, manifests) as the guarantee against what slips through. OpenCode permission enforcement remains soft (D-24/D-39); this is friction + visibility, not a wall. **Unverified assumption (Rule 6, flagged by D-47 review):** whether OpenCode matches these globs against parsed sub-commands or the raw command string is untested — if raw-string, `scripts/bootstrap.sh && <anything>` would pass as allowed. Probe this in the first live conductor session before trusting the allowlist; until then treat it as friction only.

**Do not suggest:** Widening the allowlist with write-capable commands (`sed -i`, `rm`, `git push`, `pip install`) to reduce prompts; those prompts are the point.

---

## D-44 — 2026-07-02 — The CEO gate is outcome acceptance, not diff review; refreeze approval reframed as authorization

**Decision:** The CEO does not review code or diffs — ever. The refreeze approval (terminal y/N or D-42 hash prompt) is redefined as **authorization**: "this delta is a change I asked for," verified by matching the TPM's plain-language description against the CEO's own request. The technical scrutiny of a delta is entirely mechanical and pre-approval: INV-4 surface check, contracts schema validation, hash binding. The CEO's real quality gate moves to the end of every milestone: **user-test the running prototype** (conductor launches it; CEO uses it like a real user). Definition of Done gains this as its one judgment item: orchestrate exit 0 = built-as-specified; CEO acceptance = built-right. A green suite that fails CEO acceptance is a spec defect → back to the TPM, not a code fix.

**Alternatives considered:** (a) CEO reads every diff (original D-31/D-42 framing) — rejected: not meaningful for a non-technical CEO; a signoff that can't distinguish good from bad diffs is theater and trains rubber-stamping. (b) A second LLM as diff reviewer — rejected for now: adds an unaccountable layer whose review is itself unverifiable self-report; may be revisited as a separate decision.

**Reason:** Matches the actual operator (CEO checks outcomes, not codebases) and the agile cadence: milestones are the checkpoints, prototype acceptance is the check. Aligns the gate's claimed meaning with its real meaning — the system's honesty principle applied to its own front door.

**Do not suggest:** Skipping the UAT step because tests are green; treating CEO acceptance as optional for "internal" milestones (every milestone ends at something the CEO can try — if it doesn't, the milestone was cut wrong).

---

## D-43 — 2026-07-02 — Flat hierarchy under the shell: `em`/`coder` denied the task tool

**Decision:** Both subagents get `"tools": { "task": false }` in `opencode.json`. The orchestrator invokes EM and coder independently, as direct reportees; neither agent can spawn any other agent. The EM "manages" the coder exclusively through `tasks/plan.json` — its briefs are the management; the shell delivers them, gates each result, and owns retries.

**Alternatives considered:** EM-drives-coder (the org-chart intuition the names suggest) — rejected: coder would run inside EM's sandbox context (wrong write lane), the per-task gate and mapped-test run between tasks would be skipped, escalation counters would drift, and the task tool is the known OpenCode permission-bypass route (issues cited at D-24/D-39).

**Reason:** No LLM should sit in the reporting chain of another LLM — every inter-agent handoff must cross a deterministic checkpoint (D-26). Advisory "EM never drives" becomes mechanical.

**Do not suggest:** Re-enabling the task tool for either subagent to "streamline" plan execution; having the conductor invoke coder directly around the orchestrator.

---

## D-42 — 2026-07-02 — Refreeze approval without a terminal: `--diff` / `--approve <hash>` behind the OpenCode ask-prompt

**Decision:** `scripts/refreeze.sh` gains two non-interactive modes so the conductor (D-40) can drive freezes while the human stays the gate. `--diff` validates the staging dir, prints the full diff plus its `DIFF-SHA` (sha256 of the diff text), and applies nothing. `--approve <sha>` recomputes the diff and proceeds only if the hash matches; `opencode.json` marks `scripts/refreeze.sh *` as `bash: ask`, so the CEO's click on that prompt — whose command line carries the hash of the diff they just read in chat — IS the approval. Any change to staging between review and approval changes the hash and fails closed. The interactive y/N path is unchanged and remains the fallback.

**Alternatives considered:** (a) Keep terminal-only y/N — rejected by CEO direction (no command running). (b) Honor-string approval ("CEO said yes in chat") — rejected: no binding between what was read and what is applied. (c) A `--yes` flag — rejected: approves whatever staging contains at run time, not what was reviewed.

**Reason:** The gate's essence is "a human read THIS diff and approved THIS diff." The hash preserves that binding without a TTY. Honest layer statement: the ask-prompt depends on OpenCode's permission enforcement (soft, see D-24/D-39 caveats); the backstops remain the hash binding itself, the pre-commit hook, and the frozen-manifest verification failing closed on every gate run. **Known weakening vs terminal y/N (D-47 review):** the CEO sees the diff only through the conductor's relay — a misreporting conductor could display doctored diff text alongside the true hash of different staged content, and the prompt would look right; the tty path showed the script's own output on a trusted channel. The raw diff is always at `.pipeline-state/refreeze-pending.diff` for direct reading, the terminal path remains for structural freezes, and the blast radius of an unread-but-authorized delta is one milestone, caught at UAT (D-44). Accident-class threat, accepted; not zero.

**Do not suggest:** Adding `--yes`/`--force`; letting the conductor summarize the diff instead of printing it in full; approving on a stale hash after restaging.

---

## D-41 — 2026-07-02 — Model identity leaves the repo: the blueprint is model-agnostic

**Decision:** No file in the template or its instances names an actual LLM (no model IDs in `opencode.json`, scripts, or operative docs). The repo's `opencode.json` defines roles, prompts, modes, and write lanes only. The CEO maps agents to models in the global `~/.config/opencode/opencode.json` (OpenCode merges global + project config) and loads whatever they choose in LM Studio; pre-flight probes discover the loaded model via `GET /v1/models` instead of asserting a name. The blueprint constrains model *class* only: TPM frontier-tier, EM mid-tier, coder local non-thinking (Hard Rule 1 stays, expressed class-wise).

**Alternatives considered:** (a) Keep pinned models with placeholders like `[EM_MODEL]` — rejected: placeholders leak into instances unfilled (see sparkv2) and every model swap dirties the repo. (b) Env-var indirection in the repo config — rejected: still couples the repo to a naming scheme.

**Reason:** Model choice is an operator preference that changes weekly; the pipeline's guarantees come from gates and frozen tests, not from any particular model. Hardcoding created recurring drift between what docs claimed and what was actually loaded (SANDBOX-VALIDATION.md records four different models in one week).

**Do not suggest:** Re-adding model IDs to the repo "for reproducibility" — record the model used for a given run in session notes if it matters, not in the control plane.

---

## D-40 — 2026-07-02 — OpenCode Build agent as conductor; `em`/`coder` become subagents; CEO runs no commands

**Decision:** OpenCode is the harness AND the CEO's single interface. The built-in **Build** agent is the conductor: the CEO talks to it in business language; it runs `new-project.sh`, the TPM shuttle scripts, `refreeze.sh --diff/--approve` (D-42), and `SANDBOX=1 scripts/orchestrate.sh`, then reports results. `em` and `coder` flip to `"mode": "subagent"` — machine-invocable (task tool / `opencode run --agent`), no longer Tab-cycled by a human. Procedural authority does NOT move: `orchestrate.sh` still owns the DAG, gates, counters, and escalation (D-26); Build launches it and interprets exit codes, nothing more. Project-level `opencode.json` denies the Build session edits to `tests/`, `scripts/`, `src/`, hooks, and the control plane.

**Alternatives considered:** (a) Build re-implements orchestration conversationally — rejected: reintroduces LLM procedural authority that D-26 removed for cause. (b) Keep em/coder as Tab-cycled primaries — rejected: requires the CEO to operate the TUI, contradicting the no-commands direction.

**Reason:** The CEO's two real decisions (what to build, whether to approve a freeze) never required a terminal; everything else was operator toil. Honest layer statement: Build's edit denies are OpenCode-harness-soft (the D-24/D-39 permission caveats apply) — the hard walls remain the read-only sandbox mounts for em/coder (D-30), phase-gate manifests failing closed, and the pre-commit hook.

**Do not suggest:** Moving DAG/retry/escalation logic into Build's prompt; making the TPM an OpenCode agent (OpenCode cannot deny reads — see D-39 alternative (b)); giving Build write access to `scripts/` or `tests/` to "unblock" a run.

---

## D-39 — 2026-07-02 — Agent-mode TPM: scoped repo access via `tpm-agent.sh` (D-38(b) triggered by CEO decision)

**Decision:** The TPM may now run as a repo agent — `scripts/tpm-agent.sh` launches Claude Code with `scripts/tpm-agent-settings.json`. Containment, per the shape D-38(b) recorded: WRITE only `.tpm/outbox/` (gitignored; installed exclusively through the interactive human y/N of `scripts/refreeze.sh .tpm/outbox` — refreeze already took a staging-dir argument, unchanged); READ everything except `src/` (harness-denied), with `Bash` denied entirely so the wall cannot be bypassed via `cat`; anything outside the pre-approved lane falls to the harness's ask-prompt, which the playbook tells the CEO to treat as an alarm. The TPM triggers no procedure — orchestrate/refreeze/EM/coder runs stay operator- and shell-initiated. Chat mode (D-38 pack/unpack) remains fully supported as the fallback and the stronger air gap. The operator's imagined third job — couriering prompts from TPM to EM — is explicitly documented as nonexistent: the frozen spec is the only TPM→EM handoff, delivered by `orchestrate.sh` (D-26/D-28).

**Alternatives considered:** (a) Unrestricted repo access — rejected: reading `src/` breaks oracle independence from milestone 2 onward, and free writes re-open the incident class in TPM-ROLE.md's institutional memory. (b) OpenCode agent for the TPM instead of Claude Code — rejected for containment: OpenCode `permission.edit` globs are non-transitive (bypassable via the Task tool — opencode issues #12566/#20549, already cited at D-24); Claude Code deny rules take precedence over allows and cover Read as well as writes. (c) Podman-mounted physical wall (tmpfs over `src/`) — stronger but the frontier-agent harness cannot usefully run inside the pipeline's container; recorded as the hardening step if harness-level deny ever proves insufficient in practice.

**Reason:** The CEO explicitly chose the D-38(b) upgrade path — the operator cost of chat-mode shuttling outweighed the marginal wall-strength difference for this operator. The honest layer statement is in `tpm-agent.sh`'s header: the read wall is harness-enforced (softer than the chat air gap); the write wall is layered and hard (harness deny + ask-prompts + hash-pinned manifests failing closed + the interactive refreeze gate).

**Do not suggest:** Widening the read scope to `src/` "for better test quality" — that inverts the role's reason to exist. Letting the TPM run `refreeze.sh` or answer its prompt. Removing chat mode — it is the fallback wall and the reference trust model. Weakening the `Bash` deny in `tpm-agent-settings.json` for convenience; if the TPM needs a fact only a command can produce, the operator runs the command.

---

## D-38 — 2026-07-02 — TPM shuttle scripts (`tpm-pack.sh`/`tpm-unpack.sh`) + CEO playbook; TPM stays chat-side

**Decision:** The operator's courier burden around the chat-based TPM is automated, not the air gap. `scripts/tpm-pack.sh` assembles the complete TPM session briefing (TPM-ROLE.md, contracts schema, and the currently frozen spec + VERSION when one exists) into one clipboard blob — deliberately excluding `src/` and `tests/` (oracle independence, INV-1). `scripts/tpm-unpack.sh` splits the TPM's reply — artifacts wrapped in mandatory `=== FILE: <path> ===` / `=== END FILE ===` sentinels, format recorded in TPM-ROLE.md — into `scripts/.approved/incoming/`, validating paths against the same whitelist `refreeze.sh` enforces, fail-closed (one bad path rejects the whole reply; a non-empty staging dir requires `--force`). The trust model is unchanged: unpack only stages; the human y/N diff in `refreeze.sh` remains the only installation door. `docs/CEO-PLAYBOOK.md` documents the operator loop end-to-end.

**Alternatives considered:** (a) Repo read/write access for the TPM — rejected: read access breaks oracle independence for every milestone after the first (the TPM could derive tests from `src/`), and write access re-opens the exact incident class in TPM-ROLE.md's institutional memory (an agent quietly weakening a gate to make a run pass). (b) Scoped agent-TPM (deny-read `src/`, write only `incoming/`) — viable, deferred: harness-permission scoping is a softer guarantee than the chat air gap; revisit if shuttle friction still chafes after a few real milestones. (c) Status quo (manual file courier) — rejected: per-artifact hand-selection is error-prone in both directions, and friction the operator routinely skips is a control that doesn't exist.

**Reason:** The no-repo-access design is load-bearing; the copy-paste drudgery around it is not. Separating the two makes the safe design cheap enough to actually operate: one paste starts a milestone, one command banks the reply. On CEO-PLAYBOOK.md vs D-01: this is an operator runbook for machinery that did not exist at D-01 — it restates no diagrams or rules from BLUEPRINT.md, which is what D-01 pruned.

**Do not suggest:** Giving the TPM direct repo access (see alternative (b) for the recorded upgrade path and its trigger). Having tpm-pack include `src/` or the frozen `tests/` "for context". Letting tpm-unpack write anywhere but the staging dir, or skip its path whitelist because refreeze validates too — the double validation is deliberate (named culprit at unpack time; defense in depth at install time).

---

## D-37 — 2026-07-02 — `build_extra`/`test_extra`: exact-file lane exceptions in `.gate-paths`

**Decision:** `.gate-paths` gains two optional keys, `build_extra=` and `test_extra=` — space-separated lists of **exact file paths** outside the lane directory that the legacy `build`/`test` phases may also touch. `phase-gate.sh` filters them from the violation list with `grep -vFx` (fixed-string, whole-line): no globs, no regex, no prefix matching. Unset keys change nothing — the default gate behavior is byte-identical to before. Motivating case: a JS/TS build lane that must touch `package.json` alongside its source directory.

**Alternatives considered:** (a) Glob/regex patterns — rejected: a pattern is a scope grant whose true size is unknowable at review time; an exact filename is auditable at a glance. (b) Making the lane a path *list* instead of one directory — rejected: broader redesign of every consumer of `build_dir`/`test_dir` for a need that is, so far, one file per stack. (c) Nothing (status quo) — rejected: `.gate-paths` already exists precisely so non-default layouts don't require editing the gate; "one manifest file outside the lane" is the same class of layout fact, and without this key the only workaround is disabling the gate.

**Reason:** Closes the concrete slice of the stack-flexibility gap (flagged by the 2026-07-02 external review) that costs almost nothing to carry: directories were already configurable, but one out-of-lane manifest file (`package.json`, `Cargo.toml`, `go.mod`) had no legal path. Verified in an isolated worktree: gate still fails without the key, passes with it, and a nested `frontend/package.json` does NOT match a bare `package.json` entry — exact-match semantics hold.

**Do not suggest:** Extending `build_extra`/`test_extra` to globs, regexes, or directories — if a phase needs a whole extra directory, that is a lane redesign (alternative (b)) and gets its own decision. Adding entries to `.gate-paths` on an agent's initiative: the file is control-plane-adjacent and lane-widening is a human call (Rule 3).

---

## D-36 — 2026-07-02 — Gate-script self-tests (`scripts/selftest/`) + sandbox LLM port made configurable

**Decision:** The two Python gate scripts — `validate-plan.py` and `check-test-surface.py` — get a hermetic pytest suite at `scripts/selftest/selftest_gates.py`, run by a dedicated unconditional CI job (`selftest`, no skeleton guard: it needs no project `src/` or requirements). The file is deliberately named `selftest_` (not `test_`) so the bare `pytest` / `pytest --collect-only` runs in `orchestrate.sh` and `refreeze.sh` never collect it into the frozen suite or its node-id set; it runs only when invoked explicitly. Placement under `scripts/` keeps it agent-unwritable via the existing `--rw` refusal. Both manifests track it. Separately, `sandbox-run.sh` reads `SANDBOX_LLM_PORT` (default 1234, LM Studio) instead of hardcoding the port, matching the existing `SANDBOX_LLM_HOST` pattern (D-30 addendum).

**Alternatives considered:** (a) Integration tests for `orchestrate.sh`/`refreeze.sh` — rejected for now: shell-loop harnesses are expensive to carry, and dry runs cover them until an incident says otherwise (D-32's adopt-on-trigger doctrine). (b) A root pytest config (`testpaths=tests`) to allow normal `test_*` naming — rejected: it changes what the pipeline's bare `pytest` collects for every child, a control-plane behavior change disproportionate to the need. (c) Skipping self-tests entirely — rejected: a validator that wrongly passes fails open, and these two scripts are pure functions over JSON/file trees, so coverage is cheap to write and carry.

**Reason:** External review (2026-07-02) correctly flagged that a project whose philosophy is "tests as ground truth" had zero tests for its own gate scripts. The Python gates are the highest-value, lowest-cost slice: deterministic, subprocess-testable, and the failure mode (fail-open validation) is the worst in the gate set.

**Do not suggest:** Renaming the selftest file to `test_*.py` or moving it into `tests/` (frozen TPM lane; would pollute frozen node-id collection). Extending self-tests to the bash orchestration before an incident triggers it. Conditioning the `selftest` CI job on the skeleton guard.

---

## D-35 — 2026-07-01 — Fleet Tier 3 (versioned core distribution): designed, deliberately NOT built

**Documentation-only:** This entry records a design and its adoption trigger so it is not re-litigated each session. No code exists for it, on purpose.

**Decision:** The structural endgame for fleet distribution — template-owned scripts shipped as a versioned release artifact (`blueprint-core-vN`) with its own manifest, pulled by children as a tracked dependency, giving the control plane a provenance chain anchored outside every child — is **deferred**. Chosen shape, if/when built: release-artifact over git-subtree (cleaner provenance, no merge noise in children; the D-33 manifest split already defines exactly what the artifact would contain). **Adoption trigger, per the repo's own doctrine (D-25, D-32 — adopt on trigger, don't pre-harden):** roughly five or more active children, or the D-34 update flow demonstrably chafing (updates skipped because the diff-review burden grew, or children needing divergent control-plane versions). Until then, D-33 detection + D-34 propagation cover the only incident class that has actually occurred.

**Alternatives considered:** (a) Build it now — one active child; machinery would be maintained for years before anything needs it, and the migration of existing children (establishing spark's baseline by hand — it has no birth-SHA) is real human work with no current payoff. (b) git subtree — git-native but pollutes child history and makes partial adoption ambiguous. (c) Never — at real fleet scale, per-child diff-approval of every control-plane update stops scaling; the trigger exists because the need plausibly will.

**Reason:** Cheap-to-build is not the bar; cheap-to-carry is. Recording the shape and the trigger costs one D-entry; building it costs a distribution mechanism plus child migration, against a doctrine this repo has already paid to learn twice (D-01's bloat prune, D-04's demoted line-count gate).

**Do not suggest:** Building Tier 3 before the trigger fires. Re-opening subtree-vs-artifact from scratch when it does — start from this entry's rationale and revise with evidence.

---

## D-34 — 2026-07-01 — Template propagation: update-template.sh (the refreeze pattern, applied to the control plane)

**Decision:** Children pull control-plane improvements with `scripts/update-template.sh`: it resolves the template (a local clone via `--from`, or `gh repo clone` of the `.template-version` slug), takes the file list from the **template's** `.manifest-template` at the target ref (so files added upstream flow in), shows the human one aggregate diff, requires an interactive y/N (`--dry-run` to inspect without a tty), applies contents **and exec bits**, installs the template's manifest verbatim, advances `ref=` in `.template-version`, regenerates `.manifest-project`, runs the integrity gate as a post-apply check, and commits `[template-update <sha>]`. Files removed upstream are reported for manual deletion, never auto-deleted. `--stamp` mode retrofits a pre-D-33 child (writes `ref=` only). Same protected-artifact protocol as D-31: staged delta → human diff-approval → hash re-pin → versioned commit.

**Alternatives considered:** (a) Generalize `refreeze.sh` into one approve-delta engine serving both spec and control plane — considered and rejected: the two flows share only the approval UX (~40 lines); everything else differs (staging source, validation steps — INV-4 and node-id collection are spec-only — and post-apply actions). A forced common engine is parameter soup; a shared *pattern* with two small tools is cheaper to hold. Revisit only if a third protected-artifact class appears. (b) git subtree/submodule for `scripts/` — Tier 3 machinery; see D-35 for the trigger. (c) Auto-apply in CI — propagation into a child is a human-approved act, same reasoning as D-31.

**Reason:** This closes the documented incident class directly: the Rule 8 fix that lived only in spark until hand-ported becomes `update-template.sh` + one y. Detection (D-33) says *that* you're behind; this is *how* you catch up, with the same fail-closed integrity guarantees as every other protected write.

**Do not suggest:** Auto-applying template updates. Letting the tool delete files. Running it inside the template repo (it refuses).

---

## D-33 — 2026-07-01 — Fleet drift: birth-SHA identity, ownership-split manifests, drift detection

**Decision:** Three pieces. (1) **Birth-SHA**: `.template-version` records `repo=` (template slug) and `ref=` (template HEAD SHA at instantiation, stamped by `bootstrap.sh`, retrofittable via `update-template.sh --stamp`); `gh repo create --template` leaves no upstream link, so this is the only moment fleet identity can be captured. (2) **Ownership split**: the control-plane manifest becomes `scripts/.manifest-template` (template-owned logic — gates, orchestrator, validators, schemas, prompts, hooks, drift tooling) and `scripts/.manifest-project` (per-project adaptations under Rule 3 — `.gate-paths`, `opencode.json`, `Containerfile`, `ci.yml`, the doc layer). phase-gate verifies both, fail-closed; drift is computed over exactly the template list, so a Rule 3 adaptation is never a false positive. One-shot setup scripts are deliberately unlisted: children delete them at instantiation, and the read-only mounts (D-30) already cover them. (3) **Detection**: `scripts/check-drift.sh` does a three-way compare per template-owned file (child vs template@birth vs template@HEAD) → IN_SYNC / BEHIND (exit 2, CI warns) / LOCALLY_MODIFIED, MISSING_IN_CHILD, CHILD_ONLY (exit 1, CI fails); `.github/workflows/check-drift.yml` runs it on push and weekly, skipping itself in the template repo and unstamped children.

**Alternatives considered:** (a) No fleet story — the documented failure: the Rule 8 fix lived only in spark until hand-ported. (b) One mixed manifest plus a separate drift-file list — two lists drift from each other; ownership belongs in the manifest itself. (c) Auto-sync on drift — propagation is a human-approved act (D-34); detection and propagation stay separate so CI never rewrites a child.

**Reason:** Drift you cannot compute is drift you discover in production. The birth-SHA is cheap now and unrecoverable later; the split makes "adapted" and "drifted" mechanically distinguishable; the CI job makes a quiet child hear the template move.

**Do not suggest:** Auto-applying template changes in CI. Putting template-owned files in `.manifest-project` to silence a drift failure — that is the drift, formalized.

---

## D-32 — 2026-07-01 — INV-4: test-visible surface ⊆ ERD-locked surface (lowest-confidence gate)

**Decision:** New invariant, same class as INV-1/2/3. Whatever the frozen tests observe is de-facto locked, whether or not the ERD meant to lock it — so the two locks are kept aligned mechanically: `scripts/check-test-surface.py` statically checks that tests import only `contracts.entry_points` entries (`module` or `module:symbol`) and exercise only declared `contracts.routes` path templates (segment-wise match, `{param}` wildcards). It runs inside `scripts/refreeze.sh` on the merged preview (current frozen tests + incoming delta), BEFORE the human approval prompt — a TPM test that reaches past the contracts is rejected before it can be frozen, and before it can silently shrink the EM's design space.

**Confidence flag — read this before trusting it:** this is the **lowest-confidence mechanism in the gate set**, and deliberately so. It is a grep-level static check (regex on imports and client-verb calls), in the same spirit as INV-3's grep. It catches the accident class — the test author is a frontier model following instructions, not an adversary — and does not catch dynamic imports, computed paths, or indirect observation. Tighten it from incidents per the correction-log habit; do not pre-harden speculatively.

**Alternatives considered:** (a) No check — the seam rule ("TPM locks contracts, EM owns the rest") becomes decoration the first time a test asserts on an internal. (b) AST-based analysis or import-hook enforcement at test runtime — heavier machinery than the failure class justifies today; adopt only after the crude check demonstrably misses real incidents. (c) Generating test fixtures from contracts so tests physically cannot reach elsewhere — the strongest form; noted as the escalation path if (b)'s trigger fires.

**Reason:** INV-4 is what makes the seam rule real: the EM owns everything inside the locked surface only if nothing outside the contracts can fail a build.

**Do not suggest:** Treating INV-4 as a security boundary. Loosening it by allow-listing individual violations instead of locking the surface properly in contracts.json.

---

## D-31 — 2026-07-01 — Versioned re-freeze: frozen spec changes only via human-approved delta

**Decision:** The TPM's artifacts (PRD.md, ERD.md, contracts.json in `scripts/.approved/`; the test suite in `tests/`) are hash-pinned by `scripts/.approved/frozen-manifest` and verified by **every** phase-gate run, fail-closed. They change through exactly one path: `scripts/refreeze.sh`. The operator stages the TPM's delta (full new content of only the changed files) under `scripts/.approved/incoming/`; refreeze shows the human the complete diff, requires an interactive y/N (this diff-approval IS the approval gate — it also replaces the old `Status: Approved` honor-string for the initial freeze), applies, re-collects test node-ids in the sandbox, writes `DELTA-vN.json` (changed contract ids + changed/removed test node-ids), bumps `VERSION`, regenerates the frozen-manifest, and commits `[refreeze vN]`. On the next run the orchestrator resumes **only the affected subtree**: the stale plan is re-derived by the EM, unchanged task entries keep their done status via fingerprints, and `validate-plan.py --affected DELTA-vN.json` additionally resets tasks whose mapped test content changed under an unchanged entry (plus transitive dependents). Escalated/blocked tasks get a fresh chance under the new spec.

**Alternatives considered:** (a) Frozen-forever spec — the repo's own history shows what boxed-in agents do against an unsatisfiable oracle (a gate was once quietly weakened to force a pass); wrongness needs a protocol, not a workaround. (b) Silently mutable spec — the pre-D-08 freeze-trap failure, where a re-plan architect overwrote the approved contract. (c) Approval recorded as a status string an agent can write — the original LOW-severity hole; an interactive tty prompt on a diff is not agent-forgeable through any lane. (d) Full re-run after every delta — wastes the completed subtree; the delta file exists precisely to compute the minimal reset.

**Reason:** This threads both historical failure modes: no silent mutation (agents physically cannot write the frozen artifacts — D-30 mounts + manifest check), and no dogmatic freeze (a bounded, versioned, human-approved revision path exists, and the `[refreeze vN]` commit is the durable record of every TPM round-trip).

**Do not suggest:** Letting any agent stage or apply a delta. Skipping the interactive prompt for "trivial" deltas. Editing files under `scripts/.approved/` or `tests/` directly — the next gate run fails closed on the manifest.

---

## D-30 — 2026-07-01 — Sandbox flip: read-only repo + per-lane rw mounts; pre-commit hook for the human path

**Decision:** `scripts/sandbox-run.sh` mounts the repo **read-only** and grants write access per-lane via `--rw <relpath>` (coder: build lane only; EM: `tasks/` only; test runs and smoke checks: `.cache/` only or nothing). `--rw` refuses `scripts/`, `.git/`, and `.githooks/` unconditionally — the control plane is never agent-writable. The agent user's HOME moves to a container tmpfs (OpenCode/pip session data must not live in the read-only repo). For the interactive/human entry point, `.githooks/pre-commit` enforces the active pipeline phase (from `.pipeline-state/phase` + `task_target`) and always verifies the control-plane manifest and the frozen spec; `bootstrap.sh` sets `core.hooksPath=.githooks`.

**Alternatives considered:** (a) Keep the whole-repo rw mount and rely on phase-gate detection — a prior external review demonstrated a one-phase gate-neutralization: an agent could rewrite `phase-gate.sh` plus the manifest inside its phase, and the post-phase check would execute the compromised gate. Detection-after loses to a writable detector. (b) Per-file rw mounts for the coder — Podman bind-mount granularity makes single-file mounts brittle for files that don't exist yet; lane-level mount + the `task` gate's exactly-one-file check gives the same guarantee. (c) Overlay/copy-on-write sandboxes — heavier machinery for the same property.

**Reason:** Prevention beats detection where prevention is one flag. INV-2 violations and gate-tampering become physically impossible on the orchestrated path; the gate remains as backstop for the path mounts cannot cover (a human driving directly). The control-plane manifest finally has its out-of-band anchor: the only writers of `scripts/` are the human and CI.

**Do not suggest:** Re-widening the mount to the whole repo for agent convenience. Allowing `--rw scripts/...` for any phase. Removing phase-gate because the mounts "already handle it" — the hook path and defense-in-depth are why it stays.

---

## D-29 — 2026-07-01 — Escalation ladder with batched, filesystem-only TPM round-trips

**Decision:** Escalation is a shell-owned ladder with every counter in `.pipeline-state/`: task retry (strike 1, failure evidence appended to the same brief) → EM consult at two strikes (schema-bound verdict) → `brief_wrong` (revised brief, max 2 per task) → `decomposition_wrong` (plan re-emit, re-validated, max 2 per run) → `contract_or_test_wrong` / caps exhausted / spec drift → **batched TPM bundle** → human applies the TPM's delta via `scripts/refreeze.sh` → affected subtree resumes. PRD-ambiguity escalates from the TPM to the CEO in chat. Because the TPM is a human-operated web chat (not a callable service), the shell packages each escalation as a self-contained copy-pasteable bundle (`.pipeline-state/escalations/<id>/bundle.md`, aggregated into `BATCH.md`), keeps driving every independent subtree to its own stopping point first, and halts exactly once with exit code 2. Format: `docs/ESCALATION.md`.

**Alternatives considered:** (a) Halt-and-ping on first escalation — one browser round-trip per defect; with N independent seam problems that is N round-trips instead of 1. (b) An API integration to the frontier model — assumes a service the operator does not run; the filesystem is the only integration that exists. (c) Let the EM decide when to escalate — escalation is procedure, and procedure is shell-owned (D-26).

**Reason:** Judgment escalates exactly one tier per rung, every rung is bounded, and the expensive rung (human + frontier) is batched. The bundle must be self-contained (task entry, evidence, EM diagnosis, referenced contract entries, failing frozen-test sources) because the TPM has no repo access.

**Do not suggest:** Escalating straight to the TPM without an EM diagnosis (the diagnosis is what makes the bundle actionable). Unbounded brief revisions. Letting an agent write into `.pipeline-state/escalations/`.

---

## D-28 — 2026-07-01 — Oracle projection: EM schedules frozen TPM tests, authors nothing

**Decision:** Test authorship lives at the TPM tier, frozen via re-freeze (D-31). The per-task acceptance signal of the hot loop is a **projection** of that frozen oracle: each plan task lists the frozen test node-ids expected to pass once it and its dependencies are done. The EM schedules tests onto tasks; it never authors acceptance. The plan gate enforces the mapping is total and exactly-once. Feature completion has exactly one definition: the FULL frozen suite green. The case "every task passed its projection but the full suite is red" is mechanically detected as **spec drift** and routes EM→TPM (decomposition fix or spec delta) — never to coder retries. Tasks with no covering test carry an explicitly non-oracular `smoke_check`; the validator rejects tasks with neither.

**Alternatives considered:** (a) EM authors per-task acceptance checks — re-creates oracle-authorship at the mid tier, the exact hole this redesign exists to close (the green signal must not be authored below the judgment tier). (b) Run the full suite after every task — most failures would be absent-dependency noise, drowning the real signal. (c) No per-task signal, only the final suite — failure attribution collapses; every defect surfaces at integration.

**Reason:** The working oracle of the loop and the truth oracle are the same artifact viewed through a schedule, so they cannot drift in content — only in scheduling, which the exactly-once mapping check and the drift signal both catch mechanically. INV-1 ("tests derive from the spec, not the code") is now structural rather than advisory: the tests are written before the code exists, by a tier that never sees the implementation, and no agent can edit them.

**Do not suggest:** Letting any agent author or edit tests. Treating a task's mapped-tests-green as feature-done. Routing a spec-drift signal to the coder.

---

## D-27 — 2026-07-01 — Capability ladder: TPM (web-chat frontier) / EM (mid-tier) / coder (local); test-runner agent deleted

**Decision:** The four-role pipeline (pm/architect/build/test agents) is replaced by a capability ladder matched to task type. **CEO** (human): business intent. **TPM** (frontier LLM in a human-operated web chat, outside OpenCode): PRD, ERD with machine-readable contracts, and the test suite — the smallest, highest-leverage artifacts — installed and frozen via `scripts/refreeze.sh`. **EM** (mid-tier free online LLM, OpenCode agent `em`): decomposition and diagnosis only, per D-26. **Coder** (local LLM, OpenCode agent `coder`): one file per task, pure execution. The pm/architect/build/test prompts and the test agent are deleted; tests are RUN by the orchestrator via `pytest --json-report` — a shell command needs no agent wrapped around it (Rule 5: an LLM whose job is to run a command and describe the output can only add error).

**Alternatives considered:** (a) Keep architect as a local agent — decomposition against locked seams is mid-tier work, but plan-sized judgment (contracts, tests) is not; splitting TPM/EM matches each artifact to the cheapest tier that can own it. (b) Keep a test agent to run pytest — deleted for the Rule 5 reason above. (c) All-frontier — forfeits the cost model; the ladder exists to spend frontier tokens only on spec/contract/test artifacts and escalation deltas.

**Reason:** Frontier pays per token and never stops; local is a fixed cost trending better. The ladder bets on that trendline while keeping every load-bearing artifact (contracts, tests) at the judgment tier and every procedure in shell. The seam rule: the TPM locks cross-component contracts (cheap for it, catastrophic when wrong below); the EM owns everything inside them.

**Do not suggest:** Re-adding a test-authoring or test-running agent. Giving the EM a write lane beyond `tasks/`. Calling the TPM programmatically (it is a human-operated chat; see D-29).

---

## D-26 — 2026-07-01 — Schema-validated artifact handoffs; plan.json validation gate

**Decision:** Every inter-tier handoff is a schema-validated artifact on disk; the shell orchestrator is the only actor with procedural authority. The EM's sole channel of authority is `tasks/plan.json` (schema: `scripts/schemas/plan.schema.json`), mechanically validated by `scripts/validate-plan.py` before any coder runs: one file per task and one task per file (structural atomicity), acyclic DAG, exact bijection with the frozen ERD file inventory, every frozen test node-id mapped to exactly one task, every referenced contract id present in the frozen contracts, plan freshness against `scripts/.approved/VERSION`. The plan carries **no status field** — the validator rejects one. Task status, ordering, completion, and escalation counters live in `.pipeline-state/`, owned by the shell. EM consult responses are likewise schema-bound (`scripts/schemas/diagnosis.schema.json`, verdict enum `brief_wrong | decomposition_wrong | contract_or_test_wrong`).

**Alternatives considered:** (a) EM reports decomposition and progress conversationally, orchestrator parses prose — trusts narration, the exact failure class this project exists to reject. (b) EM drives the loop itself and self-reports completion — re-creates the pre-D-05 failure (LLM forgets gates, miscounts strikes) one tier up. (c) Full `jsonschema` dependency — validator is stdlib-only (`json`/`hashlib`) to match the orchestrator's existing pre-flight contract.

**Reason:** A bad decomposition must fail loudly at validation time, not surface three phases later as an integration error. This is D-05 (deterministic shell owns procedure) applied uniformly: LLMs produce content, shell computes everything computable — so the EM's residual authority is exactly the content of its decomposition and diagnoses, nothing procedural.

**Do not suggest:** Adding a status/progress field to plan.json for the EM to maintain. Letting any agent update `.pipeline-state/`. Parsing EM free-text instead of the diagnosis schema.

---

## D-25 — 2026-06-26 — INV-3: Decision traceability gate (Adoption 3)

**Decision:** Every non-documentation decision in DECISIONS.md (tagged with a D-NN ID) MUST appear in ARCHITECTURE.md. The architect→build handoff is mechanically blocked by `scripts/phase-gate.sh architect` — the gate greps ARCHITECTURE.md for each D-ID and exits non-zero if any are missing. Documentation-only decisions are exempted via a `**Documentation-only:**` marker in the decision body.

**Rationale:** This is INV-3, same class as INV-1 and INV-2 — a mechanical, blocking gate. It closes the gap where an architect could make a decision in DECISIONS.md that never reaches the build agent (ARCHITECTURE.md is the build agent's source of truth). The grep is intentionally simple — no manifest, no registry, just string matching. This keeps the ceremony low enough that the gate is a net time-saver (catches forgotten updates) rather than a tax.

**Alternatives considered:** (a) A separate decision-manifest file — extra indirection, more things to keep in sync. (b) Requiring D-IDs in the build prompt verbatim — over-constrained, the prompt already references ARCHITECTURE.md. (c) No gate, rely on architect discipline — advisory only, contradicts the project's mechanical-gate philosophy.

**Do not suggest:** Central registry of D-IDs (the headings ARE the registry). Making the gate check for coverage in the build prompt instead of ARCHITECTURE.md.

---

## D-24 — 2026-06-26 — File-based pipeline state persistence (Adoption 2)

**Decision:** All pipeline loop state (iteration count, re-plan count, failure signature, repeat counter, current phase) is written to `.pipeline-state/` files before each agent phase. On crash, the orchestrator resumes by reading these files. `.pipeline-state/` is gitignored — runtime diagnostics only.

**Alternatives considered:** (a) Pass state via git commit messages and re-parse them — fragile, human-hostile format. (b) Store in environment variables passed to a supervisor — doesn't survive container restart. (c) Ephemeral shell variables (current design) — lost on crash.

**Reason:** A crash mid-loop (Podman OOM, network drop, host reboot) currently loses all state. The state file is a single checkpoint written BEFORE each phase, surviving anything short of `rm -rf .pipeline-state/`. Also the foundation for the OpenHands port, where the orchestrator will be an LLM agent that reads/writes files instead of shell variables.

**Do not suggest:** Version-controlling `.pipeline-state/` (ephemeral diagnostic data). Using a database, Redis, or any networked state store. Writing state after the phase (loses info on crash mid-phase).

---

## D-23 — 2026-06-26 — Fresh context per task (Adoption 1)

**Documentation-only:** This decision documents a design principle already satisfied by the shell-orchestrator architecture.

**Decision:** The orchestrator MUST spawn each build and test task in a clean context window. State transfers between tasks via structured files on disk, never via conversation history.

**How the shell orchestrator satisfies this:** `scripts/orchestrate.sh` wraps each agent phase in a separate `opencode run --attach --agent <name>` invocation (line 79-81). Each invocation starts fresh. The orchestrator itself is a shell script — no LLM context to rot.

**Target for OpenHands port:** When the orchestrator becomes an LLM agent, the coordinator loop must stay under 40% of its context budget.

**Do not suggest:** Passing state between phases as part of the agent prompt. Merging the orchestrator loop into a single agent context window.

---

## [DATE] — [Your first decision here]

**Decision:** [e.g. Using raw SQL over ORM]
**Alternatives considered:** [e.g. SQLAlchemy, Tortoise ORM]
**Reason:** [e.g. Query complexity made ORM unreadable for our join-heavy patterns]
**Do not suggest:** Switching to an ORM. This was deliberate.

---

## [DATE] — Monorepo structure (template placeholder — skip D-ID assignment)

**Decision:** Single repository for all services.
**Alternatives considered:** Separate repos per service.
**Reason:** Team size doesn't justify the overhead of managing multiple repos. Shared code is easier to refactor.
**Do not suggest:** Splitting into microservices repos until team grows past 5 engineers.

---

## D-01 — 2026-06-04 — Pruned BLUEPRINT.md (557 → ~440 lines)

**Decision:** Apply the noise/redundancy findings from a parallel LLM audit; skip the lifecycle/strategy findings from a second LLM.
**Documentation-only:** This decision documents a doc-pruning action; it does not change the API or build plan.
**Alternatives considered:** (a) accept both LLMs' suggestions and add new rules; (b) leave the file as-is; (c) full rewrite.
**Reason:** BLUEPRINT.md is the LLM's entry point. Every redundant line is context-window cost and a chance for ambiguity to compound. Pruning is a guardrail against drift, not cosmetics. Adding more rules (the second LLM's "fortify" suggestions: Doc-Sync hard rule, TDD loop, REVIEW checkpoints, `/reset-context`) would partially undo the trim and add bloat.
**Do not suggest:** Re-adding the dropped sections. The "Document Map" alone is sufficient; the verbose "Document Roles Explained" was redundant. "Step 5 — Adapt the stack" is a pointer to Rule 3, not a restatement. Bootstrap cleanup, OpenCode Configuration, and Quick Reference Card are now minimal — keep them so.

**Trimmed (12 items, ~115 lines removed):**
- Dropped "Document Roles Explained" (duplicated Document Map)
- Collapsed Bootstrap Step 5 to a 1-line pointer to Rule 3
- Trimmed Maintenance Contract from 6 rows to 4 (dropped obvious triggers)
- Trimmed Files Never to Touch from 5 items to 3 (universal best-practice items removed)
- Shrunk Bootstrap Step 4 cleanup (24→6 lines)
- Trimmed Step 7 preamble (dropped "Hard Rule 5" restatement)
- Shrunk OpenCode Configuration section (28→3 lines + pointer to `opencode.json`)
- Trimmed anti-pattern "wrong provider name" to a one-liner
- Deleted Quick Reference Card (restated diagram + rules)
- Fixed phantom "Step 4.5" reference on line 490 → "Step 4"
- Reduced duplicate "lms not lmstudio" mentions from 3 to 1
- Reduced "AGENTS.md symlinks to CLAUDE.md" mentions from 5 to 3 (one in prose + 2 short callouts)

---

## D-02 — 2026-06-04 — Auto-load assumption corrected; CLAUDE.md / opencode.json fixes

**Decision:** (a) Rewrite `CLAUDE.md`'s intro to accurately describe its load behavior — file is *fetchable via tools*, not pre-loaded; the LLM is *expected* to read it. (b) Fix the project's `opencode.json` schema (OpenCode 1.15.13 rejects the old `providers` / top-level `models` form with "Unrecognized keys"). The original commit also added a "do not re-add dropped BLUEPRINT.md sections" mirror guard to `CLAUDE.md`; that mirror was later removed (see entry below) for template-hygiene reasons.

**Documentation-only:** This decision documents a measurement and fix to doc guards and config; it does not change the API or build plan.

**Alternatives considered:** (a) Document the asymmetry but not fix it; (b) add a hook in BLUEPRINT.md to force the LLM to read CLAUDE.md first; (c) leave the broken `opencode.json` and tell users to delete it.

**Reason:** The architectural premise that "guards in CLAUDE.md auto-fire every session" was unverified and partially false. Empirical test showed the model uses the `read` tool to fetch content (not pre-loaded) and can misparse which guard applies. The memory layer is best-effort, not enforced. For things that *must* hold, prefer mechanical gates (grep, `wc -l`, CI, git hooks) that fire without the LLM's cooperation. Doc guards are strong hints, not hard gates.

**Do not suggest:** Reverting `CLAUDE.md`'s intro to the "automatically read" claim, or reverting `opencode.json` to the old `providers` schema. Both are now verified-correct by empirical test.

**Verified by:**
- `opencode run --format json --dir /tmp/opencode-autoload-test "Read AGENTS.md..."` — event log showed `tool_use` with `read` tool; model fetched content but answered wrong
- `opencode --version` → `1.15.13` (matches the schema fix)
- `opencode run "What is 2+2?" --format default` from project dir → "Four." (schema fix loads cleanly under the installed version)

**Cross-cutting lesson (worth applying to all template projects):** Treat doc guards as advisory. For must-hold rules, build mechanical checks into scripts or CI:
- Placeholder completeness → grep (BLUEPRINT.md Step 7)
- File size budgets → `wc -l` in a pre-commit hook
- Schema validity → `opencode.json` parsed at session start
- Tests as ground truth → pytest in CI (BLUEPRINT.md Rule 5)
Doc guards catch the LLM's *intent*; mechanical gates catch the *result*. Both have a place. The test just proved the first is weaker than the design claimed.

---

## D-03 — 2026-06-04 — Removed CLAUDE.md mirror guard (decoupling template from project)

**Decision:** Remove the one-line "Do not re-add sections dropped from BLUEPRINT.md in the 2026-06-04 prune" guard from `CLAUDE.md`'s "What NOT To Do" → Operating guardrails. The rule still lives in `DECISIONS.md` → "Pruned BLUEPRINT.md" entry.

**Documentation-only:** This decision documents a doc decoupling action; it does not change the API or build plan.

**Reason:** CLAUDE.md is a template — `[PROJECT_NAME]` is still a placeholder. Baking a project-specific date ("2026-06-04 prune") into a template file makes the rule meaningless for any future project created from this template. The visibility argument was real but the template-vs-project boundary was muddied. The principle (don't re-add dropped sections) stays binding via DECISIONS.md's "Do not suggest" line and the correction log capture.

**Do not suggest:** Re-adding the mirror guard. Cross-reference, don't copy.

---

## D-04 — 2026-06-06 — Demoted BLUEPRINT.md line-count gate to heuristic

**Decision:** Removed the failing `wc -l BLUEPRINT.md <= 450` check from CI and the correction log's hard-target language. The 450 number was self-imposed by the model during a pruning session, never a human requirement. Line count is a proxy that does not measure the real goal (no redundant/ambiguous content). Enforcement is replaced with a heuristic note at the bottom of BLUEPRINT.md.

**Documentation-only:** This decision documents a CI gate change; it does not change the API or build plan.

**Reason:** Enforcing a specific line count as a CI failure pressures edits to delete real content — including safety rules — to stay green. A mechanical gate is right for binary invariants (INV-2, placeholder completeness), wrong for a judgment call like doc leanness. The anti-bloat principle is genuine (BLUEPRINT is the LLM's entry point; redundancy is token cost and ambiguity risk), but enforcement should be human review and cross-reference discipline, not a numeric gate.

**Do not suggest:** Re-adding a failing line-count check, or compressing rules to hit a number. The "do not re-add pruned sections" guards in DECISIONS.md and human review are the correct mechanisms — they target redundancy directly.

---

## D-05 — 2026-06-06 — Code-driven orchestration loop

**Decision:** Moved loop control out of `architect.md` (where an LLM must remember to run the gate, read the test report, count strikes, and route) and into `scripts/orchestrate.sh`. The orchestrator is a shell script that drives the build→test loop deterministically: it starts a headless `opencode serve`, calls each agent via `opencode run --attach --agent <name>`, runs `scripts/phase-gate.sh` after each phase, parses the JSON test report via `python3 -c`, computes a `sha1(sorted(failing_node_ids))` signature for two-strike detection, and escalates to re-plan on identical failure signatures. The architect prompt shrinks to "produce/refresh the plan only."

**Reason:** Loop control in an LLM prompt is a doc-guard — the architect could forget to run the gate, mis-count strikes, or skip escalation. Moving it to a script makes the gate invocation, the two-strike counter, and the halt deterministic — each is a line of shell code, not a remembered instruction. Additionally, each scoped `opencode run` sidesteps the non-transitive-permission bug (each agent runs in its own invocation with its own permissions) and prevents context bloat over long loops. The script wraps each agent call in a `run_agent` function that is the single indirection point for future sandbox adoption.

**Do not suggest:** Putting orchestration logic back into `architect.md`, or auto-approving the PRD (the orchestrator refuses to run unless `Status: Approved`). Adding a queue, daemon, web UI, or multi-feature scheduling — one approved PRD, one run. Replacing the shell script with an orchestration framework (adopt OpenHands later if needed — note it in DECISIONS, don't pre-build for it).

**Server details (for posterity, empirically verified on OpenCode 1.15.13):**
- `opencode serve --port <n>` starts a headless server; default port is 0 (random), use `--port` explicitly.
- `opencode run --attach <url> --agent <name> <prompt>` calls a specific agent on the running server.
- Server is killed on script exit via `trap cleanup EXIT`.

---

## D-06 — 2026-06-06 — Adopted EARS for acceptance criteria

**Decision:** Acceptance criteria in `tasks/CURRENT.md` are now written in EARS notation (THE SYSTEM SHALL / WHEN...SHALL / WHILE...SHALL / IF...THEN SHALL / WHERE...SHALL). Each criterion is a single observable clause that maps one-to-one to a test case. The PM prompt enforces this at PRD time; the test prompt reinforces the mapping at test time. Template examples in CURRENT.md demonstrate all five forms plus an HTML-comment reference guide.

**Reason:** EARS forces each requirement into a single testable clause, giving the test agent an unambiguous oracle and tightening INV-1 enforcement. Vague prose criteria ("handles errors gracefully", "works correctly") were the weak point — the tester had to interpret intent, which reintroduces the ambiguity the pipeline was designed to eliminate. A one-clause-to-one-test mapping makes the test agent's job mechanical and removes the interpretation gap.

**Do not suggest:** Reverting to free-form prose criteria, or forcing all five EARS forms when a single SHALL clause suffices (avoid ceremony — see the repo's anti-over-engineering history, BLUEPRINT.md and DECISIONS.md prune entries).

---

## D-07 — 2026-06-06 — Four-role PRD→Plan→Build→Test pipeline

**Decision:** Adopted a four-role pipeline (PM, Architect, Build, Test) with two non-negotiable invariants: INV-1 (tests derive from the PRD, never from `src/` implementation) and INV-2 (Build never edits `tests/`; Test never edits `src/`). The PRD in `tasks/CURRENT.md` is the single oracle — the human's casual instruction is translated into structured acceptance criteria and flagged assumptions, then frozen on Approval. The Architect is also the orchestrator: it delegates build→test, runs `scripts/phase-gate.sh` after each phase, reads `.cache/test-report.json`, and routes failures per Rule 2/7 (build bug→build, same failure twice→re-plan, plan fails twice→PM).

**Alternatives considered:** (a) Extend the existing single-agent loop with role instructions in CLAUDE.md; (b) use OpenCode agent permissions alone for INV-2 enforcement; (c) keep the flat loop and add no roles.

**Reason:** A single-agent loop conflates planning, writing, and testing in one context — the model's self-judgment replaces the test-report oracle (Rule 5 drift) and nothing prevents it from writing tests that confirm what `src/` does rather than what the spec says (INV-1 violation). Separate roles with frozen contracts force the verification gap that catches bugs. OpenCode's agent permissions (`permission.edit` globs) are non-transitive — a restricted agent can bypass limits via the Task tool (opencode issues #12566, #20549) — so INV-2 is enforced mechanically by `scripts/phase-gate.sh`, not by permissions alone. Doc guards catch intent; mechanical gates catch the result (documented pattern from the 2026-06-04 auto-load entry). Cost rationale: build/test use the local model (free, 80% of tasks); pm/architect use frontier for reasoning walls and spec work.

**Do not suggest:** Letting the test agent read `src/` implementation to author tests (INV-1). Enforcing INV-2 with agent permissions alone — the git gate is the binding layer. Merging the four roles back into a single agent — the whole point is the verification gap between them. Letting the build or test agent edit the PRD or architecture docs.

---

## D-08 — 2026-06-09 — AC9 compliance: mandatory sandbox + freeze trap closure

**Decision:** Two changes for temp PM review compliance:

1. **AC9 (no sandbox override):** Removed the `I_UNDERSTAND_UNSANDBOXED` override entirely. `orchestrate.sh` now fails immediately if `SANDBOX != 1` — no fallback path, no debug flag. Containerized execution is mandatory.
2. **Freeze trap (P3 fix):** Moved `ARCHITECTURE.approved.md` from `docs/` (architect's writable lane) to `scripts/.approved/` (outside every agent's whitelisted directory). The orchestrator creates the directory and copies the file after the architect gate passes; no agent can touch it.

**Reason:** The frozen AC9 criterion specified no env var or flag that disables containerized execution. The `I_UNDERSTAND_UNSANDBOXED` override existed as a conversational suggestion from the PM during code review but violated the frozen spec. Debug frequency is low enough that the friction is negligible — strict compliance avoids the "advisory safety" pattern the project exists to reject. The freeze trap was exposed by an empirical test: a re-plan architect could and did overwrite `docs/ARCHITECTURE.approved.md` because `docs/` is the architect's permitted directory. Moving the file to `scripts/.approved/` makes the constraint structural (wrong lane) rather than rule-based (gate carve-out).

**Do not suggest:** Re-adding `I_UNDERSTAND_UNSANDBOXED` or any sandbox-disable flag. Moving `ARCHITECTURE.approved.md` back to `docs/`. Both were deliberate removals against verified defects.

---

## D-09 — 2026-06-06 — Sandbox Wiring in Orchestrator

**Decision:** `scripts/orchestrate.sh` routes agent calls and pytest through `scripts/sandbox-run.sh` when the `SANDBOX=1` environment variable is set. The sandbox path wraps each agent call with `timeout "${AGENT_TIMEOUT}"` (the container runs Debian where `timeout` is available from coreutils). The non-sandbox path uses `$TIMEOUT_CMD "${AGENT_TIMEOUT}"` (`gtimeout` on macOS, `timeout` on Linux). `SANDBOX_LLM_HOST` is read from the environment; both `orchestrate.sh` and `sandbox-run.sh` default it to `host.containers.internal` independently. When the orchestrator drives the run, its exported value is inherited by the container launcher; run standalone, `sandbox-run.sh` supplies its own default. The orchestrator does not hard-code the address — it reads the variable set upstream.

**Alternatives considered:**
- (a) Always run inside the sandbox, no fallback — breaks for developers without Podman
- (b) Hard-code `host.containers.internal` directly in `orchestrate.sh` — duplicates the address assumption that step 0 is supposed to prove
- (c) No sandbox path — forfeits container isolation

**Reason:** The `SANDBOX=1` env var is a single indirection point. Defaulting to `SANDBOX=0` preserves the existing non-sandbox workflow for development. The sandbox path delegates entirely to `sandbox-run.sh`, which is the single script that manages Podman flags, volume mounts, and the LLM host address. The orchestrator only knows `host.containers.internal` via the env var chain, not as a literal.

**Do not suggest:** Hard-coding `host.containers.internal` in `orchestrate.sh`; removing the `SANDBOX=0` fallback; adding a second sandboxing mechanism.

> **2026-06-09 correction:** The "SANDBOX=0 fallback" and "always run inside the sandbox" alternatives were revisited for AC9 compliance. The sandbox is now mandatory (no fallback). This decision entry is historical context; the current behavior is documented in the 2026-06-09 entry above.

---

## D-10 — 2026-06-06 — macOS Compatibility Fixes for Sandbox Scripts

**Decision:** `scripts/sandbox-run.sh` and `scripts/orchestrate.sh` use `pwd -P` instead of `pwd` to resolve macOS `/tmp` → `/private/tmp` symlink for Podman bind-mount path matching. `sandbox-run.sh` uses Podman's built-in `--timeout` flag instead of external `timeout(1)` (which does not exist on macOS). `orchestrate.sh` detects `gtimeout` (macOS, from `brew install coreutils`) vs `timeout` (Linux) for its script-level agent timeout.

**Alternatives considered:**
- (a) Install coreutils on macOS and alias `timeout` — requires every macOS dev to opt in
- (b) Skip timeout entirely on macOS — agents hang indefinitely
- (c) Use Podman's `--timeout` only (already present) and skip the script-level wrapper — the wrapper is needed for the non-sandbox path and as a belt-and-suspenders guard

**Reason:** macOS is the primary development platform (verified by `uname`). The `/tmp` symlink (`/tmp` → `/private/tmp`) causes Podman bind-mount failures because the container resolves the physical path differently than the host. External `timeout(1)` is a Linux-only command. Podman's `--timeout` flag works on both platforms and replaces it. The `gtimeout`/`timeout` detection on the orchestrator's non-sandbox path follows the same pattern as the project's other platform-detection logic.

**Do not suggest:** Removing macOS support; switching to a Linux-only requirement; wrapping `timeout` in a shell function that fails silently.

---

## D-11 — 2026-06-06 — Agent Permission Model: No Catch-All Deny

**Decision:** The test agent's `edit` permission uses explicit `src/**": "deny"` and `tests/**": "allow"` with no `**": "deny"` catch-all. The catch-all overrode the specific allow because `**` matches `tests/` paths. Build agent keeps `tests/**": "deny"` with `**": "allow"` as its catch-all — reversed logic because build's allowed set (everything except tests) is too broad to enumerate.

**Alternatives considered:**
- (a) Keep `**": "deny"` and list every non-test directory explicitly — brittle, misses new directories
- (b) Use `--dangerously-skip-permissions` server-side — bypasses the entire permission model
- (c) Single agent with no role separation — violates INV-2

**Reason:** Explicit + allow with no deny catch-all is the simplest permission config that lets the test agent write files. OpenCode's permission engine applies matching deny rules regardless of specificity — a `**`: deny always catches `tests/` paths. Removing the catch-all fixes this at the config level.

**Do not suggest:** Re-adding `**": "deny"` to the test agent; adding `--dangerously-skip-permissions` as a permanent fix.

---

## D-12 — 2026-06-06 — Local Model Tier: Qwen3.6-35B-A3B for Build/Test

**Decision:** Build and test agents default to `lms/qwen/qwen3.6-35b-a3b` (35B parameters, 3B active). The 7B `qwen3-coder-next` model produces malformed tool calls (omits required fields like `filePath` and `content` from the Write tool) and is removed from any file-writing role. PM and architect agents remain on `[FRONTIER_MODEL]` per the cost-tier design.

**Alternatives considered:**
- (a) Run all agents on frontier models — higher cost, negates local-tier savings
- (b) Wait for better 7B tool-calling support — uncertain timeline
- (c) Use Gemma-4-31B — not tested, but 35B Qwen writes files correctly

**Reason:** The 35B model is the smallest local model found that reliably constructs valid OpenCode tool calls. It writes files, installs dependencies, and passes gates. The two-tier cost model (frontier for planning, local for build/test) is preserved — the threshold is 35B, not 7B.

**Do not suggest:** Reverting build/test to the 7B model; running build/test on frontier models permanently.

---

## D-13 — 2026-06-07 — Pipeline robustness fixes (container deps, PYTHONPATH, gate recovery)

**Decision:** Bake `fastapi uvicorn httpx pydantic` into Containerfile, add `PYTHONPATH=/work` to sandbox-run.sh, soften gate violations from hard-halt to cleanup+continue, and add `pip install` fallback before pytest.

**Alternatives considered:** Installing via `pip install --user` at runtime (fails — user site-packages not on Python search path), installing via build agent (lost on container exit), mounting host `site-packages` (fragile).

**Reason:** Non-root `agent` user (UID 1000) has no sudo and `pip install --user` drops to `~/.local/lib/python3.12/site-packages/` which Python does not search by default. The 35B model sometimes writes tests during build phase despite explicit prompts — cleanup+continue is more productive than halting. `pip install` before pytest ensures deps survive container rebuilds.

**Do not suggest:** Installing deps via the build agent (agent runs in disposable container, install lost on exit). Hard-halting on gate violations (35B model needs graceful recovery). Removing `PYTHONPATH` (required for `from src.main import app`).

---

## D-14 — 2026-06-07 — Context window ceiling measurement and fix

**Decision:** Measured the largest 35B agent payload (test agent: `.opencode/prompts/test.md` ~721B + orchestrator instruction ~166B + opencode system preamble ~8000B). Total estimated at ~3000 tokens. Raised LM Studio context length for `qwen/qwen3.6-35b-a3b` from the 8192 default to 32768 (32K) — four orders of magnitude over the measured need, with generous headroom for conversation history. The model natively supports 262144 (`max_position_embeddings` confirmed via HuggingFace config). Lever used: context bump, not prompt trim — the prompts themselves are small; the ceiling was LM Studio's default.

**Reason:** The 35B model's default context window in LM Studio (8192) was too small for the combined system preamble + agent prompt + instruction, causing context-length errors in prior runs. The model supports 256K native; 32K is a comfortable operating point that leaves GPU memory headroom (35.16 GiB used, 128 GiB available on M5 Max).

**Also changed:** `developer.separateReasoningContentInAPI` in `~/.lmstudio/settings.json` from `true` to `false`. When `true`, Qwen models that have reasoning enabled return `content: ''` with output in `reasoning_content` — opencode reads `content` only, so the model was unusable. Merging reasoning into `content` (even with the `<think>` block) keeps the model functional. To fully disable thinking (no reasoning tokens wasted), toggle the "Think" switch off in LM Studio UI for this model.

**Do not suggest:** Lowering context below 32K; switching to the `-ud-mlx` variant for context reasons only (the regular model seats 32K comfortably); trimming the agent prompts (they are not the bottleneck).

---

## D-15 — 2026-06-07 — INV-2 gate: halt, not cleanup

**Decision:** Reverted the INV-2 gate handler in `scripts/orchestrate.sh` from cleanup+continue back to halt-and-flag (exit 1 with violation note in `tasks/CURRENT.md`). The prompt-hardening ("Write src/ only", "Write tests/ only") from the same commit was kept.

**Alternatives considered:** (a) Keep cleanup+continue — unblocks the run but silently swallows a boundary violation that should be visible. (b) Leave the gate as-is (soft-halt with inspection note but no exit) — same problem, different disguise.

**Reason:** A boundary violation (build wrote to `tests/` or test wrote to `src/`) is evidence that the model or instructions are wrong. That signal must stop the run and be recorded, not auto-swept. The halt is the enforcement; the gate (phase-gate.sh) is the detector. Cleaning up and continuing makes the violation invisible to the human keystone. The price of a halted run is the cost of INV-2 working correctly.

**Do not suggest:** Re-introducing cleanup+continue; treating a gate violation as a routine iteration failure rather than a process break.

---

## D-16 — 2026-06-07 — Model pin: qwen/qwen3.6-35b-a3b (base) as default

**Decision:** Standardize on `qwen/qwen3.6-35b-a3b` (base model, 8-bit MLX, 37.75 GB) as the local build/test agent model. The `-ud-mlx` variant exists at 21.66 GB (4-bit) as a lower-memory fallback. The `opencode.json` config already points to the base model — this entry confirms it as the deliberate choice, not an accidental default.

**Alternatives considered:** (a) `qwen3.6-35b-a3b-ud-mlx` — 4-bit quantized, 21.66 GB, faster load but slightly lower quality. (b) `qwen/qwen3-coder-next` — 80B, 44.86 GB, too large for routine agent calls. (c) `[FRONTIER_MODEL]` — reserved for pm/architect only.

**Reason:** The base model seated 32K context at 35.16 GiB on M5 Max (128 GB unified memory), leaving ~90 GB for other workloads. The MLX variant loads in 21.66 GB but introduces a different serving path (unsorted, unproven for this project). The base model is the one the prompts were written and validated for. The two-tier cost model (frontier for planning, local for build/test) is preserved with a line at 35B, not 7B.

**Do not suggest:** Switching to `-ud-mlx` as the default; running build/test on frontier models permanently; dropping below 35B for writing agents.

---

## D-17 — 2026-06-07 — Template deps: app packages baked into Containerfile

**Decision:** Keep `fastapi uvicorn httpx pydantic` baked into the Containerfile and `PYTHONPATH=/work` in `sandbox-run.sh` as template defaults. These are not validation-harness-only — they fix a universal bug: the non-root `agent` user (UID 1000) cannot `pip install --user` into system site-packages. Any FastAPI project in this template runs into the same failure.

**Alternatives considered:** (a) Remove baked deps, require every project to add its own via `requirements.txt` — every new project re-debugs the same user-site-packages issue. (b) Switch to root container user — defeats the isolation purpose. (c) Install via build agent at runtime — lost on container exit, which is why the orchestrator's `pip install` fallback exists on line 123.

**Reason:** The four packages cover the most common FastAPI stack. The `pip install` fallback in `orchestrate.sh` line 123 is now redundant and should be removed as a follow-up — the Containerfile guarantees the deps are present at build time. The `PYTHONPATH=/work` fix is similarly universal: without it, `from src.main import app` fails in the container regardless of project.

**Do not suggest:** Removing these deps from the Containerfile. Removing `PYTHONPATH=/work`. Both will cause the same failures for every new project and the fix will be re-discovered each time.

---

## D-18 — 2026-06-07 — 32K context as pinned default for local model

**Decision:** Confirmed the 32,768 token context length as the pinned operational setting for `qwen/qwen3.6-35b-a3b`. Measured the largest agent payload at ~3,000 tokens (test agent prompt + instruction + opencode system preamble). 32K provides 10x headroom for conversation history.

**Alternatives considered:** (a) 8,192 (LM Studio default) — caused context-length errors in prior runs. (b) 131,072 or 262,144 (model max) — unnecessary GPU memory consumption, model seats 32K at 35.16 GiB.

**Reason:** The model natively supports 262,144 tokens (`max_position_embeddings` confirmed via HuggingFace config). 32K is a comfortable operating point that leaves GPU memory headroom (35.16 GiB used across the available 128 GiB). No prompt trimming needed — the bottleneck was LM Studio's default.

**Do not suggest:** Lowering context below 32K; raising to 256K without a demonstrated need.

---

## D-19 — 2026-06-07 — docs/.pm-last-review: PM-owned ref marker

**Decision:** Introduced `docs/.pm-last-review` — a one-line file holding the last PM-reviewed commit hash. The build agent reads it at report time to scope its commit list; no agent writes or advances it. "Reviewed" means verified and accepted by the PM — not pushed, not agent-declared done. This is the same artifact-over-memory principle the project enforces on tests (PRD → tests, never src → tests), applied to reporting: the marker removes the retrieval failure (ref buried in chat), but the PM's source-side reconciliation remains the actual guarantee.

**Alternatives considered:** (a) Storing the ref in the build agent's session/context — proven unreliable, this entire fix is why. (b) Tagging the repo with each review — noisy and requires push permissions. (c) Reading the ref from a PM-API call — overengineered.

**Reason:** The previous design relied on the PM's ref persisting in conversation history across turns. It didn't. A file in the repo is persistent, versioned, and readable by tool calls. The PM advances it only after verifying the work. The file assists, it doesn't replace the human check.

**Do not suggest:** Any agent writing to this file; removing the PM's source-side reconciliation because the file exists.

## D-20 — 2026-06-07 — Advisory vs mechanical enforcement

**Decision:** Of the seven Operating Rules, only Rule 1 ("report against the tree") has a mechanical backstop — `docs/.pm-last-review` for the ref plus the PM's source-side reconciliation as the ultimate check. Rules 2–7 are advisory: they rely on PM review for enforcement and no agent workflow enforces them mechanically.

**Documentation-only:** This decision documents a process observation; it does not change the API or build plan.

**Reason:** Honest labeling prevents these rules from being mistaken for guarantees. The durable safeguard is the PM's verification, not the doc. Aspirational claims that a rule "prevents" or "ensures" something erode trust when inevitably violated.

**Do not suggest:** Claiming mechanical enforcement where none exists; adding commit-scope hooks or other automated enforcement without a separate PM decision.

---

## D-21 — 2026-06-07 — Operating Rules: rationale per rule

**Documentation-only:** This entry documents rationale for Operating Rules; it does not change the API or build plan.

**Rule 1 (report against the tree):** A hallucinated "6 commits" and an undisclosed model swap each cost a full PM review cycle to catch. The marker file makes the ref retrievable outside conversation history.

**Rule 2 (one commit, one concern):** A safety-rule change (gate halt→cleanup) was bundled with prompt edits and a pip fallback in a single commit, bypassing review. Bundling is how serious changes slip through.

**Rule 3 (stop-and-ask on constraint changes):** The gate soften was treated as routine de-blocking. Changing what happens on violation is a process decision, not a fix.

**Rule 4 (conditionals are checkpoints):** The `-ud-mlx` fallback was used silently despite its precondition (base model failure) never occurring. The swap was only caught in post-hoc review.

**Rule 5 (read the artifact):** A validation report was written from the build agent's chat summary, not from the committed artifact. The summary was less accurate than the file it described.

**Rule 6 ("detected" ≠ "enforced"):** A standalone gate-test result was placed under a live-run section, implying the pipeline enforced a boundary that was switched off at the time.

**Rule 7 (decide trivial calls):** A placement question (where in AGENTS.md to put the Reporting section) burned three turns when the PM had already stated "put it where process docs live." Re-asking after the principle is clear wastes cycles. Asking is not failure when correctness is at stake — that's the second clause of the rule.

---

## D-22 — 2026-06-07 — INV-2 gate: halt, not auto-clean (reaffirmed)

**Decision:** The INV-2 gate exits with code 1 on any boundary violation (build writes tests/, test writes src/). It does not auto-clean, retry, or continue. A boundary violation is a signal for the human keystone — evidence that the instruction or model is wrong — not noise to sweep.

**Reason reaffirmed after:** A prior session softened the gate to cleanup+continue, which silently swallowed violations. The build agent wrote to tests/ (correctly detecting), the gate auto-swept it, and the run continued as if nothing happened. That defeat is why the halt exists. The cost of a halted run is the cost of INV-2 working correctly.

**Do not suggest:** Re-softening to cleanup+continue without PM sign-off.

> Add new decisions above this line, newest first.
