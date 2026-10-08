#!/usr/bin/env bash
# e2e-sim.sh — a full milestone through the REAL pipeline with scripted models
# (D-208). Run on the Mac; the build happens inside the dev VM.
#
# 1. builds a throwaway builder-targeted app on the host (the linkbox spec
#    from examples/minimal-spec, pinned to this builder's HEAD);
# 2. copies it into the VM with scripts/vm-sync start (spec staging and the
#    fake model server go across as --copy-file, never committed);
# 3. in the VM: starts scripts/selftest/e2e_fake_llm.py, freezes the spec
#    with `swbp refreeze`, builds it with `swbp orchestrate` — real gates,
#    real Podman sandbox, real llm-call.sh pointed at the fake server;
# 4. lands the run back on the host with scripts/vm-sync land;
# 5. checks: the milestone reached [success]; the catch ledger that came home
#    holds the gates the scripted misbehaviour must trip (validate-plan,
#    coder-spec-report, coder-reply-format, test-verdict); the spec report
#    skipped the retry and reached the EM consult.
#
# Needs: the dev VM running, the builder HEAD pushed or present in the
# mounted ~/dev/sw-dev-blueprint, the sandbox image for this Containerfile
# (built on first use). Not part of the pytest suite: it drives a VM.
#
# Usage: scripts/selftest/e2e-sim.sh [--keep]
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd -P)"
BUILDER="$(cd "$HERE/../.." && pwd -P)"
MOUNTED_BUILDER="${SWBP_E2E_MOUNTED_BUILDER:-$HOME/dev/sw-dev-blueprint}"
LINKBOX_SRC="${SWBP_E2E_LINKBOX_SRC:-$HOME/dev/linkbox/src}"
KEEP=0; [ "${1:-}" = "--keep" ] && KEEP=1
VS="$BUILDER/scripts/vm-sync"
PORT=18765
fail() { echo "E2E FAIL: $*" >&2; exit 1; }
ok() { echo "  ok: $*"; }

PIN="${SWBP_E2E_PIN:-$(git -C "$MOUNTED_BUILDER" rev-parse HEAD)}"
[ -f "$LINKBOX_SRC/storage.py" ] && [ -f "$LINKBOX_SRC/api.py" ] \
  || fail "correct reference sources not found in $LINKBOX_SRC"
limactl list 2>/dev/null | grep -q "^dev-vm *Running" || fail "dev VM is not running"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/e2e-sim.XXXXXX")"
APP="$TMP/simapp"
cleanup() { [ "$KEEP" = 1 ] && echo "kept: $APP" || rm -rf "$TMP"; }
trap cleanup EXIT

echo "== 1. throwaway app (builder pin ${PIN:0:12})"
mkdir -p "$APP/tasks" "$APP/scripts/.approved/incoming/tests" "$APP/sim"
cd "$APP"
git init -q -b main
cp "$MOUNTED_BUILDER/Containerfile" "$MOUNTED_BUILDER/requirements.txt" .
printf 'build=src/\ntest=tests/\n' > .gate-paths
printf 'ref=%s\n' "$PIN" > .swbp
printf '# CURRENT.md — e2e simulation app\n' > tasks/CURRENT.md
cat > .gitignore <<'EOF'
.pipeline-state/
.measurement/
.catch-ledger.json
.cache/
.em-archive/
.coder-archive/
__pycache__/
scripts/.approved/incoming/
sim/
EOF
git add -A
git -c user.email=e2e@sim -c user.name=e2e -c core.hooksPath=/dev/null commit -qm "e2e: empty builder-targeted app"
SPEC="$BUILDER/examples/minimal-spec"
cp "$SPEC/PRD.md" "$SPEC/ERD.md" "$SPEC/contracts.json" scripts/.approved/incoming/
cp "$SPEC/tests/storage_tests.py" scripts/.approved/incoming/tests/test_storage.py
cp "$SPEC/tests/api_tests.py" scripts/.approved/incoming/tests/test_api.py
cp "$HERE/e2e_fake_llm.py" sim/
cp "$LINKBOX_SRC/storage.py" "$LINKBOX_SRC/api.py" sim/
COPY=()
for f in scripts/.approved/incoming/PRD.md scripts/.approved/incoming/ERD.md \
         scripts/.approved/incoming/contracts.json \
         scripts/.approved/incoming/tests/test_storage.py \
         scripts/.approved/incoming/tests/test_api.py \
         sim/e2e_fake_llm.py sim/storage.py sim/api.py; do
  COPY+=(--copy-file "$f")
