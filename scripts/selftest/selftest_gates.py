"""selftest_gates.py — template self-tests for the two Python gate scripts.

These test the CONTROL PLANE, not the project: validate-plan.py and
check-test-surface.py are pure functions over JSON and file trees, and a
validator that wrongly passes fails open. This file is the cheap-to-carry
slice of "test the template itself" — the bash orchestration stays covered
by dry runs until an incident says otherwise (correction-log habit: tighten
from incidents, do not pre-harden speculatively).

Deliberately NOT named test_*.py: orchestrate.sh and refreeze.sh run bare
`pytest` / `pytest --collect-only` from the repo root, and a default-collected
file here would leak into the frozen node-id set. Run explicitly:

    pytest scripts/selftest/selftest_gates.py -q

CI runs this in its own `selftest` job, unconditionally — the skeleton guard
does not apply because these tests need no project src/ or requirements.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
VALIDATE_PLAN = SCRIPTS / "validate-plan.py"
CHECK_SURFACE = SCRIPTS / "check-test-surface.py"

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


def test_ui_rules_ignore_non_playwright_files(tmp_path):
    """A backend test using .locator-ish strings is untouched by the UI gate."""
    r = run_surface(tmp_path, CONTRACTS_UI, (
        "def test_items(client):\n"
        "    assert client.get('/items').status_code == 200\n"
    ))
    assert r.returncode == 0, r.stderr


def test_missing_contracts_is_usage_error(tmp_path):
    tests_dir = tmp_path / "frozen-tests"
    tests_dir.mkdir()
    r = subprocess.run(
        [sys.executable, str(CHECK_SURFACE),
         "--tests-dir", str(tests_dir), "--contracts", str(tmp_path / "absent.json")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
