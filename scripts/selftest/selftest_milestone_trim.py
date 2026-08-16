"""D-140 control-plane pins for milestone-minimal active scope."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent
VALIDATE_PLAN = SCRIPTS / "validate-plan.py"
COMPLETION_LEDGER = SCRIPTS / "completion-ledger.py"
CONTRACTS_DELTA = SCRIPTS / "contracts-delta.py"

sys.path.insert(0, str(SCRIPTS))
import refreeze_delta  # noqa: E402


def _load_validate_plan():
    spec = importlib.util.spec_from_file_location(
        "validate_plan_milestone_trim", VALIDATE_PLAN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _empty_repo(tmp_path: Path) -> Path:
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (tmp_path / "tasks").mkdir()
    (tmp_path / ".gate-paths").write_text("build=src/\n")
    (approved / "VERSION").write_text("2\n")
    (approved / "test-nodeids").write_text("")
    (approved / "contracts.json").write_text(json.dumps({
        "erd_version": 2,
        "files": [],
        "entry_points": [],
    }))
    (approved / "DELTA-v2.json").write_text(json.dumps({
        "changed_contract_ids": [],
        "changed_tests": [],
        "retired_tests": [],
        "changed_tests_granularity": "function",
        "changed_files": [],
        "inventory_files": [],
    }))
    return tmp_path


def test_test_docstring_edit_is_not_runnable_work():
    old = 'def test_status():\n    """old explanation"""\n    assert status() == 200\n'
    new = 'def test_status():\n    """clearer explanation"""\n    assert status() == 200\n'
    changed, infra = refreeze_delta.function_changes(
        "tests/test_status.py", old, new)
    assert changed == set()
    assert infra is False


def test_executable_edit_and_retirement_are_separate_channels():
    old = (
        "def test_live():\n    assert value() == 1\n\n"
        "def test_retired():\n    assert legacy()\n"
    )
    new = "def test_live():\n    assert value() == 2\n"
    runnable, retired = refreeze_delta.compute_test_delta(
        old_nodeids={
            "tests/test_scope.py::test_live",
            "tests/test_scope.py::test_retired",
        },
        new_nodeids={"tests/test_scope.py::test_live"},
        changed_files={"tests/test_scope.py"},
        removed_files=set(),
        old_sources={"tests/test_scope.py": old},
        new_sources={"tests/test_scope.py": new},
    )
    assert runnable == ["tests/test_scope.py::test_live"]
    assert retired == ["tests/test_scope.py::test_retired"]


def test_delta_producer_snapshots_empty_inventory_and_retired_tests(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    approved = tmp_path / "scripts" / ".approved"
    state = tmp_path / ".pipeline-state"
    approved.mkdir(parents=True)
    state.mkdir()
    (approved / "contracts.json").write_text(json.dumps({
        "erd_version": 1,
        "files": ["src/accumulated_from_prior_freeze.py"],
        "entry_points": [],
    }))
    (state / "refreeze-old-nodeids").write_text(
        "tests/test_old.py::test_retired\n")
    (state / "refreeze-changed-files").write_text("")
    (state / "refreeze-removed-files").write_text("tests/test_old.py\n")
    (state / "refreeze-changed-contracts").write_text("")
    nodeids = approved / "test-nodeids"
    nodeids.write_text("")

    assert refreeze_delta.main([
        "refreeze_delta.py", "2", str(nodeids), "0",
    ]) == 0
    delta = json.loads((approved / "DELTA-v2.json").read_text())
    # No staged contracts means no current-freeze inventory: never inherit
    # the standing file list from the preceding freeze.
    assert delta["inventory_files"] == []
    assert delta["changed_tests"] == []
    assert delta["retired_tests"] == [
        "tests/test_old.py::test_retired"]


def test_active_inventory_and_instruction_packet_union_only_active_freezes(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    vp = _load_validate_plan()
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    contracts = {
        "files": ["src/accumulated.py"],
        "entry_points": [],
    }
    (approved / "contracts.json").write_text(json.dumps(contracts))
    paths = []
    for version, file_path, marker in (
        (2, "src/a.py", "freeze-two-instruction"),
        (3, "src/b.py", "freeze-three-instruction"),
    ):
        delta = approved / f"DELTA-v{version}.json"
        delta.write_text(json.dumps({
            "changed_contract_ids": [],
            "changed_tests": [],
            "changed_files": [file_path],
            "inventory_files": [file_path],
        }))
        (approved / f"ERD-DELTA-v{version}.md").write_text(marker + "\n")
        paths.append(delta)

    assert vp.active_inventory_files(paths, contracts) == [
        "src/a.py", "src/b.py"]
    texts = vp.active_erd_delta_texts(paths)
    assert [version for version, _ in texts] == [2, 3]
    assert [text.strip() for _, text in texts] == [
        "freeze-two-instruction", "freeze-three-instruction"]

    empty = approved / "DELTA-v4.json"
    empty.write_text(json.dumps({
        "changed_contract_ids": [], "changed_tests": [],
        "retired_tests": ["tests/test_old.py::test_retired"],
        "changed_files": [], "inventory_files": [],
    }))
    assert vp.active_erd_delta_texts([*paths, empty]) == texts


def test_active_erd_context_deduplicates_repeated_execution_payload():
    vp = _load_validate_plan()
    first = """# old audit preamble