done

echo "== 2. copy in"
RUN="$(bash "$VS" start "$APP" "${COPY[@]}" 2>/dev/null | tail -1)"
WS="$(sed -n 's/^vm_path=//p' "$APP/.git/swbp-vm/$RUN")"
[ -n "$WS" ] || fail "vm-sync start did not record a VM path"
ok "run $RUN -> $WS"

echo "== 3. freeze + build in the VM (real gates, real sandbox, scripted models)"
set +e
limactl shell dev-vm -- bash -lc "
set -u
cd $(printf %q "$WS")
SWBP=$(printf %q "$MOUNTED_BUILDER")/scripts/swbp
python3 sim/e2e_fake_llm.py --port $PORT --ws \"\$PWD\" --src sim --log sim/requests.jsonl &
FAKE=\$!
trap 'kill \$FAKE 2>/dev/null' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:$PORT/v1/models >/dev/null && break; sleep 0.5; done
\$SWBP refreeze --app \"\$PWD\" -- scripts/.approved/incoming > sim/refreeze.log 2>&1 || { echo REFREEZE_FAILED; tail -30 sim/refreeze.log; exit 1; }
echo REFREEZE_OK
SANDBOX_LLM_HOST=127.0.0.1 SANDBOX_LLM_PORT=$PORT SWBP_EM_MODEL=sim-em SWBP_CODER_MODEL=sim-coder \
  SWBP_SKIP_CI_CHECK=1 SWBP_PARALLEL_CODERS=1 \
  \$SWBP orchestrate --app \"\$PWD\" > sim/orchestrate.log 2>&1
echo ORCHESTRATE_RC=\$?
" 2>&1 | grep -v 'level=warning' | tee "$TMP/vm.out"
set -e
grep -q REFREEZE_OK "$TMP/vm.out" || fail "refreeze did not complete (see output above)"
ok "spec frozen in the VM"
limactl copy "dev-vm:$WS/sim/orchestrate.log" "$TMP/orchestrate.log" >/dev/null 2>&1 || true
limactl copy "dev-vm:$WS/sim/requests.jsonl" "$TMP/requests.jsonl" >/dev/null 2>&1 || true
grep -q "ORCHESTRATE_RC=0" "$TMP/vm.out" \
  || { tail -40 "$TMP/orchestrate.log" 2>/dev/null; fail "orchestrate did not finish green"; }
ok "orchestrate exited 0"

echo "== 4. land"
bash "$VS" land "$APP" "$RUN" 2>&1 | grep -v 'level=warning'
git -C "$APP" log --oneline | grep -q "\[success\] spec v1" || fail "no [success] commit on the host"
ok "[success] landed on the host"

echo "== 5. evidence"
python3 - "$APP/.catch-ledger.json" <<'PY' || fail "catch ledger does not show the expected catches"
import json, sys
gates = json.load(open(sys.argv[1]))["gates"]
want = {"validate-plan", "coder-spec-report", "coder-reply-format", "test-verdict"}
missing = want - set(gates)
print("  ledger gates:", ", ".join(sorted(gates)))
sys.exit(f"missing: {sorted(missing)}" if missing else 0)
PY
ok "catch ledger came home with every expected gate"
grep -q "coder reported a spec problem for T1 — skipping the retry, consulting the EM" "$TMP/orchestrate.log" \
  || fail "the spec report did not skip the retry"
python3 - "$TMP/requests.jsonl" <<'PY' || fail "request order wrong"
import json, sys
roles = [json.loads(l)["role"] for l in open(sys.argv[1])]
i = roles.index("coder:src/storage.py")
assert roles[i + 1] == "em:consult", roles
assert roles.count("coder:src/storage.py") == 2, roles
print("  model calls:", " -> ".join(roles))
PY
ok "spec report went straight to the EM consult (no wasted retry)"

bash "$VS" discard "$APP" "$RUN" >/dev/null 2>&1 || true
echo "E2E PASS"
