# M2b provenance fixes — implementation brief (criteria 1–4)

> TPM-ready spec for the four gate-flip blockers in
> [`tasks/BACKLOG.md`](BACKLOG.md) → "T7 M2b". Read against `979076c`
> (2026-09-04). All four are confirmed bypasses in the current
> verifier/orchestrator, each verified by reading the cited code.
>
> **Lane:** these are control-plane changes (`scripts/check-provenance.py`,
> `scripts/git-provenance.sh`, `scripts/orchestrate.sh`) plus new blind cases
> in `scripts/selftest/selftest_provenance_m2.py`. They land through a normal
> control-plane commit gated by the 493-selftest pre-push hook and by CI
> (ruff-src + mypy + 80% coverage) — **not** through `refreeze.sh` (that path
> is for `tests/` + `.approved/`). One isolated commit per criterion (Rule 2:
> each touches gate/invariant behavior).
>
> **Order:** land 1 → 3 → 4 → 2. Criterion 2 is the only design-laden one and
> depends on nothing; do it last so the smaller wins are bankable first.
>
> **Environment:** the fixes are not "verified" until the four selftest cases
> are green in the supported Linux setup with real fixture keys. The macOS host
> ran 12 fail / 3 pass with fixture-key generation unavailable (2026-09-04) —
> triage that split before declaring any criterion done.

---

## Criterion 1 — unsigned commit is rejected once provenance is active

**Where:** `scripts/check-provenance.py`, `check_commit()`, the signature block
at [lines 248–265](../scripts/check-provenance.py:248).

**Problem:** `if sig is None: row["sig"] = "missing"` sets the display field and
appends nothing to `failures`. The `else` branch appends for
revoked/wrong-key/invalid, but a *missing* signature is silent. An in-scope
commit with a valid `Swbp-Role` + well-formed trailers but no signature returns
an empty failure list and passes `--gate`.

**Change:** in the `sig is None` branch, append a failure:

```python
if sig is None:
    row["sig"] = "missing"
    failures.append("commit is unsigned (no OpenPGP signature; "
                    "signing is required after provenance activation)")
```

The activation-boundary guard at [line 378](../scripts/check-provenance.py:378)
already restricts `gate_failures` to in-scope (`i >= boundary`) commits, so
pre-activation history keeps passing while its row still shows `sig=missing`.
This mirrors how the "M1 hole" failure at
[line 268](../scripts/check-provenance.py:268) is appended unconditionally and
filtered by scope downstream — no new scope logic here.

**Tests (`selftest_provenance_m2.py`):**
- `test_unsigned_inscope_commit_fails_gate`: signed broker commit (sets
  boundary) → in-scope task commit with valid `Swbp-Role: coder`, well-formed
  `Swbp-Model`/`Swbp-Run`, **no** signature → `--gate` exits 1, failure text
  names the missing signature.
- `test_unsigned_pre_activation_commit_still_passes`: unsigned pipeline commit
  *before* the boundary → `--gate` exit 0 (regression guard; don't over-reject
  grandfathered history).

**Edge:** does not touch out-of-scope (non-pipeline) commits — they still return
early at [line 244](../scripts/check-provenance.py:244) before the signature
block, so ordinary human commits with no role are unaffected.

---

## Criterion 3 — evidence is required by role, not optional

**Where:** verifier `check_commit()` evidence block at
[lines 282–318](../scripts/check-provenance.py:282); broker capture guard at
[git-provenance.sh lines 182–204](../scripts/git-provenance.sh:182) and the
trailer block at [216+](../scripts/git-provenance.sh:216).

**Problem:** the verifier only evaluates evidence `if p_sha or r_sha` — drop
both trailers and it records `evidence=n/a`, no failure. The broker's capture is
gated on the prompt/reply files existing, so if they're absent it stages nothing
and emits no trailers — silently. A model commit with `Swbp-Run: n/a` also
skips everything. Net: a coder/em commit can carry zero evidence and pass.

**Change — verifier.** Add near the top of the module:

```python
REQUIRED_EVIDENCE_ROLES = {"em", "coder"}
EVIDENCE_SCHEMA = "1"
```

