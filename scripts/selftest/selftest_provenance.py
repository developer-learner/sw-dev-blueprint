"""selftest_provenance.py — T7 M1 (D-174): the trusted commit broker.

Fixture-driven (no live model): a temp git repo with a known ambient
identity, and the REAL scripts/git-provenance.sh sourced in a bash
subprocess — the same anti-drift pattern as selftest_plane_snapshot.py
(exercise the shipped bytes, not a copy of them).

Blind-test plan (M1 scope) from tasks/T7-provenance-decision.md:
  1. broker commit: author/committer/trailers exact
  2. prompt/reply hashes: planted bytes -> trailer values match
  3. model unset -> Swbp-Model: unset (never fabricated)
  4. provider-returned model preferred over the mapped env var
  5. source shape: every pipeline commit site routes through the broker
  6. run-id: stable across resume, new per spec version
  7. human role: ambient author, Swbp-Run: n/a
  8. guarded: nothing staged -> non-zero, no commit; bad role -> 2
(M2 signing tests land with M2, when the trust-anchor and evidence-
retention details are in place.)

Run:  pytest scripts/selftest/selftest_provenance.py -q
"""
import hashlib
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
BROKER = SCRIPTS / "git-provenance.sh"
REPO = HERE.parents[1]

AMBIENT_NAME = "Ambient Human"
AMBIENT_EMAIL = "ambient@example.com"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _mkrepo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", AMBIENT_NAME)
    _git(repo, "config", "user.email", AMBIENT_EMAIL)
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


def _run_broker(repo: Path, body: str, env_extra=None) -> subprocess.CompletedProcess:
    """Source the REAL broker in the fixture repo and run `body`."""
    script = (
        "set -euo pipefail\n"
        f"source {BROKER}\n"
        f"cd {repo}\n"
        + body
    )
    env = dict(os.environ)
    # The fixture's ambient identity is the committer; strip any ambient
    # model mapping so tests control the model source explicitly.
    for k in ("SWBP_EM_MODEL", "SWBP_CODER_MODEL", "SWBP_TPM_MODEL",
              "SWBP_PROV_MODEL", "SWBP_RUN_ID", "SWBP_PLANE_SHA",
              "SWBP_PROV_TASK", "SWBP_PROV_PROMPT_FILE", "SWBP_PROV_REPLY_FILE"):
        env.pop(k, None)
    env.update(env_extra or {})
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, cwd=str(repo), env=env)


def _log1(repo: Path, fmt: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "log", "-1",
                           f"--format={fmt}"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _trailers(repo: Path) -> dict:
    body = _log1(repo, "%B")
    return dict(line.split(": ", 1) for line in body.splitlines()
                if line.startswith("Swbp-"))


def test_broker_commit_author_committer_trailers(tmp_path):
    repo = _mkrepo(tmp_path)
    r = _run_broker(repo, 'echo "x" > f.txt\n'
                          'swbp_commit em "[plan] validated against spec v1" f.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123",
                               "SWBP_EM_MODEL": "Qwen3-Coder:30B",
                               "SWBP_PLANE_SHA": "deadbeefcafe"})
    assert r.returncode == 0, r.stderr
    assert _log1(repo, "%an") == "swbp-em-qwen3-coder-30b"
    assert _log1(repo, "%ae") == "swbp-em-qwen3-coder-30b@swbp.invalid"
    # committer is the ambient identity — author/committer separation
    assert _log1(repo, "%cn") == AMBIENT_NAME
    assert _log1(repo, "%ce") == AMBIENT_EMAIL
    assert _log1(repo, "%s") == "[plan] validated against spec v1"
    t = _trailers(repo)
    assert t["Swbp-Role"] == "em"
    assert t["Swbp-Model"] == "qwen3-coder-30b"
    assert t["Swbp-Run"] == "20260901T000000Z-abc123"
    assert t["Swbp-Plane"] == "deadbeefcafe"
    assert "Swbp-Task" not in t
    assert "Swbp-Prompt-SHA256" not in t


