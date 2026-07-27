"""selftest_gates.py — template self-tests for the two Python gate scripts.

These test the CONTROL PLANE, not the project: validate-plan.py and
check-test-surface.py are pure functions over JSON and file trees, and a
validator that wrongly passes fails open. This file is the cheap-to-carry
slice of "test the template itself" — the bash orchestration stays covered
by dry runs until an incident says otherwise (correction-log habit: tighten
from incidents, do not pre-harden speculatively). That incident arrived:
testchat M23's consult dead-ended on a schema-invalid EM diagnosis, so
consult_em is now exercised here too, via drive-consult.sh (D-71).

Deliberately NOT named test_*.py: orchestrate.sh and refreeze.sh run bare
`pytest` / `pytest --collect-only` from the repo root, and a default-collected
file here would leak into the frozen node-id set. Run explicitly:

    pytest scripts/selftest/selftest_gates.py -q

CI runs this in its own `selftest` job, unconditionally — the skeleton guard
does not apply because these tests need no project src/ or requirements.
"""
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


@pytest.fixture()
def stageable_repo(tmp_path):
    """A repo with the machinery refreeze needs to reach the REMOVED
    validation: an existing frozen spec (v1), plus a staging dir. We
    keep the staging minimal (just a REMOVED file) because we want the
    REMOVED validation to fire, not the delta plumbing beyond it."""
    (tmp_path / "scripts" / ".approved" / "incoming").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir(exist_ok=True)
    for name in ("refreeze.sh", "phase-gate.sh"):
        target = tmp_path / "scripts" / name
        target.write_bytes((SCRIPTS / name).read_bytes())
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


# --- refreeze.sh wires the preflight before approval (D-78) ------------------

def refreeze_scripts(repo):
    for name in ("validate-plan.py", "check-test-surface.py",
                 "check-swallowed-errors.py"):
        (repo / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())


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
# Plus one core-invariant test (isolation is corroborating-only, never
# gating — the fbfc1f0 amendment to D-77).

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
                    plan=None):
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "tasks" / "plan.json").write_text(
        json.dumps(plan if plan is not None else FLAKE_PLAN))
    env = {**os.environ,
           "TESTS_RC": str(tests_rc),
           "FAILING": failing,
           "FAIL_DETAIL": fail_detail,
           "RT_OUTCOMES": rt_outcomes,
           "SWBP_ELAPSED": str(swbp_elapsed),
           "SWBP_RUN_BUDGET": str(swbp_budget)}
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


def test_flake_isolation_is_evidence_only_never_gating(tmp_path):
    """fbfc1f0 amendment to D-77: isolation is corroborating evidence, never
    a gate. 0/2 isolated passes must NOT bounce the classification back to
    DRIFT — a flake that reproduces under host memory load is still a flake
    (M28's AC-42 failed 4/4 in isolation). Plan mapping is the SOLE
    discriminator; the k/2 tally is recorded, nothing more."""
    r = run_drive_drift(
        tmp_path, failing="tests/test_flake.py::test_a",
        rt_outcomes="1:1",   # both isolation retries fail
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "0"    # still flake
    assert "0/2 isolated passes" in r.stdout
    assert _kv(r.stdout, "FLAKE_NOTE").startswith("WARNING (D-77)")


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


def test_flake_budget_skip_records_evidence_not_die(tmp_path):
    """fbfc1f0 finding: over SWBP_RUN_BUDGET the isolation runs are the
    one phase safe to skip (isolation is corroborating-only, so dying
    here would fail a flake-green suite). The skip must emit an evidence
    string ('isolation runs skipped — over SWBP_RUN_BUDGET') and the
    classification still flips to flake-green."""
    r = run_drive_drift(
        tmp_path,
        failing="tests/test_flake.py::test_a|tests/test_flake.py::test_b",
        rt_outcomes="",   # must not be consumed
        swbp_elapsed=2000, swbp_budget=1000,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "FINAL_TESTS_RC") == "0"    # still flipped
    assert "isolation runs skipped — over SWBP_RUN_BUDGET" in r.stdout
    assert _kv(r.stdout, "RT_CALLS") == "0"
    assert _kv(r.stdout, "FLAKE_NOTE").startswith("WARNING (D-77)")


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