In `check_commit()`, before the existing `if p_sha or r_sha:` block, add a
role-gated requirement:

```python
if role in REQUIRED_EVIDENCE_ROLES:
    if run == "n/a" or not run:
        failures.append("role %s requires a real Swbp-Run (got n/a) — "
                        "model commits must be evidenced" % role)
    if not p_sha or not r_sha:
        failures.append("role %s requires prompt+reply evidence trailers "
                        "(Swbp-Prompt-SHA256 / Swbp-Reply-SHA256)" % role)
    schema = trailers.get("Swbp-Evidence-Schema", "")
    if schema != EVIDENCE_SCHEMA:
        failures.append("role %s: Swbp-Evidence-Schema must be %s (got %r)"
                        % (role, EVIDENCE_SCHEMA, schema))
```

The existing hash/tamper checks then run unchanged when the trailers are
present. `human`, `tpm`, and `pipeline` are the explicit exemptions (not in
`REQUIRED_EVIDENCE_ROLES`) and keep passing with `evidence=n/a`.

**Change — broker.** In `git-provenance.sh`, before the permissive capture guard
at [line 182](../scripts/git-provenance.sh:182), fail closed when a model role
is missing its evidence inputs:

```sh
case "$role" in
  em|coder)
    if [ "$run_id" = "n/a" ] || [ -z "${SWBP_PROV_ENTRY:-}" ] \
       || [ -z "$pf" ] || [ ! -f "$pf" ] || [ -z "$rf" ] || [ ! -f "$rf" ]; then
      echo "swbp_commit: role=$role requires prompt+reply evidence and a run id "
           "(run=$run_id entry=${SWBP_PROV_ENTRY:-<unset>} pf=$pf rf=$rf) — refusing (fail-closed)" >&2
      return 1
    fi ;;
esac
```

Then emit the schema trailer whenever evidence is staged — add to the trailer
block at [line 216+](../scripts/git-provenance.sh:216):

```
Swbp-Evidence-Schema: 1
```

**Wiring is already correct for the happy path:** the em site
([orchestrate.sh:1581–1585](../scripts/orchestrate.sh:1581)) and coder site
([2276–2281](../scripts/orchestrate.sh:2276)) both export `SWBP_PROV_ENTRY` +
prompt/reply files with a real `SWBP_RUN_ID`
([806](../scripts/orchestrate.sh:806)). The pipeline `[success]` commit
([2628](../scripts/orchestrate.sh:2628)) uses role `pipeline` — exempt. So the
fail-closed branch only fires on a genuine wiring break, which is the point.

**Tests:**
- `test_coder_commit_without_evidence_trailers_fails`: in-scope coder commit,
  both evidence trailers stripped → `--gate` exit 1.
- `test_coder_commit_run_na_fails`: coder commit with `Swbp-Run: n/a` → exit 1.
- `test_evidence_schema_mismatch_fails`: coder commit, trailers present, schema
  trailer absent/wrong → exit 1.
- `test_pipeline_and_human_commits_exempt`: a `pipeline` success commit and a
  bare human commit with no evidence → pass.
- `test_broker_refuses_model_commit_without_evidence_files`: call `swbp_commit
  coder` with `SWBP_PROV_PROMPT_FILE` unset → nonzero, nothing committed.

**Decision for the TPM:** the required-evidence set (`{em, coder}`) and schema
version live in the verifier as constants. If a future role needs evidence,
add it there — keep the set and `EVIDENCE_SCHEMA` in one place, versioned.

---

## Criterion 4 — finalization failure surfaces; the run does not exit 0

**Where:** `scripts/orchestrate.sh`, the `[success]` path at
[lines 2604–2648](../scripts/orchestrate.sh:2604).

**Problem:** the current order is `SUCCESS_RECORDED=1` →
`rm -rf "$STATE_DIR"` ([2609–2610](../scripts/orchestrate.sh:2609)) → attempt
the `[success]` commit with `2>/dev/null || true`
([2628](../scripts/orchestrate.sh:2628)) → `exit 0`
([2648](../scripts/orchestrate.sh:2648)). A commit failure (signing under active
provenance, git identity, a hook) is swallowed: the checkpoint is already gone
and the run reports success. The metrics-row logic downstream already *detects*
the non-advance but only warns.

