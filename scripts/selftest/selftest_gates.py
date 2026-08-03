"""selftest_gates.py — template self-tests for the two Python gate scripts.

These test the CONTROL PLANE, not the project: validate-plan.py and
check-test-surface.py are pure functions over JSON and file trees, and a
validator that wrongly passes fails open. This file is the cheap-to-carry
slice of "test the template itself" — the bash orchestration stays covered
by dry runs until an incident says otherwise (correction-log habit: tighten
from incidents, do not pre-harden speculatively). That incident arrived:
testchat M23's consult dead-ended on a schema-invalid EM diagnosis, so
consult_em is now exercised here too, via drive-consult.sh (D-71).

Deliberately NOT named test_*.py so project and control-plane suites stay
visibly separate. Production collection and execution are explicitly
confined to tests/, so this file cannot leak into the frozen oracle. Run:

    pytest scripts/selftest/selftest_gates.py -q

CI runs this in its own `selftest` job, unconditionally — the skeleton guard
does not apply because these tests need no project src/ or requirements.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
VALIDATE_PLAN = SCRIPTS / "validate-plan.py"
CHECK_SURFACE = SCRIPTS / "check-test-surface.py"
APPLY_BLOCKS = SCRIPTS / "apply-edit-blocks.py"
COMPLETION_LEDGER = SCRIPTS / "completion-ledger.py"
FLAKE_LEDGER = SCRIPTS / "flake-ledger.py"

# Derived from the script under test, never hardcoded: a cap bump must not
# break these tests (it did once — 2000→2500 left two tests asserting the
# old boundary).
MAX_BRIEF = int(re.search(
    r"^MAX_BRIEF_CHARS = (\d+)", VALIDATE_PLAN.read_text(), re.M).group(1))

CONTRACTS = {
    "files": ["src/a.py", "src/b.py"],
    "entry_points": ["src.a", "src.b:handler"],
    "routes": [
        {"id": "route-items", "path": "/items"},
        {"id": "route-item", "path": "/items/{item_id}"},
    ],
}
NODEIDS = ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]


def good_plan():
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


@pytest.fixture
def repo(tmp_path):
    """Minimal repo layout that validate-plan.py's cwd-relative paths expect."""
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "contracts.json").write_text(json.dumps(CONTRACTS))
    (approved / "test-nodeids").write_text("\n".join(NODEIDS) + "\n")
    (approved / "VERSION").write_text("1\n")
    (tmp_path / "tasks").mkdir()
    return tmp_path


def run_validate(repo, plan, *args):
    (repo / "tasks" / "plan.json").write_text(json.dumps(plan))
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), *args],
        cwd=repo, capture_output=True, text=True,
    )


def run_surface(tmp_path, contracts, test_source):
    contracts_path = tmp_path / "contracts.json"
    contracts_path.write_text(json.dumps(contracts))
    tests_dir = tmp_path / "frozen-tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text(test_source)
    return subprocess.run(
        [sys.executable, str(CHECK_SURFACE),
         "--tests-dir", str(tests_dir), "--contracts", str(contracts_path)],
        capture_output=True, text=True,
    )


# --- validate-plan.py -------------------------------------------------------

def test_valid_plan_passes(repo):
    r = run_validate(repo, good_plan())
    assert r.returncode == 0, r.stderr
    assert "plan ok" in r.stdout


def test_dependency_cycle_fails(repo):
    plan = good_plan()
    plan["tasks"][0]["depends_on"] = ["T2"]
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "cycle" in r.stderr


def test_status_field_rejected(repo):
    plan = good_plan()
    plan["tasks"][0]["status"] = "done"
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "status field" in r.stderr


def test_stale_erd_version_fails(repo):
    plan = good_plan()
    plan["erd_version"] = 2
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "stale" in r.stderr


def test_unmapped_frozen_nodeid_fails(repo):
    """An unmapped node-id whose test file imports a task-owned module is a
    decomposition hole (D-57: only observably-owned tests demand a mapping)."""
    plan = good_plan()
    plan["tasks"][1]["tests"] = []
    (repo / "tests").mkdir()
    (repo / "tests" / "test_b.py").write_text(
        "import src.b\n"
        "def test_two():\n"
        "    assert True\n"
    )
    # smoke_check now lives in contracts, not in the plan
    contracts = CONTRACTS.copy()
    contracts["smoke_checks"] = {"src/b.py": "python3 -c 'import src.b'"}
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "mapped to no task" in r.stderr
    assert "decomposition incomplete" in r.stderr


def test_unknown_contract_id_fails(repo):
    plan = good_plan()
    plan["tasks"][0]["contracts"] = ["src.nonexistent"]
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "unknown contract id" in r.stderr


def test_file_outside_build_lane_fails(repo):
    plan = good_plan()
    plan["tasks"][0]["file"] = "tests/test_a.py"
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "build lane" in r.stderr


def test_duplicate_task_file_fails(repo):
    plan = good_plan()
    plan["tasks"][1]["file"] = "src/a.py"
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "one file per task" in r.stderr


def test_topo_respects_dependencies(repo):
    r = run_validate(repo, good_plan(), "--topo")
    assert r.returncode == 0, r.stderr
    order = r.stdout.split()
    assert order.index("T1") < order.index("T2")


def test_gate_paths_overrides_build_lane(repo):
    (repo / ".gate-paths").write_text("build=app/\ntest=spec/\n")
    contracts = dict(CONTRACTS, files=["app/a.py", "app/b.py"])
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    plan = good_plan()
    plan["tasks"][0]["file"] = "app/a.py"
    plan["tasks"][1]["file"] = "app/b.py"
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


def test_dag_brief_forward_dependency_fails(repo):
    """A brief that references a file created by a downstream task is rejected."""
    plan = good_plan()
    # T1 brief references src/b.py, which T2 creates — but T2 is not an ancestor of T1
    plan["tasks"][0]["brief"] = "implement a, load config from src/b.py"
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "src/b.py" in r.stderr
    assert "not an ancestor" in r.stderr


def test_smoke_check_prose_rejected(repo):
    """A contracts.smoke_checks value that is prose (not a shell command) is rejected."""
    contracts = CONTRACTS.copy()
    contracts["smoke_checks"] = {"src/b.py": "Verify that src/b.py contains a handler function"}
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    # remove the node-id for T2 so it doesn't fail on "unmapped" before reaching smoke check
    (repo / "scripts" / ".approved" / "test-nodeids").write_text("tests/test_a.py::test_one\n")
    plan = good_plan()
    plan["tasks"][1]["tests"] = []
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "not a valid shell command" in r.stderr


def test_smoke_check_valid_command_passes(repo):
    """A valid shell command in contracts.smoke_checks passes the gate."""
    contracts = CONTRACTS.copy()
    contracts["smoke_checks"] = {"src/b.py": "grep -q 'handler' src/b.py"}
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    (repo / "scripts" / ".approved" / "test-nodeids").write_text("tests/test_a.py::test_one\n")
    plan = good_plan()
    plan["tasks"][1]["tests"] = []
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr
    assert "not a valid shell command" not in r.stderr


def test_smoke_check_injection_does_not_execute(repo, tmp_path):
    """A smoke_checks value whose first token is a command-substitution must
    NOT execute on the host during validation (blocker #2). The token is
    passed to `command -v` as data, so the payload never runs; the value is
    still rejected (it is not a real executable)."""
    canary = tmp_path / "CANARY"
    contracts = CONTRACTS.copy()
    # A single whitespace-free token (so split()[0] is the whole payload) that
    # would `touch` the canary if interpolated into the shell word — ${IFS}
    # supplies the argument separator without a literal space.
    contracts["smoke_checks"] = {"src/b.py": "foo;touch${IFS}" + str(canary)}
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    (repo / "scripts" / ".approved" / "test-nodeids").write_text("tests/test_a.py::test_one\n")
    plan = good_plan()
    plan["tasks"][1]["tests"] = []
    r = run_validate(repo, plan)
    assert not canary.exists(), "smoke_check payload executed on the host (injection)"
    assert r.returncode == 1
    assert "not a valid shell command" in r.stderr


def test_brief_over_max_chars_rejected(repo):
    """A brief exceeding MAX_BRIEF_CHARS is rejected."""
    plan = good_plan()
    plan["tasks"][0]["brief"] = "x" * (MAX_BRIEF + 1)
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert f"{MAX_BRIEF + 1} chars" in r.stderr
    assert "Rule 8" in r.stderr


def test_brief_at_max_chars_passes(repo):
    """A brief exactly at MAX_BRIEF_CHARS passes."""
    plan = good_plan()
    plan["tasks"][0]["brief"] = "x" * MAX_BRIEF
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


def test_regression_key_rejected(repo):
    """D-57: the EM never emits the carried-forward bucket — the shell
    computes it. A plan carrying a 'regression' key is rejected outright."""
    plan = good_plan()
    plan["regression"] = ["tests/test_page.py::test_carried"]
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "regression" in r.stderr
    assert "never emits" in r.stderr


def test_carried_forward_auto_assigned(repo):
    """D-57: an unmapped node-id with no ownership signal (no task-owned
    import, no claimed route) is a carried-forward regression test — the
    plan passes with it unmapped, and validate reports the auto-assignment."""
    (repo / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(NODEIDS + ["tests/test_page.py::test_carried"]) + "\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_page.py").write_text(
        "from src.main import app\n"  # pre-existing module, not in inventory
        "def test_carried():\n"
        "    assert True\n"
    )
    plan = good_plan()
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr
    assert "1 carried-forward" in r.stderr


def test_unmapped_route_test_fails(repo):
    """D-57 ownership via routes: an unmapped node-id whose test hits a
    route some task claims belongs to this delta and must be mapped."""
    contracts = dict(CONTRACTS, routes=[
        {"id": "route-items", "method": "GET", "path": "/items"},
    ])
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(contracts))
    (repo / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(NODEIDS + ["tests/test_items.py::test_list"]) + "\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_items.py").write_text(
        "def test_list(client):\n"
        "    assert client.get('/items').status_code == 200\n"
    )
    plan = good_plan()  # T2 claims route-items; test_list is unmapped
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "tests/test_items.py::test_list" in r.stderr
    assert "decomposition incomplete" in r.stderr


# --- route reachability (testchat M5) ----------------------------------------

ROUTE_CONTRACTS = {
    "files": ["src/a.py", "src/b.py"],
    "entry_points": ["src.a", "src.b:handler"],
    "routes": [
        {"id": "route:GET /widgets", "method": "GET", "path": "/widgets"},
    ],
}
ROUTE_NODEIDS = [
    "tests/test_w.py::test_service",
    "tests/test_w.py::test_route",
]


def route_repo(repo, test_source):
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(ROUTE_CONTRACTS))
    (repo / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(ROUTE_NODEIDS) + "\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_w.py").write_text(test_source)


def route_plan(t1_tests, t2_tests):
    return {
        "version": 1,
        "erd_version": 1,
        "tasks": [
            {
                "id": "T1",
                "file": "src/a.py",
                "depends_on": [],
                "brief": "implement service layer",
                "contracts": ["src.a"],
                "tests": t1_tests,
            },
            {
                "id": "T2",
                "file": "src/b.py",
                "depends_on": ["T1"],
                "brief": "implement route",
                "contracts": ["src.b:handler", "route:GET /widgets"],
                "tests": t2_tests,
            },
        ],
    }


def test_route_test_scheduled_before_route_exists_fails(repo):
    """testchat M5: a test hitting a route was mapped to the service task, but
    the route is created by a LATER task — the test can never pass there."""
    route_repo(repo, (
        "def test_service(client):\n"
        "    assert client.get('/widgets').status_code == 200\n"
        "def test_route(client):\n"
        "    assert True\n"
    ))
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],  # hits the route — wrong task
        t2_tests=["tests/test_w.py::test_route"],
    )
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "route:GET /widgets" in r.stderr
    assert "dependency closure" in r.stderr
    assert "T2" in r.stderr


def test_route_test_mapped_to_claiming_task_passes(repo):
    """The same route-hitting test mapped to the task that claims the route."""
    route_repo(repo, (
        "def test_service(client):\n"
        "    assert True\n"
        "def test_route(client):\n"
        "    assert client.get('/widgets').status_code == 200\n"
    ))
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],
        t2_tests=["tests/test_w.py::test_route"],
    )
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


def test_route_check_fails_open_on_dynamic_path(repo):
    """A dynamically-built path is invisible to the AST scan — no false fire."""
    route_repo(repo, (
        "def test_service(client):\n"
        "    path = '/wid' + 'gets'\n"
        "    assert client.get(path).status_code == 200\n"
        "def test_route(client):\n"
        "    assert True\n"
    ))
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],
        t2_tests=["tests/test_w.py::test_route"],
    )
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


def test_route_param_template_matches(repo):
    """A literal path matching a {param} route template is attributed."""
    contracts = dict(ROUTE_CONTRACTS, routes=[
        {"id": "route:GET /widgets/{wid}", "method": "GET", "path": "/widgets/{wid}"},
    ])
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    (repo / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(ROUTE_NODEIDS) + "\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_w.py").write_text(
        "def test_service(client):\n"
        "    assert client.get('/widgets/123').status_code == 200\n"
        "def test_route(client):\n"
        "    assert True\n"
    )
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],
        t2_tests=["tests/test_w.py::test_route"],
    )
    plan["tasks"][1]["contracts"] = ["src.b:handler", "route:GET /widgets/{wid}"]
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "route:GET /widgets/{wid}" in r.stderr


# --- import reachability ------------------------------------------------------

def test_import_of_downstream_module_fails(repo):
    """A test file importing a module created by a downstream task cannot even
    be collected — mapping any of its tests to an earlier task is rejected."""
    route_repo(repo, (
        "from src.b import handler\n"
        "def test_service(client):\n"
        "    assert True\n"
        "def test_route(client):\n"
        "    assert True\n"
    ))
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],  # file imports T2's module
        t2_tests=["tests/test_w.py::test_route"],
    )
    r = run_validate(repo, plan)
    assert r.returncode == 1
    assert "src.b" in r.stderr
    assert "cannot even collect" in r.stderr


def test_import_of_own_or_ancestor_module_passes(repo):
    """Imports of the mapped task's own module (or an ancestor's) are fine."""
    route_repo(repo, (
        "import src.a\n"
        "from src.b import handler\n"
        "def test_service(client):\n"
        "    assert True\n"
        "def test_route(client):\n"
        "    assert True\n"
    ))
    plan = route_plan(
        t1_tests=[],  # T1 covered by smoke_check instead
        t2_tests=["tests/test_w.py::test_service", "tests/test_w.py::test_route"],
    )
    contracts = dict(ROUTE_CONTRACTS, smoke_checks={"src/a.py": "grep -q . src/a.py"})
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


def test_import_outside_inventory_ignored(repo):
    """Imports of pre-existing modules (not in the build inventory) never fire."""
    route_repo(repo, (
        "from src.main import app\n"
        "def test_service(client):\n"
        "    assert True\n"
        "def test_route(client):\n"
        "    assert True\n"
    ))
    plan = route_plan(
        t1_tests=["tests/test_w.py::test_service"],
        t2_tests=["tests/test_w.py::test_route"],
    )
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


# --- diagnosis: Rule 8 applies to revised briefs ------------------------------

def run_diagnosis(repo, diag):
    p = repo / "diag.json"
    p.write_text(json.dumps(diag))
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--diagnosis", str(p)],
        cwd=repo, capture_output=True, text=True,
    )


def test_diagnosis_oversized_revised_brief_rejected(repo):
    """The revision path must not bypass the plan gate's brief-length cap."""
    r = run_diagnosis(repo, {
        "task_id": "T1", "verdict": "brief_wrong",
        "reason": "brief was wrong", "revised_brief": "y" * (MAX_BRIEF + 1),
    })
    assert r.returncode == 1
    assert f"{MAX_BRIEF + 1} chars" in r.stderr
    assert "Rule 8" in r.stderr


def test_diagnosis_valid_brief_wrong_passes(repo):
    r = run_diagnosis(repo, {
        "task_id": "T1", "verdict": "brief_wrong",
        "reason": "brief was wrong", "revised_brief": "implement a correctly",
    })
    assert r.returncode == 0, r.stderr
    assert "brief_wrong" in r.stdout


def test_plan_may_reference_ui_and_external_contract_ids(repo):
    """D-58 halt (testchat M7): the EM correctly listed the ui:* contracts a
    frontend task implements and the gate rejected them as unknown ids —
    every id-bearing contracts array must feed the known-id set."""
    contracts = {
        **CONTRACTS,
        "ui": [{"id": "ui:send", "testid": "send-btn", "description": "send"}],
        "externals": [{"id": "external:svc", "probe": "curl x", "capture": "captures/x.json"}],
    }
    (repo / "scripts" / ".approved" / "contracts.json").write_text(json.dumps(contracts))
    plan = good_plan()
    plan["tasks"][1]["contracts"] = ["src.b:handler", "ui:send", "external:svc"]
    r = run_validate(repo, plan)
    assert r.returncode == 0, r.stderr


# --- check-test-surface.py (INV-4) ------------------------------------------

def test_clean_surface_passes(tmp_path):
    r = run_surface(tmp_path, CONTRACTS, (
        "import src.a\n"
        "from src.b import handler\n"
        "def test_items(client):\n"
        "    assert client.get('/items').status_code == 200\n"
    ))
    assert r.returncode == 0, r.stderr
    assert "INV-4 ok" in r.stdout


def test_unlocked_module_import_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS, "import src.internal\n")
    assert r.returncode == 1
    assert "src.internal" in r.stderr


def test_unlocked_symbol_import_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS, "from src.b import secret_helper\n")
    assert r.returncode == 1
    assert "src.b:secret_helper" in r.stderr


def test_undeclared_route_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS, (
        "def test_admin(client):\n"
        "    client.get('/admin')\n"
    ))
    assert r.returncode == 1
    assert "/admin" in r.stderr


def test_param_route_template_matches(tmp_path):
    r = run_surface(tmp_path, CONTRACTS, (
        "def test_item(client):\n"
        "    client.get('/items/123')\n"
        "    client.get(f'/items/{item_id}')\n"
    ))
    assert r.returncode == 0, r.stderr


# --- check-test-surface.py UI extension (D-58) ------------------------------

CONTRACTS_UI = {
    **CONTRACTS,
    "ui": [
        {"id": "ui:send", "testid": "send-btn", "description": "send button"},
        {"id": "ui:input", "testid": "message-input", "description": "message box"},
    ],
}

UI_PREAMBLE = "from playwright.sync_api import Page\n"


def test_ui_locked_testid_passes(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE
        + "def test_send(page: Page):\n"
        + "    page.get_by_test_id('message-input').fill('hi')\n"
        + "    page.get_by_test_id('send-btn').click()\n"
    ))
    assert r.returncode == 0, r.stderr


def test_ui_unlocked_testid_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE + "def test_x(page):\n    page.get_by_test_id('sidebar').click()\n"
    ))
    assert r.returncode == 1
    assert "sidebar" in r.stderr


def test_ui_raw_css_selector_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE + "def test_x(page):\n    page.locator('.chat-bubble').click()\n"
    ))
    assert r.returncode == 1
    assert ".chat-bubble" in r.stderr


def test_ui_data_testid_selector_literal_passes(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE
        + "def test_x(page):\n"
        + "    page.locator('[data-testid=\"send-btn\"]').click()\n"
    ))
    assert r.returncode == 0, r.stderr


def test_ui_role_locator_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE + "def test_x(page):\n    page.get_by_role('button').click()\n"
    ))
    assert r.returncode == 1
    assert "role/text/label" in r.stderr


def test_ui_page_action_bare_tag_selector_fails(tmp_path):
    """Audit find 2026-07-11: page.click("button") is idiomatic Playwright and
    carried no rejectable prefix — the receiver rule must catch it."""
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE + "def test_x(page):\n    page.click('button')\n"
    ))
    assert r.returncode == 1
    assert "button" in r.stderr


def test_ui_page_action_attribute_selector_fails(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE + "def test_x(page):\n    page.fill('input[type=submit]', 'x')\n"
    ))
    assert r.returncode == 1
    assert "input[type=submit]" in r.stderr


def test_ui_page_action_locked_testid_literal_passes(tmp_path):
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE
        + "def test_x(page):\n"
        + "    page.click('[data-testid=\"send-btn\"]')\n"
    ))
    assert r.returncode == 0, r.stderr


def test_ui_locator_object_action_value_not_flagged(tmp_path):
    """get_by_test_id(...).fill('some text') takes a VALUE, not a selector —
    the page-receiver rule must not false-positive on locator-object actions."""
    r = run_surface(tmp_path, CONTRACTS_UI, (
        UI_PREAMBLE
        + "def test_x(page):\n"
        + "    page.get_by_test_id('message-input').fill('button')\n"
    ))
    assert r.returncode == 0, r.stderr


def test_ui_rules_ignore_non_playwright_files(tmp_path):
    """A backend test using .locator-ish strings is untouched by the UI gate."""
    r = run_surface(tmp_path, CONTRACTS_UI, (
        "def test_items(client):\n"
        "    assert client.get('/items').status_code == 200\n"
    ))
    assert r.returncode == 0, r.stderr


# --- apply-edit-blocks.py (D-59) ---------------------------------------------

TARGET_SRC = "line one\nline two\nline three\nline four\n"


def run_apply(tmp_path, reply):
    target = tmp_path / "target.py"
    target.write_text(TARGET_SRC)
    reply_f = tmp_path / "reply.raw"
    reply_f.write_text(reply)
    r = subprocess.run(
        [sys.executable, str(APPLY_BLOCKS), str(target), str(reply_f)],
        capture_output=True, text=True,
    )
    return r, target.read_text()


def test_apply_clean_block(tmp_path):
    r, out = run_apply(tmp_path,
        "<<<<<<< SEARCH\nline two\n=======\nline two\nline 2.5\n>>>>>>> REPLACE\n")
    assert r.returncode == 0, r.stderr
    assert "line 2.5" in out


def test_apply_missing_anchor_fails_closed(tmp_path):
    r, out = run_apply(tmp_path,
        "<<<<<<< SEARCH\nno such line\n=======\nx\n>>>>>>> REPLACE\n")
    assert r.returncode == 1
    assert "not found" in r.stderr
    assert out == TARGET_SRC  # untouched


