"""Linked Blueprint distribution: one source, project-owned state only."""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLANE = HERE.parent


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_template_manifest(source: Path, paths: list[str]) -> None:
    manifest = source / "scripts" / ".manifest-template"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(f"{_hash(source / p)}  {p}\n" for p in paths))


def _fixture(tmp_path: Path) -> tuple[Path, Path, str, str, list[str]]:
    source = tmp_path / "blueprint"
    child = tmp_path / "child"
    paths = [
        ".github/workflows/check-drift.yml",
        "scripts/link-template.sh",
        "scripts/phase-gate.sh",
        "scripts/regen-manifest.sh",
        "scripts/tool.sh",
        "scripts/update-template.sh",
    ]
    for rel in paths[:-2]:
        src = PLANE.parent / rel if rel.startswith(".github") else PLANE / rel.removeprefix("scripts/")
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    shutil.copy2(PLANE / "update-template.sh", source / "scripts/update-template.sh")
    (source / "scripts/tool.sh").write_text("#!/bin/sh\necho v1\n")
    (source / "scripts/tool.sh").chmod(0o755)
    _write_template_manifest(source, paths)
    _git(source, "init", "-q", "-b", "main")
    c1 = _commit(source, "v1")

    # The child starts in ordinary D-34 copied mode at c1.
    for rel in paths:
        dest = child / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dest)
    (child / "scripts/.manifest-template").write_bytes(
        (source / "scripts/.manifest-template").read_bytes()
    )
    (child / ".template-version").write_text(f"repo=fake/blueprint\nref={c1}\n")
    project_hash = _hash(child / ".template-version")
    (child / "scripts/.manifest-project").write_text(
        f"{project_hash}  .template-version\n"
    )
    _git(child, "init", "-q", "-b", "main")
    # link-template.sh creates a real adoption commit. Hosted CI runners have
    # no global identity, so the fixture must provide its own repository-local
    # author instead of inheriting a developer workstation's configuration.
    _git(child, "config", "user.email", "fixture@example.invalid")
    _git(child, "config", "user.name", "linked-template fixture")
    _commit(child, "copied child")

    (source / "scripts/tool.sh").write_text("#!/bin/sh\necho v2\n")
    _write_template_manifest(source, paths)
    c2 = _commit(source, "v2")
    return source, child, c1, c2, paths


def _run_link(source: Path, child: Path, ref: str, *mode: str):
    return subprocess.run(
        ["bash", str(source / "scripts/link-template.sh"),
         "--from", str(source), "--ref", ref, *mode],
        cwd=child, capture_output=True, text=True,
    )


def _approve_from_preview(source: Path, child: Path, ref: str):
    preview = _run_link(source, child, ref, "--dry-run")
    assert preview.returncode == 0, preview.stderr
    match = re.search(r"PLAN-SHA: ([0-9a-f]{64})", preview.stdout)
    assert match, preview.stdout
    applied = _run_link(source, child, ref, "--approve", match.group(1))
    assert applied.returncode == 0, applied.stderr
    return applied


def test_copy_to_link_migration_and_linked_update(tmp_path):
    source, child, _c1, c2, paths = _fixture(tmp_path)
    _approve_from_preview(source, child, c2)

    assert (child / ".template-link").read_text().startswith("mode=linked\n")
    assert (child / ".github/workflows/check-drift.yml").is_file()
    assert not (child / ".github/workflows/check-drift.yml").is_symlink()
    for rel in paths:
        if rel == ".github/workflows/check-drift.yml":
            continue
        assert (child / rel).is_symlink(), rel
        assert (child / rel).resolve() == (source / rel).resolve()
    assert f"ref={c2}" in (child / ".template-version").read_text()
    assert _git(child, "status", "--porcelain") == ""
    assert _git(source, "status", "--porcelain") == "", \
        "migration must never write through links into Blueprint"

    # A later ordinary update-template call delegates to linked mode, adds a
    # new source path as a symlink, and again leaves Blueprint untouched.
    new_rel = "scripts/new-tool.sh"
    (source / new_rel).write_text("#!/bin/sh\necho new\n")
    next_paths = paths + [new_rel]
    _write_template_manifest(source, next_paths)
    c3 = _commit(source, "v3 adds tool")
    preview = subprocess.run(
        ["bash", "scripts/update-template.sh", "--from", str(source),
         "--ref", c3, "--dry-run"], cwd=child,
        capture_output=True, text=True,
    )
    assert preview.returncode == 0, preview.stderr
    plan_sha = re.search(r"PLAN-SHA: ([0-9a-f]{64})", preview.stdout)
    assert plan_sha
    applied = subprocess.run(
        ["bash", "scripts/update-template.sh", "--from", str(source),
         "--ref", c3, "--approve", plan_sha.group(1)], cwd=child,
        capture_output=True, text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert (child / new_rel).is_symlink()
    assert (child / new_rel).resolve() == (source / new_rel).resolve()
    assert f"ref={c3}" in (child / ".template-version").read_text()
    assert _git(source, "status", "--porcelain") == ""


def test_linked_gate_rejects_local_copy_even_when_bytes_match(tmp_path):
    source, child, _c1, c2, _paths = _fixture(tmp_path)
    _approve_from_preview(source, child, c2)
    tool = child / "scripts/tool.sh"
    body = tool.read_bytes()
    tool.unlink()
    tool.write_bytes(body)
    result = subprocess.run(
        ["bash", "scripts/phase-gate.sh", "manifest"], cwd=child,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "linked-plane path is not a symlink" in result.stdout


def test_link_template_rejects_wrong_approval_hash_accepts_correct(tmp_path):
    """The --approve gate must compare the supplied hash against the previewed
    PLAN-SHA: a mismatch dies without touching the child, the correct hash is
    accepted and the plan applies. Drives both directions of the comparison."""
    source, child, _c1, c2, _paths = _fixture(tmp_path)
    preview = _run_link(source, child, c2, "--dry-run")
    assert preview.returncode == 0, preview.stderr
    match = re.search(r"PLAN-SHA: ([0-9a-f]{64})", preview.stdout)
    assert match, preview.stdout

    wrong = subprocess.run(
        ["bash", str(source / "scripts/link-template.sh"),
         "--from", str(source), "--ref", c2, "--approve", "0" * 64],
        cwd=child, capture_output=True, text=True,
    )
    assert wrong.returncode != 0, (wrong.stdout, wrong.stderr)
    assert "approval hash mismatch" in wrong.stderr, (wrong.stdout, wrong.stderr)
    assert not (child / ".template-link").exists(), \
        "a rejected approval hash must apply nothing"
    assert f"ref={c2}" not in (child / ".template-version").read_text()

    _approve_from_preview(source, child, c2)
    assert (child / ".template-link").read_text().startswith("mode=linked\n")
    assert f"ref={c2}" in (child / ".template-version").read_text()
    assert _git(child, "status", "--porcelain") == ""
