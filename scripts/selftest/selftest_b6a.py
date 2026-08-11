#!/usr/bin/env python3
"""selftest_b6a.py — escalation-bundle trim (control-plane review finding 7).

Pins the finding-7 fix in orchestrate.sh's escalation region:

  * the shared milestone slice (standing summary + ERD-DELTA) is emitted
    EXACTLY ONCE at the batch top by finalize_batch, never re-copied inside
    a per-item bundle (batching had duplicated it N times);
  * a per-item bundle's failing-test evidence is the EXTRACTED failing
    function(s) plus helpers (scripts/extract-test-functions.py), NOT the old
    `head -200` dump — a function that sits BELOW line 200 still reaches the
    bundle, and unrelated tests above it do not;
  * when the evidence names a test file but no node-id (or extraction yields
    nothing) the bundle keeps a bounded excerpt behind an explicit WARNING
    line — evidence is never silently dropped.

The real functions are extracted from orchestrate.sh at run time (the same
anti-drift `name() { ... }` sed pattern the drive-*.sh harnesses use) and run
against a synthetic fixture — a copy would silently drift from the source.

Tests are prefixed test_b6a_ and live only in this file.
Run: pytest scripts/selftest/selftest_b6a.py -q
"""
import json
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ORCHESTRATE = REPO / "scripts" / "orchestrate.sh"
EXTRACTOR = REPO / "scripts" / "extract-test-functions.py"

# Unique sentinels — must not collide with anything the bundle emits itself.
STANDING_SENTINEL = "STANDINGSLICEZZZ"
ERDDELTA_SENTINEL = "ERDDELTASLICEZZZ"
PAST200_MARKER = "FUNCPAST200ZZZ"
FILLER_MARKER = "FILLERABOVE200ZZZ"
SMALL_MARKER = "SMALLFILEBODYZZZ"

# The harness: set up the environment the extracted functions expect (mirrors
# orchestrate.sh init), pull package_escalation + finalize_batch verbatim, then
# source the per-scenario driver. finalize_batch ends in `exit 2`, so callers
# treat rc 2 as success.
HARNESS = r"""#!/usr/bin/env bash
set -euo pipefail
WORK="$1"; REPO="$2"
cd "$WORK"

STATE_DIR=".pipeline-state"
ESC_DIR="$STATE_DIR/escalations"
APPROVED="scripts/.approved"
FROZEN_V="99"
STANDING_SUMMARY="$APPROVED/ERD.md"
mkdir -p "$STATE_DIR" "$ESC_DIR" scripts

# package_escalation calls scripts/extract-test-functions.py relative to cwd.
cp "$REPO/scripts/extract-test-functions.py" scripts/

die() { echo "FAIL: $*" >&2; exit 1; }

extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "selftest_b6a: could not extract $1() from orchestrate.sh — did its shape change?" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract package_escalation)"
eval "$(extract finalize_batch)"

source ./scenario.sh
"""


def _write_fixture(work: Path) -> None:
    """Frozen-spec fixture the extracted functions read."""
    approved = work / "scripts" / ".approved"
    approved.mkdir(parents=True, exist_ok=True)
    (work / "tasks").mkdir(parents=True, exist_ok=True)
    (work / "tests").mkdir(parents=True, exist_ok=True)

    plan = {
        "version": 1,
        "erd_version": 99,
        "tasks": [
            {"id": "T1", "file": "src/a.py", "contracts": ["route-alpha"]},
            {"id": "T2", "file": "src/b.py", "contracts": ["route-beta"]},
        ],
    }
    (work / "tasks" / "plan.json").write_text(json.dumps(plan))

    contracts = {
        "entry_points": [],
        "routes": [
            {"id": "route-alpha", "method": "POST", "path": "/alpha"},
            {"id": "route-beta", "method": "GET", "path": "/beta"},
        ],
        "schemas": [],
        "errors": [],
    }
    (approved / "contracts.json").write_text(json.dumps(contracts))

    # Standing summary + ERD-DELTA carry unique sentinels so occurrence counts
    # are unambiguous.
    (approved / "ERD.md").write_text(
        f"# Standing ERD summary\n\nMarker: {STANDING_SENTINEL}\n"
    )
    (approved / "ERD-DELTA.md").write_text(
        f"# ERD delta (v99)\n\nMarker: {ERDDELTA_SENTINEL}\n"
    )

    # A test file whose target function sits BELOW line 200: ~220 filler lines,
    # then the failing function. head -200 could never reach it.
    filler = "\n".join(
        f"def test_filler_{i}():  # {FILLER_MARKER}\n    assert True"
        for i in range(120)  # 120 * 2 lines = 240 lines, so the target lands past line 200
    )
    big = (
        filler
        + "\n\n\n"
        + textwrap.dedent(
            f"""\
            def _big_helper():
                return "{PAST200_MARKER}-helper"


            def test_target_past_200():
                # {PAST200_MARKER}
                assert _big_helper() == "{PAST200_MARKER}-helper"
            """
        )
    )
    (work / "tests" / "test_big.py").write_text(big)

    # A short file for the no-node-id fallback path.
    (work / "tests" / "test_small.py").write_text(
        textwrap.dedent(
            f"""\
            def test_small_thing():
                # {SMALL_MARKER}
                assert True
            """
        )
    )