def test_apply_ambiguous_anchor_fails_closed(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("dup\nmid\ndup\n")
    reply_f = tmp_path / "reply.raw"
    reply_f.write_text("<<<<<<< SEARCH\ndup\n=======\nDUP\n>>>>>>> REPLACE\n")
    r = subprocess.run(
        [sys.executable, str(APPLY_BLOCKS), str(target), str(reply_f)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "ambiguous" in r.stderr
    assert target.read_text() == "dup\nmid\ndup\n"


def test_apply_ambiguity_checked_against_original_not_mutated_text(tmp_path):
    """Audit find 2026-07-11: an anchor ambiguous in the ORIGINAL file must
    fail even when an earlier block in the same reply consumes one of its
    occurrences and makes it look unique in the mutated text."""
    target = tmp_path / "target.py"
    original = "dup\nmid\ndup\n"
    target.write_text(original)
    reply_f = tmp_path / "reply.raw"
    reply_f.write_text(
        "<<<<<<< SEARCH\ndup\nmid\n=======\nCHANGED\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\ndup\n=======\nDUP\n>>>>>>> REPLACE\n"
    )
    r = subprocess.run(
        [sys.executable, str(APPLY_BLOCKS), str(target), str(reply_f)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "ambiguous" in r.stderr
    assert target.read_text() == original  # untouched


def test_apply_overlapping_blocks_fail_closed(tmp_path):
    """Two blocks whose anchors are each unique in the original but consume
    each other's text (here: identical repeated blocks) must abort with the
    target untouched, not half-apply."""
    target = tmp_path / "target.py"
    original = "alpha\nbeta\ngamma\n"
    target.write_text(original)
    reply_f = tmp_path / "reply.raw"
    reply_f.write_text(
        "<<<<<<< SEARCH\nbeta\n=======\nBETA\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\nbeta\n=======\nBETA2\n>>>>>>> REPLACE\n"
    )
    r = subprocess.run(
        [sys.executable, str(APPLY_BLOCKS), str(target), str(reply_f)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "overlap" in r.stderr
    assert target.read_text() == original


def test_apply_truncated_block_fails_closed(tmp_path):
    r, out = run_apply(tmp_path, "<<<<<<< SEARCH\nline two\n=======\nline TWO\n")
    assert r.returncode == 1
    assert "truncated" in r.stderr or "malformed" in r.stderr
    assert out == TARGET_SRC


def test_apply_no_changes_is_noop(tmp_path):
    r, out = run_apply(tmp_path, "=== NO CHANGES ===\n")
    assert r.returncode == 0, r.stderr
    assert out == TARGET_SRC
    assert "no changes" in r.stdout


def test_apply_empty_reply_fails(tmp_path):
    r, out = run_apply(tmp_path, "I could not decide what to do.\n")
    assert r.returncode == 1
    assert "no edit blocks" in r.stderr


def test_missing_contracts_is_usage_error(tmp_path):
    tests_dir = tmp_path / "frozen-tests"
    tests_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(CHECK_SURFACE),
         "--tests-dir", str(tests_dir), "--contracts", str(tmp_path / "absent.json")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# D-68: check-swallowed-errors.py — silent error swallows fail, justified pass
# ---------------------------------------------------------------------------

CHECK_SWALLOW = SCRIPTS / "check-swallowed-errors.py"


def run_swallow(tmp_path, name, source):
    f = tmp_path / name
    f.write_text(source)
    return subprocess.run(
        [sys.executable, str(CHECK_SWALLOW), str(f)],
        capture_output=True, text=True,
    )


def test_swallow_py_bare_except_pass_fails(tmp_path):
    r = run_swallow(tmp_path, "m.py",
        "try:\n    save()\nexcept OSError:\n    pass\n")
    assert r.returncode == 1
    assert "justification comment" in r.stdout


def test_swallow_py_commented_pass_passes(tmp_path):
    r = run_swallow(tmp_path, "m.py",
        "try:\n    unlink()\nexcept OSError:  # best-effort cleanup\n    pass\n")
    assert r.returncode == 0, r.stdout


def test_swallow_py_handled_except_passes(tmp_path):
    r = run_swallow(tmp_path, "m.py",
        "try:\n    save()\nexcept OSError as e:\n    log(e)\n")
    assert r.returncode == 0, r.stdout


def test_swallow_js_empty_catch_callback_fails(tmp_path):
    r = run_swallow(tmp_path, "m.js",
        "fetch(url).then(ok).catch(function () {});\n")
    assert r.returncode == 1
    assert "empty .catch() callback" in r.stdout


def test_swallow_js_arrow_catch_fails(tmp_path):
    r = run_swallow(tmp_path, "m.js", "p.catch(() => {});\n")
    assert r.returncode == 1


def test_swallow_js_comment_in_catch_passes(tmp_path):
    r = run_swallow(tmp_path, "m.js",
        "p.catch(function () { /* offline is fine; retried on next action */ });\n")
    assert r.returncode == 0, r.stdout


def test_swallow_js_empty_catch_block_fails(tmp_path):
    r = run_swallow(tmp_path, "m.js",
        "try { work(); } catch (e) {}\n")
    assert r.returncode == 1
    assert "empty catch block" in r.stdout


def test_swallow_js_handled_catch_passes(tmp_path):
    r = run_swallow(tmp_path, "m.js",
        "try { work(); } catch (e) { report(e); }\n")
    assert r.returncode == 0, r.stdout


def test_swallow_other_filetype_ignored(tmp_path):
    r = run_swallow(tmp_path, "m.css", "catch (e) {}\n")
    assert r.returncode == 0


# --- consult_em: D-71 diagnosis hardening (bash, via drive-consult.sh) -------
# The M23 incident this covers: the EM's one production diagnosis came back
# schema-invalid (empty task_id) and the run dead-ended with no retry. D-71
# removes task_id from the reply surface (shell stamps it) and grants one
# retry carrying the validator's errors. These drive the REAL consult_em
# extracted from orchestrate.sh against a scripted fake EM.

DRIVE_CONSULT = SCRIPTS / "selftest" / "drive-consult.sh"

VALID_DIAG = {"verdict": "decomposition_wrong", "reason": "T2 split is wrong"}


def run_consult(tmp_path, replies, task_id="T7"):
    rdir = tmp_path / "replies"
    rdir.mkdir()
    for i, reply in enumerate(replies, 1):
        raw = reply if isinstance(reply, str) else json.dumps(reply)
        (rdir / str(i)).write_text(raw)
    return subprocess.run(
        ["bash", str(DRIVE_CONSULT), str(tmp_path), task_id,
         "failed 2 attempts on src/x.py"],
        capture_output=True, text=True,
    )


def consult_calls(tmp_path):
    return int((tmp_path / ".calls").read_text())


def consult_artifact(tmp_path, task_id="T7"):
    p = tmp_path / ".pipeline-state" / f"diagnosis-{task_id}.json"
    return json.loads(p.read_text())


def test_consult_valid_first_reply_one_call(tmp_path):
    r = run_consult(tmp_path, [VALID_DIAG])
    assert r.returncode == 0, r.stderr
    assert consult_calls(tmp_path) == 1
    assert "VERDICT=decomposition_wrong" in r.stdout
    # task_id was never asked of the model; the shell stamped it
    assert consult_artifact(tmp_path)["task_id"] == "T7"


def test_consult_schema_invalid_then_valid_recovers(tmp_path):
    r = run_consult(tmp_path, [{"verdict": "bogus", "reason": "x"}, VALID_DIAG])
    assert r.returncode == 0, r.stderr
    assert consult_calls(tmp_path) == 2
    # the retry prompt carries the validator's exact complaint back to the EM
    retry_prompt = (tmp_path / "prompts" / "2").read_text()
    assert "verdict must be one of" in retry_prompt
    assert consult_artifact(tmp_path)["task_id"] == "T7"


def test_consult_non_json_then_valid_recovers(tmp_path):
    r = run_consult(
        tmp_path, ["I think the brief is wrong, because...", VALID_DIAG])
    assert r.returncode == 0, r.stderr
    assert consult_calls(tmp_path) == 2
    assert "not parseable JSON" in (tmp_path / "prompts" / "2").read_text()


def test_consult_two_invalid_replies_halt_bounded(tmp_path):
    # a third scripted reply proves the loop never takes a third bite
    r = run_consult(
        tmp_path, [{"verdict": "bogus"}, {"reason": "still bad"}, VALID_DIAG])
    assert r.returncode != 0
    assert consult_calls(tmp_path) == 2
    assert "after one retry" in r.stderr


def test_consult_model_task_id_overwritten(tmp_path):
    r = run_consult(tmp_path, [dict(VALID_DIAG, task_id="T99")])
    assert r.returncode == 0, r.stderr
    assert consult_artifact(tmp_path)["task_id"] == "T7"


def test_exhausted_brief_allowance_escalates_before_consult():
    """Do not demand a revised brief that the next branch must discard."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    task_loop = source[source.index("# EM consult (only when"):
                       source.index("# --- batch halt")]
    cap_check = task_loop.index('[ "$revs" -ge "$MAX_BRIEF_REVISIONS" ]')
    consult = task_loop.index('consult_em "$id"')
    assert cap_check < consult
    before_consult = task_loop[cap_check:consult]
    assert 'package_escalation "caps-exhausted"' in before_consult
    assert "without another EM consult" in before_consult


def test_caps_exhausted_branch_survives_strict_mode(tmp_path):
    """Regression: M33 v76 (2026-08-02) died silently mid-T1 because D-114's
    exhausted-allowance branch called package_escalation with 3 args; the
    function's `local diag="$4"` under `set -euo pipefail` aborted the whole
    script with no HALT, no escalation, no final timing mark. The source-
    order test above did not catch it — every predecessor observed the
    write, not the write. This test extracts the REAL function and the REAL
    call site, wires the minimum fixtures they read, and runs the branch
    under strict mode. Any future regression to a 3-arg shape (or any
    other mandatory-positional omission) crashes here loudly instead of
    silently on the next milestone run."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    # Real function.
    fn = re.search(r"^package_escalation\(\) \{.*?^\}$", source, re.M | re.S)
    assert fn, "package_escalation not found — extractor drift"
    fn_body = fn.group(0)
    # Real call site, as it appears in the source. We match the block that
    # wraps it so a future rewrite of variable names is still detected.
    branch = re.search(
        r'if \[ "\$revs" -ge "\$MAX_BRIEF_REVISIONS" \]; then'
        r".*?"
        r'package_escalation "caps-exhausted"[^\n]*',
        source, re.S,
    )
    assert branch, "exhausted-allowance branch not found — extractor drift"
    # Isolate just the package_escalation invocation line, verbatim.
    call_line = re.search(
        r'package_escalation "caps-exhausted"[^\n]*', branch.group(0)
    ).group(0)

    # Minimum fixtures the function reads.
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps({
        "tasks": [{"id": "T1", "file": "src/x.py", "contracts": [], "tests": []}]
    }))
    (tmp_path / "scripts" / ".approved").mkdir(parents=True)
    (tmp_path / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps({"entry_points": [], "routes": [], "schemas": [], "errors": []})
    )

    runner = f"""#!/usr/bin/env bash
set -euo pipefail
cd {tmp_path}
STATE_DIR=.pipeline-state
ESC_DIR=$STATE_DIR/escalations
FROZEN_V=76
mkdir -p "$ESC_DIR"

{fn_body}

# Reproduce the exact caller shape.
id=T1
evidence="two failed coder attempts on src/x.py; token cap + mixed-mode reply"
{call_line}
"""
    r = subprocess.run(["bash", "-c", runner], capture_output=True, text=True)
    assert r.returncode == 0, (
        "exhausted-allowance branch aborted under strict mode — "
        f"stderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    )
    bundle = tmp_path / ".pipeline-state" / "escalations" / "T1" / "bundle.md"
    assert bundle.is_file(), (
        "no escalation bundle produced — the branch ran but wrote nothing"
    )
    text = bundle.read_text()
    assert "caps-exhausted" in text
    assert "T1" in text


def test_edit_mode_output_budget_has_no_hardcoded_call_site():
    """The old 4096 literal was hardcoded at the run_coder call site.
    After D-117, the coder edit-mode budget is a validated env var and the
    call site must reference $SWBP_CODER_EDIT_MAX_OUTPUT — never a bare
    integer. This is the regression check that a future edit doesn't
    silently reintroduce the literal alongside the env var."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    assert re.search(
        r'^SWBP_CODER_EDIT_MAX_OUTPUT="\$\{SWBP_CODER_EDIT_MAX_OUTPUT:-4096\}"$',
        source, re.M,
    ), "declaration missing or default changed"
    run_coder = source[source.index("run_coder() {"):
                       source.index("# --- D-115: protocol failures", 0)
                       if "# --- D-115: protocol failures" in source
                       else source.index("consult_em() {")]
    boundary = re.search(r'SWBP_MAX_OUTPUT="\$out_budget"', run_coder)
    assert boundary, "SWBP_MAX_OUTPUT plumb line moved — extractor drift"
    edit_budget = re.search(
        r'\[ -n "\$existing" \] && out_budget="\$SWBP_CODER_EDIT_MAX_OUTPUT"',
        run_coder,
    )
    assert edit_budget, (
        "run_coder no longer sources out_budget from SWBP_CODER_EDIT_MAX_OUTPUT — "
        "either the env var was removed or a hardcoded literal snuck back"
    )
    # No stray literal 4096 remains at the SWBP_MAX_OUTPUT= assignment.
    assert not re.search(r"out_budget=4096\b", run_coder), \
        "hardcoded 4096 reappeared in run_coder"


def test_edit_mode_budget_validates_input_strictly(tmp_path):
    """SWBP_CODER_EDIT_MAX_OUTPUT must halt on empty/zero/negative/non-int.
    Silent repair (defaulting a bad value to 4096) would hide config drift —
    exactly the class of "detected but not enforced" defect Rule 6 warns
    against. Extracts the validation block and drives it against every
    invalid shape."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    validation = re.search(
        r'case "\$SWBP_CODER_EDIT_MAX_OUTPUT" in.*?esac',
        source, re.S,
    )
    assert validation, "validation block moved or removed"
    prelude = 'die() { echo "$*" >&2; exit 1; }\n'
    script = prelude + validation.group(0)

    def run_with(val):
        return subprocess.run(
            ["bash", "-c", f'set -euo pipefail\nSWBP_CODER_EDIT_MAX_OUTPUT={val!r}\n{script}\necho ACCEPTED'],
            capture_output=True, text=True,
        )

    # Rejects: empty, non-integer, zero, negative (leading '-' is non-digit),
    # decimal (non-digit), whitespace.
    for bad in ("", "abc", "0", "-1", "3.5", "   ", "8192a", "1 2"):
        r = run_with(bad)
        assert r.returncode != 0, f"silently accepted bad value {bad!r}: {r.stdout}"
        assert "SWBP_CODER_EDIT_MAX_OUTPUT must be a positive integer" in r.stderr, \
            f"die message missing for {bad!r}: {r.stderr}"
        assert "ACCEPTED" not in r.stdout, f"proceeded past validation for {bad!r}"
    # Accepts: 4096 (default), 8192 (diagnostic), 1 (smallest positive).
    for good in ("4096", "8192", "1"):
        r = run_with(good)
        assert r.returncode == 0, f"rejected valid value {good}: {r.stderr}"
        assert "ACCEPTED" in r.stdout, f"failed to proceed past validation for {good}"


def test_edit_mode_budget_reaches_llm_call(tmp_path):
    """End-to-end plumb: SWBP_CODER_EDIT_MAX_OUTPUT set at run entry must
    reach the llm-call.sh boundary as SWBP_MAX_OUTPUT with the same value,
    for edit-mode (existing-file) calls only. Create-mode calls must still
    export SWBP_MAX_OUTPUT="" (D-59's "no per-call override" contract).
    Uses a stub llm-call.sh that logs the env value the shell handed it —
    the exact boundary the real llm-call would consume."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    # Isolate the exact line pattern from run_coder that exports the budget.
    plumb = re.search(
        r'SWBP_MAX_OUTPUT="\$out_budget" .*?scripts/llm-call\.sh coder',
        source,
    )
    assert plumb, "SWBP_MAX_OUTPUT plumb line signature changed"

    stub_dir = tmp_path / "scripts"
    stub_dir.mkdir()
    stub = stub_dir / "llm-call.sh"
    stub.write_text('#!/usr/bin/env bash\n'
                    # `-` (not `:-`) distinguishes empty-string from unset.
                    'printf "%s\\n" "SEEN=${SWBP_MAX_OUTPUT-<unset>}" > log\n')
    stub.chmod(0o755)

    # Faithful mini-caller that mirrors the two run_coder shapes.
    def call(existing_flag: str, env_override: str = "") -> str:
        (tmp_path / "log").unlink(missing_ok=True)
        script = f"""
set -euo pipefail
cd {tmp_path}
SWBP_CODER_EDIT_MAX_OUTPUT="${{SWBP_CODER_EDIT_MAX_OUTPUT:-4096}}"
out_budget=""
existing={existing_flag!r}
[ -n "$existing" ] && out_budget="$SWBP_CODER_EDIT_MAX_OUTPUT"
SWBP_MAX_OUTPUT="$out_budget" scripts/llm-call.sh coder
"""
        env = {**os.environ}
        if env_override:
            k, v = env_override.split("=", 1)
            env[k] = v
        subprocess.run(["bash", "-c", script], env=env, capture_output=True, check=True)
        return (tmp_path / "log").read_text().strip()

    # Default: edit mode sees 4096.
    assert call("src/x.py") == "SEEN=4096"
    # Override reaches boundary: edit mode sees 8192.
    assert call("src/x.py", "SWBP_CODER_EDIT_MAX_OUTPUT=8192") == "SEEN=8192"
    # Create mode ignores the override; SWBP_MAX_OUTPUT is empty.
    assert call("", "SWBP_CODER_EDIT_MAX_OUTPUT=8192") == "SEEN="


def test_feature_summary_names_unaccounted_time_on_silent_crash(tmp_path):
    """Regression: the first feature-summary reported "wall clock: 409s"
    for the M33 crash while the real run lasted 869s. Reporting through-
    last-event as wall clock hides silent halts — the exact defect
    measurement is supposed to surface. When the exit trap did not run
    and no run-exit.log exists, the tool must still detect the gap using
    filesystem mtimes, and label the delta unaccounted rather than
    swallowing it into "overhead"."""
    import time
    (tmp_path / "scripts" / ".approved").mkdir(parents=True)
    (tmp_path / "scripts" / ".approved" / "VERSION").write_text("76\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "add", "-A"], check=True)
    refreeze_ts = int(time.time()) - 900   # refreeze 15 minutes ago
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "[refreeze v76]",
         "--date", f"@{refreeze_ts} +0000"],
        env={**os.environ,
             "GIT_COMMITTER_DATE": f"@{refreeze_ts} +0000",
             "GIT_AUTHOR_DATE": f"@{refreeze_ts} +0000"},
        check=True,
    )
    state = tmp_path / ".pipeline-state"
    (state / "logs").mkdir(parents=True)
    timings = state / "logs" / "timings.tsv"
    timings.write_text(
        "19:00:00\t0s\trun start (budget 1200s)\n"
        "19:00:01\t1s\tpre-flight done (spec v76)\n"
        "19:00:01\t1s\tem-call start -> tasks/plan.json\n"
        "19:06:49\t409s\tcoder T1 attempt 1 start (src/services/storage.py)\n"
    )
    # Simulate the actual M33 silent-halt: pipeline started ~600s ago,
    # last logged event 409s into the run, real activity ended 100s ago
    # (the trap did not run, so real end must be inferred from mtimes).
    now = time.time()
    run_start = now - 600
    real_end = now - 100
    os.utime(timings, (run_start, run_start))
    fresh = state / "phase"
    fresh.write_text("")
    os.utime(fresh, (real_end, real_end))

    r = subprocess.run(
        ["python3", str(SCRIPTS / "feature-summary.py")],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "UNACCOUNTED:" in r.stdout, r.stdout
    # The tool must not report "409s" as wall clock when the run kept running.
    assert re.search(r"wall clock: (?!409s)\d+s", r.stdout), (
        f"tool reported the through-last-event count as wall clock:\n{r.stdout}"
    )


def test_run_exit_trap_records_every_termination_path(tmp_path):
    """Regression: M33 v76 crashed with no HALT and no evidence — nothing
    downstream could tell "died mid-task" from "halted for the operator".
    The EXIT trap must record rc, phase, task target, and last timings row
    on every path (success, die, uncaught error), so run-exit.log is a
    reliable ground truth for the next feature-summary. Not an escalation
    substitute: unexpected rc must not fabricate a bundle."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    fn = re.search(r"^record_exit\(\) \{.*?^\}$", source, re.M | re.S)
    assert fn, "record_exit not found — extractor drift"
    fn_body = fn.group(0)
    trap_line = re.search(r"^trap 'record_exit' EXIT$", source, re.M)
    assert trap_line, "EXIT trap not installed"

    state = tmp_path / ".pipeline-state"
    (state / "logs").mkdir(parents=True)
    (state / "phase").write_text("task-T2\n")
    (state / "task_target").write_text("src/api/threads.py\n")
    (state / "logs" / "timings.tsv").write_text(
        "19:25:25\t409s\tcoder T1 attempt 1 start (src/services/storage.py)\n"
    )

    def run(scenario: str) -> tuple[int, str]:
        script = f"""#!/usr/bin/env bash
set -euo pipefail
STATE_DIR={state}
LOG_DIR=$STATE_DIR/logs
RUN_T0=$(date +%s)
run_elapsed() {{ echo $(( $(date +%s) - RUN_T0 )); }}

{fn_body}

trap 'record_exit' EXIT
{scenario}
"""
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        exit_log = (state / "logs" / "run-exit.log")
        return r.returncode, (exit_log.read_text() if exit_log.is_file() else "")

    # 1) clean exit: rc=0 recorded
    (state / "logs" / "run-exit.log").unlink(missing_ok=True)
    rc, log = run("exit 0")
    assert rc == 0 and "rc=0" in log and "phase=task-T2" in log
    assert "task=src/api/threads.py" in log
    assert "coder T1 attempt 1 start" in log

    # 2) uncaught error (simulates the M33 crash): rc!=0 recorded, no bundle
    (state / "logs" / "run-exit.log").unlink(missing_ok=True)
    rc, log = run("false  # simulate unbounded-variable-style abort")
    assert rc == 1 and "rc=1" in log and "phase=task-T2" in log
    assert not (state / "escalations").exists(), \
        "trap must not fabricate an escalation on unexpected exit"

    # 3) explicit die-style: rc=1 recorded even with a wildly divergent phase
    (state / "phase").write_text("plan\n")
    (state / "logs" / "run-exit.log").unlink(missing_ok=True)
    rc, log = run("echo halted >&2; exit 3")
    assert rc == 3 and "rc=3" in log and "phase=plan" in log


def test_full_suite_execution_is_confined_to_tests_directory():
    """No-argument run_tests cannot discover archives or selftests."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    block = source[source.index("run_tests() {"):
                   source.index("# --- Plan phase")]
    assert 'test_args=(tests/)' in block
    assert '"${test_args[@]}"' in block


def test_plan_prompt_names_every_required_schema_key():
    # linkbox M1 (2026-07-16): the EM omitted the required top-level
    # "version" key on BOTH fresh-plan emissions — the prompt's checklist
    # named erd_version but not version, and with no plan-being-revised to
    # copy the key from, the local EM follows the checklist literally.
    # Prompt-schema drift: every key the schema requires must be named in
    # the emission prompt.
    orch = (SCRIPTS / "orchestrate.sh").read_text()
    prompt = re.search(
        r'"Decompose the frozen ERD into atomic ONE-FILE tasks.*?"',
        orch, re.S).group(0)
    schema = json.loads((SCRIPTS / "schemas" / "plan.schema.json").read_text())
    for key in schema["required"]:
        # word-boundary match: "version" must not be satisfied by the
        # "erd_version" mention (the exact vacuity that hid this defect)
        assert re.search(rf"(?<![A-Za-z_]){re.escape(key)}(?![A-Za-z_])", prompt), (
            f"plan.schema.json requires top-level '{key}' but the "
            f"ensure_plan emission prompt never names it")


# --- phase-gate.sh manifest phase (fixes c139cbc) ----------------------------
# Frozen-integrity gate for the pre-commit / conductor path. Three failure
# modes the review found (2026-07-16) and c139cbc fixed:
#   #3 an absent frozen-manifest silently skipped the check (fail-open)
#   #4 a hand-added test file escaped the pin yet ran in the full suite
#   plus a regression pin: gitignored bytecode caches must not false-positive
PHASE_GATE = SCRIPTS / "phase-gate.sh"


def _init_git(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
        cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "fixture"],
        cwd=repo, check=True,
    )


@pytest.fixture()
def frozen_repo(tmp_path):
    """A post-refreeze child: control-plane manifests, a frozen VERSION,
    one pinned test file on disk. Just enough for phase-gate to run."""
    (tmp_path / "scripts" / ".approved").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts" / "phase-gate.sh").write_bytes(PHASE_GATE.read_bytes())
    (tmp_path / "scripts" / "phase-gate.sh").chmod(0o755)

    (tmp_path / "tests" / "test_x.py").write_text("def test_ok(): pass\n")
    (tmp_path / "scripts" / ".approved" / "VERSION").write_text("1\n")
    frozen_hash = subprocess.check_output(
        ["sha256sum", "tests/test_x.py"], cwd=tmp_path, text=True,
    )
    (tmp_path / "scripts" / ".approved" / "frozen-manifest").write_text(frozen_hash)

    cp_hash = subprocess.check_output(
        ["sha256sum", "scripts/phase-gate.sh"], cwd=tmp_path, text=True,
    )
    (tmp_path / "scripts" / ".manifest-template").write_text(cp_hash)
    (tmp_path / "scripts" / ".manifest-project").write_text("")

    _init_git(tmp_path)
    return tmp_path


def _run_gate(repo, phase="manifest"):
    return subprocess.run(
        ["bash", "scripts/phase-gate.sh", phase, "HEAD"],
        cwd=repo, capture_output=True, text=True,
    )


def test_phase_gate_manifest_baseline_passes(frozen_repo):
    r = _run_gate(frozen_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_phase_gate_frozen_manifest_absent_but_version_present_fails(frozen_repo):
    """The whole check used to be wrapped in `[ -f FROZEN ]`, which turned
    deleting the manifest itself into a silent skip. c139cbc fixed the
    trigger to VERSION presence."""
    (frozen_repo / "scripts" / ".approved" / "frozen-manifest").unlink()
    r = _run_gate(frozen_repo)
    assert r.returncode == 1
    assert "frozen-manifest is missing" in r.stdout


def test_phase_gate_pinned_file_tampered_fails(frozen_repo):
    (frozen_repo / "tests" / "test_x.py").write_text("def test_ok(): return 42\n")
    r = _run_gate(frozen_repo)
    assert r.returncode == 1
    assert "frozen spec tampered" in r.stdout


def test_phase_gate_unpinned_test_file_fails(frozen_repo):
    """INV-1 addition coverage — the hash loop catches modification and
    deletion of pinned files, but a fresh tests/test_y.py was invisible
    to the manifest yet ran in the full frozen suite."""
    (frozen_repo / "tests" / "test_stowaway.py").write_text("def test_x(): pass\n")
    r = _run_gate(frozen_repo)
    assert r.returncode == 1
    assert "unpinned test file" in r.stdout
    assert "test_stowaway.py" in r.stdout


def test_phase_gate_gitignored_bytecode_does_not_trip(frozen_repo):
    """Regression pin: the fix uses git ls-files (gitignore-respecting) on
    the disk side so pytest's __pycache__/.pytest_cache don't flag as
    unpinned on any child that has ever run tests."""
    (frozen_repo / ".gitignore").write_text("__pycache__/\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "add", ".gitignore"],
        cwd=frozen_repo, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "gitignore"],
        cwd=frozen_repo, check=True,
    )
    (frozen_repo / "tests" / "__pycache__").mkdir()
    (frozen_repo / "tests" / "__pycache__" / "test_x.cpython-314.pyc").write_bytes(b"\x00")
    r = _run_gate(frozen_repo)
    assert r.returncode == 0, r.stdout


# --- refreeze.sh REMOVED whitelist (fixes 64535e3) --------------------------
# The `case "$f" in tests/*.py)` whitelist accepted `tests/../scripts/foo.py`
# because bash case-globs match '/'. 64535e3 rejects traversal before the
# pattern check. We exercise refreeze in --diff mode: it runs the same
# staging validation (including the REMOVED check) but applies nothing —
# so we can test the freeze door without a real interactive terminal.
REFREEZE = SCRIPTS / "refreeze.sh"
VALID_ERD_DELTA = (
    "# Current milestone\n\n"
    "## Changed acceptance criteria\n\n"
    "None.\n\n"
    "## Superseded acceptance criteria\n\n"
    "None.\n\n"
    "## Changed files\n\n"
    "- src/app.py\n"
    "- src/api/chat.py\n"
    "- src/api/models.py\n\n"
    "## Test-to-file mapping\n\n"
    "No new mapping.\n"
)


@pytest.fixture()
def stageable_repo(tmp_path):
    """A repo with the machinery refreeze needs to reach the REMOVED
    validation: an existing frozen spec (v1), plus a staging dir. We
    keep the staging minimal (just a REMOVED file) because we want the
    REMOVED validation to fire, not the delta plumbing beyond it."""
    (tmp_path / "scripts" / ".approved" / "incoming").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir(exist_ok=True)
    for name in (
        "refreeze.sh",
        "phase-gate.sh",
        "spec_artifacts.py",
        "check-spec-delta.py",
    ):
        target = tmp_path / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
        if name.endswith(".sh"):
            target.chmod(0o755)

    # A prior freeze exists (VERSION>0), so REMOVED entries can refer to
    # files that must be present in the tree.
    (tmp_path / "scripts" / ".approved" / "VERSION").write_text("1\n")
    (tmp_path / "tests" / "test_real.py").write_text("def test_ok(): pass\n")
    # frozen-manifest is regenerated by refreeze, so any content is fine
    # for the pre-apply validation phase we're exercising.
    (tmp_path / "scripts" / ".approved" / "frozen-manifest").write_text("")

    _init_git(tmp_path)
    return tmp_path


def _run_refreeze_diff(repo):
    return subprocess.run(
        ["bash", "scripts/refreeze.sh", "--diff", "scripts/.approved/incoming"],
        cwd=repo, capture_output=True, text=True,
    )


def test_refreeze_removed_rejects_traversal(stageable_repo):
    """The specific defeat the review found: `tests/../scripts/x.py`
    matched the `tests/*.py` case-glob (bash case-globs match '/') and
    would have `rm -f`'d the traversed path at apply. The fix rejects
    traversal *before* the pattern, with a distinct 'no traversal'
    message — a generic "not tests/*.py" reject at some later stage
    isn't the invariant we want to pin (unfixed code failed later for a
    different reason, which a looser assertion would have passed)."""
    # A "victim" file at the traversed target so the pre-fix code would
    # have passed the [ -f "$f" ] existence check and continued into the
    # apply path. Reproduces the exact vulnerability shape.
    (stageable_repo / "scripts" / "x_victim.py").write_text("victim\n")
    (stageable_repo / "scripts" / ".approved" / "incoming" / "REMOVED").write_text(
        "tests/../scripts/x_victim.py\n"
    )
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "no traversal" in combined, combined


@pytest.mark.parametrize("bad_path", [
    "/etc/passwd",                 # absolute
    "../scripts/refreeze.sh",      # simple parent-escape
    "tests/../../etc/passwd",      # not tests/*.py at all
])
def test_refreeze_removed_rejects_non_tests_paths(stageable_repo, bad_path):
    """Base whitelist — both pre-fix and post-fix reject these. Kept as
    a regression pin so a future rewrite doesn't loosen the whitelist."""
    (stageable_repo / "scripts" / ".approved" / "incoming" / "REMOVED").write_text(
        bad_path + "\n"
    )
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "REMOVED entries must be" in combined, combined


def test_refreeze_removed_accepts_plain_tests_path(stageable_repo):
    """The tightening must not break the legitimate case."""
    (stageable_repo / "scripts" / ".approved" / "incoming" / "REMOVED").write_text(
        "tests/test_real.py\n"
    )
    r = _run_refreeze_diff(stageable_repo)
    # --diff mode may still fail late (delta plumbing needs more staging),
    # but it must NOT fail at the REMOVED whitelist.
    combined = r.stdout + r.stderr
    assert "REMOVED entries must be" not in combined, combined


# --- validate-plan.py --spec-preflight (D-78) --------------------------------
# testchat M28 v51: a spec froze GET /api/v1/models/catalog with no
# implementing file in contracts.files; the plan gate's exact bijection made
# it unimplementable by ANY EM, discovered ~75 minutes downstream. The
# preflight proves that from the spec alone, pre-approval. These tests pin
# the v51 reproduction and each fail-open boundary.

V51_SRC = (
    "router = APIRouter(prefix='/api/v1')\n"
    "\n"
    "@router.get('/models')\n"
    "def list_models():\n"
    "    return []\n"
)


def preflight_repo(tmp_path, src=V51_SRC):
    (tmp_path / "src" / "api").mkdir(parents=True)
    if src is not None:
        (tmp_path / "src" / "api" / "models.py").write_text(src)
    return tmp_path


def run_preflight(repo, old, new):
    old_p = repo / "old-contracts.json"
    if old is not None:
        old_p.write_text(json.dumps(old))
    new_p = repo / "new-contracts.json"
    new_p.write_text(json.dumps(new))
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--spec-preflight",
         str(old_p), str(new_p)],
        cwd=repo, capture_output=True, text=True,
    )


V51_OLD = {
    "erd_version": 1,
    "files": ["src/api/chat.py"],
    "entry_points": [],
    "routes": [{"id": "route:GET /api/v1/models",
                "method": "GET", "path": "/api/v1/models"}],
}


def v51_new(files):
    return {
        "erd_version": 2,
        "files": files,
        "entry_points": [],
        "routes": V51_OLD["routes"] + [
            {"id": "route:GET /api/v1/models/catalog",
             "method": "GET", "path": "/api/v1/models/catalog"}],
    }


def test_preflight_v51_sibling_file_outside_inventory_fails(tmp_path):
    """The exact v51 shape: new route, registered nowhere, whose path-sibling
    (GET /api/v1/models) is registered in a file absent from contracts.files.
    The failure must name that file — it IS the fix."""
    repo = preflight_repo(tmp_path)
    r = run_preflight(repo, V51_OLD, v51_new(["src/api/chat.py"]))
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "v51/M28 class" in r.stderr, r.stderr
    assert "src/api/models.py" in r.stderr, r.stderr


def test_preflight_v51_fix_file_in_inventory_passes(tmp_path):
    """The v53 recut shape: same delta plus the implementing file."""
    repo = preflight_repo(tmp_path)
    r = run_preflight(
        repo, V51_OLD, v51_new(["src/api/chat.py", "src/api/models.py"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_sibling_file_no_edit_declared_fails(tmp_path):
    """In the inventory but no_edit (D-65) is NOT implementable — the
    orchestrator never invokes the coder for no-edit files."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/api/chat.py", "src/api/models.py"])
    new["no_edit_files"] = ["src/api/models.py"]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode != 0, (r.stdout, r.stderr)


def test_preflight_route_already_registered_passes(tmp_path):
    """A route the source already serves is satisfiable regardless of the
    inventory — carried-forward surface, not delta work."""
    repo = preflight_repo(tmp_path, src=V51_SRC.replace(
        "@router.get('/models')", "@router.get('/models/catalog')"))
    r = run_preflight(repo, V51_OLD, v51_new(["src/api/chat.py"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_new_route_family_fails_open_with_editable_py(tmp_path):
    """A brand-new path family names no natural implementing file — no
    signal, so an editable .py in the inventory is accepted."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/api/chat.py"])
    new["routes"] = [{"id": "route:GET /webhooks/incoming",
                      "method": "GET", "path": "/webhooks/incoming"}]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_new_route_no_editable_py_fails(tmp_path):
    """...but an inventory that could not register ANY route fails closed."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/static/index.html"])
    new["routes"] = [{"id": "route:GET /webhooks/incoming",
                      "method": "GET", "path": "/webhooks/incoming"}]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "no editable .py" in r.stderr, r.stderr


def test_preflight_new_entry_point_module_uncreatable_fails(tmp_path):
    """A new entry_point whose module file is neither on disk nor in the
    inventory: no task may create it."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/api/chat.py"])
    new["routes"] = V51_OLD["routes"]  # isolate the entry-point check
    new["entry_points"] = ["src.services.catalog"]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "src/services/catalog.py" in r.stderr, r.stderr


def test_preflight_new_symbol_on_uninventoried_module_fails(tmp_path):
    """The one-artifact-smaller v51: a new :symbol on an on-disk module that
    no task may edit."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/api/chat.py"])
    new["routes"] = V51_OLD["routes"]  # isolate the entry-point check
    new["entry_points"] = ["src.api.models:list_model_catalog"]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "list_model_catalog" in r.stderr, r.stderr


def test_preflight_existing_symbol_outside_inventory_passes(tmp_path):
    """Locking an ALREADY-EXISTING symbol is pure surface declaration —
    no implementation work needed, inventory irrelevant."""
    repo = preflight_repo(tmp_path)
    new = v51_new(["src/api/chat.py"])
    new["routes"] = V51_OLD["routes"]  # isolate the entry-point check
    new["entry_points"] = ["src.api.models:list_models"]
    r = run_preflight(repo, V51_OLD, new)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_audit_form_old_empty_catches_v51(tmp_path):
    """The D-79 form: old={} (whole frozen spec audited against the tree).
    Sibling evidence must come from the NEW contracts' locatable routes,
    or the mid-run audit would fail open and miss v51."""
    repo = preflight_repo(tmp_path)
    r = run_preflight(repo, {}, v51_new(["src/api/chat.py"]))
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "v51/M28 class" in r.stderr, r.stderr


def test_preflight_initial_freeze_fails_open(tmp_path):
    """v1: no prior contracts, no source tree. Routes with an editable .py
    in the inventory must pass — everything is buildable from nothing."""
    (tmp_path / "src").mkdir()
    new = v51_new(["src/main.py"])
    new["erd_version"] = 1
    r = run_preflight(tmp_path, None, new)
    assert r.returncode == 0, (r.stdout, r.stderr)


# --- ensure_plan: D-79 spec-defect rung (bash, via drive-plan.sh) ------------
# M28: two different EM models failed identically at the plan gate because
# the spec was unimplementable — the ladder only knew how to escalate the
# ACTOR. The rung audits the puzzle after the plan budget is exhausted:
# audit fails -> exit 2 + TPM bundle, no more EM calls; audit passes ->
# the pre-existing actor-path halt (exit 1), unchanged.

DRIVE_PLAN = SCRIPTS / "selftest" / "drive-plan.sh"


def plan_workdir(tmp_path, contracts, replies, src=None):
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "contracts.json").write_text(json.dumps(contracts))
    (approved / "test-nodeids").write_text("\n".join(NODEIDS) + "\n")
    (approved / "VERSION").write_text(str(contracts["erd_version"]) + "\n")
    (tmp_path / "replies").mkdir()
    for i, reply in enumerate(replies, 1):
        (tmp_path / "replies" / str(i)).write_text(reply)
    if src is not None:
        (tmp_path / "src" / "api").mkdir(parents=True)
        (tmp_path / "src" / "api" / "models.py").write_text(src)
    return tmp_path


def run_drive_plan(workdir):
    return subprocess.run(
        ["bash", str(DRIVE_PLAN), str(workdir)],
        capture_output=True, text=True,
    )


def test_plan_spec_defect_routes_to_tpm_bundle(tmp_path):
    """Unsatisfiable spec + exhausted plan budget -> SPEC DEFECT: exit 2,
    a spec-defect bundle in the batch, and exactly MAX_PLAN_REVISIONS EM
    calls consumed — the rung must not invite more attempts."""
    contracts = dict(v51_new(["src/api/chat.py"]), erd_version=1)
    work = plan_workdir(tmp_path, contracts, ["{}", "{}"], src=V51_SRC)
    r = run_drive_plan(work)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "SPEC DEFECT (D-79)" in r.stdout, r.stdout
    batch = work / ".pipeline-state" / "escalations" / "BATCH.md"
    assert batch.is_file(), r.stdout
    content = batch.read_text()
    assert "spec-defect — SPEC-DEFECT" in content, content
    assert "v51/M28 class" in content, content        # audit output embedded
    assert "no EM consult" in content, content        # honest diagnosis section
    assert (work / ".calls").read_text().strip() == "2", r.stdout


def test_plan_exhaustion_satisfiable_spec_halts_actor_path(tmp_path):
    """Same exhaustion, but the spec is fine (route already registered in
    source) -> the pre-existing halt: exit 1, no bundle, and the message
    says the audit cleared the spec."""
    contracts = dict(v51_new(["src/api/chat.py"]), erd_version=1)
    registered = V51_SRC.replace(
        "@router.get('/models')",
        "@router.get('/models')\ndef _list():\n    return []\n\n"
        "@router.get('/models/catalog')")
    work = plan_workdir(tmp_path, contracts, ["{}", "{}"], src=registered)
    r = run_drive_plan(work)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "plan invalid after 2 EM revisions" in r.stderr, r.stderr
    assert "found no unsatisfiable contract" in r.stderr, r.stderr
    assert not (work / ".pipeline-state" / "escalations" / "BATCH.md").exists()


def test_plan_valid_first_emit_needs_no_rung(tmp_path):
    """Harness sanity: a valid first plan exits 0 after one EM call and the
    rung never runs."""
    work = plan_workdir(tmp_path, dict(CONTRACTS, erd_version=1),
                        [json.dumps(good_plan())])
    r = run_drive_plan(work)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "CALLS=1 PLAN=ok" in r.stdout, r.stdout
    assert "SPEC DEFECT" not in r.stdout, r.stdout


# --- preflight: TPM scope declaration (D-86) ---------------------------------
# changed_files reaches the coder's editable set through --affected. An entry
# the plan gate can never map to a task declares nothing, silently — the
# failure mode D-86 exists to remove, so it must not be reintroduced by a typo.

INDEX_HTML = (
    "<html><head>\n"
    '<link rel="stylesheet" href="/static/style.css">\n'
    "</head><body></body></html>\n"
)


def asset_repo(tmp_path, index=INDEX_HTML):
    static = tmp_path / "src" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text(index)
    (static / "style.css").write_text("body { margin: 0; }\n")
    return tmp_path


def asset_contracts(files, no_edit=None, changed=None):
    c = {"erd_version": 2, "files": files, "entry_points": []}
    if no_edit is not None:
        c["no_edit_files"] = no_edit
    if changed is not None:
        c["changed_files"] = changed
    return c


ASSET_OLD = asset_contracts(["src/static/index.html", "src/static/style.css"])


def test_preflight_changed_files_outside_inventory_fails(tmp_path):
    """A declared file absent from contracts.files can never map to a task
    (the plan gate's bijection is over files), so it scopes nothing."""
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/index.html"],
                        changed=["src/static/app.js"]))
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "not in contracts.files" in r.stderr, r.stderr


def test_preflight_changed_files_also_no_edit_fails(tmp_path):
    """Declaring a file both in-scope and unchanged is self-contradictory."""
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/index.html", "src/static/style.css"],
                        no_edit=["src/static/style.css"],
                        changed=["src/static/style.css"]))
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "no_edit_files" in r.stderr, r.stderr