## Changed acceptance criteria

AC-1 adds the first behavior.

## Changed files

`src/work.py` had an older implementation note.

## Test-to-file mapping

* `tests/test_work.py::test_first` -> `src/work.py`

## Task DAG

`src/view.py` depends on `src/work.py`

## Coder briefs (verbatim)

### T1 — src/work.py

Implement the shared behavior.

### T2 — src/view.py

Render the first behavior.
"""
    second = """# current audit preamble

## Changed acceptance criteria

AC-1 adds the first behavior.

## Changed files

`src/view.py` gains the second behavior.

## Test-to-file mapping

* `tests/test_work.py::test_first` -> `src/work.py`
* `tests/test_view.py::test_second` -> `src/view.py`

## Task DAG

`src/view.py` depends on `src/work.py`

## Coder briefs (verbatim)

### T1 — src/work.py

Implement the shared behavior.

### T2 — src/view.py

Render the second behavior.
"""

    compact = vp.compact_active_erd_context([(2, first), (3, second)])
    raw_size = len(first.encode()) + len(second.encode())

    assert "old audit preamble" not in compact
    assert "current audit preamble" in compact
    assert "older implementation note" not in compact
    assert "gains the second behavior" in compact
    assert compact.count("AC-1 adds the first behavior.") == 1
    assert compact.count("Implement the shared behavior.") == 1
    assert "Render the first behavior." in compact
    assert "Render the second behavior." in compact
    assert compact.count("tests/test_work.py::test_first") == 1
    assert compact.count("tests/test_view.py::test_second") == 1
    assert compact.count("`src/view.py` depends on `src/work.py`") == 1
    assert len(compact.encode()) < raw_size


def test_active_erd_context_keeps_single_freeze_body_verbatim():
    vp = _load_validate_plan()
    body = "# current\n\n## Changed files\n\n* `src/work.py`\n"
    compact = vp.compact_active_erd_context([(7, body)])
    assert compact == f"## Active freeze instructions — v7\n{body.rstrip()}"


def test_mechanical_plan_combines_repeated_file_briefs_across_freezes(tmp_path):
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (tmp_path / ".gate-paths").write_text("build=src/\n")
    (approved / "VERSION").write_text("3\n")
    (approved / "test-nodeids").write_text("")
    (approved / "contracts.json").write_text(json.dumps({
        "erd_version": 3,
        "files": ["src/work.py"],
        "entry_points": [],
    }))
    delta_paths = []
    for version, instruction in (
        (2, "Add the first skipped-freeze behavior."),
        (3, "Add the second skipped-freeze behavior."),
    ):
        delta = approved / f"DELTA-v{version}.json"
        delta.write_text(json.dumps({
            "changed_contract_ids": [],
            "changed_tests": [],
            "retired_tests": [],
            "changed_files": ["src/work.py"],
            "inventory_files": ["src/work.py"],
        }))
        (approved / f"ERD-DELTA-v{version}.md").write_text(
            "## Coder briefs (verbatim)\n\n"
            f"### T1 — src/work.py\n\n{instruction}\n"
        )
        delta_paths.append(str(delta.relative_to(tmp_path)))

    result = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--synthesize-plan", *delta_paths],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    brief = json.loads(result.stdout)["tasks"][0]["brief"]
    assert "first skipped-freeze behavior" in brief
    assert "second skipped-freeze behavior" in brief


def test_contract_slice_uses_active_inventory_not_standing_files(tmp_path):
    contracts = tmp_path / "contracts.json"
    contracts.write_text(json.dumps({
        "files": ["src/latest.py"],
        "entry_points": [],
        "routes": [
            {"id": "old-active", "file": "src/earlier.py"},
            {"id": "latest", "file": "src/latest.py"},
            {"id": "historical", "file": "src/historical.py"},
        ],
    }))
    env = os.environ.copy()
    env["SWBP_CONTRACT_FILES"] = "src/earlier.py\nsrc/latest.py\n"
    result = subprocess.run(
        [sys.executable, str(CONTRACTS_DELTA), str(contracts)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert [route["id"] for route in json.loads(result.stdout)["routes"]] == [
        "old-active", "latest"]


def test_retired_and_noncurrent_ids_do_not_enter_runnable_scope():
    vp = _load_validate_plan()
    live = "tests/test_scope.py::test_live"
    retired = "tests/test_scope.py::test_retired"
    assert vp.milestone_scope_ids(
        {}, [], [live, retired], "function", {live},
    ) == [live]


def test_zero_work_plan_validates_and_synthesizes_without_tasks(tmp_path):
    repo = _empty_repo(tmp_path)
    (repo / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 2, "tasks": [],
    }))
    validated = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN)], cwd=repo,
        capture_output=True, text=True,
    )
    assert validated.returncode == 0, validated.stderr

    synthesized = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN), "--synthesize-plan",
         "scripts/.approved/DELTA-v2.json"],
        cwd=repo, capture_output=True, text=True,
    )
    assert synthesized.returncode == 0, synthesized.stderr
    assert json.loads(synthesized.stdout)["tasks"] == []


def test_empty_plan_rejected_when_inventory_has_work(tmp_path):
    repo = _empty_repo(tmp_path)
    approved = repo / "scripts" / ".approved"
    delta = json.loads((approved / "DELTA-v2.json").read_text())
    delta["inventory_files"] = ["src/work.py"]
    (approved / "DELTA-v2.json").write_text(json.dumps(delta))
    contracts = json.loads((approved / "contracts.json").read_text())
    contracts["files"] = ["src/work.py"]
    (approved / "contracts.json").write_text(json.dumps(contracts))
    (repo / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 2, "tasks": [],
    }))

    result = subprocess.run(
        [sys.executable, str(VALIDATE_PLAN)], cwd=repo,
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "plan.tasks may be empty only when" in result.stderr


def test_completion_ledger_records_zero_task_success(tmp_path):
    plan = tmp_path / "plan.json"
    ledger = tmp_path / "ledger.json"
    state = tmp_path / "state"
    plan.write_text(json.dumps({"tasks": []}))
    result = subprocess.run(
        [sys.executable, str(COMPLETION_LEDGER), "record",
         "--spec-version", "2", "--plan", str(plan),
         "--ledger", str(ledger), "--task-state", str(state)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(ledger.read_text())["specs"]["2"]["tasks"] == {}


def test_zero_work_schema_allows_empty_arrays():
    contracts_schema = json.loads(
        (SCRIPTS / "schemas" / "contracts.schema.json").read_text())
    plan_schema = json.loads(
        (SCRIPTS / "schemas" / "plan.schema.json").read_text())
    assert "minItems" not in contracts_schema["properties"]["files"]
    assert "minItems" not in plan_schema["properties"]["tasks"]
