"""Focused selftests for the B4a milestone-context trim (D-116/D-117/D-120)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent.parent


def run_python(script: str, artifact: Path) -> subprocess.CompletedProcess[str]:
    """Run one owned context generator against a fixture artifact (D-116)."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), str(artifact)],
        capture_output=True,
        text=True,
        check=False,
    )


def make_pack_repo(tmp_path: Path, with_delta: bool = True) -> Path:
    """Build the minimum air-gapped TPM-pack fixture (D-117)."""
    repo = tmp_path / "repo"
    approved = repo / "scripts" / ".approved"
    approved.mkdir(parents=True)
    (repo / "scripts" / "schemas").mkdir()
    (repo / "docs").mkdir()
    for name in (
        "tpm-pack.sh",
        "spec_artifacts.py",
        "standing-summary.py",
        "contracts-delta.py",
        "context-budget.py",
    ):
        shutil.copy(SCRIPTS / name, repo / "scripts" / name)
    (approved / "VERSION").write_text("41\n")
    (approved / "PRD.md").write_text(
        "PRD — fixture\n\n"
        "## What fixture is\n\n"
        "Fixture is a local product with one current milestone.\n\n"
        "## Acceptance criteria\n\n"
        "* **AC-OLD:** DISTINCT_OLD_PRODUCT_FAMILY remains accumulated and "
        "carries enough historical product detail to prove the generated "
        "milestone slice is smaller than its standing source artifact.\n"
    )
    (approved / "ERD.md").write_text(
        "# ERD\n\n"
        "## Safety invariant\n\nNever discard persisted bytes.\n\n"
        "## As-built architecture — service\n\n"
        "* **`src/current.py`** — public interface begins on this line and\n"
        "  exposes load_current() and save_current() to milestone callers.\n\n"
        "* **`src/old.py`** — DISTINCT_ACCUMULATED_ARCHITECTURE.\n\n"
        "## Oracle mapping\n\nDISTINCT_ORACLE_INVENTORY\n\n"
        "## Risk notes\n\nDISTINCT_RISK_REGISTER\n"
    )
    if with_delta:
        (approved / "ERD-DELTA.md").write_text(
            "# ERD-DELTA\n\n"
            "## Changed acceptance criteria\n\n"
            "* **AC-NEW:** CURRENT_MILESTONE_BEHAVIOR is visible.\n\n"
            "## Superseded acceptance criteria\n\nNone.\n"
        )
    contracts = {
        "standing_detail": "accumulated contract body " * 80,
        "files": ["src/current.py"],
        "routes": [
            {"id": "route:current", "file": "src/current.py"},
            {"id": "route:old", "file": "src/old.py"},
            {"id": "route:unpinned", "shape": "conservative carry"},
        ],
        "schemas": [],
        "errors": [],
        "ui": [],
        "entry_points": ["src.current:app", "src.old:app"],
    }
    (approved / "contracts.json").write_text(json.dumps(contracts, indent=2) + "\n")
    (repo / "docs" / "TPM-ROLE.md").write_text("# TPM role\n")
    (repo / "scripts" / "schemas" / "contracts.schema.json").write_text("{}\n")
    return repo