def test_preflight_changed_files_editable_member_passes(tmp_path):
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/index.html", "src/static/style.css"],
                        no_edit=["src/static/style.css"],
                        changed=["src/static/index.html"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_absent_changed_files_is_not_an_error(tmp_path):
    """The field is optional — every pre-D-86 spec must still freeze."""
    r = run_preflight(asset_repo(tmp_path), ASSET_OLD,
                      asset_contracts(["src/static/index.html"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


# --- preflight: static-asset reachability (D-87) -----------------------------
# testchat M31 v62: the spec added src/static/current-chat.css to the
# inventory. The only <link> lives in index.html, which the delta could not
# reach, and style.css was no_edit — so the coder would have written a correct
# stylesheet nothing could ever load, the task would go green, and the ACs
# would fail naming nothing. Routes and entry_points are proved reachable by
# registration and import; an asset's only signal is a textual reference.

def test_preflight_new_asset_with_no_editable_host_fails(tmp_path):
    """The exact v62 shape. The failure must name the host file — it IS the
    fix (put index.html in the inventory, or fold the content into scope)."""
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/style.css", "src/static/current-chat.css"],
                        no_edit=["src/static/style.css"]))
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "current-chat.css" in r.stderr, r.stderr
    assert "src/static/index.html" in r.stderr, r.stderr


def test_preflight_new_asset_with_editable_host_passes(tmp_path):
    """Same delta with index.html pulled into the inventory: a task can add
    the <link>, so the asset is reachable."""
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/index.html", "src/static/style.css",
                         "src/static/current-chat.css"],
                        no_edit=["src/static/style.css"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_new_asset_already_referenced_passes(tmp_path):
    """A host that already names the asset needs no edit at all."""
    repo = asset_repo(tmp_path, index=INDEX_HTML.replace(
        "</head>", '<link rel="stylesheet" href="/static/current-chat.css">\n</head>'))
    r = run_preflight(
        repo, ASSET_OLD,
        asset_contracts(["src/static/style.css", "src/static/current-chat.css"],
                        no_edit=["src/static/style.css"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_new_asset_no_host_fails_open(tmp_path):
    """No file in the tree references assets of this type — the spec carries
    no signal about where the reference belongs. Fail open, as D-78 does for
    a brand-new route family."""
    repo = asset_repo(tmp_path, index="<html><head></head><body></body></html>")
    r = run_preflight(
        repo, ASSET_OLD,
        asset_contracts(["src/static/style.css", "src/static/current-chat.css"],
                        no_edit=["src/static/style.css"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_new_python_file_is_not_an_asset(tmp_path):
    """.py files are reached by import, which the entry_point check already
    proves — the asset rule must not double-gate them."""
    r = run_preflight(
        asset_repo(tmp_path), ASSET_OLD,
        asset_contracts(["src/static/index.html", "src/services/new.py"]))
    assert r.returncode == 0, (r.stdout, r.stderr)


# --- preflight: quote-brittle smoke_checks (D-88) ----------------------------
# testchat M31 v61: the frozen contract carried
#   grep -q '[data-active="true"]' src/static/current-chat.css
# The coder wrote `[data-active='true']` — byte-different, semantically
# identical CSS. The spec oracle failed a correct file; the ladder cannot
# recover from a spec defect below the TPM rung. Cost: 4 coder strikes + 2 EM
# diagnosis calls + an escalation halt. Provable at freeze time: only the
# robustness class of the pattern is checkable, and that is exactly what
# failed.

BRITTLE_CONTRACT = {
    "erd_version": 2,
    "files": ["src/static/current-chat.css"],
    "entry_points": [],
    "smoke_checks": {
        "src/static/current-chat.css":
            "grep -q '\\[data-active=\"true\"\\]' src/static/current-chat.css"
    },
}
SAFE_CONTRACT = {
    "erd_version": 2,
    "files": ["src/static/current-chat.css"],
    "entry_points": [],
    "smoke_checks": {
        "src/static/current-chat.css":
            "grep -qE \"\\[data-active=['\\\"]true['\\\"]\\]\""
            " src/static/current-chat.css"
    },
}


def test_preflight_v61_double_quote_in_grep_pattern_fails(tmp_path):
    """The exact v61 shape: a literal `\"` inside a grep pattern rejects a
    single-quoted implementation. The failure must name the entry AND print
    a quote-agnostic rewrite — the rewrite IS the fix."""
    r = run_preflight(tmp_path, {}, BRITTLE_CONTRACT)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "src/static/current-chat.css" in r.stderr, r.stderr
    assert "M31 v61" in r.stderr, r.stderr
    # The rewrite guidance carries the char class that would have worked.
    assert "['\\\"]" in r.stderr, r.stderr


def test_preflight_v61_fix_char_class_passes(tmp_path):
    """The corrected form: `['\"]` covers either quote character. Same delta
    that failed above must pass once rewritten."""
    r = run_preflight(tmp_path, {}, SAFE_CONTRACT)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_brittle_single_quote_pattern_fails(tmp_path):
    """Symmetric direction: literal `'` in the pattern is equally brittle."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {"src/x.py": "grep -q \"attr='val'\" src/x.py"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode != 0, (r.stdout, r.stderr)


def test_preflight_single_quote_only_bracket_class_fails(tmp_path):
    """A bracket expression with only ONE quote type is still brittle — the
    fix requires BOTH quotes so the alternative implementation matches."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {"src/x.py": "grep -qE \"attr=[']val[']\" src/x.py"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode != 0, (r.stdout, r.stderr)


def test_preflight_no_quotes_in_pattern_passes(tmp_path):
    """A pattern that names no quote at all is not this class of defect."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {"src/x.py": "grep -q handler src/x.py"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_fixed_string_grep_with_quote_fails(tmp_path):
    """`grep -F` cannot express a character class; a literal quote in a
    fixed-string pattern is brittle by construction. The fix is to switch
    to `-E`, which the failure names."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {
            "src/x.py": "grep -qF 'attr=\"true\"' src/x.py"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "grep -qE" in r.stderr, r.stderr


def test_preflight_carried_forward_brittle_pattern_passes(tmp_path):
    """A pre-existing brittle smoke_check unchanged in the delta must NOT
    fail the freeze — the class is grandfathered, same convention as
    entry_points/routes only checking new/changed."""
    old = {
        "erd_version": 1,
        "files": ["src/static/current-chat.css"],
        "entry_points": [],
        "smoke_checks": BRITTLE_CONTRACT["smoke_checks"],
    }
    new = {**BRITTLE_CONTRACT, "erd_version": 2}
    r = run_preflight(tmp_path, old, new)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_non_grep_smoke_check_passes(tmp_path):
    """A smoke_check that isn't a grep-family invocation carries no signal
    for this gate — fail open (no false positives on `python3 -c ...`,
    `test -f …`, compound pipelines)."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {
            "src/x.py": "python3 -c 'import src.x; assert src.x.OK == \"yes\"'"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode == 0, (r.stdout, r.stderr)


def test_preflight_compound_command_bails(tmp_path):
    """A compound command (`grep … && grep …`) has more than one pattern and
    reasoning about it correctly is out of scope — bail rather than
    false-positive on a legitimate multi-step check."""
    contract = {
        "erd_version": 2, "files": ["src/x.py"], "entry_points": [],
        "smoke_checks": {
            "src/x.py": "grep -q handler src/x.py && grep -q result src/x.py"},
    }
    r = run_preflight(tmp_path, {}, contract)
    assert r.returncode == 0, (r.stdout, r.stderr)


# --- preflight: per-file ERD prose mass advisory (D-89) ----------------------
# testchat M31 v64: 12 behavioral items concentrated on src/static/app.js. The
# EM's brief came out 2697 chars against MAX_BRIEF_CHARS=2500, but the plan-
# gate cap fires AFTER two EM plan calls (~250-280s each on the 4-bit seat) —
# ~10 min to learn what the ERD already implied at freeze time. This is
# advisory, not blocking: the correlation between ERD mass and brief size is
# strong but heuristic, and the plan gate is the hard backstop.

# Derived from the script under test — a threshold bump must not require
# retuning these tests (same discipline as MAX_BRIEF above).
ERD_THRESHOLD = int(re.search(
    r"^ERD_MASS_ADVISORY_THRESHOLD = (\d+)", VALIDATE_PLAN.read_text(),
    re.M).group(1))


def run_erd_mass(tmp_path, erd_text, contracts):
    erd_p = tmp_path / "ERD.md"
    erd_p.write_text(erd_text)
    c_p = tmp_path / "contracts.json"
    c_p.write_text(json.dumps(contracts))
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--erd-mass", str(erd_p), str(c_p)],
        cwd=tmp_path, capture_output=True, text=True,
    )


def test_erd_mass_flags_oversized_section(tmp_path):
    """The v64 shape: one inventory file's ERD section far exceeds the
    threshold. The advisory must name that file and its char count."""
    heavy = "x" * (ERD_THRESHOLD + 800)
    erd = (
        "# ERD\n\n"
        "## As-built\n\n"
        f"* `src/static/app.js` — {heavy}\n"
        "* `src/static/threads.js` — small.\n"
    )
    r = run_erd_mass(tmp_path, erd, {
        "files": ["src/static/app.js", "src/static/threads.js"]})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ERD MASS ADVISORY" in r.stderr, r.stderr
    assert "src/static/app.js" in r.stderr, r.stderr
    assert "src/static/threads.js" not in r.stderr, r.stderr


def test_erd_mass_within_threshold_stays_quiet(tmp_path):
    """A well-scoped ERD makes no noise — no advisory to consume, no false
    positives to train the CEO to ignore the message."""
    erd = (
        "# ERD\n\n"
        "## As-built\n\n"
        "* `src/main.py` — a compact description of the module.\n"
        "* `src/util.py` — another compact description.\n"
    )
    r = run_erd_mass(tmp_path, erd, {"files": ["src/main.py", "src/util.py"]})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ERD MASS ADVISORY" not in r.stderr, r.stderr


def test_erd_mass_heading_caps_last_file_section(tmp_path):
    """The last file in a list must NOT absorb every subsequent section —
    if it did, threads.js in testchat's v65 ERD would report ~5.5KB and
    a well-scoped file would false-positive on every freeze. A `#`-heading
    ends the current file's section."""
    trailing = "x" * (ERD_THRESHOLD + 500)
    erd = (
        "# ERD\n\n"
        "## As-built\n\n"
        "* `src/a.py` — compact.\n"
        "* `src/b.py` — also compact.\n"
        "\n## Behavior locked\n\n"
        + trailing
        + "\n"
    )
    r = run_erd_mass(tmp_path, erd, {"files": ["src/a.py", "src/b.py"]})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ERD MASS ADVISORY" not in r.stderr, r.stderr


def test_erd_mass_file_not_mentioned_no_signal(tmp_path):
    """A file with no section-start mention yields no measurement — no
    signal, no advisory (a mid-sentence mention or absence is not proof
    the file is oversized OR undersized)."""
    erd = "# ERD\n\n## As-built\n\n* `src/a.py` — small.\n"
    r = run_erd_mass(tmp_path, erd,
                     {"files": ["src/a.py", "src/never_mentioned.py"]})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ERD MASS ADVISORY" not in r.stderr, r.stderr


def test_erd_mass_table_format_recognized(tmp_path):
    """sparkv3-style file inventory tables (`| \\`src/main.py\\` |`) must
    match — the heuristic can't require a bullet marker or every non-
    testchat spec silently produces zero measurements."""
    heavy = "x" * (ERD_THRESHOLD + 400)
    erd = (
        "# ERD\n\n"
        "## Inventory\n\n"
        "| File | Purpose |\n"
        "|---|---|\n"
        f"| `src/main.py` | {heavy} |\n"
        "| `src/util.py` | small. |\n"
    )
    r = run_erd_mass(tmp_path, erd, {"files": ["src/main.py", "src/util.py"]})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "ERD MASS ADVISORY" in r.stderr, r.stderr
    assert "src/main.py" in r.stderr, r.stderr


def test_erd_mass_missing_erd_file_is_not_an_error(tmp_path):
    """A contracts-only delta may not stage ERD.md — the advisory has no
    input, exits 0, prints nothing."""
    c_p = tmp_path / "contracts.json"
    c_p.write_text(json.dumps({"files": ["src/a.py"]}))
    r = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--erd-mass",
         str(tmp_path / "no-such-ERD.md"), str(c_p)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stderr == "", r.stderr


def test_plan_gate_brief_overflow_names_erd_mass(tmp_path):
    """D-89 back-half: the plan-gate halt message for a >MAX_BRIEF_CHARS
    brief names the file's ERD section size, so a future TPM restage
    routes to spec size (`the spec is oversized`) rather than another
    actor swap (`the EM wrote long`)."""
    # Stand up a repo layout the plan gate expects: scripts/.approved/{VERSION,
    # contracts.json, test-nodeids, ERD.md}, and tasks/plan.json.
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "VERSION").write_text("2")
    contracts = {
        "erd_version": 2,
        "files": ["src/app.py"],
        "entry_points": [],
        "routes": [],
    }
    (approved / "contracts.json").write_text(json.dumps(contracts))
    (approved / "test-nodeids").write_text("tests/test_app.py::test_x\n")
    heavy = "x" * (ERD_THRESHOLD + 700)
    (approved / "ERD.md").write_text(
        "# ERD\n\n## As-built\n\n"
        f"* `src/app.py` — {heavy}\n"
    )
    (tmp_path / "tasks").mkdir()
    long_brief = "y" * (MAX_BRIEF + 50)
    plan = {
        "erd_version": 2,
        "tasks": [{
            "id": "T1", "file": "src/app.py",
            "depends_on": [], "brief": long_brief,
            "contracts": [], "tests": ["tests/test_app.py::test_x"],
        }],
    }
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps(plan))
    (tmp_path / ".gate-paths").write_text("src/\n")
    r = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    # The base error is still there — this is a plan-gate defect regardless.
    assert "brief is" in combined and "max" in combined, combined
    # The hint that D-89 adds: the file's ERD section size.
    assert "ERD section for src/app.py" in combined, combined
    assert "D-89" in combined, combined


# --- refreeze.sh wires the preflight before approval (D-78) ------------------

def refreeze_scripts(repo):
    for name in ("validate-plan.py", "check-test-surface.py",
                 "check-swallowed-errors.py", "check-spec-delta.py"):
        (repo / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
    (repo / "scripts" / ".approved" / "incoming"
     / "ERD-DELTA.md").write_text(VALID_ERD_DELTA)


def test_refreeze_diff_mode_runs_preflight(stageable_repo):
    """refreeze --diff must reject a v51-shaped delta BEFORE printing a
    DIFF-SHA — the CEO never reviews a doomed spec."""
    repo = stageable_repo
    refreeze_scripts(repo)
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "models.py").write_text(V51_SRC)
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(V51_OLD))
    (repo / "scripts" / ".approved" / "incoming" / "contracts.json").write_text(
        json.dumps(v51_new(["src/api/chat.py"])))
    r = _run_refreeze_diff(repo)
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "D-78" in combined, combined
    assert "DIFF-SHA" not in combined, combined


def test_refreeze_diff_mode_prints_erd_mass_advisory(stageable_repo):
    """D-89: refreeze --diff must surface the ERD-mass advisory before the
    human approval prompt on a staged ERD with an oversized file section,
    so the CEO sees the size at the moment approval is possible."""
    repo = stageable_repo
    refreeze_scripts(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("# empty\n")
    contracts = {"erd_version": 2, "files": ["src/app.py"],
                 "entry_points": [], "routes": []}
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(contracts))
    (repo / "scripts" / ".approved" / "ERD.md").write_text("# ERD v1\n")
    heavy = "x" * (ERD_THRESHOLD + 800)
    (repo / "scripts" / ".approved" / "incoming" / "contracts.json").write_text(
        json.dumps(contracts))
    (repo / "scripts" / ".approved" / "incoming" / "ERD.md").write_text(
        "# ERD\n\n## As-built\n\n"
        f"* `src/app.py` — {heavy}\n"
    )
    r = _run_refreeze_diff(repo)
    combined = r.stdout + r.stderr
    assert "ERD MASS ADVISORY" in combined, combined
    assert "src/app.py" in combined, combined
    # Advisory-only: --diff must still reach the DIFF-SHA gate.
    assert "DIFF-SHA" in combined, combined


# --- refreeze.sh D-68 debt sweep at freeze time (D-80) -----------------------
# M28: models.py's pre-existing unjustified handler failed T11's D-68 gate
# mid-run, forcing the v54 recut — the debt was on record since 07-17 but
# nothing surfaced it at spec time. The sweep prints it at the human gate,
# advisory: the freeze still proceeds (a DIFF-SHA is still offered).

def debt_delta(repo, app_source):
    """Stage a minimal contracts-only delta whose inventory holds src/app.py
    with the given source. No routes/entry_points, so the D-78 preflight
    stays out of the way."""
    refreeze_scripts(repo)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(app_source)
    contracts = {"erd_version": 2, "files": ["src/app.py"], "entry_points": []}
    (repo / "scripts" / ".approved" / "incoming" / "contracts.json").write_text(
        json.dumps(contracts))


def test_refreeze_debt_sweep_warns_and_still_freezes(stageable_repo):
    debt_delta(stageable_repo,
               "def f():\n"
               "    try:\n"
               "        risky()\n"
               "    except Exception:\n"
               "        pass\n")
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "WARNING (D-80)" in r.stdout, r.stdout
    assert "src/app.py:4" in r.stdout, r.stdout      # names file AND line
    assert "DIFF-SHA" in r.stdout, r.stdout          # advisory, not a blocker


def test_refreeze_debt_sweep_silent_on_justified_swallow(stageable_repo):
    debt_delta(stageable_repo,
               "def f():\n"
               "    try:\n"
               "        risky()\n"
               "    except Exception:\n"
               "        pass  # best-effort cleanup; failure is safe to drop\n")
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "WARNING (D-80)" not in r.stdout, r.stdout
    assert "DIFF-SHA" in r.stdout, r.stdout


# --- refreeze.sh freeze-hygiene advisory (D-83) -------------------------------
# Both defect-bearing M28 freezes were authored minutes after the prior
# milestone closed. The note fires when the last [success] is under an
# hour old; it is advisory — the freeze proceeds either way.

CLEAN_APP = "def f():\n    return 1\n"


def success_commit(repo, epoch=None):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@local",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@local")
    if epoch is not None:
        env["GIT_COMMITTER_DATE"] = f"@{epoch} +0000"
        env["GIT_AUTHOR_DATE"] = f"@{epoch} +0000"
    subprocess.run(["git", "commit", "--allow-empty", "-m", "[success] spec v1"],
                   cwd=repo, env=env, check=True, capture_output=True)


def test_refreeze_hygiene_note_on_fresh_success(stageable_repo):
    debt_delta(stageable_repo, CLEAN_APP)
    success_commit(stageable_repo)
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "NOTE (D-83)" in r.stdout, r.stdout
    assert "DIFF-SHA" in r.stdout, r.stdout          # advisory, not a blocker


def test_refreeze_hygiene_silent_on_old_success(stageable_repo):
    debt_delta(stageable_repo, CLEAN_APP)
    success_commit(stageable_repo, epoch=int(time.time()) - 7200)
    r = _run_refreeze_diff(stageable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "NOTE (D-83)" not in r.stdout, r.stdout


# --- run_coder: gate-failure propagation (review blocker #1, drive-coder.sh) -
# The 2026-07-16 pre-publish review's worst finding: run_coder is always
# invoked as an if-condition, which suppresses `set -e` for its whole body,
# and the task lane gate at its tail had no explicit failure handling — a
# failing gate was silently ignored and the caller committed the file anyway.
# Fixed with an explicit `|| die` (hard halt, D-15/D-22). The same bug class
# had already been fixed once in em_call (D-71) and recurred here; these
# tests are the mechanical guard against a third occurrence. The harness
# reproduces the exact calling shape (if-condition + commit-on-success).

DRIVE_CODER = SCRIPTS / "selftest" / "drive-coder.sh"

CODER_GOOD_REPLY = (
    "=== FILE: src/x.py ===\n"
    "def f():\n"
    "    return 1\n"
    "=== END FILE ===\n"
)


def run_coder_drive(tmp_path, reply, gate_rc, task_file="src/x.py"):
    rdir = tmp_path / "replies"
    rdir.mkdir()
    (rdir / "1").write_text(reply)
    return subprocess.run(
        ["bash", str(DRIVE_CODER), str(tmp_path), "T7", task_file, str(gate_rc)],
        capture_output=True, text=True,
    )


def coder_commit_count(tmp_path):
    return int(subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True,
    ).stdout.strip())


def test_coder_gate_pass_writes_and_commits(tmp_path):
    r = run_coder_drive(tmp_path, CODER_GOOD_REPLY, gate_rc=0)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "RC=0" in r.stdout
    assert coder_commit_count(tmp_path) == 2  # fixture + [task T7]
    assert (tmp_path / "src" / "x.py").read_text().startswith("def f():")


def test_coder_gate_failure_is_hard_halt_and_nothing_committed(tmp_path):
    """THE blocker-#1 pin. A failing lane gate must kill the run via die
    (exit, which escapes the set -e suppression) BEFORE the call site can
    commit. Pre-fix behavior: run_coder returned 0, the file was committed,
    and the harness would print RC=0 COMMITS=2 — every assertion below
    fails against that code."""
    r = run_coder_drive(tmp_path, CODER_GOOD_REPLY, gate_rc=1)
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "hard halt" in r.stderr
    assert "RC=" not in r.stdout          # die fired before the call site resumed
    assert coder_commit_count(tmp_path) == 1  # fixture only — no [task] commit


def test_coder_wrong_path_reply_is_strike_not_commit(tmp_path):
    """Reply naming a different path than the task = coder FAILURE (return 1,
    strike evidence), never a write and never a commit. The parser's failure
    reason must reach CODER_EVIDENCE — the sentinel-parser exits via
    sys.exit(msg) to stderr, so the capture at orchestrate.sh:386 needs 2>&1
    to reach the retry brief and the EM consult (D-73/D-71). Pre-fix
    behavior: EVIDENCE was empty on every create-mode failure, the retry
    brief carried no failure note, and the EM diagnosed from bare context
    (the M25 misdiagnosis class D-73 also fixed)."""
    wrong = CODER_GOOD_REPLY.replace("src/x.py", "src/other.py")
    r = run_coder_drive(tmp_path, wrong, gate_rc=0)
    assert r.returncode == 0, (r.stdout, r.stderr)   # harness survives; strike path
    assert "RC=1" in r.stdout
    assert coder_commit_count(tmp_path) == 1
    assert not (tmp_path / "src" / "x.py").exists()
    assert not (tmp_path / "src" / "other.py").exists()
    # EVIDENCE=- is drive-coder's sentinel for an empty capture — the exact
    # pre-fix defect. The nonempty message names the wrong path so a retry
    # brief can actually diagnose.
    assert "EVIDENCE=coder wrote to 'src/other.py'" in r.stdout


# --- runtime verdict/state guards -------------------------------------------

DRIVE_RUNTIME = SCRIPTS / "selftest" / "drive-runtime.sh"


def _runtime_git_commit(repo, subject):
    marker = repo / "history"
    marker.write_text(marker.read_text() + subject + "\n" if marker.exists()
                      else subject + "\n")
    subprocess.run(["git", "add", "history"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=selftest@local",
         "-c", "user.name=selftest", "commit", "-qm", subject],
        cwd=repo, check=True,
    )


def test_run_tests_rejects_stale_green_report_when_sandbox_fails(tmp_path):
    """A failed sandbox launch must not replay the previous invocation's
    green JSON report. The runner deletes the report before launch, so the
    existing NO_REPORT path produces an inconclusive verdict."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "test-report.json").write_text(json.dumps({
        "summary": {"total": 1, "passed": 1},
        "tests": [{"nodeid": "tests/test_old.py::test_old",
                   "outcome": "passed"}],
        "collectors": [],
    }))
    r = subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "tests", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "FINAL_TESTS_RC=3" in r.stdout
    assert "FINAL_FAILING=NO_REPORT" in r.stdout


def _run_with_json_report(tmp_path, report):
    source = tmp_path / "fresh-report.json"
    source.write_text(json.dumps(report))
    env = {**os.environ, "SANDBOX_REPORT_SOURCE": str(source),
           "SANDBOX_STUB_RC": "0"}
    return subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "tests", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )


def _actual_pytest_json_report(tmp_path, test_source):
    fixture = tmp_path / "report-fixture"
    fixture.mkdir()
    test_file = fixture / "test_actual_report.py"
    test_file.write_text(test_source)
    report = tmp_path / "actual-report.json"
    generated = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q",
         "-p", "no:cacheprovider", "--json-report",
         f"--json-report-file={report}"],
        cwd=fixture, capture_output=True, text=True,
    )
    assert generated.returncode == 0, (generated.stdout, generated.stderr)
    assert report.is_file(), "pytest-json-report produced no report"
    return report


def _run_report_file(tmp_path, report):
    env = {**os.environ, "SANDBOX_REPORT_SOURCE": str(report),
           "SANDBOX_STUB_RC": "0"}
    return subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "tests", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )


def test_run_tests_accepts_real_pytest_json_report(tmp_path):
    """Compatibility is exercised against the installed reporting plugin,
    not only hand-built dictionaries that can drift from its real schema."""
    report = _actual_pytest_json_report(
        tmp_path, "def test_real_pass():\n    assert True\n"
    )
    r = _run_report_file(tmp_path, report)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "FINAL_TESTS_RC=0" in r.stdout


def test_run_tests_rejects_real_skipped_report_and_ci_installs_plugin(tmp_path):
    """The real plugin's skipped shape must stay red, and the unconditional
    selftest job must install that plugin even in a bare template repo."""
    report = _actual_pytest_json_report(
        tmp_path,
        "import pytest\n\n"
        "@pytest.mark.skip(reason='compatibility fixture')\n"
        "def test_real_skip():\n    assert True\n",
    )
    r = _run_report_file(tmp_path, report)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "FINAL_TESTS_RC=1" in r.stdout
    assert "test_actual_report.py::test_real_skip" in r.stdout
    workflow = (SCRIPTS.parent / ".github" / "workflows" / "ci.yml").read_text()
    install = re.search(r"run:\s*pip install ([^\n]+)", workflow)
    assert install and "pytest-json-report" in install.group(1), workflow


def test_run_tests_rejects_skipped_and_xfailed_outcomes(tmp_path):
    """Frozen acceptance is fail-closed: a collected test that did not
    ordinarily pass cannot make the task or full suite green."""
    r = _run_with_json_report(tmp_path, {
        "summary": {"total": 2, "skipped": 2},
        "tests": [
            {"nodeid": "tests/test_x.py::test_skipped",
             "outcome": "skipped"},
            {"nodeid": "tests/test_x.py::test_xfail",
             "outcome": "xfailed"},
        ],
        "collectors": [],
    })
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "FINAL_TESTS_RC=1" in r.stdout
    assert "tests/test_x.py::test_skipped" in r.stdout
    assert "tests/test_x.py::test_xfail" in r.stdout


def test_run_tests_rejects_xfail_marked_pass(tmp_path):
    """An XPASS may be encoded as outcome=passed plus wasxfail metadata.
    It is still not an ordinary frozen-oracle pass."""
    r = _run_with_json_report(tmp_path, {
        "summary": {"total": 1, "passed": 1},
        "tests": [{
            "nodeid": "tests/test_x.py::test_xpass",
            "outcome": "passed",
            "call": {"wasxfail": "known defect"},
        }],
        "collectors": [],
    })
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "FINAL_TESTS_RC=1" in r.stdout
    assert "tests/test_x.py::test_xpass" in r.stdout


def test_state_guard_allows_intentional_post_success_cleanup(tmp_path):
    """The success path deliberately removes .pipeline-state. A prior task
    followed by a newer success commit is therefore a legitimate fresh start,
    not evidence of mid-milestone state loss."""
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    _runtime_git_commit(tmp_path, "[task T1] attempt 1")
    _runtime_git_commit(tmp_path, "[success] spec v1")
    r = subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "state", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "STATE_GUARD=pass" in r.stdout


def test_state_guard_still_halts_on_mid_milestone_loss(tmp_path):
    """A task newer than the most recent success means work was in flight
    when its state vanished. The fail-closed loss guard must still halt."""
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    _runtime_git_commit(tmp_path, "[task T1] attempt 1")
    _runtime_git_commit(tmp_path, "[success] spec v1")
    _runtime_git_commit(tmp_path, "[task T2] attempt 1")
    r = subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "state", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "task-state is empty" in r.stderr


def test_state_guard_explicit_rebuild_override_is_named_and_loud(tmp_path):
    """An intentional rebuild has a real escape path instead of the old
    ineffective instruction to delete an already-empty directory."""
    subprocess.run(["git", "init", "-q", "."], cwd=tmp_path, check=True)
    _runtime_git_commit(tmp_path, "[task T1] attempt 1")
    env = {**os.environ, "SWBP_REBUILD_FROM_SCRATCH": "1"}
    r = subprocess.run(
        ["bash", str(DRIVE_RUNTIME), "state", str(tmp_path)],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "SWBP_REBUILD_FROM_SCRATCH=1" in r.stdout
    assert "STATE_GUARD=pass" in r.stdout


# --- D-108 durable completion ledger ----------------------------------------


def _completion_fixture(tmp_path):
    tasks = [
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
            "contracts": ["src.b"],
            "tests": ["tests/test_b.py::test_two"],
        },
    ]
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1,
        "erd_version": 1,
        "tasks": tasks,
    }))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("A = 1\n")
    (tmp_path / "src" / "b.py").write_text("B = 2\n")
    state = tmp_path / ".pipeline-state" / "tasks"
    state.mkdir(parents=True)
    for task in tasks:
        fingerprint = hashlib.sha256(
            json.dumps(task, sort_keys=True).encode()
        ).hexdigest()
        (state / f"{task['id']}.status").write_text("done\n")
        (state / f"{task['id']}.fp").write_text(f"{fingerprint}\n")
    return tasks


def _run_completion(tmp_path, action):
    return subprocess.run(
        [sys.executable, str(COMPLETION_LEDGER), action,
         "--spec-version", "1"],
        cwd=tmp_path, capture_output=True, text=True,
    )


def _run_prior_spec_resolution(tmp_path, current_spec):
    """Execute the exact D-113 resolver extracted from orchestrate.sh."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    block = source.split(
        "# BEGIN D-113 prior-spec resolution (selftest extracts this function)\n",
        1,
    )[1].split("# END D-113 prior-spec resolution", 1)[0]
    env = {
        **os.environ,
        "STATE_DIR": str(tmp_path / ".pipeline-state"),
        "TASK_STATE": str(tmp_path / ".pipeline-state" / "tasks"),
        "COMPLETION_LEDGER": str(tmp_path / ".pipeline-completions.json"),
        "COMPLETION_LEDGER_TOOL": str(COMPLETION_LEDGER),
        "FROZEN_V": str(current_spec),
    }
    script = f"""set -euo pipefail
read_state() {{ [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }}
die() {{ echo "FAIL: $*" >&2; exit 1; }}
{block}
LAST_V=$(resolve_last_spec_version)
echo "LAST_V=$LAST_V"
if [ "$LAST_V" != "$FROZEN_V" ]; then echo "SPEC_ADVANCED=1"; else echo "SPEC_ADVANCED=0"; fi
"""
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, env=env,
    )


def _run_active_delta_resolution(
    tmp_path, last_spec, current_spec, available_versions,
    baseline_spec=None,
):
    source = (SCRIPTS / "orchestrate.sh").read_text()
    block = source.split(
        "# BEGIN D-113 active-delta range (selftest extracts this block)\n",
        1,
    )[1].split("# END D-113 active-delta range", 1)[0]
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True, exist_ok=True)
    for version in available_versions:
        (approved / f"DELTA-v{version}.json").write_text("{}\n")
    env = {
        **os.environ,
        "APPROVED": str(approved),
        "LAST_V": str(last_spec),
        "DELTA_BASELINE_V": str(
            last_spec if baseline_spec is None else baseline_spec
        ),
        "FROZEN_V": str(current_spec),
        "SPEC_ADVANCED": str(int(last_spec != current_spec)),
    }
    script = f"""set -euo pipefail
die() {{ echo "FAIL: $*" >&2; exit 1; }}
{block}
printf 'DELTA=%s\n' "${{ACTIVE_DELTA_FILES[@]}}"
"""
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, env=env,
    )


