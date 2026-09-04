#!/usr/bin/env python3
"""check-provenance.py — T7 M2 (D-184): the provenance verifier.

Verifies the Swbp-* provenance trail on a git rev range:

  1. signature   — every in-scope broker commit is GPG-signed; the signature
                   is cryptographically valid against the committed pub.asc
                   bundle (a dedicated temp keyring — the user's keyring is
                   never touched);
  2. trust anchor — the signing key's fingerprint is in the pinned list
                   (machine tier, CEO-only writer) and NOT in the revoked
                   list (revocation beats pinning, permanently);
  3. the hole    — a commit with a pipeline subject but no Swbp-Role trailer
                   is a non-broker pipeline commit: the exact gap M1 closes.
                   Gate mode fails on it.
  4. trailers    — role/model/run/plane well-formedness;
  5. evidence    — Swbp-Prompt-SHA256 / Swbp-Reply-SHA256 recomputed from the
                   commit's own tree (.swbp-evidence/<run>/<entry>/); a later
                   commit in the range modifying that run's evidence path is
                   tampering (evidence is append-only per run by
                   construction).

Attestation semantics (the ceiling, stated for the record): the Swbp-*
trailers record what the TRUSTED PIPELINE RECORDED — the model id it
observed on its own call path (provider-returned when the server reports
one, else the role's mapped model, else "unset"), the run, the task, the
plane, and the hashes of the prompt/reply bytes it archived. The GPG
signature attests that the pipeline's broker made this commit with these
trailer values. It does NOT independently prove which model generated a
reply; only the pipeline's own call path (llm-call.sh seat check, D-62) can
make that claim. The provider-returned model id / call id are the
server's own claims, recorded by the pipeline and attested by the
signature.

Scope boundary: pre-M2 history is out of scope — no retroactive signing.
The in-scope set starts at the first SIGNED broker commit in the range
(inclusive); everything before it is reported as "pre-m2" and skipped.
Once the pipeline signs, every subsequent in-scope pipeline commit must
verify. Non-pipeline commits (manual human commits) are out of scope
entirely — unsigned, not failed.

Usage:
  check-provenance.py [range] [--gate] [--pinned F] [--revoked F]
                      [--pub F] [--repo DIR]

  range     git rev range (default: HEAD~50..HEAD; CI passes the push range)
  --gate    gate mode: exit 1 on any in-scope failure (the M2b flip)
  --pinned  machine-tier pin file (default ~/.swbp/provenance/pinned-fingerprints)
  --revoked revocation file (default ~/.swbp/provenance/revoked-fingerprints)
  --pub     committed pub.asc bundle (default <repo>/scripts/.provenance/pub.asc)
  --repo    repo to verify (default: cwd)

Report mode (default): per-commit table, exit 0 — advisory (M2a).
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROLES = {"em", "coder", "tpm", "pipeline", "human"}
PIPELINE_SUBJECTS = (
    "[plan]", "[task ", "[success]", "[refreeze v", "[template-",
    "chore: bootstrap from sw-dev-blueprint template",
)
PGP_BEGIN = b"-----BEGIN PGP SIGNATURE-----"
PGP_END = b"-----END PGP SIGNATURE-----\n"
FPR_RE = re.compile(r"^[0-9A-Fa-f]{40}$")


def git(repo, *args, binary=False):
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args),
                                                  r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def commit_message(repo, sha):
    return git(repo, "log", "-1", "--format=%B", sha)


def commit_object(repo, sha):
    return git(repo, "cat-file", "commit", sha, binary=True)


def parse_trailers(message):
    """Swbp-* trailers: key -> value (last occurrence wins, git
    interpret-trailers semantics for our flat single-paragraph set)."""
    out = {}
    for line in message.splitlines():
        m = re.match(r"^(Swbp-[A-Za-z0-9-]+):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def is_pipeline_subject(subject):
    return any(subject.startswith(p) for p in PIPELINE_SUBJECTS)


def split_signature(obj):
    """Return (message_bytes, signature_bytes) or (obj, None) if unsigned.

    Handles both commit formats: the git >= 2.50 'gpgsig' header form and
    the legacy trailing-block form (older gits, e.g. CI images)."""
    # header form: gpgsig -----BEGIN PGP SIGNATURE----- ... END ...
    i = obj.find(b"gpgsig " + PGP_BEGIN)
    if i >= 0:
        line_start = obj.rfind(b"\n", 0, i) + 1
        e = obj.find(PGP_END, i)
        if e < 0:
            return obj, None
        end = e + len(PGP_END)
        sig = obj[i + len(b"gpgsig "):end]
        msg = obj[:line_start] + obj[end:]
        return msg, sig
    # legacy form: trailing block after a blank-line separator
    i = obj.find(PGP_BEGIN)
    if i >= 0:
        e = obj.find(PGP_END, i)
        if e < 0:
            return obj, None
        end = e + len(PGP_END)
        return obj[:i], obj[i:end]
    return obj, None


class GpgVerifier:
    """gpg --status-fd verification against a temp keyring holding the
    committed pub bundle. No network, no keyserver, user keyring untouched."""

    def __init__(self, pub_path):
        self.have_pub = pub_path is not None and os.path.exists(pub_path)
        self.home = None
        if self.have_pub:
            self.home = tempfile.mkdtemp(prefix="swbp-verify-")
            os.chmod(self.home, 0o700)
            r = subprocess.run(
                ["gpg", "--homedir", self.home, "--batch", "--import",
                 str(pub_path)],
                capture_output=True)
            self.have_pub = r.returncode == 0

    def verify(self, msg, sig):
        """Return (status, fingerprint): status in
        valid|bad|expired|error|no-pub."""
        if not self.have_pub:
            return "no-pub", None
        d = tempfile.mkdtemp(prefix="swbp-vfy-", dir=self.home)
        msg_f, sig_f = os.path.join(d, "msg"), os.path.join(d, "sig")
        with open(msg_f, "wb") as f:
            f.write(msg)
        with open(sig_f, "wb") as f:
            f.write(sig)
        r = subprocess.run(
            ["gpg", "--homedir", self.home, "--batch", "--status-fd", "1",
             "--verify", sig_f, msg_f],
            capture_output=True)
        status, fpr = "error", None
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("[GNUPG:] VALIDSIG "):
                status, fpr = "valid", line.split()[2]
            elif line.startswith("[GNUPG:] EXPSIG "):
                status, fpr = "expired", line.split()[2]
            elif line.startswith("[GNUPG:] BSIG "):
                status = "bad"
            elif line.startswith("[GNUPG:] ERRSIG "):
                status = "error"
        return status, fpr

    def close(self):
        if self.home:
            subprocess.run(["rm", "-rf", self.home], capture_output=True)


def read_fpr_list(path):
    out = set()
    if path and os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tok = line.split()[0]
            if FPR_RE.match(tok):
                out.add(tok.upper())
    return out


def evidence_added_in(repo, sha, run):
    """Evidence paths THIS commit added under .swbp-evidence/<run>/ (the
    commit's own entry — derived from its tree diff, no naming assumption)."""
    out = git(repo, "diff-tree", "--no-commit-id", "--name-only", "--diff-filter=A",
              "-r", sha, "--", ".swbp-evidence/%s/" % run, binary=False)
    return [p for p in out.splitlines() if p.strip()]


def later_touches_evidence(repo, sha, paths, all_shas):
    """Any commit NEWER than sha in the range that MODIFIES one of the
    original commit's own evidence paths (tampering). Adding NEW sibling
    entries under the same run directory is normal (a run's evidence is
    append-only per ENTRY, and a run has many entries)."""
    idx = all_shas.index(sha) if sha in all_shas else -1
    for newer in all_shas[idx + 1:]:
        out = git(repo, "diff-tree", "--no-commit-id", "--name-status", "-r",
                  newer, "--", *paths, binary=False)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] in ("M", "D", "T", "C"):
                return newer
    return None


