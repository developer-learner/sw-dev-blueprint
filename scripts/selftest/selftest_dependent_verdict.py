"""D-112 amend (2026-09-30) + D-191 (2026-10-01): the verdict also runs
DEPENDENT frozen tests — and an uncertain dependent lookup must fall back to
the full frozen suite, never silently narrow to the mapped union.

The mapped union covered only tests the plan assigned; the D-57 ownership
projection counts only CREATED modules, so a frozen test of a MODIFIED module
was neither mapped nor run and vortex v43 reached [success] with the full
suite 3 red. D-191 (security plan item 4) extends the dependency to the
transitive import graph and to modified conftest.py directory subtrees, and
makes missing or unparseable inputs a non-zero exit that the verdict block
turns into a full-suite fallback. These pin validate-plan's
dependent_node_ids and its wiring into orchestrate.sh's verdict block
(driven through drive-verdict.sh).
"""

import importlib.util
import sys
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent


def _vp():
    spec = importlib.util.spec_from_file_location("vp_dependent", SCRIPTS / "validate-plan.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


def _tests(tmp_path, files):
    for name, body in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


def test_src_layout_test_of_a_modified_module_is_dependent(tmp_path, monkeypatch):
    """`src/pkg/ui.py` is imported by tests as `pkg.ui` (src layout); a test
    of it is dependent even though the milestone only modified ui.py."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    assert PAGE\n",
        "tests/test_other.py": "import json\n\ndef test_b():\n    assert json\n",
    })
    ids = _vp().dependent_node_ids(
        ["src/pkg/ui.py"],
        ["tests/test_ui.py::test_a", "tests/test_other.py::test_b"])
    assert ids == ["tests/test_ui.py::test_a"]


def test_flat_layout_and_from_package_import_forms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "tests/test_a.py": "import src.svc.core\n\ndef test_a():\n    pass\n",
        "tests/test_b.py": "from src.svc import core\n\ndef test_b():\n    pass\n",
    })
    ids = _vp().dependent_node_ids(
        ["src/svc/core.py"], ["tests/test_a.py::test_a", "tests/test_b.py::test_b"])
    assert ids == ["tests/test_a.py::test_a", "tests/test_b.py::test_b"]


def test_mapped_ids_are_excluded_from_dependents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n",
    })
    ids = _vp().dependent_node_ids(
        ["src/pkg/ui.py"],
        ["tests/test_ui.py::test_a", "tests/test_ui.py::test_b"],
        mapped={"tests/test_ui.py::test_a"})
    assert ids == ["tests/test_ui.py::test_b"]


def test_transitive_import_is_dependent(tmp_path, monkeypatch):
    """D-191: a test of pkg.svc is dependent when the milestone modified
    pkg.core, which pkg.svc imports — the edge is two hops, not direct."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "src/pkg/core.py": "VALUE = 1\n",
        "src/pkg/svc.py": "from pkg.core import VALUE\n\ndef run():\n    return VALUE\n",
        "tests/test_s.py": "from pkg.svc import run\n\ndef test_s():\n    assert run()\n",
        "tests/test_unrelated.py": "import json\n\ndef test_u():\n    assert json\n",
    })
    ids = _vp().dependent_node_ids(
        ["src/pkg/core.py"],
        ["tests/test_s.py::test_s", "tests/test_unrelated.py::test_u"])
    assert ids == ["tests/test_s.py::test_s"]


def test_conftest_inventory_covers_its_subtree(tmp_path, monkeypatch):
    """D-191: pytest loads conftest.py without an import edge, so a modified
    conftest makes every frozen test under its directory dependent."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "tests/sub/conftest.py": "import pytest\n\n@pytest.fixture\ndef f():\n    return 1\n",
        "tests/sub/test_b.py": "def test_b(f):\n    assert f\n",
        "tests/test_a.py": "def test_a():\n    assert True\n",
        "tests/other/test_c.py": "def test_c():\n    assert True\n",
    })
    ids = _vp().dependent_node_ids(
        ["tests/sub/conftest.py"],
        ["tests/test_a.py::test_a", "tests/sub/test_b.py::test_b",
         "tests/other/test_c.py::test_c"])
    assert ids == ["tests/sub/test_b.py::test_b"]


def test_unparseable_frozen_test_file_is_uncertain(tmp_path, monkeypatch):
    """D-191: a frozen test file that cannot be parsed makes the selection
    uncertain — it raises instead of being silently dropped (the old
    fail-open that let v43 through)."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "src/pkg/ui.py": "PAGE = 1\n",
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    pass\n",
        "tests/test_bad.py": "from pkg.ui import (\n",
    })
    vp = _vp()
    with pytest.raises(vp.DependentLookupError):
        vp.dependent_node_ids(
            ["src/pkg/ui.py"],
            ["tests/test_ui.py::test_a", "tests/test_bad.py::test_c"])