**Change — reorder to persist → commit → then tear down, and surface failure:**

1. Keep the durable persists where they are — the completion ledger
   ([2586](../scripts/orchestrate.sh:2586)) and `record_measurement 0`
   ([2608](../scripts/orchestrate.sh:2608)) already run *before* the commit, so
   validated results survive regardless. Leave `FAULT_ROLE="none"` — the feature
   *was* validated; finalization is a separate axis.
2. Move `rm -rf "$STATE_DIR"` to **after** a successful `[success]` commit.
3. Replace the swallowed commit with a checked one:

```sh
if ! git diff --cached --quiet; then
  if ! swbp_commit pipeline "$success_subject"; then
    echo "orchestrate: validation PASSED for v$FROZEN_V but FINALIZATION FAILED "
         "(the [success] commit did not land — signing/identity/hook). Durable "
         "results were persisted (completion ledger, measurement, evidence); "
         "runtime state kept at $STATE_DIR for recovery. Re-run finalization or "
         "commit manually." >&2
    SUCCESS_RECORDED=1   # measurement row already written; avoid a duplicate
    exit 3               # distinct nonzero: validated-but-unfinalized
  fi
fi
SUCCESS_RECORDED=1
rm -rf "$STATE_DIR"
```

4. The existing metrics-row block ([2620–2647](../scripts/orchestrate.sh:2620))
   stays report-only and unchanged — it now runs only on the success path.

**Interaction with the EXIT trap** ([549–574](../scripts/orchestrate.sh:549)):
on `exit 3`, the trap fires, appends an `rc=3` row to `run-exit.log` (visible
finalization signal), and — because `SUCCESS_RECORDED=1` — does **not** write a
duplicate measurement row. The measurement row already recorded `rc=0 /
fault_role=none` (validation truth). This keeps metrics honest (feature
validated) while the process exit and `run-exit.log` carry the finalization
failure. Do **not** set `FAULT_ROLE` to a tier here — a finalization failure is
not a feature fault and must not be attributed as one.

**Tests:**
- `test_success_commit_failure_exits_nonzero`: stub `swbp_commit` (or force a
  signing failure) at the success site with staged changes → orchestrate exits
  3, stderr says "validation PASSED … FINALIZATION FAILED", `$STATE_DIR` still
  exists, completion ledger + measurement row present.
- `test_success_commit_clean_still_exits_0`: happy path → exit 0, `[success]`
  commit present, `$STATE_DIR` removed (regression guard).