def test_prompt_reply_hashes_match_planted_bytes(tmp_path):
    repo = _mkrepo(tmp_path)
    prompt = b"the exact prompt bytes\n"
    reply = b'{"plan": true}\n'
    (repo / "p.txt").write_bytes(prompt)
    (repo / "r.json").write_bytes(reply)
    (repo / "f.txt").write_text("x\n")
    r = _run_broker(repo,
                    'swbp_commit coder "[task t1] attempt 1" f.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123",
                               "SWBP_CODER_MODEL": "coder-m",
                               "SWBP_PROV_TASK": "t1",
                               "SWBP_PROV_PROMPT_FILE": str(repo / "p.txt"),
                               "SWBP_PROV_REPLY_FILE": str(repo / "r.json")})
    assert r.returncode == 0, r.stderr
    t = _trailers(repo)
    assert t["Swbp-Prompt-SHA256"] == hashlib.sha256(prompt).hexdigest()
    assert t["Swbp-Reply-SHA256"] == hashlib.sha256(reply).hexdigest()
    assert t["Swbp-Task"] == "t1"
    # absent bytes -> trailer omitted, never a hash of nothing
    (repo / "f2.txt").write_text("y\n")
    r = _run_broker(repo, 'swbp_commit coder "[task t2] attempt 1" f2.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123",
                               "SWBP_CODER_MODEL": "coder-m",
                               "SWBP_PROV_PROMPT_FILE": str(repo / "missing.txt")})
    assert r.returncode == 0, r.stderr
    t = _trailers(repo)
    assert "Swbp-Prompt-SHA256" not in t
    assert "Swbp-Reply-SHA256" not in t


def test_model_unset_is_never_fabricated(tmp_path):
    repo = _mkrepo(tmp_path)
    (repo / "f.txt").write_text("x\n")
    r = _run_broker(repo, 'swbp_commit em "[plan] validated against spec v1" f.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123"})
    assert r.returncode == 0, r.stderr
    assert _trailers(repo)["Swbp-Model"] == "unset"
    assert _log1(repo, "%ae") == "swbp-em-unset@swbp.invalid"


def test_provider_returned_model_preferred_over_mapped(tmp_path):
    repo = _mkrepo(tmp_path)
    (repo / "f.txt").write_text("x\n")
    r = _run_broker(repo, 'swbp_commit em "[plan] validated against spec v1" f.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123",
                               "SWBP_EM_MODEL": "mapped-model",
                               "SWBP_PROV_MODEL": "served-model-x"})
    assert r.returncode == 0, r.stderr
    assert _trailers(repo)["Swbp-Model"] == "served-model-x"
    # and when the server reported nothing, the mapped model stands
    (repo / "f2.txt").write_text("y\n")
    r = _run_broker(repo, 'swbp_commit em "[plan] validated against spec v2" f2.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123",
                               "SWBP_EM_MODEL": "mapped-model",
                               "SWBP_PROV_MODEL": ""})
    assert r.returncode == 0, r.stderr
    assert _trailers(repo)["Swbp-Model"] == "mapped-model"


def test_run_id_stable_across_resume_new_per_spec(tmp_path):
    repo = _mkrepo(tmp_path)
    r = _run_broker(repo,
                    'id1=$(swbp_run_id 7)\n'
                    'id2=$(swbp_run_id 7)\n'
                    'id3=$(swbp_run_id 8)\n'
                    'echo "id1=$id1 id2=$id2 id3=$id3"\n')
    assert r.returncode == 0, r.stderr
    m = re.match(r"id1=(\S+) id2=(\S+) id3=(\S+)$", r.stdout.strip())
    assert m, r.stdout
    id1, id2, id3 = m.groups()
    assert id1 == id2, "resume with the same spec must reuse the run id"
    assert id1 != id3, "a new spec version starts a new attempt sequence"
    assert re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{6}", id1)


def test_human_role_ambient_author_na_run(tmp_path):
    repo = _mkrepo(tmp_path)
    (repo / "f.txt").write_text("x\n")
    r = _run_broker(repo, 'swbp_commit human "[template-update abc123456789]" f.txt\n')
    assert r.returncode == 0, r.stderr
    assert _log1(repo, "%an") == AMBIENT_NAME
    assert _log1(repo, "%ae") == AMBIENT_EMAIL
    assert _log1(repo, "%an") == _log1(repo, "%cn"), "human: author == committer"
    t = _trailers(repo)
    assert t["Swbp-Role"] == "human"
    assert t["Swbp-Model"] == "unset"
    assert t["Swbp-Run"] == "n/a"


def test_plane_falls_back_to_template_version_then_na(tmp_path):
    repo = _mkrepo(tmp_path)
    (repo / ".template-version").write_text("ref=abc123def456\n")
    (repo / "f.txt").write_text("x\n")
    r = _run_broker(repo, 'swbp_commit pipeline "[success] spec v1" f.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123"})
    assert r.returncode == 0, r.stderr
    assert _trailers(repo)["Swbp-Plane"] == "abc123def456"
    # no .template-version, no SWBP_PLANE_SHA -> "n/a"
    os.unlink(repo / ".template-version")
    (repo / "f2.txt").write_text("y\n")
    r = _run_broker(repo, 'swbp_commit pipeline "[success] spec v2" f2.txt\n',
                    env_extra={"SWBP_RUN_ID": "20260901T000000Z-abc123"})
    assert r.returncode == 0, r.stderr
    assert _trailers(repo)["Swbp-Plane"] == "n/a"


def test_guarded_nothing_staged_and_bad_role(tmp_path):
    repo = _mkrepo(tmp_path)
    before = _log1(repo, "%H")
    # nothing staged -> non-zero, no commit
    r = _run_broker(repo, 'swbp_commit em "subject" || echo "rc=$?"\n')
    assert r.returncode == 0, r.stderr
    assert "rc=1" in r.stdout
    assert _log1(repo, "%H") == before
    # bad role -> 2, no commit
    r = _run_broker(repo, 'swbp_commit wizard "subject" || echo "rc=$?"\n')
    assert r.returncode == 0, r.stderr
    assert "rc=2" in r.stdout
    assert _log1(repo, "%H") == before


def test_source_shape_all_pipeline_sites_route_through_broker():
    """A bare `git commit` at a pipeline site is exactly the hole T7 closes:
    the source shape IS the guarantee."""
    orch = (SCRIPTS / "orchestrate.sh").read_text()
    refreeze = (SCRIPTS / "refreeze.sh").read_text()
    update = (SCRIPTS / "update-template.sh").read_text()
    link = (SCRIPTS / "link-template.sh").read_text()
    bootstrap = (SCRIPTS / "bootstrap.sh").read_text()
    llm = (SCRIPTS / "llm-call.sh").read_text()

    # orchestrate: the three run commit sites
    assert 'swbp_commit em "[plan]' in orch
    assert 'swbp_commit coder "[task' in orch
    assert 'swbp_commit pipeline "$success_subject"' in orch
    for bare in ('git commit -m "[plan]', 'git commit -m "[task',
                 'git commit -m "$success_subject"'):
        assert bare not in orch, f"bare pipeline commit reappeared: {bare}"
    # the broker is sourced and the run id initialized after preflight
    assert 'source "$PLANE_DIR/scripts/git-provenance.sh"' in orch
    assert 'swbp_run_id "$FROZEN_V"' in orch
    # provider-returned model: meta sidecar at BOTH model call sites, and
    # the coder prompt is byte-captured (it was not archived before)
    assert orch.count("SWBP_LLM_META_OUT=") >= 2
    assert 'tee "$LOG_DIR/$id-a$attempt.prompt"' in orch
    assert "$FROZEN_V.$id.$coder_revs.$attempt.prompt" in orch

    # refreeze: the freeze commit
    assert 'swbp_commit tpm "[refreeze' in refreeze
    assert 'git commit -m "[refreeze' not in refreeze
    assert "source scripts/git-provenance.sh" in refreeze

    # update-template: all four template commit sites
    assert update.count("swbp_commit human") >= 4
    assert 'git commit -m "[template' not in update
    assert "source scripts/git-provenance.sh" in update

    # link-template: the link commit
    assert 'swbp_commit human "[template-link' in link
    assert 'git commit -m "[template-link' not in link
    assert "source scripts/git-provenance.sh" in link

    # bootstrap: the first commit of a greenfield child
    assert 'swbp_commit human "chore: bootstrap' in bootstrap
    assert 'git commit -m "chore: bootstrap' not in bootstrap

    # llm-call: the meta sidecar exists and is opt-in
    assert "SWBP_LLM_META_OUT" in llm


def test_llm_call_meta_sidecar_written_only_when_requested(tmp_path):
    """Behavioral: the sidecar carries the response envelope's OWN model/id
    when SWBP_LLM_META_OUT is set, and is a no-op (no file) when unset —
    existing callers are untouched. A local mock endpoint stands in for the
    model server; no live model is called."""
    import http.server
    import json
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.dumps({
                "id": "chatcmpl-test123",
                "model": "served-by-server",
                "choices": [{"message": {"role": "assistant",
                                         "content": "HELLO"},
                             "finish_reason": "stop"}],
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sysf = tmp_path / "sys.md"
        sysf.write_text("you are a test model")
        env = dict(os.environ)
        env["SWBP_EM_MODEL"] = "mapped-model"
        env["SANDBOX_LLM_HOST"] = "127.0.0.1"
        env["SANDBOX_LLM_PORT"] = str(port)
        meta = tmp_path / "meta.txt"
        env["SWBP_LLM_META_OUT"] = str(meta)
        r = subprocess.run(
            ["bash", str(SCRIPTS / "llm-call.sh"), "em", str(sysf),
             "--max-time", "10"],
            input="hi", capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "HELLO"
        assert meta.read_text() == \
            "model=served-by-server\ncall_id=chatcmpl-test123\n"
        # unset -> no file, same successful call
        env.pop("SWBP_LLM_META_OUT")
        r = subprocess.run(
            ["bash", str(SCRIPTS / "llm-call.sh"), "em", str(sysf),
             "--max-time", "10"],
            input="hi", capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "HELLO"
        assert not (tmp_path / "meta2.txt").exists()
    finally:
        srv.shutdown()