def run_pack(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the real TPM bundle assembler inside its fixture repo (D-117)."""
    return subprocess.run(
        ["bash", "scripts/tpm-pack.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_b4a_contracts_slice_has_only_in_scope_and_unpinned_entries(
    tmp_path: Path,
) -> None:
    """D-120 drops the out-of-scope index but conservatively carries unpinned bodies."""
    source = tmp_path / "contracts.json"
    payload = {
        "files": ["src/current.py"],
        "routes": [
            {"id": "keep", "file": "src/current.py", "detail": "full body"},
            {"id": "drop", "file": "src/old.py", "detail": "legacy body"},
            {"id": "carry", "detail": "unpinned full body"},
        ],
        "schemas": [],
        "errors": [],
        "ui": [],
        "entry_points": ["src.current:app", "src.old:app", "external"],
    }
    source.write_text(json.dumps(payload, indent=2) + "\n")

    result = run_python("contracts-delta.py", source)

    assert result.returncode == 0, result.stderr
    sliced = json.loads(result.stdout)
    assert "out_of_scope" not in sliced
    assert [entry["id"] for entry in sliced["routes"]] == ["keep", "carry"]
    assert sliced["routes"][1]["detail"] == "unpinned full body"
    assert sliced["entry_points"] == ["src.current:app", "external"]
    assert len(result.stdout.encode()) <= len(source.read_bytes())


def test_b4a_contracts_slice_without_pins_carries_full_source(tmp_path: Path) -> None:
    """D-120 remains inert until a contract body carries an ownership pin."""
    source = tmp_path / "contracts.json"
    source.write_text('{"files":[],"routes":[{"id":"unpinned"}]}')

    result = run_python("contracts-delta.py", source)

    assert result.returncode == 0, result.stderr
    assert result.stdout == source.read_text()


def test_b4a_standing_summary_is_rules_plus_real_file_interfaces(
    tmp_path: Path,
) -> None:
    """D-116 drops unrelated appendices and reads wrapped interface paragraphs."""
    erd = tmp_path / "ERD.md"
    erd.write_text(
        "# Standing architecture\n\n"
        "## Safety invariant\n\nNever discard persisted bytes.\n\n"
        "## As-built architecture — service\n\n"
        "* **`src/service.py`** — public interface begins here and\n"
        "  exposes load_snapshot() plus save_snapshot() to callers.\n\n"
        "## File inventory\n\nDISTINCT_FULL_INVENTORY\n\n"
        "## Oracle mapping\n\nDISTINCT_ORACLE_MAPPING\n\n"
        "## Smoke checks\n\nDISTINCT_SMOKE_TOUR\n\n"
        "## Risk notes\n\nDISTINCT_RISK_REGISTER\n"
    )

    result = run_python("standing-summary.py", erd)

    assert result.returncode == 0, result.stderr
    assert "## Safety invariant" in result.stdout
    assert "## File map" in result.stdout
    assert "exposes load_snapshot() plus save_snapshot()" in result.stdout
    assert "DISTINCT_FULL_INVENTORY" not in result.stdout
    assert "DISTINCT_ORACLE_MAPPING" not in result.stdout
    assert "DISTINCT_SMOKE_TOUR" not in result.stdout
    assert "DISTINCT_RISK_REGISTER" not in result.stdout
    assert len(result.stdout.encode()) <= len(erd.read_bytes())


def test_b4a_standing_summary_refuses_to_expand_a_tiny_source(tmp_path: Path) -> None:
    """D-116 fails to the caller when summary scaffolding would add context bytes."""
    erd = tmp_path / "ERD.md"
    erd.write_text("# ERD\n")

    result = run_python("standing-summary.py", erd)

    assert result.returncode == 1
    assert result.stdout == ""


def test_b4a_tpm_pack_emits_only_milestone_product_and_contract_context(
    tmp_path: Path,
) -> None:
    """D-117/D-120 pack the product capsule, current criteria, and contract bodies."""
    repo = make_pack_repo(tmp_path)

    result = run_pack(repo)

    assert result.returncode == 0, result.stderr
    assert "Fixture is a local product with one current milestone." in result.stdout
    assert "CURRENT_MILESTONE_BEHAVIOR" in result.stdout
    assert "DISTINCT_OLD_PRODUCT_FAMILY" not in result.stdout
    assert "- `src/old.py` — DISTINCT_ACCUMULATED_ARCHITECTURE." in result.stdout
    assert "DISTINCT_ORACLE_INVENTORY" not in result.stdout
    assert "DISTINCT_RISK_REGISTER" not in result.stdout
    assert '"id":"route:current"' in result.stdout
    assert '"id":"route:unpinned"' in result.stdout
    assert '"id": "route:old"' not in result.stdout
    assert "out_of_scope" not in result.stdout


def test_b4a_tpm_pack_missing_delta_warns_and_falls_back_to_full_artifacts(
    tmp_path: Path,
) -> None:
    """D-117 makes missing-delta context expansion loud rather than lossy."""
    repo = make_pack_repo(tmp_path, with_delta=False)

    result = run_pack(repo)

    assert result.returncode == 0, result.stderr
    assert "DISTINCT_OLD_PRODUCT_FAMILY" in result.stdout
    assert "DISTINCT_ACCUMULATED_ARCHITECTURE" in result.stdout
    assert "current PRD delta unavailable" in result.stderr
    assert "ERD-DELTA.md" not in result.stdout.split(
        "=== REPLY FORMAT", 1
    )[0]


def test_b4a_tpm_pack_generator_failures_warn_and_ship_full_sources(
    tmp_path: Path,
) -> None:
    """D-116/D-120 preserve context loudly when either generator is unavailable."""
    repo = make_pack_repo(tmp_path)
    (repo / "scripts" / "standing-summary.py").unlink()
    (repo / "scripts" / "contracts-delta.py").unlink()

    result = run_pack(repo)

    assert result.returncode == 0, result.stderr
    assert "DISTINCT_ACCUMULATED_ARCHITECTURE" in result.stdout
    assert '"id": "route:old"' in result.stdout
    assert "standing summary generation failed" in result.stderr
    assert "contracts index generation failed" in result.stderr
DELTA_WITH_DECOMPOSITION = """\
# ERD-DELTA M99

## Changed acceptance criteria

* **AC-99:** change app.js

## Superseded acceptance criteria

None.

## Changed files

* `src/static/app.js`

## Test-to-file mapping

* `tests/test_ui.py::test_widget` -> `src/static/app.js`

## Coder briefs (verbatim)

### T1 — src/static/app.js (feature)

Add the widget. Keep `renderThread`. Self-verify: the widget appears.
SENTINEL_BRIEF_BODY that must never reach the TPM bundle.

## Task DAG

`src/static/app.js` depends on `src/api/chat.py`
Task order: T1 (app) -> T2 (api)
"""


def _build_repo(tmp_path):
    """A controlled repo tree that runs the REAL tpm-pack.sh against a spec
    whose ERD-DELTA carries coder briefs + DAG + task scheduling."""
    repo = tmp_path / "repo"
    (repo / "scripts" / ".approved").mkdir(parents=True)
    (repo / "scripts" / "schemas").mkdir(parents=True)
    (repo / "docs").mkdir(parents=True)
    for name in (
        "tpm-pack.sh",
        "spec_artifacts.py",
        "standing-summary.py",
        "context-budget.py",
    ):
        shutil.copy(SCRIPTS / name, repo / "scripts" / name)
    approved = repo / "scripts" / ".approved"
    (approved / "VERSION").write_text("99\n")
    (approved / "PRD.md").write_text(
        "# PRD\n\n## What fixture is\n\n"
        "Fixture is a local product with one current milestone, described in "
        "enough standing prose that the generated capsule is smaller than its "
        "source artifact.\n\n## Acceptance criteria\n\n"
        "* **AC-99:** change app.js\n")
    (approved / "ERD.md").write_text(
        "## Rule\n\nkeep\n\n## As-built architecture — front end\n\n"
        "* **`src/static/app.js`** — accumulated milestone detail that runs on "
        "well past the truncation threshold with no informational value left.\n")
    (approved / "ERD-DELTA.md").write_text(DELTA_WITH_DECOMPOSITION)
    (approved / "contracts.json").write_text(
        '{"files": ["src/static/app.js"], "smoke_checks": [], '
        '"test_mapping": {}}\n')
    (repo / "docs" / "TPM-ROLE.md").write_text("# TPM role\n")
    (repo / "scripts" / "schemas" / "contracts.schema.json").write_text("{}\n")
    return repo


# A contracts.json exercising every family in both pinned and unpinned shapes
# (D-141): the index must list ALL of it with pins; bodies must follow only
# the requested owning files.
CONTRACTS_FIXTURE = {
    "standing_detail": "accumulated interface contract body " * 80,
    "files": ["src/api/chat.py", "src/static/app.js"],
    "smoke_checks": [],
    "test_mapping": {},
    "entry_points": ["src.main:app", "src.api.chat:create_chat"],
    "routes": [
        {"id": "route:POST /api/v1/chat", "method": "POST",
         "path": "/api/v1/chat", "file": "src/api/chat.py"},
        {"id": "route:GET /", "method": "GET", "path": "/"},
    ],
    "schemas": [
        {"id": "schema:ChatRequest",
         "fields": {"message": "string",
                    "history": "array of HistoryEntry, optional, default []"}},
        {"id": "schema:Widget", "fields": {"label": "string", "count": "integer"},
         "file": "src/static/app.js"},
    ],
    "errors": [
        {"id": "error:422-validation", "status": 422, "file": "src/api/chat.py"},
    ],
    "ui": [
        {"id": "ui:message-input", "testid": "message-input",
         "file": "src/static/app.js"},
        {"id": "ui:unpinned-testid", "testid": "unpinned"},
    ],
}


def _build_contracts_repo(tmp_path):
    """_build_repo plus the REAL contracts-delta.py and a two-file pinned spec
    so both D-141 stages run against the actual producer."""
    repo = _build_repo(tmp_path)
    shutil.copy(SCRIPTS / "contracts-delta.py", repo / "scripts" / "contracts-delta.py")
    (repo / "scripts" / ".approved" / "contracts.json").write_text(
        json.dumps(CONTRACTS_FIXTURE))
    return repo


def _contracts_region(bundle: str) -> str:
    """The contracts.json CONTEXT FILE block of the packed bundle."""
    marker = "=== CONTEXT FILE: scripts/.approved/contracts.json"
    start = bundle.index(marker)
    end = bundle.index("=== END CONTEXT FILE ===", start)
    return bundle[start:end]


def _delta_region(bundle: str) -> str:
    """The ERD-DELTA CONTEXT FILE block of the packed bundle."""
    marker = "=== CONTEXT FILE: scripts/.approved/ERD-DELTA.md ==="
    start = bundle.index(marker)
    end = bundle.index("=== END CONTEXT FILE ===", start)
    return bundle[start:end]


def test_tpm_pack_strips_decomposition_but_keeps_spec_slice(tmp_path):
    repo = _build_repo(tmp_path)
    r = subprocess.run(
        ["bash", "scripts/tpm-pack.sh"], cwd=str(repo),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    region = _delta_region(r.stdout)

    # kept: ACs, supersessions, changed files, test-to-file mapping
    assert "## Changed acceptance criteria" in region
    assert "AC-99" in region
    assert "## Superseded acceptance criteria" in region
    assert "## Changed files" in region
    assert "## Test-to-file mapping" in region
    assert "`tests/test_ui.py::test_widget` -> `src/static/app.js`" in region

    # stripped: coder briefs section (heading + body), DAG lines, Task order
    assert "Coder briefs (verbatim)" not in region
    assert "SENTINEL_BRIEF_BODY" not in region
    assert "depends on" not in region
    assert "Task order:" not in region
    # the emptied dedicated DAG heading must not survive as an orphan title
    assert "## Task DAG" not in region


def test_tpm_pack_strip_is_pack_only_orchestrate_reads_full_delta():
    """HARD CONSTRAINT: the strip is confined to tpm-pack.sh. The execution
    lane must not gain the strip — orchestrate.sh keeps assembling the full
    ERD-DELTA.md, and only tpm-pack.sh defines generate_delta_slice."""
    orch = (SCRIPTS / "orchestrate.sh").read_text()
    assert "generate_delta_slice" not in orch
    pack = (SCRIPTS / "tpm-pack.sh").read_text()
    assert "generate_delta_slice" in pack


def test_tpm_pack_stage1_ships_complete_interface_index_not_bodies(tmp_path):
    """D-141 stage 1: the contracts block is the COMPLETE interface index —
    every family's ids with pins, schema field NAMES only, never bodies, and
    never the standing inventory array."""
    repo = _build_contracts_repo(tmp_path)
    r = subprocess.run(
        ["bash", "scripts/tpm-pack.sh"], cwd=str(repo),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    region = _contracts_region(r.stdout)

    # complete: every interface of every family is visible, pinned or not
    for token in (
        "src.main:app", "src.api.chat:create_chat",
        "route:POST /api/v1/chat", "route:GET /",
        "schema:ChatRequest", "schema:Widget",
        "error:422-validation",
        "ui:message-input", "ui:unpinned-testid",
        '"by_file"', '"counts"', '"kind":"interface-index (D-141)"',
    ):
        assert token in region, token

    # grouped by owning file (compact index): pinned families are nested
    # under their file key — the path is written once, not on ~120 entries.
    assert '"routes":[{"id":"route:POST /api/v1/chat","method":"POST","path":"/api/v1/chat"}]' in region
    assert '"src/static/app.js":{"schemas":[{"id":"schema:Widget","fields":["label","count"]}]' in region

    # unpinned entries collate under a single "(unpinned)" key, not per entry
    assert '"id":"route:GET /","method":"GET","path":"/"' in region
    assert '"(unpinned)"' in region

    # entry points stay lossless as plain ids — no per-entry file field
    assert '"entry_points":["src.main:app","src.api.chat:create_chat"]' in region

    # interface = names + pins: schema field names are listed, body types not
    assert '"fields":["message","history"]' in region
    assert "array of HistoryEntry, optional, default []" not in region
    assert '"count":"integer"' not in region

    # the standing accumulated inventory is not an interface — no files list
    assert '"files":["src/api/chat.py"' not in region

    # the bundle tells the TPM how to request stage-2 bodies
    assert "tpm-pack.sh --contracts-for" in r.stdout


def test_tpm_pack_contracts_for_ships_bodies_for_named_files_only(tmp_path):
    """D-141 stage 2: --contracts-for delivers full bodies of exactly the
    requested owning files plus the conservative unpinned carries — and never
    bodies of unrequested owning files."""
    repo = _build_contracts_repo(tmp_path)
    r = subprocess.run(
        ["bash", "scripts/tpm-pack.sh", "--contracts-for", "src/api/chat.py"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "stage 2 of 2" in r.stdout
    region = _contracts_region(r.stdout)
    assert "full bodies" in region
    assert "array of HistoryEntry, optional, default []" in region  # unpinned carry
    assert '"message":"string"' in region
    assert "route:POST /api/v1/chat" in region  # pinned to chat.py
    assert "src.api.chat:create_chat" in region  # self-pins to chat.py
    assert "src.main:app" not in region          # self-pins to main.py — not requested
    assert "schema:Widget" not in region        # pinned to app.js — not requested
    assert "ui:message-input" not in region
    assert "interface-index" not in region

    r2 = subprocess.run(
        ["bash", "scripts/tpm-pack.sh", "--contracts-for", "src/static/app.js"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    region2 = _contracts_region(r2.stdout)
    assert '"count":"integer"' in region2       # Widget body present
    assert "route:POST /api/v1/chat" not in region2  # pinned to chat.py
    assert "error:422-validation" not in region2


def test_tpm_pack_contracts_for_requires_named_files(tmp_path):
    """--contracts-for without files is a usage error, not an empty slice."""
    repo = _build_contracts_repo(tmp_path)
    r = subprocess.run(
        ["bash", "scripts/tpm-pack.sh", "--contracts-for"],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "--contracts-for needs at least one file" in r.stderr


def test_tpm_pack_stage1_reports_active_inventory(tmp_path):
    """D-140: stage 1 notes the EXECUTOR's active build inventory distinct
    from the COMPLETE interface index — a consolidation shows none, so the
    next feature is authored against active scope, not the standing list."""
    repo = _build_contracts_repo(tmp_path)

    # legacy v99 must not shadow the modern v105 (numeric newest wins)
    (repo / "scripts" / ".approved" / "DELTA-v99.json").write_text(
        json.dumps({"version": 99, "changed_files": []}))
    # consolidation snapshot: inventory_files empty -> pack says none
    (repo / "scripts" / ".approved" / "DELTA-v105.json").write_text(
        json.dumps({"version": 105, "inventory_files": []}))
    r = subprocess.run(
        ["bash", "scripts/tpm-pack.sh"], cwd=str(repo),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "Active build inventory (D-140): none" in r.stdout
    assert "DELTA-v105.json is a consolidation" in r.stdout
    # the index stays COMPLETE regardless of the (empty) active inventory
    assert '"kind":"interface-index (D-141)"' in _contracts_region(r.stdout)

    # active snapshot with files -> names them, still no standing reintroduction
    (repo / "scripts" / ".approved" / "DELTA-v106.json").write_text(
        json.dumps({"version": 106,
                    "inventory_files": ["src/api/chat.py"]}))
    r2 = subprocess.run(
        ["bash", "scripts/tpm-pack.sh"], cwd=str(repo),
        capture_output=True, text=True,
    )
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    assert "Active build inventory (D-140): src/api/chat.py" in r2.stdout
