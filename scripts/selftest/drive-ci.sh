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

if [ -e no-gh ]; then
  # Scrub PATH down to the system dirs so `command -v gh` genuinely fails —
  # merely omitting the stub would still find a real gh installed on the host
  # and exercise a DIFFERENT branch than the one this case claims to test.
  export PATH="$PWD/fakebin:/usr/bin:/bin:/usr/sbin:/sbin"
  if command -v gh >/dev/null 2>&1; then
    echo "drive-ci: cannot test the gh-absent branch — gh is on the scrubbed PATH ($(command -v gh))" >&2
    exit 66
  fi
else
  export PATH="$PWD/fakebin:$PATH"
fi

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

extract() {
  local body
  body=$(sed -n "/^$1() {/,/^}/p" "$REPO/scripts/orchestrate.sh")
  printf '%s\n' "$body" | grep -q '^}' \
    || { echo "drive-ci: could not extract $1() from orchestrate.sh" >&2; exit 65; }
  printf '%s\n' "$body"
}
eval "$(extract check_ci_health)"

check_ci_health
echo "RC=$?"