**Decision for the TPM:** exit code for validated-but-unfinalized. Brief
proposes `3` (distinct from `die`'s `1` and clean `0`) so CI/automation can tell
"the feature is fine, re-run finalization" from "the run failed." Confirm no
existing automation keys on exit 3.

---

## Criterion 2 — activation boundary is durable, not window-derived

**Where:** `scripts/check-provenance.py`, `main()` boundary scan at
[lines 350–376](../scripts/check-provenance.py:350).

**Problem:** `boundary` is recomputed each invocation as the first *signed
broker commit within the inspected `shas`*. Two failure modes: (a) a window that
excludes the signed broker commit leaves `boundary = None`, so every commit
becomes `pre-m2` and `--gate` passes; (b) the boundary floats with whatever
range the caller passes rather than a fixed point in history. The default range
`HEAD~50..HEAD` ([325](../scripts/check-provenance.py:325)) makes this trivially
reachable.

**Design — durable activation anchor (recommended).** Record the boundary once,
in-tree, and validate inspected commits against it by ancestry rather than by
window membership.

1. **Anchor file** `scripts/.provenance/activation` (same directory as the pin
   and revocation lists — travels with the tree, diffable, and already how trust
   state is stored):

   ```
   commit=<40-hex boundary sha>
   fingerprint=<activating key fpr>
   activated=<iso8601>
   ```

   `commit` = the first commit at/after which every in-scope pipeline commit
   must be signed.

2. **Broker subcommand** `git-provenance.sh activate` (join the existing
   `init|active|rotate|revoke|retire` dispatch at
   [424–429](../scripts/git-provenance.sh:424)): writes the anchor file for the
   current active fingerprint with `commit` defaulting to `HEAD`, refuses to
   overwrite an existing anchor with an *earlier* boundary (monotonic — you can
   only move activation forward, never retroactively expand scope), and stages
   the file. The operator commits it as the activating (signed) commit.

3. **Verifier `main()`** — replace the window scan:
   - Read the anchor from the **tree of the newest inspected commit**
     (`git show <newest>:scripts/.provenance/activation`), not the working dir —
     committed state can't be dodged by a dirty checkout, and an unsigned commit
     that *deletes* the anchor is caught by the fail-closed rule below.
   - Resolve `A = anchor.commit`.
   - For each inspected commit `C`: in-scope iff `C == A` or
     `git merge-base --is-ancestor A C` (C descends from A). This is measured
     against the durable `A`, independent of which commits are in the window.
   - **Fail-explicit conditions in `--gate`** (never silently pass):
     - anchor absent at the tip **but** the range contains signed pipeline
       commits or the pinned list is non-empty (provenance is live) → fail:
       "provenance active but no activation anchor recorded".
     - `A` set but not present in local history (`git cat-file -e A` fails) and
       an inspected commit's ancestry to `A` can't be resolved → fail: "required
       activation history unavailable (shallow clone?) — deepen and re-run".
     - an inspected pipeline commit is neither `A`, ancestor of `A`, nor
       descendant of `A` (unrelated line) → fail rather than classify.
   - Pre-flip (advisory mode, empty pins, no anchor) keeps today's behavior:
     everything `pre-m2`, exit 0.

4. **Gate the actual introduced range, not a fixed default.** `HEAD~50..HEAD` is
   a dev-inspection convenience only. At the enforcement points:
   - **pre-push hook:** read the push range from stdin
     (`<local> <remote>`) and verify `remote..local`.
   - **CI:** verify `base..head` of the push/PR.
   - If the base/anchor is unreachable in a shallow checkout → fail explicit
     (condition above), don't pass by omission.

**Tests:**
- `test_window_excluding_anchor_still_gates_descendants`: anchor recorded at A;
  inspect a range that starts *after* A and contains an unsigned in-scope commit
  → `--gate` exit 1 (the window can't downgrade it to pre-m2).
- `test_missing_anchor_with_signed_history_fails`: signed pipeline commits
  present, anchor file absent → exit 1.
- `test_anchor_unreachable_shallow_fails`: anchor SHA not in local history,
  ancestry unresolved → exit 1 with the "deepen" message.
- `test_pre_activation_advisory_passes`: no pins, no anchor, unsigned pipeline
  commits → exit 0 (regression guard).
- `test_activate_monotonic`: `git-provenance.sh activate` refuses to move the
  boundary backward.

**Decision for the TPM (anchor storage):** brief recommends the committed file
for parity with the pin/revocation lists. Alternatives considered — a signed
git **tag** (`swbp-activation`) or a **git note** — both travel less cleanly
(tags aren't fetched by default; notes need explicit refspecs) and are harder to
diff in review. Pick the committed file unless there's a reason the boundary
must live outside the tree.

---

## Summary of files touched

| Criterion | `check-provenance.py` | `git-provenance.sh` | `orchestrate.sh` | `selftest_provenance_m2.py` |
|---|---|---|---|---|
| 1 unsigned | append failure @248 | — | — | 2 cases |
| 3 evidence | role-gate @282 + constants | fail-closed @182, schema trailer @216 | — | 5 cases |
| 4 finalize | — | — | reorder @2604–2648 | 2 cases |
| 2 boundary | anchor logic @350 + range | `activate` subcommand @424 | — (pre-push/CI range) | 5 cases |

Each criterion is one isolated commit. Land 1 → 3 → 4 → 2. Nothing here goes
through `refreeze.sh`; all of it is gated by the 493 control-plane selftests
(pre-push) plus CI (ruff-src, mypy, coverage). Do not declare any criterion
verified until its selftest cases are green in the Linux setup with real fixture
keys.
