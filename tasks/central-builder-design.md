# Central builder — design (D-186, PROPOSED)

Status: **proposed, awaiting CEO approval** (Rule 3: this changes how the
control plane is enforced in children, not just how it detects).

## Problem

The 2026-08-24 direction: the blueprint is a template at seed and a builder
for life — "all future apps will not have their control plane." Behavior
already matches (every vortex change routes through the pipeline). Packaging
does not: each child still *hosts* the plane.

| Child | How it carries the plane today |
|---|---|
| vortex | 89 symlinks into `../sw-dev-blueprint`, `.manifest-template` + `.manifest-project`, `.template-version` pin, `.template-link`, `check-drift.yml`, in-repo hooks |
| testchat | same (linked since D-177) |
| rich-adoption | linked at `1684e0b` |

Hosting costs: the manifest/pin/drift/link layer (D-33/D-34/D-35/D-183),
"keep the shared checkout on main" (children run whatever it has checked
out), CI must reconstruct `../sw-dev-blueprint` beside the child, and a
child's `pre-push` runs the *control-plane* selftests instead of the child's
own suite (the "local release-gate ≠ CI" gap).

## What already exists

`orchestrate.sh`'s `plane_entry_guard` (D-168) materializes the pinned plane
into `~/.cache/swbp-plane/<sha>` via `git archive` and re-execs from that
snapshot with cwd = the app, recording `.pipeline-state/plane-sha` and
forbidding mid-milestone plane changes. Execution-from-outside-the-app is
already how milestones run. Only the *reach* (symlinks) and the *verification
of the reach* (manifests, drift) remain in the child.

## Design

**Entry point.** One launcher in the builder: `scripts/swbp <cmd> --app <path>
[--ref <sha>]`, cmd ∈ {refreeze, orchestrate, status, …}. It resolves the ref
(default: the app's pin), materializes the snapshot exactly as D-168 does
today, and execs `<snapshot>/scripts/<cmd>` with cwd = the app. Generalizes
`plane_entry_guard` from orchestrate-only to every entry.

**Two roots.** Every script distinguishes `PLANE_DIR` (snapshot, read-only)
from the app root (cwd). Plane files are read from `$PLANE_DIR/scripts/…`;
app files (`tests/`, `scripts/.approved/`, `tasks/`, `.pipeline-state/`,
`src/`) from cwd. Today both resolve to the same `scripts/…` relative path —
that conflation (~130 references in orchestrate.sh + refreeze.sh) is the bulk
of the work.

**What the app keeps.**
- product: `src/`, `tests/`, `requirements.txt`, app docs
- frozen spec: `scripts/.approved/` (rename deferred — not worth the churn now)
- app adaptations: `.gate-paths`, `opencode.json`, `Containerfile`,
  `.dockerignore`, `ci.yml`, `container-build.yml`, `CLAUDE.md`/`AGENTS.md`,
  `CONVENTIONS.md`
- `.swbp` — one file, `ref=<builder sha>`: the builder version the app
  declares. Replaces `.template-version`, `.template-link`, both manifests.
  Upgrading = edit the ref (a `[builder-adopt <sha>]` commit), still forbidden
  mid-milestone (D-168 rule unchanged).

**What the app loses.** All plane symlinks, `.manifest-template`,
`.manifest-project`, `.template-version`, `.template-link`, `check-drift.yml`,
tracked `.githooks/`.

**Enforcement that replaces in-app hooks.**
1. *Run-time lanes — unchanged.* `phase-gate.sh` still re-verifies the tree
   after every phase; the coder still writes only its task path; the frozen
   manifest in `scripts/.approved/` still pins spec + tests.
2. *Local human path.* `swbp` sets `core.hooksPath` in the app's **untracked**
   `.git/config` to the builder checkout's hooks. The pre-commit hook keeps
   verifying the frozen manifest and the active phase. Nothing is committed.
3. *App pre-push* runs the **app's** suite (+ ruff/mypy as in its `ci.yml`),
   closing the "release-gate ≠ CI" gap. Control-plane selftests move to the
   builder's own pre-push/CI, where they belong.
4. *App CI guard* (`swbp-guard.yml`, physical file, like check-drift today):
   commits touching `tests/` or `scripts/.approved/` must carry builder
   `Swbp-*` trailers (D-174) and, once M2b's gate flips, a valid provenance
   signature (D-184). **Report-first**, flipped to failing after one clean
   milestone — same staging D-184 used.

The app's own `.manifest-project` protection of adaptations is dropped: during
runs the lane gate already blocks agents from those files; on the human path
they are the owner's files by definition (Rule 3 adaptations).

## Stages (each its own commit set, selftests green at every step)

| Stage | Change | Old path still works? |
|---|---|---|
| A | two-root split; `PLANE_DIR` threaded through all scripts; linked children still run via symlink + `PLANE_DIR` = snapshot | yes |
| B | `scripts/swbp --app` launcher; generalize `plane_entry_guard` to all entries; untracked hooksPath setup | yes |
| C | app pre-push template + `swbp-guard.yml` (report-first) | yes |
| D | migrate **vortex**: delete links/manifests/pin/drift workflow, add `.swbp`; run its next real feature end-to-end via `swbp` (TPM→EM→coder) | vortex no, others yes |
| E | migrate testchat, rich-adoption; `new-project.sh` seeds builder-targeted apps (supersedes D-183 born-linked) | — |
| F | delete the sync layer: `link-template.sh`, `update-template.sh`, `check-drift.sh`, `manifest-drift-guard.sh`, `regen-manifest.sh`'s child role, `.template-link` handling, their selftests | — |

Rollback: until F, a migrated child can be re-linked with `link-template.sh`.
F happens only after every child has completed one real milestone under `swbp`.

## Done criteria

1. Vortex, testchat, rich-adoption contain no plane file, symlink, or manifest.
2. Each has completed ≥1 real milestone via `swbp` with a green verdict.
3. Each app's CI passes with no reference to `../sw-dev-blueprint`.
4. `swbp-guard` has flipped to failing, and a deliberate unsigned commit to
   `tests/` is rejected (live-fire, Rule 6 — not just a selftest).
5. The sync-layer scripts in stage F are gone from the builder.

## Open questions for the CEO

1. Default ref when `--ref` is omitted: the app's `.swbp` pin (reproducible,
   proposed) vs builder HEAD (always newest)?
2. OK to drop `.manifest-project` protection of app adaptations (see above)?
3. Vortex first (proposed — its plane is already pure links)?