def _run(work: Path, scenario: str, expect_rc: int) -> None:
    (work / "harness.sh").write_text(HARNESS)
    (work / "scenario.sh").write_text(scenario)
    proc = subprocess.run(
        ["bash", str(work / "harness.sh"), str(work), str(REPO)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == expect_rc, (
        f"harness rc={proc.returncode} (want {expect_rc})\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )


# ---------------------------------------------------------------------------


def test_b6a_shared_context_appears_exactly_once_in_batch(tmp_path):
    """Pin: standing summary + ERD-DELTA appear ONCE in the whole batch, no
    matter how many items it carries."""
    _write_fixture(tmp_path)
    ev1 = "mapped tests failing: tests/test_big.py::test_target_past_200"
    ev2 = "mapped tests failing: tests/test_small.py::test_small_thing"
    scenario = (
        f'package_escalation "caps-exhausted" "T1" "{ev1}" "-"\n'
        f'package_escalation "spec-wrong" "T2" "{ev2}" "-"\n'
        "finalize_batch\n"
    )
    _run(tmp_path, scenario, expect_rc=2)  # finalize_batch halts with exit 2

    batch = (tmp_path / ".pipeline-state" / "escalations" / "BATCH.md").read_text()
    assert batch.count(STANDING_SENTINEL) == 1, "standing summary must appear exactly once"
    assert batch.count(ERDDELTA_SENTINEL) == 1, "ERD-DELTA must appear exactly once"
    # And it is in the shared header, above the first per-item section.
    assert "Shared milestone context" in batch
    assert batch.index(STANDING_SENTINEL) < batch.index("## Escalation:")


def test_b6a_per_item_bundle_has_no_context_recopy(tmp_path):
    """Pin: an individual bundle carries NO milestone-slice copy."""
    _write_fixture(tmp_path)
    ev = "mapped tests failing: tests/test_big.py::test_target_past_200"
    scenario = f'package_escalation "caps-exhausted" "T1" "{ev}" "-"\n'
    _run(tmp_path, scenario, expect_rc=0)

    bundle = (
        tmp_path / ".pipeline-state" / "escalations" / "T1" / "bundle.md"
    ).read_text()
    assert STANDING_SENTINEL not in bundle
    assert ERDDELTA_SENTINEL not in bundle
    assert "Milestone slice" not in bundle  # the old per-item heading is gone


def test_b6a_extracts_failing_function_below_line_200(tmp_path):
    """Pin: the failing function is extracted by node-id even when it sits far
    below line 200 — and the unrelated tests above it are NOT spliced in."""
    _write_fixture(tmp_path)
    # Guard against the fixture silently going vacuous: the target must really
    # sit below line 200, else head -200 would have reached it anyway.
    big_lines = (tmp_path / "tests" / "test_big.py").read_text().splitlines()
    target_line = next(
        n for n, ln in enumerate(big_lines, 1) if "def test_target_past_200" in ln
    )
    assert target_line > 200, f"fixture target at line {target_line}, must be > 200"

    ev = "mapped tests failing: tests/test_big.py::test_target_past_200"
    scenario = f'package_escalation "caps-exhausted" "T1" "{ev}" "-"\n'
    _run(tmp_path, scenario, expect_rc=0)

    bundle = (
        tmp_path / ".pipeline-state" / "escalations" / "T1" / "bundle.md"
    ).read_text()
    # Focused extraction path was taken (not the WARNING fallback).
    assert "extracted:" in bundle
    assert "WARNING: focused extraction" not in bundle
    # The below-line-200 function (and the helper it calls) are present.
    assert PAST200_MARKER in bundle
    assert "def test_target_past_200" in bundle
    assert "def _big_helper" in bundle
    # The unrelated filler tests above line 200 are NOT dumped in.
    assert FILLER_MARKER not in bundle


def test_b6a_no_nodeid_falls_back_to_bounded_excerpt_with_warning(tmp_path):
    """Pin: evidence naming a file but no node-id keeps a bounded excerpt
    behind an explicit WARNING — never a silent drop (Rule 6 negative space)."""
    _write_fixture(tmp_path)
    # A file reference with NO ::node-id (e.g. a smoke-check failure).
    ev = "smoke_check failed: tests/test_small.py present but assertion broke"
    scenario = f'package_escalation "caps-exhausted" "T1" "{ev}" "-"\n'
    _run(tmp_path, scenario, expect_rc=0)

    bundle = (
        tmp_path / ".pipeline-state" / "escalations" / "T1" / "bundle.md"
    ).read_text()
    assert "WARNING: focused extraction found no" in bundle
    assert SMALL_MARKER in bundle  # the bounded excerpt still carries the source
    assert "extracted:" not in bundle


def test_b6a_real_artifact_extracts_quarantine_function(tmp_path):
    """Real-artifact read-only check: the extractor pulls
    test_quarantine_rename_failure_is_unavailable (testchat
    tests/test_storage_service.py, ~line 175) — proving focused extraction on a
    genuine frozen suite, not just a synthetic fixture."""
    target = Path("/Users/arc.elixir/dev/testchat/tests/test_storage_service.py")
    if not target.is_file():
        pytest.skip("testchat real artifact not present on this host")
    node = f"{target}::test_quarantine_rename_failure_is_unavailable"
    proc = subprocess.run(
        ["python3", str(EXTRACTOR), str(target), node],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "def test_quarantine_rename_failure_is_unavailable" in proc.stdout
    # It also pulls the module-level helper the function calls.
    assert "def _use(" in proc.stdout
    # Focused: it does not dump the whole 214-line file.
    assert proc.stdout.count("def test_") <= 2