def _run_completion_transition(tmp_path, current_spec):
    """Run the exact resolver, active-range, restore, and reset composition."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    resolver = source.split(
        "# BEGIN D-113 prior-spec resolution (selftest extracts this function)\n",
        1,
    )[1].split("# END D-113 prior-spec resolution", 1)[0]
    active_range = source.split(
        "# BEGIN D-113 active-delta range (selftest extracts this block)\n",
        1,
    )[1].split("# END D-113 active-delta range", 1)[0]
    affected_helpers = source.split(
        "# BEGIN D-113 affected helpers (selftest extracts this block)\n",
        1,
    )[1].split("# END D-113 affected helpers", 1)[0]

    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True, exist_ok=True)
    for version in range(2, current_spec + 1):
        (approved / f"DELTA-v{version}.json").write_text("{}\n")
    # This boundary stub asserts the shell supplies the full skipped range;
    # validate-plan's real multi-delta union is tested separately below.
    validator = tmp_path / "scripts" / "validate-plan.py"
    validator.write_text(
        "import pathlib, sys\n"
        "names = [pathlib.Path(p).name for p in sys.argv[2:]]\n"
        f"assert names == {[f'DELTA-v{v}.json' for v in range(2, current_spec + 1)]!r}, names\n"
        "print('T1')\n"
    )
    env = {
        **os.environ,
        "STATE_DIR": str(tmp_path / ".pipeline-state"),
        "TASK_STATE": str(tmp_path / ".pipeline-state" / "tasks"),
        "BRIEF_DIR": str(tmp_path / ".pipeline-state" / "briefs"),
        "COMPLETION_LEDGER": str(tmp_path / ".pipeline-completions.json"),
        "COMPLETION_LEDGER_TOOL": str(COMPLETION_LEDGER),
        "APPROVED": str(approved),
        "FROZEN_V": str(current_spec),
    }
    script = f"""set -euo pipefail
