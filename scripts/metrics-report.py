#!/usr/bin/env python3
"""
metrics-report — the metrics layer (D-126): per-milestone aggregate over the
data the pipeline already writes — read ONLY from artifacts that survive the
success teardown's `rm -rf .pipeline-state` (orchestrate.sh; D-126 ordering in
its success path, P3-5's SHA-verified `[success]` commit guard — the row is
bound to the commit THIS run made, never a stale HEAD). D-108's lesson,
applied: the row must be recomputable after the milestone, from what outlives
it.

Durable sources (all survive teardown):
  - .measurement/counters            per-run exit rows: rc, phase, task,
                                     spec, elapsed (Phase 5 instrumentation)
  - .measurement/timings-<TS>.tsv    per-run timings copies
  - .em-archive/*/meta.txt           EM call outcome + gate result (spec-tagged)
  - .pipeline-flakes.json            committed per-spec flake history (D-111)
  - git history                      milestone ref, date, feature version,
                                     and who changed the build lane (D-211)
  - .measurement/legacy-v<N>.json    existing-suite regression record (D-212)

D-211 columns, from the D-174 `Swbp-Role` commit trailers: `human_edits` =
commits during this milestone (first refreeze since the previous [success]
up to this [success]) that change build-lane files (`.gate-paths` build=)
and were NOT made by the pipeline (role human, or no trailer: a hand
commit). `post_success_fixes` = the same kind of commit between the PREVIOUS
[success] and this milestone's first refreeze — hand repairs to work the
pipeline had already declared done ("" when there is no previous success).
`legacy_regressions` = existing-suite tests failing at success that the
project's legacy pin does not list as known failures ("" when the project
has no legacy pin, D-212).

Appends one TSV row per milestone to .measurement/metrics.tsv (idempotent: a
milestone+feature already recorded is skipped). With --evidence it prints the
same numbers WITHOUT writing anything — the measured-evidence block a D-115
retirement entry must cite. A report, never a gate: nothing in the completion
path reads the output, and a write can never fail a run (wired with `|| true`
in orchestrate.sh). Invoke from the project root (or pass --root).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

COLS = [
    "milestone", "date", "feature", "gate_hours", "selftest_count",
    "selftest_s", "em_calls", "em_waste", "flakes", "success_runs",
    "retry_runs", "human_edits", "post_success_fixes", "legacy_regressions",
]
PIPELINE_ROLES = {"em", "coder", "tpm", "pipeline"}
METRICS_REL = Path(".measurement") / "metrics.tsv"
RE_FEATURE = re.compile(r"\[(?:success\] spec|refreeze) v(\d+)")
RE_RC = re.compile(r"rc=(\d+)")
RE_SPEC = re.compile(r"spec=(\d+)")
RE_ELAPSED = re.compile(r"elapsed=(\d+)s")


def sh(root: Path, *a: str) -> str:
    return subprocess.run(
        a, cwd=root, capture_output=True, text=True
    ).stdout.strip()


def resolve_milestone(
    root: Path, milestone: str, feature_override: str
) -> tuple[str, str, str]:
    """Return (short-ref, commit-date-iso, feature-version)."""
    short = sh(root, "git", "rev-parse", "--short", milestone)
    date = sh(root, "git", "log", "-1", "--format=%ad", "--date=short", milestone)
    subject = sh(root, "git", "log", "-1", "--format=%s", milestone)
    m = RE_FEATURE.search(subject)
    feature = feature_override or (m.group(1) if m else "")
    return short, date or "", feature


def counter_runs(path: Path, spec: int | None) -> list[dict[str, str]]:
    """Exit rows in .measurement/counters, filtered to one spec."""
    if not path.is_file():
        return []
    runs = []
    for line in path.read_text().splitlines():
        if "exit rc=" not in line:
            continue
        rc = RE_RC.search(line)
        elapsed = RE_ELAPSED.search(line)
        if not rc or not elapsed:
            continue
        m_spec = RE_SPEC.search(line)
        if spec is not None and (not m_spec or int(m_spec.group(1)) != spec):
            continue
        runs.append({"rc": rc.group(1), "elapsed": elapsed.group(1)})
    return runs


def newest_timings_copy(meas_dir: Path) -> Path | None:
    """The most recent .measurement/timings-<TS>.tsv, by timestamp sort."""
    if not meas_dir.is_dir():
        return None
    copies = sorted(meas_dir.glob("timings-*.tsv"))
    return copies[-1] if copies else None


def timings_for_spec(meas_dir: Path, spec: int | None) -> Path | None:
    """The timings copy for THIS milestone's spec, matched on the `(spec vN)`
    marker the run writes into its pre-flight line. A spec with no tagged copy
    ran no timed phases of its own (e.g. a zero-work consolidation) — return
    None rather than inherit the newest file's phases, which would report
    another milestone's timings (a zero-work v105 showing v101's 152s). The
    trailing ")" in the marker prevents v8 matching v80. With no spec (ad-hoc
    --evidence), fall back to the newest copy (unchanged behavior)."""
    if spec is None:
        return newest_timings_copy(meas_dir)
    if not meas_dir.is_dir():
        return None
    marker = f"(spec v{spec})"
    tagged = sorted(
        c for c in meas_dir.glob("timings-*.tsv")
        if marker in c.read_text(errors="ignore")
    )
    return tagged[-1] if tagged else None


def read_timings(path: Path) -> list[tuple[int, str]]:
    """Return [(elapsed_seconds, label)] for THIS run only (last run start)."""
    if not path.is_file():
        return []
    rows: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        hms, elapsed, label = parts
        if label.startswith("run start"):
            rows = []
        try:
            rows.append((int(elapsed.rstrip("s")), label))
        except ValueError:
            pass
    return rows


def selftest_stats(path: Path | None) -> tuple[int, int]:
    """(selftest_count, selftest_s) from the newest timings copy."""
    if path is None:
        return 0, 0
    count = 0
    seconds = 0
    prev = 0
    for elapsed, label in read_timings(path):
        dt = max(0, elapsed - prev)
        prev = elapsed
        if "tests" in label or "pytest" in label:
            count += 1
            seconds += dt
    return count, seconds


def em_outcomes(archive: Path, spec: int | None) -> tuple[int, int]:
    """(em_calls, em_waste) — EM calls whose meta tags this spec version."""
    if not archive.is_dir():
        return 0, 0
    calls = waste = 0
    for d in sorted(archive.iterdir()):
        if not d.is_dir():
            continue
        meta = d / "meta.txt"
        if not meta.is_file():
            continue
        entry_spec = None
        outcome = "ok"
        for line in meta.read_text().splitlines():
            if line.startswith("spec_version="):
                entry_spec = line.split("=", 1)[1].strip()
            elif line.startswith("plan_gate="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("verdict="):
                outcome = line.split("=", 1)[1]
            elif line.startswith("outcome=") and outcome == "ok":
                outcome = line.split("=", 1)[1]
        if spec is not None and entry_spec != str(spec):
            continue
        calls += 1
        if outcome not in ("ok", "accepted", "valid"):
            waste += 1
    return calls, waste


def flake_count(path: Path, feature: str) -> int:
    """Events with spec_version == feature across all nodes (D-111 ledger)."""
    if not feature or not path.is_file():
        return 0
    try:
        ledger = json.loads(path.read_text())
        nodes = ledger.get("nodes")
        if not isinstance(nodes, dict):
            return 0
        target = int(feature)
    except (ValueError, OSError, json.JSONDecodeError):
        return 0
    count = 0
    for events in nodes.values():
        if not isinstance(events, list):
            continue
        count += sum(
            1 for e in events
            if isinstance(e, dict) and e.get("spec_version") == target
        )
    return count


def build_paths(root: Path) -> list[str]:
    """The build lane from .gate-paths (`build=`), default src/."""
    gp = root / ".gate-paths"
    if gp.is_file():
        for line in gp.read_text().splitlines():
            if line.startswith("build="):
                paths = line.split("=", 1)[1].split()
                if paths:
                    return paths
    return ["src/"]


def first_match(root: Path, rev_range: str, pattern: str, last: bool) -> str:
    """SHA of the newest (last=True) or oldest commit in rev_range whose
    subject matches the extended regex pattern, or ""."""
    shas = sh(root, "git", "log", "--format=%H", "-E", f"--grep={pattern}",
              rev_range).split()
    if not shas:
        return ""
    return shas[0] if last else shas[-1]


def hand_commits(root: Path, rev_range: str) -> int:
    """Non-merge commits in rev_range that change the build lane and were not
    made by a pipeline role (D-211). Role comes from the D-174 trailer; a
    commit without one was made by hand."""
    out = sh(root, "git", "log", "--no-merges",
             "--format=%H%x1f%(trailers:key=Swbp-Role,valueonly,separator=%x2c)",
             rev_range, "--", *build_paths(root))
    count = 0
    for line in out.splitlines():
        role = line.split("\x1f", 1)[1].strip().lower() if "\x1f" in line else ""
        if role not in PIPELINE_ROLES:
            count += 1
    return count


def intervention_counts(root: Path, milestone: str) -> tuple[str, str]:
    """(human_edits, post_success_fixes) for the milestone ending at
    `milestone` (D-211)."""
    if not sh(root, "git", "rev-parse", "--verify", "--quiet", milestone):
        return "0", ""
    prev = first_match(root, f"{milestone}^", r"^\[success\] spec v", last=True) \
        if sh(root, "git", "rev-parse", "--verify", "--quiet", f"{milestone}^") else ""
    window = f"{prev}..{milestone}" if prev else milestone
    start = first_match(root, window, r"^\[refreeze v", last=False)
    if not start:
        return "0", ("0" if prev else "")
    edits = hand_commits(root, f"{start}..{milestone}")
    fixes = str(hand_commits(root, f"{prev}..{start}^")) if prev else ""
    return str(edits), fixes


def legacy_regressions(meas_dir: Path, feature: str) -> str:
    """Count from the D-212 record for this spec version, "" if none."""
    if not feature:
        return ""
    rec = meas_dir / f"legacy-v{feature}.json"
    try:
        data = json.loads(rec.read_text())
        return str(len(data["regressions"]))
    except (OSError, ValueError, KeyError, TypeError):
        return ""


def compute(root: Path, milestone: str, feature_override: str) -> dict[str, str]:
    meas_dir = root / ".measurement"
    archive = root / ".em-archive"
    short, date, feature = resolve_milestone(root, milestone, feature_override)
    # The orchestrator's success path passes `--feature v$FROZEN_V` (with the
    # "v" prefix, e.g. v99) and RE_FEATURE captures the bare digits from the
    # subject — normalize to the integer form once so the spec filter, flake
    # count, and the v-prefixed row all agree. Before this, int("v99") raised
    # and the caller's `|| true` swallowed it: no .measurement/metrics.tsv row.
    feature = re.sub(r"^[vV]", "", feature.strip())
    spec = int(feature) if feature else None

    runs = counter_runs(meas_dir / "counters", spec)
    gate_hours = sum(int(r["elapsed"]) for r in runs) / 3600.0
    success = sum(1 for r in runs if r["rc"] == "0")
    retries = len(runs) - success

    selftest_count, selftest_s = selftest_stats(timings_for_spec(meas_dir, spec))
    em_calls, em_waste = em_outcomes(archive, spec)
    human_edits, post_success_fixes = intervention_counts(root, milestone)

    return {
        "milestone": short,
        "date": date,
        "feature": f"v{feature}" if feature else "",
        "gate_hours": f"{gate_hours:.2f}",
        "selftest_count": str(selftest_count),
        "selftest_s": str(selftest_s),
        "em_calls": str(em_calls),
        "em_waste": str(em_waste),
        "flakes": str(flake_count(root / ".pipeline-flakes.json", feature)),
        "success_runs": str(success),
        "retry_runs": str(retries),
        "human_edits": human_edits,
        "post_success_fixes": post_success_fixes,
        "legacy_regressions": legacy_regressions(meas_dir, feature),
    }


def evidence_block(row: dict[str, str]) -> str:
    return (
        f"metrics evidence — milestone {row['milestone']}, feature "
        f"{row['feature'] or '(none)'}, {row['date'] or '(no date)'}\n"
        f"  gate_hours={row['gate_hours']}  "
        f"selftest_count={row['selftest_count']}  "
        f"selftest_s={row['selftest_s']}\n"
        f"  em_calls={row['em_calls']}  em_waste={row['em_waste']}  "
        f"flakes={row['flakes']}\n"
        f"  success_runs={row['success_runs']}  "
        f"retry_runs={row['retry_runs']}\n"
        f"  human_edits={row['human_edits']}  "
        f"post_success_fixes={row['post_success_fixes'] or 'n/a'}  "
        f"legacy_regressions={row['legacy_regressions'] or 'n/a'}\n"
    )


def upgrade_header(path: Path) -> None:
    """A metrics.tsv written before columns were appended (D-211) gets the
    current header, its old rows padded with empty fields — never reordered,
    never dropped. A header that is not a prefix of COLS is left alone."""
    lines = path.read_text().splitlines()
    if not lines:
        return
    old = lines[0].split("\t")
    if old == COLS or old != COLS[:len(old)]:
        return
    pad = "\t" * (len(COLS) - len(old))
    rows = [r + pad if r else r for r in lines[1:]]
    path.write_text("\n".join(["\t".join(COLS)] + rows) + "\n")


def append_row(path: Path, row: dict[str, str]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Self-ignore the sink (same pattern as orchestrate.sh's .em-archive /
    # .measurement writers): the dir is runtime state in the Blueprint's own
    # tree too, and a bare `git add -A` must never sweep it in. Existing
    # children whose .gitignore predates the .measurement/ entry rely on this.
    gi = path.parent / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    if path.is_file():
        upgrade_header(path)
        for line in path.read_text().splitlines():
            fields = line.split("\t")
            if len(fields) == len(COLS) and fields[0] == row["milestone"] \
                    and fields[2] == row["feature"]:
                return False
        lines = path.read_text().splitlines()
    else:
        lines = []
    if not lines:
        lines = ["\t".join(COLS)]
    lines.append("\t".join(row[c] for c in COLS))
    path.write_text("\n".join(lines) + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--milestone", default="HEAD",
        help="git ref of the milestone to measure (default HEAD)",
    )
    parser.add_argument(
        "--feature", default="",
        help="explicit spec version (e.g. v84); overrides subject parsing",
    )
    parser.add_argument(
        "--evidence", action="store_true",
        help="print the measured-evidence block without writing metrics.tsv",
    )
    args = parser.parse_args(argv)

    row = compute(args.root, args.milestone, args.feature)
    if args.evidence:
        print(evidence_block(row))
        return 0

    out = args.root / METRICS_REL
    if append_row(out, row):
        print(f"metrics.tsv: recorded {row['milestone']} "
              f"(feature {row['feature'] or '(none)'})")
    else:
        print(f"metrics.tsv: milestone {row['milestone']} feature "
              f"{row['feature'] or '(none)'} already recorded — skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
