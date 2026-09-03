"""Linked Blueprint distribution: one source, project-owned state only."""

import hashlib
import os
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
        "BLUEPRINT.md",
        "QUICKSTART.md",
        "scripts/git-provenance.sh",
        "scripts/link-template.sh",
        "scripts/phase-gate.sh",
        "scripts/regen-manifest.sh",
        "scripts/tool.sh",
        "scripts/update-template.sh",
    ]
    for rel in paths[:-2]:
        if rel.startswith("scripts/"):
            src = PLANE / rel.removeprefix("scripts/")
        else:
            src = PLANE.parent / rel
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    shutil.copy2(PLANE / "update-template.sh", source / "scripts/update-template.sh")
    (source / "scripts/tool.sh").write_text("#!/bin/sh\necho v1\n")
    (source / "scripts/tool.sh").chmod(0o755)
    (source / ".template-version").write_text("repo=fake/blueprint\nref=UNSTAMPED\n")
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


def test_linked_gate_worktree_hook_env_queries_blueprint_store(tmp_path):
    """Regression (linked worktree): git sets GIT_DIR to the (absolute)
    worktree gitdir in hook environments, and a bare `git -C <blueprint>`
    inherits it — querying the CHILD's object store instead of the
    Blueprint's, so the linked-ref check failed with 'lacks pinned ref'
    on every commit made from a linked worktree. The gate must clear the
    repo-local git env for that one call and still pass."""
    source, child, _c1, c2, _paths = _fixture(tmp_path)
    _approve_from_preview(source, child, c2)

    wt = tmp_path / "child-wt"
    _git(child, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    wt_gitdir = Path(_git(wt, "rev-parse", "--git-dir"))
    assert wt_gitdir.is_absolute(), \
        "worktree gitdir must be absolute — that is the bug trigger"

    # The hook environment git builds for a worktree: absolute GIT_DIR and
    # GIT_WORK_TREE, cwd at the worktree root.
    env = dict(os.environ)
    env["GIT_DIR"] = str(wt_gitdir)
    env["GIT_WORK_TREE"] = str(wt)
    result = subprocess.run(
        ["bash", "scripts/phase-gate.sh", "manifest"],
        cwd=wt, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "gate ok: manifest" in result.stdout


def test_born_linked_seed(tmp_path):
    """D-183: new-project.sh --linked creates a sibling child that is born in
    the linked state — every plane path a symlink into the blueprint, the
    child-owned files real, the manifests pinned, the gate green, and the
    blueprint checkout untouched."""
    source, _child, _c1, _c2, paths = _fixture(tmp_path)

    # Child-owned seed files in the fake blueprint (the real blueprint has all
    # of these; the fixture only needs what the assertions check).
    (source / "CLAUDE.md").write_text("# [PROJECT_NAME] ops\n")
    (source / "README.md").write_text("# [PROJECT_NAME]\n")
    (source / ".gitignore").write_text(".venv/\n.env\n")
    (source / ".gate-paths").write_text("\n")
    (source / "opencode.json").write_text("{}\n")
    (source / "Containerfile").write_text("FROM scratch\n")
    (source / "requirements.txt").write_text("fastapi\n")
    (source / ".dockerignore").write_text(".venv\n")
    (source / ".env.example").write_text("KEY=\n")
    (source / "CONVENTIONS.md").write_text("# conventions\n")
    (source / ".github/workflows/ci.yml").write_text("name: ci\n")
    _commit(source, "child-owned seed files")

    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "born-linked fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "born-linked fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    })
    result = subprocess.run(
        ["bash", str(PLANE / "new-project.sh"), "--linked", "bornchild",
         "--from", str(source), "--skip-bootstrap"],
        cwd=source, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)

    child = tmp_path / "bornchild"
    # Every plane path is a symlink into the source; check-drift stays a file.
    for rel in paths:
        if rel == ".github/workflows/check-drift.yml":
            assert (child / rel).is_file()
            assert not (child / rel).is_symlink()
        else:
            assert (child / rel).is_symlink(), rel
            assert (child / rel).resolve() == (source / rel).resolve(), rel
    # Child-owned files are real (not symlinks into the blueprint).
    for rel in ["CLAUDE.md", "README.md", ".gitignore",
                "docs/DECISIONS.md", "tasks/CURRENT.md", "tasks/BACKLOG.md",
                ".github/workflows/ci.yml"]:
        assert (child / rel).is_file(), rel
        assert not (child / rel).is_symlink(), rel
    # AGENTS.md is a child-internal symlink to CLAUDE.md (not into the blueprint).
    assert (child / "AGENTS.md").is_symlink()
    assert (child / "AGENTS.md").resolve() == (child / "CLAUDE.md").resolve()
    # The placeholder was renamed at seed time (no bootstrap in this mode).
    claudemd = (child / "CLAUDE.md").read_text()
    assert "[PROJECT_NAME]" not in claudemd
    assert "bornchild" in claudemd
    # Linked state: mode=linked, ref pinned to the source HEAD, no PENDING.
    assert (child / ".template-link").read_text().startswith("mode=linked\n")
    src_head = _git(source, "rev-parse", "HEAD")
    assert f"ref={src_head}" in (child / ".template-version").read_text()
    assert "PENDING" not in (child / "scripts/.manifest-project").read_text()
    # History: seed commit then the template-link conversion.
    log = _git(child, "log", "--format=%s")
    assert "born-linked from sw-dev-blueprint" in log
    assert "template-link" in log
    # The blueprint checkout was never written through the links.
    assert _git(source, "status", "--porcelain") == ""
    # The gate is green in the born-linked child.
    gate = subprocess.run(
        ["bash", "scripts/phase-gate.sh", "manifest"], cwd=child,
        capture_output=True, text=True,
    )
    assert gate.returncode == 0, gate.stdout
    assert "gate ok: manifest" in gate.stdout


def test_link_template_blocks_traversal_retired_path(tmp_path):
    """A retired path carrying `..` (a traversal out of the child) must be
    refused by the unsafe-retired-path guard, not deleted via `rm -f`.
    The child's template manifest lists `../outside.sh` — a row an update
    should never have — so the retire loop walks it on the next adoption."""
    source, child, _c1, c2, paths = _fixture(tmp_path)
    manifest = child / "scripts/.manifest-template"
    rows = manifest.read_text()
    rows += f"{'0' * 64}  ../outside.sh\n"
    manifest.write_text(rows)
    _commit(child, "fixture: manifest carries a traversal path")

    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\necho do-not-delete-me\n")

    preview = _run_link(source, child, c2, "--dry-run")
    assert preview.returncode == 0, preview.stderr
    plan_sha = re.search(r"PLAN-SHA: ([0-9a-f]{64})", preview.stdout)
    assert plan_sha, preview.stdout

    applied = subprocess.run(
        ["bash", str(source / "scripts/link-template.sh"),
         "--from", str(source), "--ref", c2, "--approve", plan_sha.group(1)],
        cwd=child, capture_output=True, text=True,
    )
    assert applied.returncode != 0, (applied.stdout, applied.stderr)
    assert "unsafe retired path: ../outside.sh" in applied.stderr, \
        (applied.stdout, applied.stderr)
    assert outside.exists(), "the guard must refuse before any rm runs"
    assert not (child / ".template-link").exists()
    for rel in paths:
        assert not (child / rel).is_symlink(), rel