mkdir -p "$TASK_STATE" "$BRIEF_DIR"
read_state() {{ [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" || true; }}
write_state() {{ printf '%s\n' "$2" > "$STATE_DIR/$1"; }}
set_tstat() {{ printf '%s\n' "$2" > "$TASK_STATE/$1.status"; }}
die() {{ echo "FAIL: $*" >&2; exit 1; }}
{resolver}
LAST_V=$(resolve_last_spec_version)
SPEC_ADVANCED=0
if [ "$FROZEN_V" != "$LAST_V" ]; then SPEC_ADVANCED=1; fi
DELTA_BASELINE_V="$LAST_V"
{active_range}
{affected_helpers}
compute_active_delta_scope
python3 "$COMPLETION_LEDGER_TOOL" restore --spec-version "$FROZEN_V" \
  --ledger "$COMPLETION_LEDGER" --task-state "$TASK_STATE"
if [ "$SPEC_ADVANCED" = "1" ]; then reset_active_delta_tasks; fi
write_state spec_version "$FROZEN_V"
"""
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path,
        capture_output=True, text=True, env=env,
    )


def test_completion_ledger_records_and_restores_exact_outputs(tmp_path):
    """A successful run survives state cleanup and restores task markers only
    when both the task definition and its output bytes still match."""
    _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    ledger = json.loads(
        (tmp_path / ".pipeline-completions.json").read_text()
    )
    assert set(ledger["specs"]["1"]["tasks"]) == {"T1", "T2"}

    state = tmp_path / ".pipeline-state" / "tasks"
    for path in state.iterdir():
        path.unlink()
    restored = _run_completion(tmp_path, "restore")
    assert restored.returncode == 0, (restored.stdout, restored.stderr)
    assert "restored 2 task(s)" in restored.stdout
    assert (state / "T1.status").read_text().strip() == "done"
    assert (state / "T2.status").read_text().strip() == "done"


def test_completion_ledger_rejects_stale_file_and_plan_fingerprints(tmp_path):
    """History is a cache, never an assertion: changed output bytes and changed
    task definitions both stay pending for the live acceptance loop."""
    tasks = _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    state = tmp_path / ".pipeline-state" / "tasks"
    for path in state.iterdir():
        path.unlink()

    (tmp_path / "src" / "a.py").write_text("A = 99\n")
    tasks[1]["brief"] = "changed definition"
    plan = json.loads((tmp_path / "tasks" / "plan.json").read_text())
    plan["tasks"] = tasks
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps(plan))

    restored = _run_completion(tmp_path, "restore")
    assert restored.returncode == 0, (restored.stdout, restored.stderr)
    assert "restored 0 task(s)" in restored.stdout
    assert not list(state.glob("*.status"))


def test_completion_ledger_never_overwrites_live_runtime_state(tmp_path):
    """A crash checkpoint is newer evidence than durable history. If any task
    state exists, restore must leave the whole live checkpoint untouched."""
    _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    state = tmp_path / ".pipeline-state" / "tasks"
    for path in state.iterdir():
        path.unlink()
    (state / "T1.status").write_text("pending\n")

    restored = _run_completion(tmp_path, "restore")
    assert restored.returncode == 0, (restored.stdout, restored.stderr)
    assert "live task state present" in restored.stdout
    assert (state / "T1.status").read_text() == "pending\n"
    assert not (state / "T2.status").exists()


def test_post_success_new_freeze_uses_ledger_version_for_delta_reset(tmp_path):
    """Success deletes runtime spec_version. The next freeze must recover the
    prior successful version from durable history, otherwise an affected task
    whose test body changed under the same node-id can be restored as done
    before the delta reset gets a chance to invalidate it."""
    _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    state = tmp_path / ".pipeline-state"
    for path in (state / "tasks").iterdir():
        path.unlink()

    resolved = _run_prior_spec_resolution(tmp_path, current_spec=2)
    assert resolved.returncode == 0, (resolved.stdout, resolved.stderr)
    assert "LAST_V=1" in resolved.stdout
    assert "SPEC_ADVANCED=1" in resolved.stdout


def test_prior_spec_resolution_fails_closed_on_damaged_ledger(tmp_path):
    """A corrupt durable baseline cannot silently fall back to current spec;
    that would recreate the skipped-delta-reset defect."""
    (tmp_path / ".pipeline-completions.json").write_text(
        '{"schema_version": 1, "specs": []}\n'
    )
    resolved = _run_prior_spec_resolution(tmp_path, current_spec=2)
    assert resolved.returncode != 0
    assert "ledger specs is not an object" in resolved.stderr
    assert "could not supply the prior spec version" in resolved.stderr


def test_empty_task_checkpoint_uses_ledger_not_runtime_version(tmp_path):
    """A lone runtime spec_version can survive partial state loss. With no
    task markers it must not suppress replay of the last success's deltas."""
    _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    state = tmp_path / ".pipeline-state"
    for path in (state / "tasks").iterdir():
        path.unlink()
    (state / "spec_version").write_text("2\n")

    resolved = _run_prior_spec_resolution(tmp_path, current_spec=2)
    assert resolved.returncode == 0, (resolved.stdout, resolved.stderr)
    assert "LAST_V=1" in resolved.stdout
    assert "SPEC_ADVANCED=1" in resolved.stdout


def test_active_delta_range_spans_every_freeze_since_success(tmp_path):
    resolved = _run_active_delta_resolution(
        tmp_path, last_spec=1, current_spec=3, available_versions=(2, 3)
    )
    assert resolved.returncode == 0, (resolved.stdout, resolved.stderr)
    assert "DELTA=" in resolved.stdout
    assert "DELTA-v2.json" in resolved.stdout
    assert "DELTA-v3.json" in resolved.stdout


def test_active_delta_range_fails_closed_when_history_is_missing(tmp_path):
    resolved = _run_active_delta_resolution(
        tmp_path, last_spec=1, current_spec=3, available_versions=(3,)
    )
    assert resolved.returncode != 0
    assert "missing" in resolved.stderr
    assert "DELTA-v2.json" in resolved.stderr


def test_active_delta_range_survives_same_spec_resume(tmp_path):
    """After the first reset writes runtime spec v3, retries still need the
    v1 success baseline so D-65 keeps both v2 and v3 tasks editable."""
    resolved = _run_active_delta_resolution(
        tmp_path, last_spec=3, current_spec=3,
        available_versions=(2, 3), baseline_spec=1,
    )
    assert resolved.returncode == 0, (resolved.stdout, resolved.stderr)
    assert "DELTA-v2.json" in resolved.stdout
    assert "DELTA-v3.json" in resolved.stdout


def test_success_cleanup_to_two_freezes_restores_then_resets_delta_hit(tmp_path):
    """Full D-113 composition: v1 success is cleaned, v2 changes T1 under
    the same task fingerprint, v3 is reached, exact matches restore, and the
    unioned reset returns T1—not unrelated T2—to pending."""
    _completion_fixture(tmp_path)
    recorded = _run_completion(tmp_path, "record")
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    task_state = tmp_path / ".pipeline-state" / "tasks"
    for path in task_state.iterdir():
        path.unlink()

    transitioned = _run_completion_transition(tmp_path, current_spec=3)
    assert transitioned.returncode == 0, (
        transitioned.stdout, transitioned.stderr
    )
    assert (task_state / "T1.status").read_text() == "pending\n"
    assert (task_state / "T2.status").read_text() == "done\n"
    assert (tmp_path / ".pipeline-state" / "spec_version").read_text() == "3\n"


@pytest.mark.parametrize("bad_version", ["0", "01"])
def test_completion_ledger_rejects_noncanonical_spec_versions(
    tmp_path, bad_version
):
    """Zero collides with latest's no-history sentinel and leading zeroes
    create multiple spellings for one milestone; neither is trustworthy."""
    (tmp_path / ".pipeline-completions.json").write_text(json.dumps({
        "schema_version": 1,
        "specs": {bad_version: {"tasks": {}}},
    }))
    latest = subprocess.run(
        [sys.executable, str(COMPLETION_LEDGER), "latest"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert latest.returncode != 0
    assert "invalid ledger spec version" in latest.stderr


def test_orchestrator_orders_completion_restore_and_record_safely():
    """Restore must precede delta invalidation; record must precede runtime
    cleanup; and the explicit rebuild path must bypass durable history."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    plan = source.index('echo "=== Phase: plan ==="')
    restore = source.index('"$COMPLETION_LEDGER_TOOL" restore', plan)
    delta_reset = source.index('if [ "$SPEC_ADVANCED" = "1" ]', restore)
    record = source.index('"$COMPLETION_LEDGER_TOOL" record', delta_reset)
    cleanup = source.index('rm -rf "$STATE_DIR"', record)
    assert plan < restore < delta_reset < record < cleanup
    restore_guard = source[source.rfind("if ", plan, restore):restore]
    assert "SWBP_REBUILD_FROM_SCRATCH" in restore_guard
    assert source.count("scripts/validate-plan.py --affected") == 1
    assert 'write_state delta_baseline_spec "$DELTA_BASELINE_V"' in source
    assert source.count(
        "ensure_plan\n        compute_active_delta_scope\n"
        "        reset_active_delta_tasks"
    ) == 1
    assert source.count(
        "ensure_plan\n  compute_active_delta_scope\n"
        "  reset_active_delta_tasks"
    ) == 1


# --- D-111 durable recurring-flake history ---------------------------------


def _run_flake_ledger(tmp_path, action, *args):
    return subprocess.run(
        [sys.executable, str(FLAKE_LEDGER), action,
         "--ledger", str(tmp_path / ".pipeline-flakes.json"), *args],
        cwd=tmp_path, capture_output=True, text=True,
    )


def test_flake_ledger_records_specs_idempotently_and_counts(tmp_path):
    nodeid = "tests/test_flake.py::test_a"
    for spec in ("1", "1", "2"):
        recorded = _run_flake_ledger(
            tmp_path, "record", "--spec-version", spec,
            "--nodeid", nodeid, "--isolation-passes", "1",
        )
        assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    counted = _run_flake_ledger(tmp_path, "count", "--nodeid", nodeid)
    assert counted.returncode == 0, (counted.stdout, counted.stderr)
    assert counted.stdout.strip() == "2"
    ledger = json.loads((tmp_path / ".pipeline-flakes.json").read_text())
    assert [event["spec_version"] for event in ledger["nodes"][nodeid]] == [1, 2]


def test_flake_ledger_projected_counts_spec_versions(tmp_path):
    """Verify projected counts across spec versions: absent ledger spec2 -> 1; record spec1; project spec1 -> 1; project spec2 -> 2."""
    nodeid = "tests/test_flake.py::test_a"

    projected = _run_flake_ledger(
        tmp_path, "projected-count", "--spec-version", "2",
        "--nodeid", nodeid,
    )
    assert projected.returncode == 0, (projected.stdout, projected.stderr)
    assert projected.stdout.strip() == "1"

    recorded = _run_flake_ledger(
        tmp_path, "record", "--spec-version", "1",
        "--nodeid", nodeid, "--isolation-passes", "1",
    )
    assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)

    projected1 = _run_flake_ledger(
        tmp_path, "projected-count", "--spec-version", "1",
        "--nodeid", nodeid,
    )
    assert projected1.returncode == 0, (projected1.stdout, projected1.stderr)
    assert projected1.stdout.strip() == "1"

    projected2 = _run_flake_ledger(
        tmp_path, "projected-count", "--spec-version", "2",
        "--nodeid", nodeid,
    )
    assert projected2.returncode == 0, (projected2.stdout, projected2.stderr)
    assert projected2.stdout.strip() == "2"


def test_flake_ledger_fails_closed_when_history_is_malformed(tmp_path):
    ledger = tmp_path / ".pipeline-flakes.json"
    ledger.write_text('{"schema_version": 1, "nodes": []}\n')
    counted = _run_flake_ledger(
        tmp_path, "count", "--nodeid", "tests/test_flake.py::test_a"
    )
    assert counted.returncode != 0
    assert "ledger nodes is not an object" in counted.stderr


# --- D-77 flake triage: the highest-blast-radius branch in orchestrate.sh ----
# This block is the ONLY code that converts a red frozen suite into `exit 0`
# + `[success]` commit + `rm -rf` of `.pipeline-state`; per Rule 9 (D-81,
# gate strength proportional to blast radius) it needs the same drive-*.sh
# coverage the lower-consequence rungs already have. The 2026-07-22 review
# flagged its zero-test state; these seven tests pin the five untested
# behaviors from that finding:
#   (a) one mapped node among many unmapped keeps the DRIFT path
#   (b) COLLECTION_ERROR bypasses the flake path entirely
#   (c) FAILING/FAIL_DETAIL survive the isolation loop's run_tests clobber
#       (both when isolation ran, and when it never entered)
#   (d) the fbfc1f0 budget-skip emits skip evidence instead of dying
#   (e) the flake path builds FLAKE_NOTE for the [success] block downstream
# D-100 adds the minimum mechanical flake signal: every failing carried node
# must pass at least one isolation run; 0/2 and budget-skipped isolation stay
# red. The 2/2 threshold remains deliberately rejected.

DRIVE_DRIFT = SCRIPTS / "selftest" / "drive-drift.sh"

FLAKE_PLAN = {
    "version": 1,
    "erd_version": 1,
    "tasks": [
        {"id": "T1", "file": "src/a.py", "brief": "atomic delta work",
         "depends_on": [], "contracts": [],
         "tests": ["tests/test_delta.py::test_new"]},
    ],
}


def run_drive_drift(tmp_path, *, tests_rc=1, failing="", fail_detail="",
                    rt_outcomes="", swbp_elapsed=0, swbp_budget=0,
                    frozen_v=3, plan=None):
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "tasks" / "plan.json").write_text(
        json.dumps(plan if plan is not None else FLAKE_PLAN))
    env = {**os.environ,
           "TESTS_RC": str(tests_rc),
           "FAILING": failing,
           "FAIL_DETAIL": fail_detail,
           "RT_OUTCOMES": rt_outcomes,
           "SWBP_ELAPSED": str(swbp_elapsed),
           "SWBP_RUN_BUDGET": str(swbp_budget),
           "FROZEN_V": str(frozen_v)}
    return subprocess.run(
        ["bash", str(DRIVE_DRIFT), str(tmp_path)],
        capture_output=True, text=True, env=env,
    )


def _kv(stdout, key):
    """Extract the harness's `KEY=value` line."""
    for line in stdout.splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:]
    return None


def test_flake_all_unmapped_flips_red_to_green(tmp_path):
    """Every failure is a carried-forward, plan-unmapped node -> the block
    treats the suite as flake-green: TESTS_RC flipped 0, FLAKE_NOTE populated,
    WARNING printed. This is the one branch that overrides a red suite."""
    r = run_drive_drift(
        tmp_path, failing="tests/test_flake.py::test_a",
        rt_outcomes="0:0",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "0"
    assert "WARNING (D-77)" in r.stdout
    assert _kv(r.stdout, "FLAKE_NOTE").startswith("WARNING (D-77)")
    assert "2/2 isolated passes" in r.stdout
    assert _kv(r.stdout, "RT_CALLS") == "2"


def test_flake_reproducing_twice_keeps_drift(tmp_path):
    """An unmapped failure that reproduces in both isolation runs is not
    mechanically demonstrated to be a flake. Keep the frozen suite red."""
    r = run_drive_drift(
        tmp_path, failing="tests/test_flake.py::test_a",
        rt_outcomes="1:1",   # both isolation retries fail
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "1"
    assert "0/2 isolated passes" in r.stdout
    assert _kv(r.stdout, "FLAKE_NOTE") == ""


def test_flake_one_isolated_pass_allows_flake_green(tmp_path):
    """The D-77 compromise: plan-unmapped plus at least one isolated pass
    provides mechanical flake evidence without demanding deterministic 2/2."""
    r = run_drive_drift(
        tmp_path, failing="tests/test_flake.py::test_a",
        rt_outcomes="1:0",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "0"
    assert "1/2 isolated passes" in r.stdout
    assert _kv(r.stdout, "FLAKE_NOTE").startswith("WARNING (D-77)")


def test_flake_recurring_threshold_keeps_suite_red_for_escalation(tmp_path):
    """Two prior accepted occurrences plus this isolated-pass occurrence hit
    the default threshold of three. The bypass closes and the existing drift
    ladder receives a red suite with explicit recurring-flake evidence."""
    nodeid = "tests/test_flake.py::test_a"
    for spec in ("1", "2"):
        recorded = _run_flake_ledger(
            tmp_path, "record", "--spec-version", spec,
            "--nodeid", nodeid, "--isolation-passes", "1",
        )
        assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    r = run_drive_drift(
        tmp_path, failing=nodeid, rt_outcomes="1:0",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "1"
    assert "recurring flake threshold reached" in r.stdout
    assert _kv(r.stdout, "FLAKE_NOTE") == ""


def test_flake_same_spec_rerun_does_not_reach_recurring_threshold(tmp_path):
    """Same-spec idempotency: re-recording the same spec versions for a nodeid
    does not increment the occurrence count toward the recurring threshold."""
    nodeid = "tests/test_flake.py::test_a"
    for spec in ("1", "2"):
        recorded = _run_flake_ledger(
            tmp_path, "record", "--spec-version", spec,
            "--nodeid", nodeid, "--isolation-passes", "1",
        )
        assert recorded.returncode == 0, (recorded.stdout, recorded.stderr)
    r = run_drive_drift(
        tmp_path, failing=nodeid, rt_outcomes="1:0", frozen_v=2,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "0"
    assert _kv(r.stdout, "RECURRING_FLAKE") == "0"
    assert "recurring flake threshold reached" not in r.stdout


def test_recurring_flake_bypasses_em_and_routes_to_tpm_bundle():
    """Once history mechanically proves a chronic frozen-oracle defect, the
    shell packages it before the generic EM drift-consult branch."""
    source = (SCRIPTS / "orchestrate.sh").read_text()
    drift = source.index("drift_evidence=")
    recurring = source.index('if [ "$RECURRING_FLAKE" = "1" ]', drift)
    em_consult = source.index('consult_em "DRIFT"', recurring)
    block = source[recurring:em_consult]
    assert 'package_escalation "recurring-flake" "DRIFT"' in block
    assert "finalize_batch" in block


def test_flake_one_mapped_among_many_keeps_drift(tmp_path):
    """A single delta-mapped failing node — even alongside many unmapped
    ones — is real signal, not a flake candidate. The all_carried loop
    breaks on the first mapped hit, the DRIFT path is preserved, and
    isolation runs must NEVER fire (they would waste budget on a
    known-drift case)."""
    r = run_drive_drift(
        tmp_path,
        failing="tests/test_flake.py::test_a|tests/test_delta.py::test_new",
        rt_outcomes="",   # must not be consumed — a call would go BAD
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "1"    # DRIFT preserved
    assert _kv(r.stdout, "FLAKE_NOTE") == ""
    assert _kv(r.stdout, "RT_CALLS") == "0"          # no isolation runs


def test_flake_collection_error_bypasses_the_whole_block(tmp_path):
    """A pytest collection error means we cannot even enumerate failures —
    treating it as a flake would silently swallow syntax breakage in the
    test suite. The block's guard bans COLLECTION_ERROR outright: the
    whole flake branch is skipped, DRIFT stands, no isolation runs fire."""
    r = run_drive_drift(
        tmp_path,
        failing="COLLECTION_ERROR (see .cache/test-report.json)",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "1"
    assert _kv(r.stdout, "FLAKE_NOTE") == ""
    assert _kv(r.stdout, "RT_CALLS") == "0"
    assert "WARNING (D-77)" not in r.stdout


def test_flake_budget_skip_keeps_drift_without_evidence(tmp_path):
    """If isolation cannot run, no mechanical flake evidence exists. Record
    the budget skip and keep the original frozen-suite failure red."""
    r = run_drive_drift(
        tmp_path,
        failing="tests/test_flake.py::test_a|tests/test_flake.py::test_b",
        rt_outcomes="",   # must not be consumed
        swbp_elapsed=2000, swbp_budget=1000,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "1"
    assert "isolation runs skipped — over SWBP_RUN_BUDGET" in r.stdout
    assert _kv(r.stdout, "RT_CALLS") == "0"
    assert _kv(r.stdout, "FLAKE_NOTE") == ""


def test_flake_failing_and_detail_survive_isolation_clobber(tmp_path):
    """The real run_tests clobbers FAILING/FAIL_DETAIL on every call. The
    block saves them before the isolation loop and restores after, so the
    downstream DRIFT/[success] paths see the original evidence. Without
    the restore, the DRIFT message would name only the LAST isolated
    node-id and its detail would be empty. This test enters the isolation
    loop (all unmapped) and asserts the restore fired."""
    r = run_drive_drift(
        tmp_path, failing="tests/test_flake.py::test_a",
        fail_detail="original detail preserved across isolation",
        rt_outcomes="0:0",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_FAILING") == "tests/test_flake.py::test_a"
    assert _kv(r.stdout, "FINAL_FAIL_DETAIL") == \
        "original detail preserved across isolation"


def test_flake_failing_and_detail_untouched_when_isolation_never_ran(tmp_path):
    """When a mapped node short-circuits the flake path, the save/restore
    dance is never reached — but nothing else touches FAILING/FAIL_DETAIL
    either (RT_CALLS=0 above proves it), so the values arrive at the DRIFT
    handler unmodified. This is the symmetric pin to the isolation-ran
    case above: same guarantee, different code path."""
    r = run_drive_drift(
        tmp_path,
        failing="tests/test_flake.py::test_a|tests/test_delta.py::test_new",
        fail_detail="original detail",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_FAILING") == \
        "tests/test_flake.py::test_a|tests/test_delta.py::test_new"
    assert _kv(r.stdout, "FINAL_FAIL_DETAIL") == "original detail"


# --- check_ci_health: D-85, the external verdict -----------------------------
# CI is the only check running outside this pipeline's own gates, so it is the
# only thing that catches what the gates structurally cannot (types, lint,
# packaging). Nothing consumed its verdict until D-85: testchat ran RED for 7
# days / 46 runs on one mypy error and shipped `[success] spec v56` during the
# blackout (2026-07-24). These tests pin the verdict mapping, which is the part
# of a CI-health gate that goes wrong: green passes, red halts, and every
# "cannot tell" path says INCONCLUSIVE and proceeds rather than implying green
# (Rule 4 / Rule 6 — an unobtainable answer is not a passing answer).

DRIVE_CI = SCRIPTS / "selftest" / "drive-ci.sh"


def run_drive_ci(tmp_path, *, runs=None, gh_rc=0, no_gh=False,
                 no_remote=False, detached=False, env=None):
    if runs is not None:
        (tmp_path / "gh-output").write_text(json.dumps(runs))
    if gh_rc:
        (tmp_path / "gh-rc").write_text(str(gh_rc))
    for flag, on in (("no-gh", no_gh), ("no-remote", no_remote),
                     ("detached", detached)):
        if on:
            (tmp_path / flag).touch()
    return subprocess.run(
        ["bash", str(DRIVE_CI), str(tmp_path)],
        capture_output=True, text=True, env={**os.environ, **(env or {})},
    )


def _run(name, conclusion, status="completed"):
    return {"workflowName": name, "conclusion": conclusion, "status": status}


def test_ci_green_passes(tmp_path):
    r = run_drive_ci(tmp_path, runs=[_run("CI", "success")])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "RC=0" in r.stdout
    assert "green" in r.stdout


def test_ci_red_halts_the_run(tmp_path):
    """THE pin. A completed failing workflow must die before any model call —
    pre-D-85 behavior was to proceed, which is how a [success] shipped on a
    red build for seven days."""
    r = run_drive_ci(tmp_path, runs=[_run("CI", "failure")])
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "RC=" not in r.stdout          # die fired; the caller never resumed
    assert "CI is RED" in r.stderr
    assert "SWBP_SKIP_CI_CHECK=1" in r.stderr   # the escape hatch is named


def test_ci_red_not_masked_by_newer_green_sibling_workflow(tmp_path):
    """gh returns newest-first across ALL workflows. Checking only the single
    newest run would let a green check-drift (which runs on every push and
    finishes in ~8s) mask a red CI — precisely the blackout D-85 exists to
    prevent. The newest run of EACH workflow is what counts."""
    r = run_drive_ci(tmp_path, runs=[
        _run("check-drift", "success"),   # newer, green
        _run("CI", "failure"),            # older, red — must still halt
    ])
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "CI is RED" in r.stderr
    assert "CI" in r.stderr


def test_ci_stale_red_superseded_by_newer_green_same_workflow(tmp_path):
    """The converse: a workflow that failed and was then re-run green is
    green. Only the newest run per workflow is consulted, so an old red must
    not halt a fixed build."""
    r = run_drive_ci(tmp_path, runs=[
        _run("CI", "success"),   # newest
        _run("CI", "failure"),   # the earlier failure, already fixed
    ])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "RC=0" in r.stdout


def test_ci_pending_is_not_a_failure(tmp_path):
    """A run still in flight is unknown, not red — halting on it would block
    every push-then-run sequence."""
    r = run_drive_ci(tmp_path, runs=[_run("CI", None, status="in_progress")])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "in flight" in r.stdout


def test_ci_no_runs_yet_proceeds(tmp_path):
    r = run_drive_ci(tmp_path, runs=[])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "no CI runs" in r.stdout


def test_ci_no_remote_skips(tmp_path):
    """The 2026-07-14 meta-rule: a gate that lives only in CI does not exist
    until a remote does. A child with no remote must not be blocked."""
    r = run_drive_ci(tmp_path, no_remote=True, runs=[_run("CI", "failure")])
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "no 'origin' remote" in r.stdout


def test_ci_missing_gh_is_inconclusive_not_green(tmp_path):
    """Rule 4: a check that did not run must SAY so. The wording must not
    imply the build is green."""
    r = run_drive_ci(tmp_path, no_gh=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "INCONCLUSIVE" in r.stdout
    assert "not installed" in r.stdout
    assert "green" not in r.stdout


def test_ci_gh_failure_is_inconclusive_not_green(tmp_path):
    """Unauthenticated / offline gh exits nonzero and writes its complaint to
    stderr, leaving stdout EMPTY — so no runs are supplied here. (Scripting a
    failing gh that also emits valid JSON on stdout is not a real state; the
    function would then have real data and rightly act on it.) Same contract:
    inconclusive and proceed, never a silent pass presented as green."""
    r = run_drive_ci(tmp_path, gh_rc=1)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "INCONCLUSIVE" in r.stdout
    assert "green" not in r.stdout


def test_ci_override_skips_even_a_red_build(tmp_path):
    """Running the pipeline is often exactly how a red CI gets fixed; a gate
    with no override there is a deadlock, not a safeguard."""
    r = run_drive_ci(tmp_path, runs=[_run("CI", "failure")],
                     env={"SWBP_SKIP_CI_CHECK": "1"})
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "SKIPPED" in r.stdout
    assert "RC=0" in r.stdout


# --- refreeze oracle confinement --------------------------------------------
# Collection is confined to tests/, staged files are content-classified, and
# generated tests execute only through the Linux sandbox. The fixture uses a
# local sandbox adapter so this behavior stays testable without containers;
# production has no host fallback.


@pytest.fixture()
def freezable_repo(tmp_path):
    """A repo complete enough for refreeze.sh to run the FULL apply path:
    a prior freeze v1 (VERSION, contracts, node-ids, manifest), one carried
    test, and staging holding one new test file. The staged test is
    parametrized AND trivially passing on purpose: AST sees one id where
    pytest collection expands two (the collection pin), and D-75 must run
    it and fire the already-passing warning (the red-check pin)."""
    approved = tmp_path / "scripts" / ".approved"
    (approved / "incoming" / "tests").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    for name in (
        "refreeze.sh",
        "check-test-surface.py",
        "spec_artifacts.py",
        "check-spec-delta.py",
    ):
        target = tmp_path / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
        if name.endswith(".sh"):
            target.chmod(0o755)
    sandbox = tmp_path / "scripts" / "sandbox-run.sh"
    sandbox.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  case \"$1\" in --rw) shift 2 ;; --) shift; break ;; *) break ;; esac\n"
        "done\n"
        "exec \"$@\"\n"
    )
    sandbox.chmod(0o755)
    (approved / "VERSION").write_text("1\n")
    (approved / "contracts.json").write_text(json.dumps({
        "files": ["src/app.py"], "entry_points": [], "routes": [],
        "schemas": [], "errors": [], "erd_version": 1,
    }))
    (tmp_path / "tests" / "test_carried.py").write_text(
        "def test_carried():\n    assert True\n")
    (approved / "test-nodeids").write_text(
        "tests/test_carried.py::test_carried\n")
    # regenerated by refreeze; any content satisfies the pre-apply phase
    (approved / "frozen-manifest").write_text("")
    (approved / "ERD-DELTA.md").write_text("# Previous milestone\n")
    (approved / "incoming" / "tests" / "test_delta.py").write_text(
        "import pytest\n"
        "\n"
        "\n"
        '@pytest.mark.parametrize("x", ["a", "b"])\n'
        "def test_param(x):\n"
        "    assert True\n"
    )
    (approved / "incoming" / "ERD-DELTA.md").write_text(VALID_ERD_DELTA)
    _init_git(tmp_path)
    # refreeze's own `git commit -m "[refreeze vN]"` needs repo identity
    subprocess.run(["git", "config", "user.email", "t@t"],
                   cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"],
                   cwd=tmp_path, check=True)
    return tmp_path


def _run_refreeze_approve(repo):
    """--diff to get the hash, then --approve <hash>: the D-42 agent flow,
    which is the only non-interactive way through the apply path."""
    d = subprocess.run(
        ["bash", "scripts/refreeze.sh", "--diff", "scripts/.approved/incoming"],
        cwd=repo, capture_output=True, text=True,
    )
    assert d.returncode == 0, (d.stdout, d.stderr)
    m = re.search(r"DIFF-SHA: ([0-9a-f]{64})", d.stdout)
    assert m, d.stdout
    return subprocess.run(
        ["bash", "scripts/refreeze.sh", "--approve", m.group(1),
         "scripts/.approved/incoming"],
        cwd=repo, capture_output=True, text=True,
    )


def test_refreeze_collection_is_sandboxed_and_confined(freezable_repo):
    """Parametrized ids expand in the sandbox, while a test-shaped archive
    outside tests/ can never enter the frozen oracle."""
    decoy = freezable_repo / "project-trail" / "old" / "tests"
    decoy.mkdir(parents=True)
    (decoy / "test_decoy.py").write_text(
        "def test_must_not_be_collected():\n    assert True\n")
    r = _run_refreeze_approve(freezable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "via sandbox" in r.stdout, r.stdout
    frozen = (freezable_repo / "scripts" / ".approved" / "test-nodeids").read_text()
    assert "tests/test_delta.py::test_param[a]" in frozen, frozen
    assert "tests/test_delta.py::test_param[b]" in frozen, frozen
    assert "test_must_not_be_collected" not in frozen, frozen


def test_refreeze_redcheck_runs_only_in_sandbox(freezable_repo):
    """The red check is conclusive through the sandbox and has no host arm."""
    r = _run_refreeze_approve(freezable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "red-check ran via: sandbox" in r.stdout, r.stdout
    assert "INCONCLUSIVE" not in r.stdout, r.stdout
    assert "ALREADY PASS" in r.stdout, r.stdout
    assert "test_param" in r.stdout, r.stdout


def test_refreeze_identical_staged_test_does_not_widen_delta(freezable_repo):
    """A byte-identical carried test in a whole-suite return is not changed."""
    incoming = freezable_repo / "scripts" / ".approved" / "incoming" / "tests"
    (incoming / "test_carried.py").write_bytes(
        (freezable_repo / "tests" / "test_carried.py").read_bytes())
    r = _run_refreeze_approve(freezable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    delta = json.loads((freezable_repo / "scripts" / ".approved"
                        / "DELTA-v2.json").read_text())
    assert not any("test_carried" in node for node in delta["changed_tests"])


# --- refreeze.sh D-95 auto mode (retires the ceremonial y/N) -----------------
# The pre-D-95 default prompted the CEO for y/N after every mechanical
# preflight had already passed — the material verdict was the gates
# green, and the extra keystroke rubber-stamped 5 straight testchat
# refreezes (v60–v64). D-95 makes auto the default: on preflight-green
# the freeze applies, printing an audit line with the DIFF-SHA; on ANY
# preflight failure the script still `die`s with the specific finding.
# The interactive path is preserved as an opt-in flag.


def test_refreeze_auto_proceeds_without_terminal(freezable_repo):
    """No flags, no tty (subprocess pipes stdin) — auto mode applies the
    freeze and prints the D-95 audit line. Pre-D-95 this would have died
    at the `[ -t 0 ]` check demanding a terminal for the y/N prompt."""
    r = subprocess.run(
        ["bash", "scripts/refreeze.sh", "scripts/.approved/incoming"],
        cwd=freezable_repo, capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "auto-approved (D-95)" in r.stdout, r.stdout
    assert "DIFF-SHA" in r.stdout, r.stdout
    # No y/N prompt reached the user (the string the old interactive path printed).
    assert "Approve this delta" not in r.stdout, r.stdout
    # The freeze commit landed — this is a real apply, not a dry-run.
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=freezable_repo, capture_output=True, text=True, check=True,
    )
    assert log.stdout.strip() == "[refreeze v2]", log.stdout


def test_refreeze_auto_halts_on_preflight_fail(stageable_repo):
    """A v51-shaped delta (route without an implementing file) MUST die at
    D-78 in auto mode — auto is not "proceed regardless," it's "proceed
    when every gate is green." The audit line must NOT print."""
    repo = stageable_repo
    refreeze_scripts(repo)
    (repo / "src" / "api").mkdir(parents=True)
    (repo / "src" / "api" / "models.py").write_text(V51_SRC)
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(V51_OLD))
    (repo / "scripts" / ".approved" / "incoming" / "contracts.json").write_text(
        json.dumps(v51_new(["src/api/chat.py"])))
    r = subprocess.run(
        ["bash", "scripts/refreeze.sh", "scripts/.approved/incoming"],
        cwd=repo, capture_output=True, text=True,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "D-78" in combined, combined
    assert "auto-approved" not in combined, combined


def test_refreeze_interactive_flag_requires_terminal(freezable_repo):
    """--interactive is the opt-in eyeball path — under subprocess (no tty)
    it must die with a message pointing back to the D-95 auto default and
    the D-42 explicit flow. Preserves the escape hatch without silently
    degrading to auto when the user asked for interactive."""
    r = subprocess.run(
        ["bash", "scripts/refreeze.sh", "--interactive",
         "scripts/.approved/incoming"],
        cwd=freezable_repo, capture_output=True, text=True,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "--interactive" in combined, combined
    assert "D-95" in combined, combined


# --- subtree re-plan: --subtree-scope / --merge-subtree (Fix A) --------------
# On a re-freeze the EM used to re-emit the ENTIRE plan — O(inventory) cost
# for an O(delta) change (testchat M31: 282s = 68% of the run, re-emitting
# 19,572 chars for a 3-task delta). Fix A: the shell computes the delta's
# scope against the prior validated plan, the EM emits only that subtree,
# the shell merges, and the full validate() gate judges the merged artifact
# unchanged — the D-64 bijection is a property of the artifact, not of who
# authored which part. Id discipline is rejected, never repaired: silent
# renumbering would make depends_on references ambiguous.

SUB_CONTRACTS = {
    "files": ["src/a.py", "src/b.py", "src/c.py"],   # c is NEW at v2
    "entry_points": [],
    "routes": [],
    "erd_version": 2,
}
SUB_NODEIDS = [
    "tests/test_a.py::test_one",
    "tests/test_b.py::test_two",
    "tests/test_b.py::test_three",                    # new at v2
    "tests/test_c.py::test_four",                     # new at v2
]
SUB_PRIOR = {
    "version": 3,
    "erd_version": 1,
    "tasks": [
        {"id": "T1", "file": "src/a.py", "depends_on": [],
         "brief": "build a", "contracts": [],
         "tests": ["tests/test_a.py::test_one"]},
        {"id": "T2", "file": "src/b.py", "depends_on": ["T1"],
         "brief": "build b", "contracts": [],
         "tests": ["tests/test_b.py::test_two"]},
    ],
}
SUB_DELTA = {
    "changed_contract_ids": [],
    "changed_tests": ["tests/test_b.py::test_two",
                      "tests/test_b.py::test_three",
                      "tests/test_c.py::test_four"],
    "changed_files": ["src/b.py"],
}
SUB_GOOD_REPLY = {
    "version": 1,
    "erd_version": 2,
    "tasks": [
        {"id": "T2", "file": "src/b.py", "depends_on": ["T1"],
         "brief": "rebuild b", "contracts": [],
         "tests": ["tests/test_b.py::test_two",
                   "tests/test_b.py::test_three"]},
        {"id": "T3", "file": "src/c.py", "depends_on": ["T2"],
         "brief": "build c", "contracts": [],
         "tests": ["tests/test_c.py::test_four"]},
    ],
}


@pytest.fixture()
def subtree_repo(tmp_path):
    """Spec frozen at v2 with a still-on-disk plan validated against v1 —
    the exact state ensure_plan sees right after a re-freeze."""
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "contracts.json").write_text(json.dumps(SUB_CONTRACTS))
    (approved / "test-nodeids").write_text("\n".join(SUB_NODEIDS) + "\n")
    (approved / "VERSION").write_text("2\n")
    (approved / "DELTA-v2.json").write_text(json.dumps(SUB_DELTA))
    (tmp_path / "tasks").mkdir()
    (tmp_path / ".pipeline-state").mkdir()
    (tmp_path / ".pipeline-state" / "plan-prior.json").write_text(
        json.dumps(SUB_PRIOR))
    return tmp_path


def run_scope(repo, *deltas):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--subtree-scope",
         ".pipeline-state/plan-prior.json", *deltas],
        cwd=repo, capture_output=True, text=True,
    )


def run_affected(repo, *deltas):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--affected", *deltas],
        cwd=repo, capture_output=True, text=True,
    )


def _scoped(repo, *deltas):
    """Run --subtree-scope and stage its output where the merge reads it,
    exactly as orchestrate.sh does."""
    r = run_scope(repo, *(deltas or ("scripts/.approved/DELTA-v2.json",)))
    assert r.returncode == 0, (r.stdout, r.stderr)
    (repo / ".pipeline-state" / "subtree-scope.json").write_text(r.stdout)
    return json.loads(r.stdout)


def run_merge(repo, subtree):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--merge-subtree",
         ".pipeline-state/plan-prior.json", subtree,
         ".pipeline-state/subtree-scope.json"],
        cwd=repo, capture_output=True, text=True,
    )


def test_subtree_scope_computes_delta(subtree_repo):
    """Direct hit via changed_files, a new inventory file, and the map list
    = still-current changed tests ∪ everything the re-emitted task had."""
    s = _scoped(subtree_repo)
    assert s["reemit"] == [{"file": "src/b.py", "keep_id": "T2"}]
    assert s["new_files"] == ["src/c.py"]
    assert set(s["map_nodeids"]) == {
        "tests/test_b.py::test_two", "tests/test_b.py::test_three",
        "tests/test_c.py::test_four"}
    assert s["carried"] == [{"id": "T1", "file": "src/a.py", "depends_on": []}]
    assert s["em_needed"] is True


def test_subtree_scope_transitive_dependents(subtree_repo):
    """A delta hitting T1 drags its dependent T2 into the re-emit set —
    same closure rule cmd_affected applies to task-state resets."""
    (subtree_repo / "d.json").write_text(json.dumps(
        {"changed_contract_ids": [], "changed_tests": [],
         "changed_files": ["src/a.py"]}))
    s = json.loads(run_scope(subtree_repo, "d.json").stdout)
    assert {e["keep_id"] for e in s["reemit"]} == {"T1", "T2"}
    assert s["carried"] == []


def test_affected_unions_every_delta_since_last_success(subtree_repo):
    """A run can skip more than one freeze. Reset/edit scope must include a
    task hit only by an intermediate delta as well as the newest delta."""
    current_plan = {
        "version": 4,
        "erd_version": 2,
        "tasks": [
            *SUB_PRIOR["tasks"],
            {"id": "T3", "file": "src/c.py", "depends_on": [],
             "brief": "build c", "contracts": [],
             "tests": ["tests/test_c.py::test_four"]},
        ],
    }
    (subtree_repo / "tasks" / "plan.json").write_text(
        json.dumps(current_plan)
    )
    (subtree_repo / "v2.json").write_text(json.dumps({
        "changed_contract_ids": [], "changed_tests": [],
        "changed_files": ["src/a.py"],
    }))
    (subtree_repo / "v3.json").write_text(json.dumps({
        "changed_contract_ids": [], "changed_tests": [],
        "changed_files": ["src/c.py"],
    }))
    affected = run_affected(subtree_repo, "v2.json", "v3.json")
    assert affected.returncode == 0, (affected.stdout, affected.stderr)
    assert set(affected.stdout.split()) == {"T1", "T2", "T3"}


def test_subtree_scope_refuses_inventory_removal(subtree_repo):
    """A file leaving the inventory can invalidate carried briefs and
    dependencies in ways no subtree can express — full emission."""
    c = dict(SUB_CONTRACTS, files=["src/b.py", "src/c.py"])
    (subtree_repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(c))
    r = run_scope(subtree_repo, "scripts/.approved/DELTA-v2.json")
    assert r.returncode == 1
    assert "left the inventory" in r.stderr, r.stderr


def test_subtree_scope_refuses_unhomeable_mappings(subtree_repo):
    """A changed current test with NO file re-planned would need its
    mapping to land on a carried task — a subtree reply cannot express
    that; refuse so the caller re-plans in full."""
    c = dict(SUB_CONTRACTS, files=["src/a.py", "src/b.py"])
    (subtree_repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(c))
    (subtree_repo / "d.json").write_text(json.dumps(
        {"changed_contract_ids": [],
         "changed_tests": ["tests/test_b.py::test_three"],
         "changed_files": []}))
    r = run_scope(subtree_repo, "d.json")
    assert r.returncode == 1
    assert "re-plans no file" in r.stderr, r.stderr


def test_subtree_scope_docs_only_em_not_needed(subtree_repo):
    """A delta that invalidates nothing (docs-only re-freeze) yields an
    empty scope with em_needed=False — the D-86 empty-delta class gets a
    zero-EM-call path instead of a full re-emission."""
    c = dict(SUB_CONTRACTS, files=["src/a.py", "src/b.py"])
    (subtree_repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(c))
    (subtree_repo / "d.json").write_text(json.dumps(
        {"changed_contract_ids": [], "changed_tests": [],
         "changed_files": []}))
    s = json.loads(run_scope(subtree_repo, "d.json").stdout)
    assert s["reemit"] == [] and s["new_files"] == []
    assert s["map_nodeids"] == []
    assert s["em_needed"] is False


def test_merge_subtree_produces_fully_valid_plan(subtree_repo):
    """THE Fix A property: carried tasks verbatim + EM subtree, and the
    merged artifact passes the FULL validate() gate unchanged — bijection,
    mapping, DAG — proving the gate never weakened."""
    _scoped(subtree_repo)
    (subtree_repo / "tasks" / "plan-subtree.json").write_text(
        json.dumps(SUB_GOOD_REPLY))
    r = run_merge(subtree_repo, "tasks/plan-subtree.json")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "1 carried + 2 subtree" in r.stdout, r.stdout
    v = subprocess.run([sys.executable, str(VALIDATE_PLAN)],
                       cwd=subtree_repo, capture_output=True, text=True)
    assert v.returncode == 0, (v.stdout, v.stderr)
    merged = json.loads((subtree_repo / "tasks" / "plan.json").read_text())
    assert merged["erd_version"] == 2
    assert merged["version"] == 4                     # prior 3, shell-bumped
    by_id = {t["id"]: t for t in merged["tasks"]}
    assert by_id["T1"]["brief"] == "build a"          # carried byte-identical
    assert by_id["T2"]["brief"] == "rebuild b"
    assert set(by_id) == {"T1", "T2", "T3"}


def test_merge_rejects_wrong_keep_id(subtree_repo):
    """A re-planned file under a different id would dangle every carried
    depends_on reference — rejected with the id named, never renumbered."""
    _scoped(subtree_repo)
    bad = json.loads(json.dumps(SUB_GOOD_REPLY))
    bad["tasks"][0]["id"] = "T9"
    (subtree_repo / "tasks" / "plan-subtree.json").write_text(json.dumps(bad))
    r = run_merge(subtree_repo, "tasks/plan-subtree.json")
    assert r.returncode == 1
    assert "must keep the carried plan's id T2" in r.stderr, r.stderr


def test_merge_rejects_new_file_id_collision(subtree_repo):
    """A new-file task reusing a carried id would make its references
    ambiguous (carried T1 or this task?) — rejected, never repaired."""
    _scoped(subtree_repo)
    bad = json.loads(json.dumps(SUB_GOOD_REPLY))
    bad["tasks"][1]["id"] = "T1"
    bad["tasks"][1]["depends_on"] = ["T2"]
    (subtree_repo / "tasks" / "plan-subtree.json").write_text(json.dumps(bad))
    r = run_merge(subtree_repo, "tasks/plan-subtree.json")
    assert r.returncode == 1
    assert "collides with a carried task id" in r.stderr, r.stderr


def test_merge_rejects_overreach_and_omission(subtree_repo):
    """The subtree must cover the scope exactly: a task outside it is
    overreach (the D-65 no-edit philosophy applied to planning), a scope
    file without a task is an incomplete reply. Both are named."""
    _scoped(subtree_repo)
    over = json.loads(json.dumps(SUB_GOOD_REPLY))
    over["tasks"].append({"id": "T4", "file": "src/z.py", "depends_on": [],
                          "brief": "sneak", "contracts": [], "tests": []})
    (subtree_repo / "tasks" / "plan-subtree.json").write_text(json.dumps(over))
    r = run_merge(subtree_repo, "tasks/plan-subtree.json")
    assert r.returncode == 1
    assert "outside the delta scope" in r.stderr and "src/z.py" in r.stderr

    short = json.loads(json.dumps(SUB_GOOD_REPLY))
    del short["tasks"][1]                             # no task for new src/c.py
    (subtree_repo / "tasks" / "plan-subtree.json").write_text(json.dumps(short))
    r = run_merge(subtree_repo, "tasks/plan-subtree.json")
    assert r.returncode == 1
    assert "missing task(s)" in r.stderr and "src/c.py" in r.stderr


def test_merge_empty_subtree_docs_only(subtree_repo):
    """'-' merge: carried tasks only, versions stamped, defensively
    stripped stale mappings — and the result passes the full gate."""
    c = dict(SUB_CONTRACTS, files=["src/a.py", "src/b.py"])
    (subtree_repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(c))
    prior = json.loads(json.dumps(SUB_PRIOR))
    prior["tasks"][0]["tests"].append("tests/test_gone.py::test_gone")
    (subtree_repo / ".pipeline-state" / "plan-prior.json").write_text(
        json.dumps(prior))
    (subtree_repo / "d.json").write_text(json.dumps(
        {"changed_contract_ids": [], "changed_tests": [],
         "changed_files": []}))
    _scoped(subtree_repo, "d.json")
    r = run_merge(subtree_repo, "-")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "2 carried + 0 subtree" in r.stdout, r.stdout
    merged = json.loads((subtree_repo / "tasks" / "plan.json").read_text())
    assert merged["erd_version"] == 2 and merged["version"] == 4
    by_id = {t["id"]: t for t in merged["tasks"]}
    assert by_id["T1"]["tests"] == ["tests/test_a.py::test_one"]  # stale gone
    v = subprocess.run([sys.executable, str(VALIDATE_PLAN)],
                       cwd=subtree_repo, capture_output=True, text=True)
    assert v.returncode == 0, (v.stdout, v.stderr)


# --- ensure_plan drives the subtree path end-to-end (bash, drive-plan.sh) ----

def test_plan_subtree_replan_one_em_call(tmp_path):
    """Fix A through the REAL ensure_plan: a re-freeze with a valid prior
    plan takes ONE subtree EM call whose prompt is the delta instruction
    (carried briefs deliberately absent), the merge lands, the full gate
    passes, carried briefs survive byte-identical, temps are cleaned."""
    work = plan_workdir(tmp_path, dict(SUB_CONTRACTS),
                        [json.dumps(SUB_GOOD_REPLY)])
    (work / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(SUB_NODEIDS) + "\n")
    (work / "scripts" / ".approved" / "DELTA-v2.json").write_text(
        json.dumps(SUB_DELTA))
    (work / "tasks").mkdir()
    (work / "tasks" / "plan.json").write_text(json.dumps(SUB_PRIOR))
    r = run_drive_plan(work)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "subtree re-plan armed" in r.stdout, r.stdout
    assert (work / ".calls").read_text().strip() == "1", r.stdout
    prompt = (work / "prompts" / "1").read_text()
    assert "Delta re-plan" in prompt
    assert "src/b.py (keep id T2)" in prompt
    assert "src/c.py (new file)" in prompt
    assert "build a" not in prompt        # carried briefs stay out of the call
    assert "Playwright-importing test file" in prompt
    assert "MERGED plan (D-64)" in prompt
    assert "empty contracts array" in prompt
    assert "command not found" not in r.stderr
    merged = json.loads((work / "tasks" / "plan.json").read_text())
    assert merged["erd_version"] == 2 and merged["version"] == 4
    by_id = {t["id"]: t for t in merged["tasks"]}
    assert by_id["T1"]["brief"] == "build a"
    assert by_id["T2"]["brief"] == "rebuild b"
    assert not (work / ".pipeline-state" / "plan-prior.json").exists()
    assert not (work / "tasks" / "plan-subtree.json").exists()


def test_plan_docs_only_delta_zero_em_calls(tmp_path):
    """A delta invalidating nothing merges the carried plan mechanically:
    ZERO EM calls, no plan-revision budget consumed, gate green."""
    contracts = dict(SUB_CONTRACTS, files=["src/a.py", "src/b.py"])
    work = plan_workdir(tmp_path, contracts, ["SHOULD-NEVER-BE-CALLED"])
    (work / "scripts" / ".approved" / "DELTA-v2.json").write_text(json.dumps(
        {"changed_contract_ids": [], "changed_tests": [],
         "changed_files": []}))
    (work / "tasks").mkdir()
    (work / "tasks" / "plan.json").write_text(json.dumps(SUB_PRIOR))
    r = run_drive_plan(work)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "no EM call" in r.stdout, r.stdout
    assert not (work / ".calls").exists(), r.stdout
    merged = json.loads((work / "tasks" / "plan.json").read_text())
    assert merged["erd_version"] == 2 and merged["version"] == 4
    # budget untouched: the mechanical path never writes the counter
    assert not (work / ".pipeline-state" / "plan_revisions").exists()


# --- Cut 2: trivial one-file re-plan constructed mechanically (no EM) --------
# When the delta re-plans exactly ONE existing file with no contract changes
# and no new inventory files, no judgment survives for the EM to add: the
# carried task's brief and contracts still describe what the file does, the
# D-59 coder receives the file's current content anyway, and only the mapped
# node-ids change. --subtree-scope's trivial_construct flag drives this;
# --construct-one-file is the mechanical builder; ensure_plan wires them so
# a real trivial re-freeze consumes ZERO EM calls and no plan-revision
# budget. If the constructed plan fails validation, the escalation ladder
# (D-70) summons the EM at its consult rung — exactly where its judgment is
# real, not on the happy path where it isn't.

TRIVIAL_CONTRACTS = dict(SUB_CONTRACTS, files=["src/a.py", "src/b.py"])
TRIVIAL_DELTA = {                                    # only tests change
    "changed_contract_ids": [],
    "changed_tests": ["tests/test_b.py::test_two",
                      "tests/test_b.py::test_three"],
    "changed_files": ["src/b.py"],
}


def _trivial_scope_repo(tmp_path):
    """Same shape as subtree_repo but tuned to the trivial precondition:
    no new inventory files, no contract changes across the delta range."""
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "contracts.json").write_text(json.dumps(TRIVIAL_CONTRACTS))
    (approved / "test-nodeids").write_text("\n".join(SUB_NODEIDS[:3]) + "\n")
    (approved / "VERSION").write_text("2\n")
    (approved / "DELTA-v2.json").write_text(json.dumps(TRIVIAL_DELTA))
    (tmp_path / "tasks").mkdir()
    (tmp_path / ".pipeline-state").mkdir()
    (tmp_path / ".pipeline-state" / "plan-prior.json").write_text(
        json.dumps(SUB_PRIOR))
    return tmp_path


def test_subtree_scope_flags_trivial_construct(tmp_path):
    """One re-emit, no new files, no contract changes across any delta —
    trivial_construct fires."""
    repo = _trivial_scope_repo(tmp_path)
    s = json.loads(run_scope(repo, "scripts/.approved/DELTA-v2.json").stdout)
    assert s["trivial_construct"] is True
    assert s["reemit"] == [{"file": "src/b.py", "keep_id": "T2"}]
    assert s["new_files"] == []
    assert s["em_needed"] is True                    # still an EM path in principle


def test_subtree_scope_trivial_off_when_contracts_change(tmp_path):
    """Contract changes are the exact case a carried brief may not still
    describe — trivial_construct must NOT fire even for a one-file re-plan.
    Checked across MULTIPLE deltas (skip-behind restart)."""
    repo = _trivial_scope_repo(tmp_path)
    # A second delta in the range carrying a contract change — nothing to
    # hit in the tasks (no ids overlap), so scope still has one reemit,
    # but trivial_construct must recognize the contract shift.
    (repo / "d2.json").write_text(json.dumps(
        {"changed_contract_ids": ["route-nonexistent"],
         "changed_tests": [], "changed_files": []}))
    s = json.loads(run_scope(
        repo, "scripts/.approved/DELTA-v2.json", "d2.json").stdout)
    assert s["reemit"] == [{"file": "src/b.py", "keep_id": "T2"}]
    assert s["trivial_construct"] is False


def test_subtree_scope_trivial_off_with_new_files(subtree_repo):
    """A new inventory file needs contract selection judgment (which
    contract ids does it implement?) — the shell cannot make that call, so
    trivial_construct stays False when new_files is non-empty."""
    s = _scoped(subtree_repo)
    assert s["new_files"] == ["src/c.py"]
    assert s["trivial_construct"] is False


def run_construct(repo):
    return subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--construct-one-file",
         ".pipeline-state/plan-prior.json",
         ".pipeline-state/subtree-scope.json"],
        cwd=repo, capture_output=True, text=True,
    )


def test_construct_one_file_carries_prior_brief_and_contracts(tmp_path):
    """The mechanical builder reuses the prior task's brief, contracts,
    and depends_on verbatim; only tests are refreshed. The output is
    subtree-shaped so --merge-subtree consumes it exactly as an EM reply."""
    repo = _trivial_scope_repo(tmp_path)
    _scoped(repo, "scripts/.approved/DELTA-v2.json")
    r = run_construct(repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    reply = json.loads(r.stdout)
    assert len(reply["tasks"]) == 1
    t = reply["tasks"][0]
    assert t["id"] == "T2" and t["file"] == "src/b.py"
    assert t["brief"] == "build b"                   # prior brief carried
    assert t["depends_on"] == ["T1"]
    assert set(t["tests"]) == {                      # scope's map_nodeids
        "tests/test_b.py::test_two",
        "tests/test_b.py::test_three"}


def test_construct_one_file_refuses_non_trivial_scope(subtree_repo):
    """A scope with a new file (or contract changes) is not trivial —
    the mode refuses so callers cannot hand-fabricate over EM judgment."""
    _scoped(subtree_repo)                            # SUB scope has new_files
    r = run_construct(subtree_repo)
    assert r.returncode == 1
    assert "not trivial_construct" in r.stderr, r.stderr


def test_construct_one_file_merges_to_valid_plan(tmp_path):
    """End-to-end mechanical path: construct + merge = a plan that passes
    the FULL validate() gate unchanged, same guarantee as the EM path."""
    repo = _trivial_scope_repo(tmp_path)
    _scoped(repo, "scripts/.approved/DELTA-v2.json")
    r = run_construct(repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    (repo / "tasks" / "plan-subtree.json").write_text(r.stdout)
    m = run_merge(repo, "tasks/plan-subtree.json")
    assert m.returncode == 0, (m.stdout, m.stderr)
    v = subprocess.run([sys.executable, str(VALIDATE_PLAN)],
                       cwd=repo, capture_output=True, text=True)
    assert v.returncode == 0, (v.stdout, v.stderr)
    merged = json.loads((repo / "tasks" / "plan.json").read_text())
    by_id = {t["id"]: t for t in merged["tasks"]}
    assert by_id["T1"]["brief"] == "build a"         # carried byte-identical
    assert by_id["T2"]["brief"] == "build b"         # prior brief reused
    assert set(by_id["T2"]["tests"]) == {
        "tests/test_b.py::test_two",
        "tests/test_b.py::test_three"}


# --- D-107: ERD-DELTA.md is the checked current-milestone artifact ----------
# The standing ERD grew big enough that per-milestone freeze diffs were no
# longer reviewable — testchat let five straight refreezes (v60-v64) through
# a rubber-stamped y/N. Split: ERD.md carries the standing architecture,
# ERD-DELTA.md carries the per-delta ACs/mapping/inventory changes; both
# pinned in one freeze. Machinery is minimal (accept, whitelist, diff-show,
# manifest-pin, D-89 union) plus a required behavioral-delta contract. These
# tests pin acceptance, rejection, coverage, and stale-delta retirement.


def test_refreeze_accepts_and_pins_erd_delta(freezable_repo):
    """Stage an ERD-DELTA.md alongside the existing artifacts. The whole
    apply path must complete and the manifest must pin the new file, so
    any post-freeze mutation of ERD-DELTA.md would trip the same
    tamper-detection gate that guards every other frozen artifact."""
    (freezable_repo / "scripts" / ".approved" / "incoming"
     / "ERD-DELTA.md").write_text(
        VALID_ERD_DELTA.replace("None.\n\n## Superseded", "AC-1\n\n## Superseded"))
    r = _run_refreeze_approve(freezable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    approved = freezable_repo / "scripts" / ".approved"
    assert (approved / "ERD-DELTA.md").read_text().startswith("# Current milestone"), \
        "ERD-DELTA.md must install to scripts/.approved/"
    manifest = (approved / "frozen-manifest").read_text()
    assert "scripts/.approved/ERD-DELTA.md" in manifest, manifest


def test_refreeze_rejects_unexpected_staging_path(freezable_repo):
    """The whitelist keeps every other filename out — staging a stray
    file must still fail-closed, not slip through because we widened the
    whitelist for ERD-DELTA.md."""
    (freezable_repo / "scripts" / ".approved" / "incoming"
     / "ERD-OTHER.md").write_text("stray\n")
    d = subprocess.run(
        ["bash", "scripts/refreeze.sh", "--diff", "scripts/.approved/incoming"],
        cwd=freezable_repo, capture_output=True, text=True,
    )
    assert d.returncode != 0, (d.stdout, d.stderr)
    combined = d.stdout + d.stderr
    assert "unexpected files" in combined and "ERD-OTHER.md" in combined


def test_refreeze_behavior_delta_requires_fresh_erd_delta(freezable_repo):
    """The M32 failure shape: changed tests plus a carried old delta may not
    reach approval without a freshly staged current-change artifact."""
    (freezable_repo / "scripts" / ".approved" / "incoming"
     / "ERD-DELTA.md").unlink()
    r = _run_refreeze_diff(freezable_repo)
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "behavioral re-freeze must stage ERD-DELTA.md" in combined


def test_refreeze_delta_requires_sections_ac_ids_and_files(freezable_repo):
    """A token delta file is not enough: new AC ids and the TPM's editable
    file declaration must be traceable in the current-milestone design."""
    approved = freezable_repo / "scripts" / ".approved"
    (approved / "incoming" / "tests" / "test_delta.py").write_text(
        "# AC-133\n"
        "def test_selector_unlocked():\n"
        "    assert True\n"
    )
    contracts = json.loads((approved / "contracts.json").read_text())
    contracts["erd_version"] = 2
    contracts["changed_files"] = ["src/static/catalog.js"]
    (approved / "incoming" / "contracts.json").write_text(json.dumps(contracts))
    (approved / "incoming" / "ERD-DELTA.md").write_text(
        "# Incomplete delta\n\n## Changed acceptance criteria\n")
    r = _run_refreeze_diff(freezable_repo)
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "missing required section" in combined
    assert "AC-133" in combined
    assert "src/static/catalog.js" in combined


def test_refreeze_docs_only_retires_previous_erd_delta(freezable_repo):
    """A non-behavioral freeze must not leave the previous milestone's delta
    in the next EM context."""
    approved = freezable_repo / "scripts" / ".approved"
    (approved / "incoming" / "tests" / "test_delta.py").unlink()
    (approved / "incoming" / "ERD-DELTA.md").unlink()
    (approved / "incoming" / "ERD.md").write_text("# Standing ERD wording\n")
    r = _run_refreeze_approve(freezable_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not (approved / "ERD-DELTA.md").exists()
    assert "ERD-DELTA.md" not in (approved / "frozen-manifest").read_text()


def test_tpm_shuttle_carries_erd_delta_end_to_end(tmp_path):
    """The chat-side TPM must receive the frozen delta doc and be able to
    return its replacement through the same sentinel shuttle."""
    (tmp_path / "scripts" / "schemas").mkdir(parents=True)
    (tmp_path / "scripts" / ".approved").mkdir()
    (tmp_path / "docs").mkdir()
    for name in ("tpm-pack.sh", "tpm-unpack.sh"):
        target = tmp_path / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
    policy = SCRIPTS / "spec_artifacts.py"
    if policy.exists():
        (tmp_path / "scripts" / policy.name).write_bytes(policy.read_bytes())
    (tmp_path / "docs" / "TPM-ROLE.md").write_text("TPM role\n")
    (tmp_path / "scripts" / "schemas" / "contracts.schema.json").write_text("{}\n")
    approved = tmp_path / "scripts" / ".approved"
    (approved / "VERSION").write_text("4\n")
    (approved / "PRD.md").write_text("# PRD\n")
    (approved / "ERD.md").write_text("# Standing ERD\n")
    (approved / "ERD-DELTA.md").write_text("# Frozen delta marker\n")
    (approved / "contracts.json").write_text("{}\n")

    packed = subprocess.run(
        ["bash", "scripts/tpm-pack.sh"], cwd=tmp_path,
        capture_output=True, text=True,
    )
    assert packed.returncode == 0, (packed.stdout, packed.stderr)
    assert "CONTEXT FILE: scripts/.approved/ERD-DELTA.md" in packed.stdout
    assert "# Frozen delta marker" in packed.stdout
    assert "ERD-DELTA.md" in packed.stdout.split("Allowed paths ONLY:", 1)[1]

    reply = (
        "=== FILE: ERD-DELTA.md ===\n"
        "# Replacement delta\n"
        "=== END FILE ===\n"
    )
    unpacked = subprocess.run(
        ["bash", "scripts/tpm-unpack.sh"], cwd=tmp_path, input=reply,
        capture_output=True, text=True,
    )
    assert unpacked.returncode == 0, (unpacked.stdout, unpacked.stderr)
    assert (approved / "incoming" / "ERD-DELTA.md").read_text() == \
        "# Replacement delta\n"


def test_spec_artifact_policy_is_shared_by_all_shuttle_boundaries():
    """The refreeze, pack, and unpack allowlists previously drifted twice.
    All three runtime boundaries must consume one policy module."""
    policy = SCRIPTS / "spec_artifacts.py"
    assert policy.exists(), "missing shared spec-artifact policy"
    for name in ("refreeze.sh", "tpm-pack.sh", "tpm-unpack.sh",
                 "tpm-agent.sh"):
        source = (SCRIPTS / name).read_text()
        assert "spec_artifacts" in source, f"{name} bypasses shared policy"
    allowed = subprocess.run(
        [sys.executable, str(policy), "check",
         "ERD-DELTA.md", "tests/fixtures/provider.json"],
        capture_output=True, text=True,
    )
    assert allowed.returncode == 0, allowed.stderr
    traversal = subprocess.run(
        [sys.executable, str(policy), "check", "tests/../src/secret.py"],
        capture_output=True, text=True,
    )
    assert traversal.returncode != 0


def test_onboarding_prints_the_model_override_names_llm_call_reads():
    """Onboarding must teach SWBP_<ROLE>_MODEL, not the transposed names
    that llm-call ignores."""
    for name in ("bootstrap.sh", "new-project.sh"):
        source = (SCRIPTS / name).read_text()
        assert "SWBP_EM_MODEL" in source
        assert "SWBP_CODER_MODEL" in source
        assert "SWBP_MODEL_EM" not in source
        assert "SWBP_MODEL_CODER" not in source


def test_ci_lints_template_owned_python_scripts():
    """The unconditional control-plane job must lint scripts/, where the
    gate code and its selftests live, even for an unbootstrapped skeleton.
    The rule set is explicit and isolated so local config or ruff releases
    cannot silently widen or narrow the contract."""
    workflow = (SCRIPTS.parent / ".github" / "workflows" / "ci.yml").read_text()
    assert re.search(
        r"(?m)^\s*run:\s*ruff check --isolated "
        r"--select E4,E7,E9,F scripts/?\s*$",
        workflow,
    )


def test_plan_trivial_one_file_zero_em_calls(tmp_path):
    """Cut 2 through the REAL ensure_plan: a trivial one-file re-freeze
    takes ZERO EM calls, no plan-revision budget spent, gate green,
    carried and re-planned tasks both intact — the escalation ladder is
    what catches the case where the carried brief no longer fits, not a
    speculative EM re-emission."""
    work = plan_workdir(tmp_path, dict(TRIVIAL_CONTRACTS),
                        ["SHOULD-NEVER-BE-CALLED"])
    (work / "scripts" / ".approved" / "test-nodeids").write_text(
        "\n".join(SUB_NODEIDS[:3]) + "\n")
    (work / "scripts" / ".approved" / "DELTA-v2.json").write_text(
        json.dumps(TRIVIAL_DELTA))
    (work / "tasks").mkdir()
    (work / "tasks" / "plan.json").write_text(json.dumps(SUB_PRIOR))
    r = run_drive_plan(work)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "constructed mechanically (no EM call)" in r.stdout, r.stdout
    assert not (work / ".calls").exists(), r.stdout
    assert not (work / ".pipeline-state" / "plan_revisions").exists()
    merged = json.loads((work / "tasks" / "plan.json").read_text())
    assert merged["erd_version"] == 2 and merged["version"] == 4
    by_id = {t["id"]: t for t in merged["tasks"]}
    assert by_id["T1"]["brief"] == "build a"
    assert by_id["T2"]["brief"] == "build b"         # prior brief carried
    assert set(by_id["T2"]["tests"]) == {
        "tests/test_b.py::test_two",
        "tests/test_b.py::test_three"}


# --- update-template.sh D-96 auto mode (mirrors D-95) ------------------------
# The doc had already conceded (script line 36 pre-D-96) that this y/N was
# an "authorization that the control plane changed with a human aware — not
# a code review." An authorization with no defect-catching role is exactly
# what the CEO's rubber-stamp complaint targets. Correctness upstream: the
# template's own selftests ran green before the template committed the
# change. Correctness downstream: phase-gate.sh manifest HEAD runs
# fail-closed post-apply. The middle keystroke was ceremony.


def _run_ut(cmd, cwd):
    """Subprocess wrapper for update-template tests — plain capture, no env."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def template_pull_pair(tmp_path):
    """A minimal (child repo, template clone) pair with a real diff.

    Template clone ships scripts/hello.sh with "new" content and a
    scripts/.manifest-template pinning it. Child ships hello.sh with "old"
    content, a matching .manifest-template pinning the OLD hash, an empty
    .manifest-project (regen-manifest tolerates zero entries), a
    .template-version pointing at a fake ref (CLAIMS falls back cleanly on
    a base ref not in the clone), and the three scripts the pull needs:
    update-template.sh, regen-manifest.sh, phase-gate.sh. Post-apply,
    phase-gate.sh manifest HEAD passes because hello.sh matches its
    newly-installed template manifest hash and .manifest-project is empty."""
    child = tmp_path / "child"
    clone = tmp_path / "clone"
    (child / "scripts").mkdir(parents=True)
    (clone / "scripts").mkdir(parents=True)

    # Template clone: one committed version of hello.sh + a manifest pinning it.
    hello_new = "#!/bin/sh\necho new-content\n"
    (clone / "scripts" / "hello.sh").write_text(hello_new)
    (clone / "scripts" / "hello.sh").chmod(0o755)
    new_hash = subprocess.run(
        ["sha256sum", "scripts/hello.sh"],
        cwd=clone, capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    (clone / "scripts" / ".manifest-template").write_text(
        f"{new_hash}  scripts/hello.sh\n")
    _init_git(clone)

    # Child: old content + template manifest pinning the OLD hash. This diff
    # is what update-template.sh will detect and offer to apply.
    hello_old = "#!/bin/sh\necho old-content\n"
    (child / "scripts" / "hello.sh").write_text(hello_old)
    (child / "scripts" / "hello.sh").chmod(0o755)
    old_hash = subprocess.run(
        ["sha256sum", "scripts/hello.sh"],
        cwd=child, capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    (child / "scripts" / ".manifest-template").write_text(
        f"{old_hash}  scripts/hello.sh\n")
    (child / "scripts" / ".manifest-project").write_text("")

    (child / ".template-version").write_text(
        "repo=fake/template\n"
        "ref=0000000000000000000000000000000000000000\n"
    )

    for name in ("update-template.sh", "regen-manifest.sh", "phase-gate.sh"):
        target = child / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
        target.chmod(0o755)

    _init_git(child)
    subprocess.run(["git", "config", "user.email", "t@t"],
                   cwd=child, check=True)
    subprocess.run(["git", "config", "user.name", "t"],
                   cwd=child, check=True)
    return child, clone


def test_update_template_auto_proceeds_without_terminal(template_pull_pair):
    """No flags, no tty — auto applies the pull and prints the D-96 audit
    line. Pre-D-96 this died at the `[ -t 0 ]` check demanding a terminal
    for the y/N prompt. Verifies the [template-update ...] commit lands
    (real apply, not a dry-run) and phase-gate integrity holds post-apply."""
    child, clone = template_pull_pair
    r = _run_ut(["bash", "scripts/update-template.sh", "--from", str(clone)], child)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "auto-approved (D-96)" in r.stdout, r.stdout
    # The rubber-stamp prompt must not print in auto mode.
    assert "Apply this template update?" not in r.stdout, r.stdout
    # A real commit landed — not a dry-run degrade.
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=child, capture_output=True, text=True, check=True,
    )
    assert log.stdout.strip().startswith("[template-update "), log.stdout
    # And the file actually changed to the template's content.
    assert "new-content" in (child / "scripts" / "hello.sh").read_text()


def test_update_template_interactive_flag_requires_terminal(template_pull_pair):
    """--interactive is the opt-in eyeball path — under subprocess (no tty)
    it must die with a message pointing back to the D-96 auto default,
    D-61 hash-bound apply, or --review. Preserves the escape hatch without
    silently degrading to auto when the operator asked for interactive."""
    child, clone = template_pull_pair
    r = _run_ut(
        ["bash", "scripts/update-template.sh", "--interactive",
         "--from", str(clone)],
        child,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    combined = r.stdout + r.stderr
    assert "--interactive" in combined, combined
    assert "D-96" in combined, combined
    # No accidental apply.
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=child, capture_output=True, text=True, check=True,
    )
    assert not log.stdout.strip().startswith("[template-update "), log.stdout


def test_update_template_applies_removal_only_update(template_pull_pair):
    """A file retired from the upstream template must be deleted, staged, and
    committed even when every still-listed file already matches upstream."""
    child, clone = template_pull_pair
    template_hello = (clone / "scripts" / "hello.sh").read_bytes()
    (child / "scripts" / "hello.sh").write_bytes(template_hello)
    hello_hash = subprocess.run(
        ["sha256sum", "scripts/hello.sh"], cwd=child,
        capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    obsolete = child / "scripts" / "obsolete.sh"
    obsolete.write_text("#!/bin/sh\necho obsolete\n")
    obsolete.chmod(0o755)
    obsolete_hash = subprocess.run(
        ["sha256sum", "scripts/obsolete.sh"], cwd=child,
        capture_output=True, text=True, check=True,
    ).stdout.split()[0]
    (child / "scripts" / ".manifest-template").write_text(
        f"{hello_hash}  scripts/hello.sh\n"
        f"{obsolete_hash}  scripts/obsolete.sh\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=child, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "fixture: add obsolete template file"],
        cwd=child, check=True,
    )

    r = _run_ut(
        ["bash", "scripts/update-template.sh", "--from", str(clone)], child)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "scripts/obsolete.sh" in r.stdout
    assert not obsolete.exists()
    assert "scripts/obsolete.sh" not in \
        (child / "scripts" / ".manifest-template").read_text()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "scripts/obsolete.sh"],
        cwd=child, capture_output=True, text=True,
    )
    assert tracked.returncode != 0, tracked.stdout
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=child,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert subject.startswith("[template-update "), subject


# --- sandbox image build context --------------------------------------------


def test_containerfile_never_copies_the_project_tree_into_an_image_layer():
    """The sandbox image needs the dependency manifest, not source, runtime
    state, captures, or local secrets. COPY . permanently retains all of them
    in an earlier image layer even when a later RUN deletes the directory."""
    containerfile = (SCRIPTS.parent / "Containerfile").read_text()
    assert not re.search(r"(?m)^COPY\s+\.\s", containerfile), containerfile
    assert re.search(
        r"(?m)^COPY\s+requirements\.txt\s+/tmp/requirements\.txt$",
        containerfile,
    ), containerfile
    dockerignore = (SCRIPTS.parent / ".dockerignore").read_text().splitlines()
    for required in (
        ".env*", ".pipeline-state", ".pipeline-completions.json",
        ".pipeline-flakes.json", ".em-archive",
    ):
        assert required in dockerignore, (required, dockerignore)


def test_real_container_build_is_change_scoped_and_scheduled():
    """The expensive browser image gets a real clean build when packaging
    changes and on a weekly backstop, without taxing every source commit."""
    workflow_path = (
        SCRIPTS.parent / ".github" / "workflows" / "container-build.yml"
    )
    assert workflow_path.is_file(), "container build workflow is missing"
    workflow = workflow_path.read_text()
    for required in (
        "schedule:", "workflow_dispatch:", "Containerfile",
        ".dockerignore", "requirements.txt", "docker build",
        "--pull", "--no-cache", "docker run",
    ):
        assert required in workflow, (required, workflow)


# --- status.sh / teardown.sh (D-97 housekeeping) -----------------------------
# The pipeline had no answer for "what's resident right now?" and no protocol
# for "wrap up now." status.sh is the read-only reporter (never writes,
# tolerates missing limactl/nc/lms/podman); teardown.sh is the operator-
# invoked reclaimer (default-safe, --dry-run available, --lima and
# --em-archive opt-in outside --all — the two flags whose consequences the
# operator should say by name).


@pytest.fixture()
def housekeeping_repo(tmp_path):
    """Sandboxed repo for the two housekeeping scripts.

    Layout: tmp_path/repo (the tree the scripts act on), tmp_path/stubbin
    (argv-logging no-op stubs for lms/limactl/pkill/nc), tmp_path/stub.log
    (what the stubs were invoked with — kept OUTSIDE repo/ so status.sh's
    read-only invariant holds while the stubs still log).

    The stubs exist because teardown's --lm-studio/--containers/--lima
    actions act on HOST processes and the VM, not the repo tree: a real
    `--all` under the inherited host PATH executed `lms server stop`
    against the host's live LM Studio server (2026-07-27). tmp_path
    confines file scope only — the process/VM boundary must be stubbed
    explicitly. File-scoped behavior stays real. The limactl stub reports
    dev-vm as Stopped so both scripts take their skip branches
    deterministically; the nc stub exits 1 ("not reachable") so no host
    port state leaks into assertions."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("status.sh", "teardown.sh"):
        target = repo / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
        target.chmod(0o755)
    stubbin = tmp_path / "stubbin"
    stubbin.mkdir()
    stub = (
        "#!/bin/sh\n"
        '# argv-logging no-op stub — housekeeping selftests never touch host state\n'
        'echo "$(basename "$0") $*" >> "${STUB_LOG:?}"\n'
        'case "$(basename "$0")" in\n'
        '  limactl) [ "$1" = list ] && echo "Stopped" ;;\n'
        "  nc) exit 1 ;;\n"
        "esac\n"
        "exit 0\n"
    )
    for name in ("lms", "limactl", "pkill", "nc"):
        s = stubbin / name
        s.write_text(stub)
        s.chmod(0o755)
    return repo


def _run_hk(cmd, repo):
    """Housekeeping runner: PATH-shadows the host-global tools with the
    fixture's stubs. Everything else (rm, find, du, df, awk...) resolves
    normally, so the file-scoped behavior under test is the real thing.
    (_run_ut inherits the host env on purpose — the update-template tests
    need real git — so housekeeping gets its own runner.)"""
    env = dict(os.environ)
    env["PATH"] = f"{repo.parent / 'stubbin'}:{env['PATH']}"
    env["STUB_LOG"] = str(repo.parent / "stub.log")
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env)


def test_status_writes_nothing_and_reports_every_section(housekeeping_repo):
    """Read-only invariant: after running, the directory tree must be
    byte-identical to what it was before. And every declared section must
    appear so a partial-report regression is loud."""
    before = sorted((p.relative_to(housekeeping_repo), p.stat().st_mtime_ns)
                    for p in housekeeping_repo.rglob("*") if p.is_file())
    r = _run_hk(["bash", "scripts/status.sh"], housekeeping_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    for section in ("Lima dev-vm", "LLM servers", "podman containers",
                    "pipeline state", "repo disk"):
        assert section in r.stdout, (section, r.stdout)
    after = sorted((p.relative_to(housekeeping_repo), p.stat().st_mtime_ns)
                   for p in housekeeping_repo.rglob("*") if p.is_file())
    assert before == after, "status.sh mutated the tree — read-only invariant broken"


def test_teardown_bare_invocation_prints_help(housekeeping_repo):
    """Nothing defaults to destructive: `teardown.sh` with no flags must
    print help and exit 0 — never wipe state on a mis-typed command."""
    r = _run_hk(["bash", "scripts/teardown.sh"], housekeeping_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "Flags:" in r.stdout, r.stdout
    assert "--dry-run" in r.stdout, r.stdout


def test_teardown_dry_run_does_not_touch_the_tree(housekeeping_repo):
    """--dry-run must run the full plan but leave the filesystem alone."""
    (housekeeping_repo / ".pipeline-state").mkdir()
    (housekeeping_repo / ".pipeline-state" / "victim").write_text("x")
    r = _run_hk(
        ["bash", "scripts/teardown.sh", "--state", "--dry-run"],
        housekeeping_repo,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "DRY RUN" in r.stdout, r.stdout
    assert (housekeeping_repo / ".pipeline-state" / "victim").exists()


def test_teardown_state_flag_removes_pipeline_state(housekeeping_repo):
    """--state removes .pipeline-state/ end-to-end — and a REAL run must not
    carry the dry-run banner. The banner shipped printing on every run
    (${DRY:+} fires on DRY=0 — "0" is a non-empty string); the dry-run test
    asserting the banner PRESENT was vacuously green the whole time. For any
    mode banner, the absence assertion on the opposite mode is the one that
    detects."""
    (housekeeping_repo / ".pipeline-state").mkdir()
    (housekeeping_repo / ".pipeline-state" / "victim").write_text("x")
    r = _run_hk(["bash", "scripts/teardown.sh", "--state"], housekeeping_repo)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not (housekeeping_repo / ".pipeline-state").exists(), r.stdout
    assert "DRY RUN" not in r.stdout, r.stdout


def test_teardown_all_does_not_touch_em_archive_or_lima(housekeeping_repo):
    """--all is safe to type without regret: it must NOT prune .em-archive/
    (feeds the M28 diagnosis-brief A/B) and must NOT stop Lima (biggest
    cost to reverse). Those two need explicit --em-archive / --lima."""
    (housekeeping_repo / ".em-archive").mkdir()
    (housekeeping_repo / ".em-archive" / "keep").write_text("x")
    r = _run_hk(
        ["bash", "scripts/teardown.sh", "--all", "--dry-run"],
        housekeeping_repo,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "--em-archive" not in r.stdout, r.stdout   # section header absent
    assert "--lima" not in r.stdout, r.stdout
    # The corpus survives even a real (non-dry-run) --all.
    r2 = _run_hk(["bash", "scripts/teardown.sh", "--all"], housekeeping_repo)
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    assert (housekeeping_repo / ".em-archive" / "keep").exists()
    # Process-level proof via the stub log: the real --all DID invoke the
    # lm-studio stop (wiring exercised — against the stub, never the host)
    # and never told Lima to stop.
    log = (housekeeping_repo.parent / "stub.log").read_text()
    assert "lms server stop" in log, log
    assert "limactl stop" not in log, log


def test_teardown_rejects_unknown_flag(housekeeping_repo):
    """Unknown flag → non-zero and a pointer to --help. No silent no-op."""
    r = _run_hk(
        ["bash", "scripts/teardown.sh", "--wipe-everything"],
        housekeeping_repo,
    )
    assert r.returncode != 0, (r.stdout, r.stderr)
    assert "--help" in r.stdout + r.stderr
