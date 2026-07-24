#!/usr/bin/env bash
# drive-ci.sh — selftest harness for orchestrate.sh's check_ci_health (D-85).
#
# Exercises the REAL function (extracted from orchestrate.sh at run time,
# never copied — a copy would silently drift), same contract as
# drive-consult.sh / drive-plan.sh / drive-coder.sh.
#
# The function reaches outside the repo in exactly two ways, both stubbed here
# by prepending a fake bin/ to PATH:
#   gh   — replays <workdir>/gh-output verbatim; exits <workdir>/gh-rc (default 0)
#   git  — real, but the workdir is a throwaway repo whose 'origin' remote and
#          branch the pytest side controls
#
# The point under test is the VERDICT MAPPING, which is where a CI-health gate
# goes wrong: green must pass, red must die, and every "cannot tell" path must
# say INCONCLUSIVE and proceed rather than imply green (Rule 4 / Rule 6 — an
# unobtainable answer is not a passing answer).
#
# Usage: drive-ci.sh <workdir>
# Workdir inputs (all optional):
#   gh-output          stdout the fake `gh run list` prints (JSON)
#   gh-rc              exit code for the fake gh (default 0)
#   no-gh              if present, gh is absent from PATH entirely
#   no-remote          if present, the repo has no 'origin' remote
#   detached           if present, the repo is left on a detached HEAD
# Env: SWBP_SKIP_CI_CHECK honored by the function itself.
#
# Stdout: the function's own output, then RC=<exit status>. A die (red CI)
# exits non-zero before RC= is printed — pytest asserts on both.
set -uo pipefail

WORK="${1:?usage: drive-ci.sh <workdir>}"
REPO=$(cd "$(dirname "$0")/../.." && pwd -P)

cd "$WORK"
mkdir -p fakebin

# --- Fake gh: replays a scripted payload -------------------------------------
if [ ! -e no-gh ]; then
  cat > fakebin/gh <<'STUB'
#!/usr/bin/env bash
# record the invocation so the test can assert the query shape
printf '%s\n' "$*" >> "$PWD/gh-calls"
rc=$(cat "$PWD/gh-rc" 2>/dev/null || echo 0)
[ -f "$PWD/gh-output" ] && cat "$PWD/gh-output"
exit "$rc"
STUB
  chmod +x fakebin/gh
fi

# `timeout` is used by the function; on a box without it (macOS without
# coreutils) provide a pass-through so the harness still exercises the logic.
if ! command -v timeout >/dev/null 2>&1; then
  cat > fakebin/timeout <<'STUB'
#!/usr/bin/env bash
shift   # drop the duration
exec "$@"
STUB
  chmod +x fakebin/timeout
fi

export PATH="$PWD/fakebin:$PATH"

# --- A throwaway repo the function can interrogate ----------------------------
git init -q . 2>/dev/null || true
git config user.email selftest@local
git config user.name selftest
git add -A 2>/dev/null || true
git commit -qm fixture --allow-empty
[ -e no-remote ] || git remote add origin https://example.invalid/o/r.git 2>/dev/null || true
[ -e detached ] && git checkout -q --detach

# --- Environment the extracted function expects ------------------------------
die() { echo "FAIL: $*" >&2; exit 1; }

# Extraction runs BEFORE any PATH scrubbing below — the harness's own machinery
# (sed, grep) must not be constrained by the environment we build for the
# function under test.
extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-ci: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract check_ci_health)"

if [ -e no-gh ]; then
  # `command -v gh` must genuinely fail. Omitting the stub is not enough — a
  # real gh on the host would be found and would exercise a DIFFERENT branch
  # than this case claims to test. Scrubbing to the system dirs is not enough
  # either: GitHub Actions runners ship gh at /usr/bin/gh, which is exactly
  # how CI caught this harness (2026-07-24).
  # So: build a directory holding ONLY the tools the FUNCTION needs (git,
  # python3, timeout) and make it the entire PATH, applied here — after
  # extraction — so the harness keeps its own tools. Deterministic on any
  # host, wherever gh happens to live.
  mkdir -p minbin
  for tool in git python3 timeout; do
    real=$(command -v "$tool" 2>/dev/null || true)
    if [ -n "$real" ]; then
      ln -sf "$real" "minbin/$tool"
    elif [ -x "fakebin/$tool" ]; then
      cp "fakebin/$tool" "minbin/$tool"   # e.g. the timeout shim above
    fi
  done
  export PATH="$PWD/minbin"
  if command -v gh >/dev/null 2>&1; then
    echo "drive-ci: cannot test the gh-absent branch — gh resolved on a PATH containing only $PWD/minbin ($(command -v gh))" >&2
    exit 66
  fi
fi

check_ci_health
echo "RC=$?"
