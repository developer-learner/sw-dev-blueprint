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
import re
import subprocess
import sys
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
    strike evidence), never a write and never a commit."""
    wrong = CODER_GOOD_REPLY.replace("src/x.py", "src/other.py")
    r = run_coder_drive(tmp_path, wrong, gate_rc=0)
    assert r.returncode == 0, (r.stdout, r.stderr)   # harness survives; strike path
    assert "RC=1" in r.stdout
    assert coder_commit_count(tmp_path) == 1
    assert not (tmp_path / "src" / "x.py").exists()
    assert not (tmp_path / "src" / "other.py").exists()