def test_missing_frozen_test_file_is_uncertain(tmp_path, monkeypatch):
    """D-191: a frozen node-id whose file is gone from the tree is a stale
    freeze — uncertain, not "no dependents"."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "src/pkg/ui.py": "PAGE = 1\n",
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    pass\n",
    })
    vp = _vp()
    with pytest.raises(vp.DependentLookupError):
        vp.dependent_node_ids(
            ["src/pkg/ui.py"],
            ["tests/test_ui.py::test_a", "tests/test_ghost.py::test_g"])


def test_unparseable_file_in_the_graph_is_uncertain(tmp_path, monkeypatch):
    """D-191: if a file in the import graph cannot be parsed, its edges are
    unknown, so the selection is uncertain — never "no dependents" (which
    would silently narrow the verdict to the mapped union)."""
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "src/pkg/ui.py": "PAGE = 1\n",
        "src/pkg/broken.py": "def oops(:\n",
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    pass\n",
    })
    vp = _vp()
    with pytest.raises(vp.DependentLookupError):
        vp.dependent_node_ids(["src/pkg/ui.py"], ["tests/test_ui.py::test_a"])


def _cli(workdir):
    return subprocess.run(
        ["python3", str(SCRIPTS / "validate-plan.py"), "--dependent-ids"],
        capture_output=True, text=True, cwd=str(workdir))


def _cli_workdir(tmp_path, task_file, task_tests, nodeids, files):
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 1,
        "tasks": [{"id": "T1", "file": task_file, "brief": "b",
                   "depends_on": [], "contracts": [], "tests": task_tests}]}))
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True, exist_ok=True)
    (approved / "test-nodeids").write_text("\n".join(nodeids) + "\n")
    _tests(tmp_path, files)


def test_cli_uncertain_exits_nonzero(tmp_path):
    """D-191: the CLI reports uncertainty as exit 1 with a reason on stderr —
    the verdict block turns that into the full-suite fallback."""
    _cli_workdir(
        tmp_path,
        "src/pkg/ui.py",
        ["tests/test_new.py::test_new"],
        ["tests/test_new.py::test_new", "tests/test_bad.py::test_c"],
        {"src/pkg/ui.py": "PAGE = 1\n",
         "tests/test_new.py": "from pkg.ui import PAGE\n\ndef test_new():\n    pass\n",
         "tests/test_bad.py": "from pkg.ui import (\n"})
    r = _cli(tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "uncertain" in r.stderr


def test_cli_certain_empty_exits_zero(tmp_path):
    """D-191: a certain empty selection (no Python inventory) stays exit 0
    with no output — the fallback must not fire on the happy path."""
    _cli_workdir(
        tmp_path,
        "static/app.js",
        [],
        ["tests/test_js.py::test_j"],
        {"static/app.js": "// js\n",
         "tests/test_js.py": "def test_j():\n    assert True\n"})
    r = _cli(tmp_path)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert r.stdout == ""


def test_verdict_falls_back_to_full_suite_on_uncertain_lookup(tmp_path):
    """D-191: driven through drive-verdict.sh — an unparseable frozen test
    file makes the verdict run the WHOLE frozen suite (run_tests with no
    args), not the mapped union plus the computable dependents."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 1,
        "tasks": [{"id": "T1", "file": "src/pkg/ui.py", "brief": "b",
                   "depends_on": [], "contracts": [],
                   "tests": ["tests/test_new.py::test_new"]}]}))
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "test-nodeids").write_text(
        "tests/test_new.py::test_new\ntests/test_ui.py::test_old\n"
        "tests/test_bad.py::test_c\n")
    _tests(tmp_path, {
        "src/pkg/ui.py": "PAGE = 1\n",
        "tests/test_new.py": "from pkg.ui import PAGE\n\ndef test_new():\n    pass\n",
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_old():\n    pass\n",
        "tests/test_bad.py": "from pkg.ui import (\n",
    })
    env = {**os.environ, "FULL_SUITE_CHECK": "0", "RT_OUTCOMES": "0",
           "PLANE_DIR": str(REPO)}
    r = subprocess.run(["bash", str(SCRIPTS / "selftest" / "drive-verdict.sh"),
                        str(tmp_path)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "RT_CALLS") == "1"
    assert _kv(r.stdout, "RT_ARGS") == ""
    assert "uncertain" in r.stdout


def test_no_python_inventory_means_no_dependents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {"tests/test_ui.py": "import pkg.ui\n\ndef test_a():\n    pass\n"})
    assert _vp().dependent_node_ids(["static/app.js"], ["tests/test_ui.py::test_a"]) == []


def _kv(out, key):
    m = re.search(rf"^{key}=(.*)$", out, re.M)
    return m.group(1) if m else None


def test_verdict_block_runs_mapped_plus_dependent_ids(tmp_path):
    """Driven through drive-verdict.sh with the plane path set: the verdict run
    carries the mapped union AND the dependent node-ids, mapped first."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "plan.json").write_text(json.dumps({
        "version": 1, "erd_version": 1,
        "tasks": [{"id": "T1", "file": "src/pkg/ui.py", "brief": "b", "depends_on": [],
                   "contracts": [], "tests": ["tests/test_new.py::test_new"]}]}))
    approved = tmp_path / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (approved / "test-nodeids").write_text(
        "tests/test_new.py::test_new\ntests/test_ui.py::test_old\ntests/test_x.py::test_x\n")
    _tests(tmp_path, {
        "src/pkg/ui.py": "PAGE = 1\n",
        "tests/test_new.py": "from pkg.ui import PAGE\n\ndef test_new():\n    pass\n",
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_old():\n    pass\n",
        "tests/test_x.py": "import json\n\ndef test_x():\n    pass\n",
    })
    env = {**os.environ, "FULL_SUITE_CHECK": "0", "RT_OUTCOMES": "0", "PLANE_DIR": str(REPO)}
    r = subprocess.run(["bash", str(SCRIPTS / "selftest" / "drive-verdict.sh"), str(tmp_path)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert _kv(r.stdout, "RT_CALLS") == "1"
    assert _kv(r.stdout, "RT_ARGS") == "tests/test_new.py::test_new tests/test_ui.py::test_old"
