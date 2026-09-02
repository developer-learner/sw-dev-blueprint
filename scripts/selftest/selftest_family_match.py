"""D-116/D-124 family-match pins.

Node-ids legitimately flip between `name[chromium]` and `name` across
collection methods (pytest-style suffixed ids vs the static/AST bare ids).
Every raw-match site in validate-plan.py must match on the stable family so
a shape-flipped pin still:

  (a) enters the milestone slice via the D-124 completeness repair
      (v117: the router UI test's pinned `[chromium]` id never matched the
      bare id the static fallback recorded, so its task entered the plan
      with no runnable mapped test);
  (b) auto-places at its declared owner task;
  (c) stays exempt from the D-64 final-task sweep.

Covered in both flip directions, plus the family-mapping collision guard.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent
VALIDATE_PLAN = SCRIPTS / "validate-plan.py"

SUFFIXED = "tests/test_ui.py::test_foo[chromium]"
BARE = "tests/test_ui.py::test_foo"
OWNER = "src/app.py"


def _load_validate_plan():
    spec = importlib.util.spec_from_file_location(
        "validate_plan_family_match", VALIDATE_PLAN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- direct: milestone_scope_ids (sites 3 & 4) -----------------------------


def test_suffixed_pin_bare_current_enters_slice_via_d124_repair():
    """v117 regression: the pinned id is suffixed, the current id is bare.
    The D-124 completeness repair must match on family so the pinned id
    enters the function-granular slice."""
    vp = _load_validate_plan()
    mapping = {SUFFIXED: OWNER}
    scope = vp.milestone_scope_ids(
        mapping, [OWNER], [BARE], "function", {BARE})
    assert SUFFIXED in scope, (
        "shape-flipped pin (suffixed pin, bare current) must enter the "
        f"slice via the D-124 repair; got {sorted(scope)}")


def test_bare_pin_suffixed_current_enters_slice_via_d124_repair():
    """Mirror: the pinned id is bare, the current id is suffixed."""
    vp = _load_validate_plan()
    mapping = {BARE: OWNER}
    scope = vp.milestone_scope_ids(
        mapping, [OWNER], [SUFFIXED], "function", {SUFFIXED})
    assert BARE in scope, (
        "shape-flipped pin (bare pin, suffixed current) must enter the "
        f"slice via the D-124 repair; got {sorted(scope)}")


def test_changed_test_family_matched_against_current():
    """The first scope line (changed_tests ∩ current) must also match on
    family, so a shape-flipped changed test is not dropped (no pins — the
    slice is inert and the raw set rides)."""
    vp = _load_validate_plan()
    scope = vp.milestone_scope_ids({}, [], [SUFFIXED], "function", {BARE})
    assert SUFFIXED in scope, (
        "shape-flipped changed test (suffixed changed, bare current) must "
        f"survive the current-intersection; got {sorted(scope)}")


# --- direct: _family_mapping collision guard --------------------------------


def test_family_mapping_collision_is_a_spec_error():
    """Two pins sharing a family but naming different owners is a spec
    error (parametrized variants of one test must share a behavioral
    owner) — never a silent last-win."""
    vp = _load_validate_plan()
    mapping = {
        "tests/test_ui.py::test_foo[chromium]": "src/app.py",
        "tests/test_ui.py::test_foo[firefox]": "src/browser.py",
    }
    try:
        vp._family_mapping(mapping)
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("family collision must fail the plan gate")


def test_family_mapping_agrees_on_shared_owner():
    """Parametrized variants of one test that pin the SAME owner collapse
    cleanly to one family entry."""
    vp = _load_validate_plan()
    mapping = {
        "tests/test_ui.py::test_foo[chromium]": OWNER,
        "tests/test_ui.py::test_foo": OWNER,
    }
    assert vp._family_mapping(mapping) == {BARE: OWNER}


# --- end-to-end: auto-placement + D-64 exemption (sites 1 & 2) --------------

CONTRACTS = {
    "files": ["src/a.py", "src/b.py"],
    "entry_points": ["src.a", "src.b:handler"],
    "routes": [
        {"id": "route-items", "path": "/items"},
        {"id": "route-item", "path": "/items/{item_id}"},
    ],
}


def _repo(tmp_path: Path) -> Path:
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tests").mkdir()
    (approved / "contracts.json").write_text(json.dumps(CONTRACTS))
    (approved / "VERSION").write_text("1\n")
    return tmp_path


def _good_plan():
    return {
        "version": 1,
        "erd_version": 1,
        "tasks": [
            {
                "id": "T1",
                "file": "src/a.py",
                "depends_on": [],
                "brief": "implement a",
                "contracts": ["src.a"],
                "tests": ["tests/test_a.py::test_one"],
            },
            {
                "id": "T2",
                "file": "src/b.py",
                "depends_on": ["T1"],
                "brief": "implement b",
                "contracts": ["src.b:handler", "route-items"],
                "tests": ["tests/test_b.py::test_two"],
            },
        ],
    }


def _run_validate(repo, plan, nodeids):
    (repo / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(nodeids) + "\n")
    (repo / "tasks" / "plan.json").write_text(json.dumps(plan))
    run_env = os.environ.copy()
    run_env.pop("SWBP_ACTIVE_DELTA_FILES", None)
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN)],
        cwd=repo, capture_output=True, text=True, env=run_env,
    )


def test_shape_flipped_pin_auto_placed_at_owner_task(tmp_path):
    """The pin is suffixed, the plan's node-id is bare. The auto-placement
    must resolve the pin via family match and move the bare node-id to its
    owner task (T1), not leave it on T2 where the EM mapped it."""
    repo = _repo(tmp_path)
    contracts = dict(CONTRACTS)
    contracts["test_mapping"] = {
        "tests/test_b.py::test_two[chromium]": "src/a.py",  # suffixed pin
    }
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(contracts))
    plan = _good_plan()
    plan["tasks"][1]["tests"] = ["tests/test_b.py::test_two"]  # bare, on T2
    r = _run_validate(repo, plan, [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",  # bare current
    ])
    assert r.returncode == 0, r.stderr
    assert "(pinned by test_mapping)" in r.stderr
    on_disk = json.loads((repo / "tasks" / "plan.json").read_text())
    by_id = {t["id"]: t for t in on_disk["tasks"]}
    assert "tests/test_b.py::test_two" in by_id["T1"]["tests"]
    assert "tests/test_b.py::test_two" not in by_id["T2"]["tests"]


def test_shape_flipped_pin_exempt_from_d64_sweep(tmp_path):
    """The pin is suffixed, the plan's node-id is bare, and the test file is
    a browser (Playwright) file on a non-final task. The D-64 sweep must NOT
    move the bare node-id to the final task — it is pinned (via family
    match) to T1, so the fallback never sweeps it off its owner."""
    repo = _repo(tmp_path)
    (repo / "tests" / "test_browser.py").write_text(
        "from playwright.sync_api import sync_playwright\n"
        "def test_sees_page():\n"
        "    assert True\n"
    )
    contracts = dict(CONTRACTS)
    contracts["test_mapping"] = {
        "tests/test_browser.py::test_sees_page[chromium]": "src/a.py",
    }
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(contracts))
    plan = _good_plan()
    plan["tasks"][0]["tests"] = [
        "tests/test_browser.py::test_sees_page",  # bare, on T1 (non-final)
    ]
    r = _run_validate(repo, plan, [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",
        "tests/test_browser.py::test_sees_page",  # bare current
    ])
    assert r.returncode == 0, r.stderr
    on_disk = json.loads((repo / "tasks" / "plan.json").read_text())
    by_id = {t["id"]: t for t in on_disk["tasks"]}
    assert "tests/test_browser.py::test_sees_page" in by_id["T1"]["tests"]
    assert "tests/test_browser.py::test_sees_page" not in by_id["T2"]["tests"]
