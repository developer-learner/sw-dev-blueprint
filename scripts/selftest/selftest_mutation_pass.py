"""Behavioral tests for D-161's report-only mutation measurement."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


RUNNER = Path(__file__).resolve().parents[1] / "mutation-pass.sh"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def child(tmp_path: Path) -> Path:
    repo = tmp_path / "child"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "calc.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    (repo / "src" / "unused.py").write_text("FLAG = True\n", encoding="utf-8")
    (repo / "tests" / "test_calc.py").write_text(
        "import unittest\n"
        "from src.calc import add\n\n"
        "class CalcTest(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Mutation Test",
        "-c",
        "user.email=mutation@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return repo


def _run(child: Path, mutants: Path, report: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(RUNNER),
            "--repo",
            str(child),
            "--mutants",
            str(mutants),
            "--suite",
            "python3 -m unittest discover -s tests -q",
            "--out",
            str(report),
        ],
        capture_output=True,
        text=True,
    )


def test_mutants_run_in_exact_head_clone_and_source_is_unchanged(
    child: Path, tmp_path: Path
) -> None:
    mutants = tmp_path / "mutants.tsv"
    mutants.write_text(
        "src/calc.py\treturn left + right\treturn left - right\taddition operator\n"
        "src/unused.py\tFLAG = True\tFLAG = False\tunused flag\n",
        encoding="utf-8",
    )
    before = _git(child, "status", "--porcelain").stdout
    report = tmp_path / "report.md"

    result = _run(child, mutants, report)

    assert result.returncode == 0, result.stderr
    assert "total=2 killed=1 survived=1 authoring_errors=0" in result.stdout
    report_text = report.read_text(encoding="utf-8")
    assert "1 killed; 1 survived" in report_text
    assert "`return left + right`" in report_text
    assert _git(child, "status", "--porcelain").stdout == before
    assert (child / "src" / "calc.py").read_text(encoding="utf-8").endswith(
        "return left + right\n"
    )


def test_dirty_green_checkout_cannot_mask_red_head(child: Path, tmp_path: Path) -> None:
    source = child / "src" / "calc.py"
    source.write_text(source.read_text().replace("left + right", "left - right"))
    _git(child, "add", "src/calc.py")
    _git(
        child,
        "-c",
        "user.name=Mutation Test",
        "-c",
        "user.email=mutation@example.invalid",
        "commit",
        "-qm",
        "red head",
    )
    source.write_text(source.read_text().replace("left - right", "left + right"))
    mutants = tmp_path / "mutants.tsv"
    mutants.write_text(
        "src/calc.py\treturn left - right\treturn left + right\toperator\n",
        encoding="utf-8",
    )

    result = _run(child, mutants, tmp_path / "report.md")

    assert result.returncode == 3
    assert "exact-HEAD baseline is not green" in result.stderr
    assert "return left + right" in source.read_text(encoding="utf-8")


def test_authoring_error_fails_loud_without_touching_source(
    child: Path, tmp_path: Path
) -> None:
    mutants = tmp_path / "mutants.tsv"
    mutants.write_text(
        "src/calc.py\tnot present\treplacement\tinvalid anchor\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.md"

    result = _run(child, mutants, report)

    assert result.returncode == 4
    assert "AUTHORING_ERROR" in result.stdout
    assert "find text occurs 0 times" in report.read_text(encoding="utf-8")
    assert _git(child, "status", "--porcelain").stdout == ""
