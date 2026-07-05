#!/usr/bin/env bash
# verify-sandbox-in-vm.sh — constraint-2 verification for HANDOFF-dev-vm.md.
# Proves sandbox-run.sh works under native Podman inside the Lima guest.
#
# Checks:
#   1. Image builds successfully (auto-rebuild on content hash).
#   2. Repo is mounted read-only (write attempt fails).
#   3. --rw lane is writable.
#   4. Network is disabled (curl/ping fail).
#   5. A pytest invocation in the sandbox completes (the orchestrate.sh pattern).
#
# Exit 0 = all checks pass. Non-zero = stop and report (per constraint 2).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$REPO"

pass=0; fail=0
check() {
  local label="$1"; shift
  if "$@"; then
    echo "  PASS: $label"
    pass=$((pass + 1))
  else
    echo "  FAIL: $label"
    fail=$((fail + 1))
  fi
}

echo "=== Constraint-2 sandbox verification (native Podman in Lima guest) ==="
echo "Repo: $REPO"
echo ""

# 0. Podman is native (not podman-machine)
echo "[0] Podman is native Linux..."
check "podman info succeeds" podman info >/dev/null 2>&1
OS=$(podman info --format '{{.Host.OS}}' 2>/dev/null || echo "unknown")
check "podman host OS is linux" [ "$OS" = "linux" ]
echo ""

# 1. Image auto-build
echo "[1] Image auto-build (content-hash tag)..."
STACK_HASH="$(cat "$REPO/Containerfile" "$REPO/requirements.txt" 2>/dev/null | sha256sum | cut -c1-12)"
IMAGE="swbp-sandbox:$STACK_HASH"
# Force a rebuild to verify it works
podman rmi "$IMAGE" >/dev/null 2>&1 || true
check "sandbox-run.sh builds image on demand" \
  scripts/sandbox-run.sh -- echo "image-ok"
check "image exists after run" podman image exists "$IMAGE"
echo ""

# 2. Read-only repo mount
echo "[2] Repo mounted read-only..."
# Try to write to a control-plane file — must fail
if scripts/sandbox-run.sh -- sh -c 'touch /work/scripts/SHOULD_NOT_EXIST 2>/dev/null'; then
  echo "  FAIL: write to /work/scripts succeeded (should be RO)"
  fail=$((fail + 1))
else
  echo "  PASS: write to /work/scripts blocked"
  pass=$((pass + 1))
fi
# Also try writing to repo root
if scripts/sandbox-run.sh -- sh -c 'touch /work/SHOULD_NOT_EXIST 2>/dev/null'; then
  echo "  FAIL: write to /work root succeeded (should be RO)"
  fail=$((fail + 1))
else
  echo "  PASS: write to /work root blocked"
  pass=$((pass + 1))
fi
echo ""

# 3. --rw lane is writable
echo "[3] --rw lane grants write access..."
mkdir -p .cache
check "--rw .cache allows write" \
  scripts/sandbox-run.sh --rw .cache -- sh -c 'echo "rw-ok" > /work/.cache/sandbox-test && cat /work/.cache/sandbox-test'
[ -f .cache/sandbox-test ] && rm -f .cache/sandbox-test
echo ""

# 4. Network disabled
echo "[4] Network isolation (--network none)..."
if scripts/sandbox-run.sh -- python3 -c 'import urllib.request; urllib.request.urlopen("http://1.1.1.1", timeout=2)' 2>/dev/null; then
  echo "  FAIL: network access succeeded (should be blocked)"
  fail=$((fail + 1))
else
  echo "  PASS: network access blocked"
  pass=$((pass + 1))
fi
echo ""

# 5. pytest runs (the orchestrate.sh pattern)
echo "[5] pytest invocation pattern..."
# Create a trivial test file to have something to run
mkdir -p .cache
cat > /tmp/test_sandbox_trivial.py <<'EOF'
def test_trivial():
    assert 1 + 1 == 2
EOF
mkdir -p tests
cp /tmp/test_sandbox_trivial.py tests/test_sandbox_trivial.py
check "pytest in sandbox succeeds" \
  scripts/sandbox-run.sh --rw .cache -- pytest -p no:cacheprovider \
    --json-report --json-report-file=.cache/test-report.json \
    tests/test_sandbox_trivial.py
check "test report written to RW lane" [ -f .cache/test-report.json ]
# Clean up
rm -f tests/test_sandbox_trivial.py .cache/test-report.json .cache/sandbox-test
rmdir tests 2>/dev/null || true
echo ""

# Summary
echo "=== Results: $pass passed, $fail failed ==="
if [ "$fail" -gt 0 ]; then
  echo "CONSTRAINT 2 VIOLATED — sandbox-run.sh does not work in this environment."
  echo "Do NOT proceed to further setup. Report this failure."
  exit 1
fi
echo "Constraint 2 satisfied: sandbox-run.sh works under native Podman in Lima guest."
exit 0
