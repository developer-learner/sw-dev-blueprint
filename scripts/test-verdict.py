#!/usr/bin/env python3
"""Host-side pytest evidence validation. Never writes diagnostics into .cache.

prepare: refuse a symlinked cache and unlink the previous report safely.
<runner-status> [selector...]: compare the untrusted report with host-observed
status and frozen node IDs. Stdout is failure IDs then bounded detail; exit
0 = pass, 1 = failed acceptance, 3 = unavailable/inconsistent evidence.
copy <dest>: copy the report to a host-owned destination without following
symlinks (the escalation bundle ships externally — a planted link would read
a read-only mount and exfiltrate its target).
This is consistency checking, not attestation of hostile in-process pytest.
"""

import json
import os
import re
import secrets
import stat
import sys
from collections import Counter
from pathlib import Path

MAX_REPORT_BYTES = 64 * 1024 * 1024
OUTCOMES = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")


def cache_fd() -> int:
    return os.open(".cache", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def prepare(filename: str = "test-report.json") -> None:
    try:
        os.mkdir(".cache")
    except FileExistsError:
        pass
    fd = cache_fd()
    try:
        try:
            os.unlink(filename, dir_fd=fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(fd)


def read_report(filename: str = "test-report.json") -> dict:
    directory = cache_fd()
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("report must be a regular file with exactly one link")
            data = stream.read(MAX_REPORT_BYTES + 1)
            if len(data) > MAX_REPORT_BYTES:
                raise ValueError("report exceeds 64 MiB")
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ValueError("report is not an object")
            return result
    finally:
        os.close(directory)


def copy_report(dest: Path) -> None:
    directory = cache_fd()
    try:
        fd = os.open("test-report.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("report must be a regular file with exactly one link")
            data = stream.read(MAX_REPORT_BYTES + 1)
            if len(data) > MAX_REPORT_BYTES:
                raise ValueError("report exceeds 64 MiB")
    finally:
        os.close(directory)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(tmp, dest)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def expected_ids(selectors: list[str]) -> set[str]:
    frozen = {n.strip() for n in Path("scripts/.approved/test-nodeids").read_text().splitlines()
              if n.strip()}
    if not frozen:
        raise ValueError("frozen test-nodeids is empty")
    if not selectors or selectors == ["tests/"]:
        return frozen
    selected = set()
    for selector in selectors:
        matches = {n for n in frozen if n == selector or n.startswith(selector + "[")
                   or n.startswith(selector.rstrip("/") + "/")
                   or n.startswith(selector + "::")}
        if not matches:
            raise ValueError(f"selector has no frozen node IDs: {selector}")
        selected.update(matches)
    return selected


def build_dirs() -> tuple[str, ...]:
    """The build lane from .gate-paths build= (D-213), default src/."""
    try:
        for line in Path(".gate-paths").read_text().splitlines():
            if line.startswith("build="):
                dirs = tuple(d.rstrip("/") + "/" for d in line[6:].split())
                if dirs:
                    return dirs
    except OSError:
        pass
    return ("src/",)


def source_frames(phases: list[dict], limit: int = 3) -> str:
    """D-210: where in the IMPLEMENTATION a failure happened — the traceback
    frames under the build lane, innermost last — so a retry brief can point
    the coder at its own lines without showing it the frozen test's code.
    A pytest rootdir below the repo (rich: tests/pytest.ini) reports
    `../rich/x.py`; leading `../` is dropped before matching."""
    lanes = build_dirs()
    frames: list[str] = []
    for p in phases:
        tb = p.get("traceback")
        if not isinstance(tb, list):
            continue
        for entry in tb:
            if not isinstance(entry, dict):
                continue
            path, line = entry.get("path"), entry.get("lineno")
            while isinstance(path, str) and path.startswith("../"):
                path = path[3:]
            if isinstance(path, str) and path.startswith(lanes) and isinstance(line, int):
                frame = f"{path}:{line}"
                if frame not in frames:
                    frames.append(frame)
    return ", ".join(frames[-limit:])


def tail(value: object, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def emit(rc: int, label: str, detail: str = "") -> int:
    print(re.sub(r"[\r\n]", " ", label))
    print(tail(detail, 900))
    return rc


def skip_tolerated() -> set[str]:
    """D-215: node-ids whose SKIP is not a failure — only the D-112 dependent
    set of the milestone verdict, which the shell lists in the file named by
    SWBP_SKIP_TOLERATED_FILE. Those tests are pulled in to catch breakage; a
    platform-gated skip (rich: `Windows specific` on Linux) shows none.
    Mapped (spec) tests are never listed: for them a skip is no evidence."""
    path = os.environ.get("SWBP_SKIP_TOLERATED_FILE", "")
    if not path:
        return set()
    try:
        return {line.strip() for line in Path(path).read_text().splitlines() if line.strip()}
    except OSError:
        return set()


def verdict(r: dict, runner: int, expected: set[str]) -> int:
    tests, summary, collectors = r.get("tests"), r.get("summary"), r.get("collectors", [])
    if (not isinstance(tests, list) or not isinstance(summary, dict)
            or not isinstance(collectors, list)
            or any(not isinstance(c, dict) for c in collectors)):
        raise ValueError("invalid tests, summary or collectors")
    if type(r.get("exitcode")) is not int or r["exitcode"] != runner:
        raise ValueError(f"report exitcode disagrees with runner status {runner}")
    if type(summary.get("total")) is not int or summary["total"] != len(tests):
        raise ValueError("summary.total disagrees with test records")
    ids = []
    for t in tests:
        if (not isinstance(t, dict) or not isinstance(t.get("nodeid"), str)
                or not t["nodeid"] or t.get("outcome") not in OUTCOMES):
            raise ValueError("invalid test record")
        for phase in ("setup", "call", "teardown"):
            if phase in t and not isinstance(t[phase], dict):
                raise ValueError("invalid phase record")
        ids.append(t["nodeid"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate test node IDs")
    counts = Counter(t["outcome"] for t in tests)
    for outcome in OUTCOMES:
        count = summary.get(outcome, 0)
        if type(count) is not int or count != counts[outcome]:
            raise ValueError(f"summary.{outcome} disagrees with test records")
    failed_collectors = [c for c in collectors if c.get("outcome") == "failed"]
    if not tests and not failed_collectors:
        return emit(3, "NO_TESTS")
    if not failed_collectors and set(ids) != expected:
        raise ValueError(f"frozen test coverage mismatch: missing={sorted(expected - set(ids))}, "
                         f"unexpected={sorted(set(ids) - expected)}")
    failed, details = [], []
    tolerated = skip_tolerated()
    for t in tests:
        phases = [t.get(p, {}) for p in ("setup", "call", "teardown")]
        if (t["outcome"] == "skipped" and t["nodeid"] in tolerated
                and not any("wasxfail" in p for p in [t, *phases])
                and all(p.get("outcome") in ("passed", "skipped", None) for p in phases)):
            continue
        ordinary = (t["outcome"] == "passed"
                    and not any("wasxfail" in p for p in [t, *phases])
                    and all(p.get("outcome") == "passed" for p in phases))
        if ordinary:
            continue
        failed.append(t["nodeid"])
        reason = f"outcome={t['outcome']} (not an ordinary complete pass)"
        for p in phases:
            crash = p.get("crash") or {}
            if not isinstance(crash, dict):
                raise ValueError("invalid crash record")
            if crash.get("message") or p.get("longrepr"):
                reason = tail(crash.get("message") or p["longrepr"])
                break
        where = source_frames(phases)
        details.append(f"{t['nodeid']}: {reason}" + (f" [at {where}]" if where else ""))
    if failed_collectors:
        failed.append("COLLECTION_ERROR (see .cache/test-report.json)")
        details.append("collection: " + tail(failed_collectors[0].get("longrepr", "")))
    if runner not in (0, 1, 2):
        return emit(3, "RUNNER_ERROR", f"pytest/sandbox exited {runner}")
    if failed:
        return emit(1, "|".join(failed), " || ".join(details[:3]))
    if runner != 0:
        return emit(3, "RUNNER_ERROR", f"pytest/sandbox exited {runner} despite passed records")
    return 0


def redcheck() -> None:
    """Advisory pre-implementation result; no host writes into the cache."""
    report = read_report("redcheck-report.json")
    tests = report.get("tests")
    if not isinstance(tests, list) or any(
        not isinstance(t, dict) or not isinstance(t.get("nodeid"), str)
        for t in tests
    ):
        raise ValueError("invalid red-check test records")
    passed = sorted(t["nodeid"] for t in tests if t.get("outcome") == "passed")
    print("  red-check ran via: sandbox")
    if passed:
        Path(".pipeline-state").mkdir(exist_ok=True)
        Path(".pipeline-state/redcheck-already-green").touch()
        print("\n  WARNING (D-75): delta test(s) ALREADY PASS with no implementation done:")
        for node in passed:
            print(f"    {node}")
        print("  A test that never goes red gates nothing. Expected only for no_edit_files")
        print("  acceptance (D-65) or carried-forward behavior — anything else is a vacuous")
        print("  test: bounce it back to the TPM before running the pipeline.")
    else:
        print("  red-check: all delta tests red pre-implementation, as INV-1 expects")


def main() -> int:
    if sys.argv[1:] in (["prepare"], ["prepare-redcheck"]):
        try:
            prepare("redcheck-report.json" if sys.argv[1] == "prepare-redcheck"
                    else "test-report.json")
        except (OSError, ValueError) as exc:
            return emit(3, "UNSAFE_CACHE", str(exc))
        return 0
    if sys.argv[1:] == ["redcheck"]:
        try:
            redcheck()
        except (OSError, ValueError, TypeError) as exc:
            return emit(3, "INVALID_REDCHECK_REPORT", str(exc))
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "copy":
        try:
            copy_report(Path(sys.argv[2]))
        except (OSError, ValueError) as exc:
            return emit(3, "UNSAFE_REPORT_COPY", str(exc))
        return 0
    try:
        report = read_report()
    except FileNotFoundError:
        return emit(3, "NO_REPORT")
    except (OSError, ValueError) as exc:
        return emit(3, "INVALID_REPORT", str(exc))
    try:
        return verdict(report, int(sys.argv[1]), expected_ids(sys.argv[2:]))
    except (OSError, ValueError, TypeError, IndexError) as exc:
        return emit(3, "INVALID_REPORT", str(exc))


if __name__ == "__main__":
    sys.exit(main())
