"""D-145 context byte-budget and no-expansion regression pins."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


SCRIPTS = Path(__file__).resolve().parent.parent
BUDGET_TOOL = SCRIPTS / "context-budget.py"


def run_budget(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the real D-145 budget tool."""
    return subprocess.run(
        [sys.executable, str(BUDGET_TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def load_budget_module() -> ModuleType:
    """Load the hyphenated helper so its pinned surface table is inspectable."""
    spec = importlib.util.spec_from_file_location("context_budget", BUDGET_TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_budget_limits_are_explicit_and_pinned() -> None:
    module = load_budget_module()
    assert module.SURFACE_BUDGETS == {
        "tpm-stage1": 88_000,
        "product-capsule": 8_192,
        "standing-summary": 8_192,
        "interface-index": 16_384,
        "em-context": 65_536,
        "escalation-shared": 32_768,
    }


def test_context_budget_warns_without_blocking() -> None:
    result = run_budget("warn-bytes", "tpm-stage1", "88001")
    assert result.returncode == 0
    assert "WARNING tpm-stage1 is 88001 bytes" in result.stderr
    assert "over by 1" in result.stderr

    within = run_budget("warn-bytes", "tpm-stage1", "88000")
    assert within.returncode == 0
    assert within.stderr == ""


def test_context_slice_larger_than_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sliced = tmp_path / "slice"
    source.write_bytes(b"1234")
    sliced.write_bytes(b"12345")

    result = run_budget("slice", "role-slice", str(sliced), str(source))

    assert result.returncode == 1
    assert "slice is 5 bytes" in result.stderr
    assert "4-byte source" in result.stderr


def test_context_slice_equal_or_smaller_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    sliced = tmp_path / "slice"
    source.write_bytes(b"12345")
    sliced.write_bytes(b"1234")
    assert run_budget(
        "slice", "standing-summary", str(sliced), str(source)
    ).returncode == 0
    sliced.write_bytes(source.read_bytes())
    assert run_budget(
        "slice", "standing-summary", str(sliced), str(source)
    ).returncode == 0


def test_contract_index_refuses_to_expand_its_source(tmp_path: Path) -> None:
    source = tmp_path / "contracts.json"
    source.write_text(json.dumps({"routes": []}))

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "contracts-delta.py"), "--index", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""


def test_all_context_surfaces_are_wired_to_the_budget_tool() -> None:
    pack = (SCRIPTS / "tpm-pack.sh").read_text()
    for invocation in (
        'accept_slice role-slice "$role_slice" docs/TPM-ROLE.md',
        'accept_slice schema-slice "$schema_slice" scripts/schemas/contracts.schema.json',
        'accept_slice product-capsule "$prd_slice" "$APPROVED/PRD.md"',
        'accept_slice standing-summary "$summary" "$APPROVED/ERD.md"',
        'accept_slice erd-delta-slice "$delta_slice" "$APPROVED/ERD-DELTA.md"',
        'accept_slice interface-index "$contracts_slice" "$APPROVED/contracts.json"',
        'accept_slice contracts-body-slice "$slice" "$APPROVED/contracts.json"',
        'warn-bytes tpm-stage1 "$OUT_BYTES"',
    ):
        assert invocation in pack

    orchestrate = (SCRIPTS / "orchestrate.sh").read_text()
    assert 'warn standing-summary "$STANDING_SUMMARY"' in orchestrate
    assert "warn em-context \\" in orchestrate
    assert '"$sys_prompt" "$schema" "$LOG_DIR/em-last.prompt"' in orchestrate
    assert 'warn escalation-shared "$shared"' in orchestrate
    assert '} > "$shared"' in orchestrate
