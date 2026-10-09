"""D-216: the coder's user message puts the file block FIRST and the brief +
reply rules LAST. With the instructions first and a large file last, the
coder (Qwen3.8 Flash Next) answered rich v1's prompt with a bare Read tool
call or prose about the code in 6 of 6 reproductions; file-first gave edit
blocks 6 of 6. run_coder and prefetch_launch share coder_prompt, so the
prefetch reuse (identical prompt) cannot drift from the sequential call.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "orchestrate.sh"


def fn(name: str) -> str:
    src = ORCH.read_text()
    return re.search(rf"^{name}\(\) \{{.*?^\}}", src, re.S | re.M).group(0)


def prompt(tmp_path: Path, file_exists: bool) -> str:
    target = tmp_path / "pkg" / "mod.py"
    if file_exists:
        target.parent.mkdir(parents=True)
        target.write_text("def existing():\n    return 1\n")
    script = (fn("build_context") + "\n" + fn("coder_prompt")
              + '\ncoder_prompt "pkg/mod.py" "BRIEF TEXT\nReply with ONLY edit blocks"\n')
    return subprocess.run(["bash", "-c", "set -euo pipefail\n" + script], cwd=tmp_path,
                          capture_output=True, text=True, check=True).stdout


def test_existing_file_comes_first_and_the_instructions_last(tmp_path):
    out = prompt(tmp_path, file_exists=True)
    assert out.index("### existing (pkg/mod.py)") < out.index("def existing()") < out.index("BRIEF TEXT")
    assert out.rstrip().endswith("Reply with ONLY edit blocks")


def test_create_mode_prompt_is_just_the_instructions(tmp_path):
    out = prompt(tmp_path, file_exists=False)
    assert out == "BRIEF TEXT\nReply with ONLY edit blocks\n"


def test_run_coder_and_prefetch_build_the_prompt_the_same_way():
    src = ORCH.read_text()
    assert src.count("coder_prompt \"") == 2, "both call sites use coder_prompt"
    assert not re.search(r'printf .%s\\n. "\$instr"; build_context "\$existing"', src)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
