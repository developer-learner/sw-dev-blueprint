"""selftest_b6b.py — D-133 delta-only brief enforcement pins (2026-08-11 audit
item 4). Standalone and NOT listed in the control-plane manifest (per the lane
brief), mirroring the subprocess-against-a-temp-repo shape of selftest_gates.py.

Each test drives scripts/validate-plan.py end-to-end over a throwaway repo. The
milestone's three canonical mutations, all on one fixed setup with only the
plan brief varied — that variance IS the mutation that proves the gate reads
the brief:

  * restate a carried symbol the delta never touches -> gate FIRES (rc 1)
  * describe only the delta                           -> gate PASSES (rc 0)
  * the TPM's verbatim brief                          -> gate PASSES (rc 0)

Plus the fail-OPEN boundary the S6 lesson (2026-08-08) demands: no ERD-DELTA,
a new file, and a symbol the delta doc authorizes all leave the same restating
brief un-flagged.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATE_PLAN = REPO / "scripts" / "validate-plan.py"

FILE = "src/a.py"
NODEID = "tests/test_a.py::test_one"

# The on-disk file defines two symbols. `touched_func` is what the delta
# changes (and the ERD-DELTA names it); `legacy_helper` is carried behavior the
# delta never mentions — restating it is the defect D-133 catches.
SRC = (
    "def legacy_helper(x):\n"
    "    return x\n"
    "\n"
    "def touched_func(y):\n"
    "    return y\n"
)

# The TPM's authored delta. It names `touched_func` (the change) but NEVER
# `legacy_helper`, so legacy_helper is unauthorized carried behavior.
VERBATIM_BRIEF = (
    "Implementation constraints: `src/a.py`. Modify `touched_func` to return "
    "`y + 1`. Keep the module's other functions exactly as they are."
)
ERD_DELTA = (
    "# ERD-DELTA — test slice\n\n"
    "## Changed files\n\n"
    "* `src/a.py` — `touched_func` returns `y + 1`.\n\n"
    "## Coder briefs (verbatim)\n\n"
    f"### T1 — {FILE} (AC-1, a seam)\n\n"
    f"{VERBATIM_BRIEF}\n"
)

CONTRACTS = {"files": [FILE], "entry_points": ["src.a"], "routes": []}

# Brief variants — identical repo, only this line changes.
RESTATING_BRIEF = (
    "Modify `touched_func` to return `y + 1`. Also, `legacy_helper` validates "
    "and returns x unchanged; keep that behavior."
)
DELTA_ONLY_BRIEF = "Modify `touched_func` to return `y + 1`."


def _plan(brief):
    return {
        "version": 1,
        "erd_version": 1,
        "tasks": [{
            "id": "T1",
            "file": FILE,
            "depends_on": [],
            "brief": brief,
            "contracts": ["src.a"],
            "tests": [NODEID],
        }],
    }


def _make_repo(tmp_path, *, brief, erd_delta=ERD_DELTA, src=SRC):
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "contracts.json").write_text(json.dumps(CONTRACTS))
    (approved / "test-nodeids").write_text(NODEID + "\n")
    (approved / "VERSION").write_text("1\n")
    if erd_delta is not None:
        (approved / "ERD-DELTA.md").write_text(erd_delta)
    (tmp_path / "tasks").mkdir()
    if src is not None:
        srcp = tmp_path / FILE
        srcp.parent.mkdir(parents=True, exist_ok=True)
        srcp.write_text(src)
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps(_plan(brief)))
    return tmp_path


def _run(repo):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN)],
        cwd=repo, capture_output=True, text=True,
    )


# --- the three canonical mutations -----------------------------------------

def test_restating_carried_symbol_fires(tmp_path):
    r = _run(_make_repo(tmp_path, brief=RESTATING_BRIEF))
    assert r.returncode == 1, f"expected fail, got rc0\n{r.stdout}\n{r.stderr}"
    assert "restates carried behavior" in r.stderr, r.stderr
    assert "D-133" in r.stderr, r.stderr
    # exactly the carried symbol is named; the delta symbol is not flagged.
    assert "['legacy_helper']" in r.stderr, r.stderr
    assert "touched_func" not in r.stderr, r.stderr


def test_delta_only_brief_passes(tmp_path):
    r = _run(_make_repo(tmp_path, brief=DELTA_ONLY_BRIEF))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


def test_verbatim_tpm_brief_passes(tmp_path):
    # A brief equal to the TPM block is exempt outright — the synthesis path
    # can never be rejected by this gate (item-4 constraint).
    r = _run(_make_repo(tmp_path, brief=VERBATIM_BRIEF))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


# --- fail-OPEN boundary (the S6 over-strictness guard) ----------------------

def test_no_erd_delta_skips(tmp_path):
    # No authored delta → no authority to diverge from → the restating brief
    # must NOT fire.
    r = _run(_make_repo(tmp_path, brief=RESTATING_BRIEF, erd_delta=None))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


def test_new_file_skips(tmp_path):
    # File absent on disk → no carried behavior to restate → skip even with the
    # restating brief.
    r = _run(_make_repo(tmp_path, brief=RESTATING_BRIEF, src=None))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


def test_delta_authorized_symbol_not_flagged(tmp_path):
    # `touched_func` is defined in the file AND named in the ERD-DELTA, so a
    # brief that elaborates it (beyond the verbatim text) is authorized context,
    # never a restatement.
    brief = "Rework `touched_func` thoroughly; it now returns `y + 1` always."
    r = _run(_make_repo(tmp_path, brief=brief))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


def test_new_symbol_not_yet_in_file_not_flagged(tmp_path):
    # A brief may name a helper the delta INTRODUCES (`_new_guard`) — not yet in
    # the file, so it is the delta, not carried behavior.
    brief = "Modify `touched_func` to call a new `_new_guard` before returning."
    r = _run(_make_repo(tmp_path, brief=brief))
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout
