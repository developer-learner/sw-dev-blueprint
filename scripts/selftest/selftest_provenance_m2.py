"""selftest_provenance_m2.py — T7 M2 (D-184): signing, trust anchor,
durable evidence, and the verifier.

Fixture-driven (no live model, no user keyring): a temp git repo, a
dedicated fixture gpg homedir under a fake HOME, pinned/revoked files
under that fake HOME, and the REAL scripts/git-provenance.sh sourced in
a bash subprocess (the anti-drift pattern of selftest_provenance.py —
exercise the shipped bytes, not a copy of them). The REAL
scripts/check-provenance.py runs as a subprocess against the fixture
repo.

Blind-test plan (M2 scope) from tasks/T7-m2-design.md §3.3:
  1. broker commit (fixture key) verifies: signature valid, fingerprint
     pinned, trailers well-formed, evidence hashes match
  2. wrong-key commit (different fixture key, not pinned) -> gate fails,
     names the fingerprint
  3. revoked fingerprint (pinned AND revoked) -> gate fails, names the
     revocation
  4. tampered evidence: a later commit modifies
     .swbp-evidence/<run>/.../prompt.txt -> gate fails, names the path
  5. non-broker pipeline commit: a bare `git commit` with subject
     `[task x] attempt 1` and no trailers -> gate fails (the hole)
  6. rotation overlap: two pinned fingerprints, commits signed by either
     -> both verify; after the first is revoked, its commits fail and the
     second's pass
  7. Swbp-Call-Id: present in meta -> trailer present and matching;
     absent -> trailer omitted (never fabricated)
  8. size guard: a planted 6MB reply -> broker refuses to commit
     (fail-closed), nothing staged
  9. report mode on the same failures: exit 0, every failure named in
     the table
 10. machine-tier and public-tier fingerprint lists agree (when both are
     present in the test env; the public tier lands with M2b)

Run:  pytest scripts/selftest/selftest_provenance_m2.py -q
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("gpg") is None,
    reason="T7 M2 selftests require gpg; not installed here")

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
BROKER = SCRIPTS / "git-provenance.sh"
VERIFIER = SCRIPTS / "check-provenance.py"
BLUEPRINT = HERE.parents[1]

UID = "swbp-provenance@swbp.invalid"
INTRUDER_UID = "intruder@swbp.invalid"
AMBIENT_NAME = "Ambient Human"
AMBIENT_EMAIL = "ambient@example.com"


# ---------------------------------------------------------------- fixture

def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr))
    return r


def _gpg(home, *args):
    return subprocess.run(["gpg", "--homedir", str(home), "--batch", *args],
                          capture_output=True, text=True)


def _fpr(gpg_home, uid=None):
    args = ["--list-keys", "--with-colons"] + ([uid] if uid else [])
    out = _gpg(gpg_home, *args).stdout
    fprs = [l.split(":")[9] for l in out.splitlines() if l.startswith("fpr:")]
    return fprs[0] if fprs else None


class Fixture:
    """fake HOME + temp repo + fixture key material.

    The fake HOME (which holds the gpg homedir) must live at a SHORT
    path: gpg-agent's socket is <homedir>/S.gpg-agent, and socket paths
    break past ~96 chars (macOS sun_path). pytest's tmp_path under
    /var/folders/... is too deep for that; /tmp (-> /private/tmp) keeps
    the socket at ~67. The git repo itself stays in tmp_path (no socket
    constraint)."""

    def __init__(self, tmp_path):
        self.home = Path("/tmp") / ("swbp-m2-%d-%s" % (os.getpid(),
                                                       uuid4().hex[:6]))
        (self.home / ".swbp/provenance").mkdir(parents=True)
        os.chmod(self.home, 0o700)
        self.gpg_home = self.home / ".swbp/provenance/gnupg"
        self.gpg_home.mkdir()
        os.chmod(self.gpg_home, 0o700)
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.name", AMBIENT_NAME)
        _git(self.repo, "config", "user.email", AMBIENT_EMAIL)
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / ".provenance").mkdir()
        (self.repo / "README.md").write_text("# fixture\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.pinned = self.home / ".swbp/provenance/pinned-fingerprints"
        self.revoked = self.home / ".swbp/provenance/revoked-fingerprints"
        self.pub = self.repo / "scripts" / ".provenance" / "pub.asc"
        self.run_id = "20260903T000000Z-abc123"

    def cleanup(self):
        subprocess.run(["rm", "-rf", str(self.home)], capture_output=True)

    def gen_key(self, uid=UID, expiry="never"):
        _gpg(self.gpg_home, "--pinentry-mode", "loopback", "--passphrase", "",
             "--quick-generate-key", uid, "ed25519", "sign", expiry)
        return _fpr(self.gpg_home, uid)

    def set_active(self, fpr):
        (self.home / ".swbp/provenance/active").write_text(fpr + "\n")

    def pin(self, fpr, note="test"):
        with open(self.pinned, "a") as f:
            f.write("%s  # %s\n" % (fpr, note))

    def revoke(self, fpr, marker="revoked"):
        if self.pinned.exists():
            lines = [l for l in self.pinned.read_text().splitlines()
                     if not l.startswith(fpr)]
            self.pinned.write_text("\n".join(lines) + "\n")
        with open(self.revoked, "a") as f:
            f.write("%s  # %s\n" % (fpr, marker))

    def export_pub(self):
        out = _gpg(self.gpg_home, "--armor", "--export")
        assert out.returncode == 0, out.stderr
        self.pub.write_text(out.stdout)

    def broker(self, role, subject, files=(), env=()):
        """Run the REAL broker in a bash subprocess under the fake HOME."""
        env_lines = "\n".join("export %s" % e for e in env)
        files_args = " ".join('"%s"' % f for f in files)
        script = (
            "set -u\n"
            "source \"%s\"\n"
            "%s\n"
            "swbp_commit %s \"%s\" %s\n" % (BROKER, env_lines, role, subject,
                                            files_args)
        )
        e = dict(os.environ)
        e["HOME"] = str(self.home)
        return subprocess.run(["bash", "-c", script], cwd=str(self.repo),
                              env=e, capture_output=True, text=True)

    def cli(self, *args):
        """Run the REAL key-management CLI under the fake HOME."""
        e = dict(os.environ)
        e["HOME"] = str(self.home)
        return subprocess.run(["bash", BROKER, *args], env=e,
                              capture_output=True, text=True)

    def plain_commit(self, subject, file=None, content=None):
        """A NON-broker commit (the hole / the tamperer). Always commits a
        real file (a bare empty commit would not model the hole: a
        pipeline-style change committed outside the broker)."""
        if file is None:
            n = len(list(self.repo.glob("manual-*.txt")))
            file = "manual-%d.txt" % n
        if content is None:
            content = ("manual change %s\n" % subject).encode()
        p = self.repo / file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        _git(self.repo, "add", file)
        _git(self.repo, "commit", "-q", "-m", subject)

    def verifier(self, *extra, gate=False):
        args = [str(VERIFIER), "HEAD~20..HEAD",
                "--pinned", str(self.pinned),
                "--revoked", str(self.revoked),
                "--pub", str(self.pub),
                "--repo", str(self.repo)]
        if gate:
            args.append("--gate")
        args += list(extra)
        return subprocess.run([sys_python(), *args],
                              capture_output=True, text=True)

    def make_evidence_src(self, prompt=b"prompt bytes",
                          reply=b"reply bytes",
                          meta=b"model=fixture-model\ncall_id=cid-1\n"):
        d = self.repo / "evsrc"
        d.mkdir(exist_ok=True)
        (d / "prompt.txt").write_bytes(prompt)
        (d / "reply.raw").write_bytes(reply)
        (d / "meta.txt").write_bytes(meta)
        return d

    def task_env(self, entry, call_id=None, meta_file=True):
        env = [
            "SWBP_RUN_ID=%s" % self.run_id,
            "SWBP_PROV_ENTRY=%s" % entry,
            "SWBP_PROV_TASK=T1",
            "SWBP_PROV_MODEL=fixture-model",
            "SWBP_PROV_PROMPT_FILE=%s" % (self.repo / "evsrc/prompt.txt"),
            "SWBP_PROV_REPLY_FILE=%s" % (self.repo / "evsrc/reply.raw"),
        ]
        if meta_file:
            env.append("SWBP_PROV_META_FILE=%s" % (self.repo / "evsrc/meta.txt"))
        if call_id is not None:
            env.append("SWBP_PROV_CALL_ID=%s" % call_id)
        return env


def sys_python():
    return sys.executable or "python3"


@pytest.fixture
def fx(tmp_path):
    f = Fixture(tmp_path)
    yield f
    f.cleanup()


# ------------------------------------------------------------------ tests

def test_1_broker_commit_verifies(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.export_pub()
    fx.make_evidence_src()
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1", call_id="cid-1"))
    assert r.returncode == 0, r.stderr
    # report mode: clean
    v = fx.verifier()
    assert v.returncode == 0, v.stdout + v.stderr
    assert "valid" in v.stdout
    assert "matches" in v.stdout
    # gate mode: ok
    g = fx.verifier(gate=True)
    assert g.returncode == 0, g.stdout
    assert "gate ok: provenance" in g.stdout


def test_2_wrong_key_fails_gate(fx):
    fpr_a = fx.gen_key(UID)
    fpr_b = fx.gen_key(INTRUDER_UID)
    fx.pin(fpr_a)  # A pinned, B not
    fx.set_active(fpr_b)  # broker signs with B
    fx.export_pub()  # bundle holds both — the sig is cryptographically
    # valid; the FINGERPRINT check is what gate mode trusts
    fx.make_evidence_src()
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode == 0, r.stderr
    g = fx.verifier(gate=True)
    assert g.returncode == 1, g.stdout
    assert fpr_b in g.stdout  # names the fingerprint
    assert "not in the pinned list" in g.stdout


def test_3_revoked_fails_gate(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.revoke(fpr)  # pinned AND revoked -> revoked wins
    fx.export_pub()
    fx.make_evidence_src()
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode == 0, r.stderr
    g = fx.verifier(gate=True)
    assert g.returncode == 1, g.stdout
    assert "REVOKED" in g.stdout
    assert fpr in g.stdout


def test_4_tampered_evidence_fails_gate(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.export_pub()
    fx.make_evidence_src()
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode == 0, r.stderr
    # a later commit modifies the run's evidence path
    fx.plain_commit("harmless follow-up",
                    file=".swbp-evidence/%s/T1-a1/prompt.txt" % fx.run_id,
                    content=b"tampered prompt")
    g = fx.verifier(gate=True)
    assert g.returncode == 1, g.stdout
    assert "tampered" in g.stdout
    assert "prompt.txt" in g.stdout


def test_5_hole_fails_gate(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.export_pub()
    fx.make_evidence_src()
    # a signed broker commit first — establishes the in-scope boundary
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode == 0, r.stderr
    # then a bare pipeline-subject commit with no trailers (the hole)
    fx.plain_commit("[task T2] attempt 1")
    g = fx.verifier(gate=True)
    assert g.returncode == 1, g.stdout
    assert "no Swbp-Role" in g.stdout


def test_6_rotation_overlap(fx):
    fpr_a = fx.gen_key(UID)
    fpr_b = fx.gen_key(INTRUDER_UID)  # same role, different key
    fx.pin(fpr_a)
    fx.pin(fpr_b)
    fx.export_pub()  # bundle: both keys
    fx.make_evidence_src()
    fx.set_active(fpr_a)
    r1 = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                   env=fx.task_env("T1-a1"))
    assert r1.returncode == 0, r1.stderr
    (fx.repo / "README.md").write_text("# fixture v2\n")
    fx.set_active(fpr_b)
    r2 = fx.broker("coder", "[task T1] attempt 2", files=["README.md"],
                   env=fx.task_env("T1-a2"))
    assert r2.returncode == 0, r2.stderr
    # overlap: both verify
    g = fx.verifier(gate=True)
    assert g.returncode == 0, g.stdout
    # retire A after the clean cycle: A's commits fail, B's pass
    fx.revoke(fpr_a, marker="retired")
    g2 = fx.verifier(gate=True)
    assert g2.returncode == 1, g2.stdout
    assert fpr_a in g2.stdout
    assert "REVOKED" in g2.stdout
    # the CLI rotate path: generate a SECOND key in the same homedir
    # (unique uid — gpg refuses duplicate uids), switch active, pin it
    r3 = fx.cli("rotate")
    assert r3.returncode == 0, r3.stderr
    new_active = (fx.home / ".swbp/provenance/active").read_text().strip()
    assert new_active not in (fpr_a, fpr_b)
    assert new_active in fx.pinned.read_text()


def test_7_call_id_trailer(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.export_pub()
    # present in meta -> trailer present and matching
    fx.make_evidence_src(meta=b"model=fixture-model\ncall_id=cid-42\n")
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1", call_id="cid-42"))
    assert r.returncode == 0, r.stderr
    msg = _git(fx.repo, "log", "-1", "--format=%B").stdout
    assert "Swbp-Call-Id: cid-42" in msg
    # absent -> trailer omitted (never fabricated)
    (fx.repo / "README.md").write_text("# fixture v2\n")
    fx.make_evidence_src(meta=b"model=fixture-model\ncall_id=\n")
    r2 = fx.broker("coder", "[task T1] attempt 2", files=["README.md"],
                   env=fx.task_env("T1-a2", call_id=None))
    assert r2.returncode == 0, r2.stderr
    msg2 = _git(fx.repo, "log", "-1", "--format=%B").stdout
    assert "Swbp-Call-Id" not in msg2


def test_8_size_guard_fails_closed(fx):
    fpr = fx.gen_key()
    fx.pin(fpr)
    fx.export_pub()
    fx.make_evidence_src(reply=b"x" * (6 * 1024 * 1024))  # 6MB > 5MB
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode != 0, "size guard must refuse"
    assert "5MB" in r.stderr
    # no commit, nothing staged
    n = int(_git(fx.repo, "rev-list", "--count", "HEAD").stdout.strip())
    assert n == 1, "no commit may be created"
    assert _git(fx.repo, "diff", "--cached", "--quiet")
    assert not (fx.repo / ".swbp-evidence").exists()


def test_9_report_mode_exit0_names_every_failure(fx):
    fpr_a = fx.gen_key(UID)
    fpr_b = fx.gen_key(INTRUDER_UID)
    fx.pin(fpr_a)
    fx.set_active(fpr_b)  # wrong key
    fx.export_pub()
    fx.make_evidence_src()
    r = fx.broker("coder", "[task T1] attempt 1", files=["README.md"],
                  env=fx.task_env("T1-a1"))
    assert r.returncode == 0, r.stderr
    fx.plain_commit("[task T2] attempt 1")  # the hole
    v = fx.verifier()  # report mode
    assert v.returncode == 0, "report mode must exit 0"
    assert "not in the pinned list" in v.stdout
    assert "no Swbp-Role" in v.stdout
    assert "(advisory)" in v.stdout


def test_10_machine_public_tier_agree():
    """Machine tier (this test's env) and public tier
    (docs/PROVENANCE.md) fingerprint lists agree when both are present.
    The public tier lands with M2b — until then this passes vacuously."""
    pub_md = BLUEPRINT / "docs" / "PROVENANCE.md"
    machine = Path(os.path.expanduser("~/.swbp/provenance/pinned-fingerprints"))
    if not pub_md.exists() or not machine.exists():
        pytest.skip("public tier (M2b) or machine tier not present in this env")
    import re
    fpr_re = re.compile(r"^[0-9A-Fa-f]{40}$")
    pub = set()
    for line in pub_md.read_text().splitlines():
        for tok in line.split():
            if fpr_re.match(tok):
                pub.add(tok.upper())
    mach = set()
    for line in machine.read_text().splitlines():
        tok = line.split()[0] if line.split() else ""
        if fpr_re.match(tok):
            mach.add(tok.upper())
    assert pub == mach, "machine tier and public tier fingerprint lists disagree"
