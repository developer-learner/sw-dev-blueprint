"""D-112 amend (2026-09-30): the verdict also runs DEPENDENT frozen tests.

The mapped union covered only tests the plan assigned; the D-57 ownership
projection counts only CREATED modules, so a frozen test of a MODIFIED module
was neither mapped nor run and vortex v43 reached [success] with the full
suite 3 red. These pin validate-plan's dependent_node_ids and its wiring into
orchestrate.sh's verdict block (driven through drive-verdict.sh).
"""

import importlib.util
import sys
import json
import os
import re
import subprocess
from pathlib import Path

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


def test_mapped_ids_and_unparseable_files_are_excluded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _tests(tmp_path, {
        "tests/test_ui.py": "from pkg.ui import PAGE\n\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n",
        "tests/test_bad.py": "from pkg.ui import (\n",
    })
    ids = _vp().dependent_node_ids(
        ["src/pkg/ui.py"],
        ["tests/test_ui.py::test_a", "tests/test_ui.py::test_b", "tests/test_bad.py::test_c"],
        mapped={"tests/test_ui.py::test_a"})
    assert ids == ["tests/test_ui.py::test_b"]


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