def sha256_of_blob(repo, blob_ref):
    data = git(repo, "cat-file", "blob", blob_ref, binary=True)
    return hashlib.sha256(data).hexdigest()


def check_commit(repo, sha, gpg, pinned, revoked, all_shas):
    """Return (is_pipeline, in_scope_status, failures[list of str],
    table_row[dict])."""
    msg = commit_message(repo, sha)
    subject = msg.splitlines()[0] if msg.splitlines() else ""
    trailers = parse_trailers(msg)
    role = trailers.get("Swbp-Role", "")
    is_pipe = bool(role) or is_pipeline_subject(subject)

    obj = commit_object(repo, sha)
    _, sig = split_signature(obj)

    row = {
        "sha": sha[:10],
        "subject": subject[:56],
        "role": role or ("?" if is_pipe else "-"),
        "model": trailers.get("Swbp-Model", "-"),
        "run": trailers.get("Swbp-Run", "-"),
        "sig": "unsigned",
        "evidence": "-",
    }
    if not is_pipe:
        return False, "out-of-scope", [], row

    # signature
    failures = []
    msg_bytes, sig = split_signature(obj)
    if sig is None:
        row["sig"] = "missing"
    else:
        status, fpr = gpg.verify(msg_bytes, sig)
        if status == "valid":
            if fpr and fpr.upper() in revoked:
                row["sig"] = "revoked"
                failures.append("signing key %s is REVOKED (revocation beats pinning)" % fpr)
            elif fpr and fpr.upper() in pinned:
                row["sig"] = "valid"
            else:
                row["sig"] = "wrong-key"
                failures.append("signing key %s is not in the pinned list" % fpr)
        else:
            row["sig"] = status
            failures.append("signature %s (pub bundle: %s)"
                            % (status, "absent" if not gpg.have_pub else "mismatch"))

    # the hole: pipeline subject, no Swbp-Role
    if not role:
        failures.append("pipeline subject with no Swbp-Role trailer "
                        "(non-broker pipeline commit — the M1 hole)")

    # trailer well-formedness
    if role and role not in ROLES:
        failures.append("malformed Swbp-Role: %r" % role)
    model = trailers.get("Swbp-Model", "")
    if role and not re.match(r"^[a-z0-9._-]+$", model):
        failures.append("malformed Swbp-Model: %r" % model)
    run = trailers.get("Swbp-Run", "")
    if role and run != "n/a" and not re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$", run):
        failures.append("malformed Swbp-Run: %r" % run)

    # evidence
    p_sha = trailers.get("Swbp-Prompt-SHA256", "")
    r_sha = trailers.get("Swbp-Reply-SHA256", "")
    if p_sha or r_sha:
        if run == "n/a" or not run:
            failures.append("evidence trailers present but Swbp-Run is n/a")
            row["evidence"] = "absent"
        else:
            added = evidence_added_in(repo, sha, run)
            p_path = next((p for p in added if p.endswith("/prompt.txt")), None)
            r_path = next((p for p in added if p.endswith("/reply.raw")), None)
            ok = True
            if p_sha:
                if not p_path:
                    failures.append("Swbp-Prompt-SHA256 present but no prompt.txt "
                                    "added under .swbp-evidence/%s/" % run)
                    ok = False
                elif sha256_of_blob(repo, "%s:%s" % (sha, p_path)) != p_sha:
                    failures.append("prompt evidence hash mismatch (%s)" % p_path)
                    ok = False
            if r_sha:
                if not r_path:
                    failures.append("Swbp-Reply-SHA256 present but no reply.raw "
                                    "added under .swbp-evidence/%s/" % run)
                    ok = False
                elif sha256_of_blob(repo, "%s:%s" % (sha, r_path)) != r_sha:
                    failures.append("reply evidence hash mismatch (%s)" % r_path)
                    ok = False
            tamper = later_touches_evidence(repo, sha, added, all_shas)
            if tamper:
                failures.append("evidence tampered: %s modifies %s after "
                                "the evidence commit" % (tamper[:10],
                                                         ", ".join(added)))
                ok = False
            row["evidence"] = "matches" if ok else "mismatch"
    else:
        row["evidence"] = "n/a"

    return True, "pipeline", failures, row


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("range", nargs="?", default="HEAD~50..HEAD")
    ap.add_argument("--gate", action="store_true",
                    help="gate mode: exit 1 on any in-scope failure")
    ap.add_argument("--pinned", default=os.path.expanduser(
        "~/.swbp/provenance/pinned-fingerprints"))
    ap.add_argument("--revoked", default=os.path.expanduser(
        "~/.swbp/provenance/revoked-fingerprints"))
    ap.add_argument("--pub", default=None,
                    help="pub.asc bundle (default <repo>/scripts/.provenance/pub.asc)")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    pub = args.pub or os.path.join(repo, "scripts", ".provenance", "pub.asc")

    try:
        shas = git(repo, "rev-list", args.range).split()
    except RuntimeError:
        shas = git(repo, "rev-list", "HEAD").split()
    shas = list(reversed(shas))  # old -> new

    pinned = read_fpr_list(args.pinned)
    revoked = read_fpr_list(args.revoked)
    gpg = GpgVerifier(pub)

    # in-scope boundary: first SIGNED broker commit (inclusive)
    boundary = None
    for i, sha in enumerate(shas):
        try:
            trailers = parse_trailers(commit_message(repo, sha))
            if trailers.get("Swbp-Role"):
                _, sig = split_signature(commit_object(repo, sha))
                if sig is not None:
                    boundary = i
                    break
        except RuntimeError:
            continue

    rows, gate_failures = [], []
    for i, sha in enumerate(shas):
        try:
            is_pipe, status, failures, row = check_commit(
                repo, sha, gpg, pinned, revoked, shas)
        except RuntimeError as e:
            rows.append({"sha": sha[:10], "subject": "(unreadable)", "role": "-",
                         "model": "-", "run": "-", "sig": "error",
                         "evidence": "-"})
            if args.gate:
                gate_failures.append("%s: %s" % (sha[:10], e))
            continue
        row["scope"] = "in" if (is_pipe and boundary is not None and i >= boundary) \
            else ("pre-m2" if is_pipe else "out")
        rows.append(row)
        if is_pipe and boundary is not None and i >= boundary and failures:
            gate_failures.append("%s %s: %s" % (sha[:10], row["subject"][:40],
                                                "; ".join(failures)))

    gpg.close()

    # report (always printed; report mode exits 0)
    if not rows:
        print("check-provenance: no commits in range %s" % args.range)
        return 0
    w = {"sha": 10, "scope": 7, "role": 9, "model": 28, "run": 26,
         "sig": 10, "evidence": 9}
    hdr = "%(sha)-10s %(scope)-7s %(role)-9s %(model)-28s %(run)-26s %(sig)-10s %(evidence)-9s subject" % w
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print("%(sha)-10s %(scope)-7s %(role)-9s %(model)-28s %(run)-26s %(sig)-10s %(evidence)-9s %(subject)s" % r)
    n_pipe = sum(1 for r in rows if r["scope"] in ("in", "pre-m2"))
    print("-" * len(hdr))
    print("commits: %d (pipeline: %d, in-scope: %d, pre-m2: %d)  mode: %s"
          % (len(rows), n_pipe,
             sum(1 for r in rows if r["scope"] == "in"),
             sum(1 for r in rows if r["scope"] == "pre-m2"),
             "GATE" if args.gate else "report"))
    if args.gate:
        if gate_failures:
            print("\nGATE FAILURES (%d):" % len(gate_failures))
            for f in gate_failures:
                print("  - %s" % f)
            return 1
        print("gate ok: provenance")
        return 0
    if gate_failures:
        print("\n(advisory) %d in-scope failure(s) — report only in M2a; "
              "the M2b gate flip makes these a release failure" % len(gate_failures))
        for f in gate_failures:
            print("  - %s" % f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
