#!/usr/bin/env bash
# mutation-pass.sh — D-161 one-shot, report-only oracle-strength measurement.
#
# The source repository is never edited. The runner clones its exact HEAD into
# a temporary directory, applies one curated mutant at a time there, runs the
# frozen suite, restores the clone, and removes the clone on every exit path.
#
# Mutant file format (tab-separated; one physical line per mutant):
#   <relative source path>  <exact find text>  <exact replacement>  <reason>
# Blank lines and lines beginning with # are ignored. Empty fields and
# tabs/newlines inside a field are deliberately unsupported; every find text
# must occur exactly once.
#
# Usage:
#   scripts/mutation-pass.sh --repo /path/to/child --mutants mutants.tsv \
#     [--suite "python3 -m pytest tests -q"] [--out report.md]
set -euo pipefail

REPO=""
MUTANTS=""
SUITE="python3 -m pytest tests -q"
OUT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo needs a path}"; shift 2 ;;
    --mutants) MUTANTS="${2:?--mutants needs a file}"; shift 2 ;;
    --suite) SUITE="${2:?--suite needs a command}"; shift 2 ;;
    --out) OUT="${2:?--out needs a file}"; shift 2 ;;
    *) echo "mutation-pass: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$REPO" ] && [ -n "$MUTANTS" ] || {
  echo "usage: $0 --repo R --mutants M [--suite C] [--out F]" >&2
  exit 2
}
[ -f "$MUTANTS" ] || {
  echo "mutation-pass: mutants file not found: $MUTANTS" >&2
  exit 2
}
command -v git >/dev/null 2>&1 || { echo "mutation-pass: git is required" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "mutation-pass: python3 is required" >&2; exit 2; }

REPO_ROOT=$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null) || {
  echo "mutation-pass: --repo must resolve to a git work tree" >&2
  exit 2
}
SOURCE_HEAD=$(git -C "$REPO_ROOT" rev-parse --verify HEAD)
MUTANTS=$(cd "$(dirname "$MUTANTS")" && pwd -P)/$(basename "$MUTANTS")
if [ -n "$OUT" ]; then
  OUT_DIR=$(cd "$(dirname "$OUT")" && pwd -P)
  OUT="$OUT_DIR/$(basename "$OUT")"
fi

PASS_TMP=$(mktemp -d "${TMPDIR:-/tmp}/swbp-mutation.XXXXXX")
cleanup() {
  case "$PASS_TMP" in
    "${TMPDIR:-/tmp}"/swbp-mutation.*) rm -rf -- "$PASS_TMP" ;;
    *) echo "mutation-pass: refusing unsafe cleanup path: $PASS_TMP" >&2 ;;
  esac
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

WORK="$PASS_TMP/repo"
RESULTS="$PASS_TMP/results.tsv"
: > "$RESULTS"

git clone --quiet --no-local --no-checkout "$REPO_ROOT" "$WORK"
git -C "$WORK" checkout --quiet --detach "$SOURCE_HEAD"

echo "== source: $REPO_ROOT@$SOURCE_HEAD"
echo "== baseline suite run (isolated exact-HEAD clone)"
set +e
(cd "$WORK" && PYTHONDONTWRITEBYTECODE=1 bash -c "$SUITE") > "$PASS_TMP/baseline.log" 2>&1
BASE_RC=$?
set -e
if [ "$BASE_RC" -ne 0 ]; then
  echo "mutation-pass: exact-HEAD baseline is not green (rc=$BASE_RC)" >&2
  tail -20 "$PASS_TMP/baseline.log" >&2
  exit 3
fi
echo "baseline green"

apply_mutant() {
  python3 - "$WORK" "$1" "$2" "$3" <<'PYEOF'
from pathlib import Path
import sys

root, relative, find, replacement = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
path = (root / relative).resolve()
try:
    path.relative_to(root.resolve())
except ValueError:
    raise SystemExit("path escapes source tree")
if not path.is_file():
    raise SystemExit("source file does not exist")
text = path.read_text(encoding="utf-8")
count = text.count(find)
if count != 1:
    raise SystemExit(f"find text occurs {count} times, expected exactly once")
path.write_text(text.replace(find, replacement, 1), encoding="utf-8")
PYEOF
}

total=0
killed=0
survived=0
authoring_errors=0
while IFS=$'\t' read -r file find replacement reason extra || [ -n "${file:-}" ]; do
  [ -z "${file:-}" ] && continue
  case "$file" in \#*) continue ;; esac
  total=$((total + 1))
  if [ -n "${extra:-}" ] || [ -z "${find:-}" ] || \
     [ -z "${replacement:-}" ] || [ -z "${reason:-}" ]; then
    authoring_errors=$((authoring_errors + 1))
    printf 'AUTHORING_ERROR\t%s\t%s\t%s\t%s\n' "$file" "$find" "$replacement" \
      "expected exactly four non-empty TSV fields" >> "$RESULTS"
    echo "[$total] AUTHORING_ERROR $file"
    continue
  fi

  if ! apply_error=$(apply_mutant "$file" "$find" "$replacement" 2>&1); then
    authoring_errors=$((authoring_errors + 1))
    printf 'AUTHORING_ERROR\t%s\t%s\t%s\t%s\n' "$file" "$find" "$replacement" \
      "$apply_error" >> "$RESULTS"
    echo "[$total] AUTHORING_ERROR $file — $apply_error"
    continue
  fi

  set +e
  (cd "$WORK" && PYTHONDONTWRITEBYTECODE=1 bash -c "$SUITE") > "$PASS_TMP/mutant-$total.log" 2>&1
  mutant_rc=$?
  set -e
  git -C "$WORK" restore --source=HEAD --staged --worktree -- .

  if [ "$mutant_rc" -eq 0 ]; then
    verdict="SURVIVED"
    survived=$((survived + 1))
  else
    verdict="KILLED"
    killed=$((killed + 1))
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$verdict" "$file" "$find" "$replacement" "$reason" >> "$RESULTS"
  echo "[$total] $verdict (suite rc=$mutant_rc) $file — $reason"
done < "$MUTANTS"

echo "== summary: total=$total killed=$killed survived=$survived authoring_errors=$authoring_errors"

if [ -n "$OUT" ]; then
  python3 - "$RESULTS" "$OUT" "$REPO_ROOT" "$SOURCE_HEAD" "$SUITE" \
    "$total" "$killed" "$survived" "$authoring_errors" <<'PYEOF'
import csv
from pathlib import Path
import sys

results, output = Path(sys.argv[1]), Path(sys.argv[2])
repo, head, suite = sys.argv[3:6]
total, killed, survived, errors = sys.argv[6:10]

def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("`", "\\`").replace("\n", " ")

lines = [
    "# D-161 mutation-pass results",
    "",
    f"- source: `{cell(repo)}@{head}` (isolated exact-HEAD clone)",
    "- baseline: green",
    f"- suite: `{cell(suite)}`",
    f"- totals: {total} mutants; {killed} killed; {survived} survived; {errors} authoring errors",
    "- enforcement: report-only; survivors are evidence for oracle improvement, never a build gate",
    "",
    "| verdict | file | mutation | reason |",
    "|---|---|---|---|",
]
with results.open(encoding="utf-8", newline="") as handle:
    for verdict, file, find, replacement, reason in csv.reader(
        handle, delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        lines.append(
            f"| {cell(verdict)} | `{cell(file)}` | `{cell(find)}` → `{cell(replacement)}` | {cell(reason)} |"
        )
output.write_text("\n".join(lines) + "\n", encoding="utf-8")
PYEOF
  echo "report written: $OUT"
fi

[ "$authoring_errors" -eq 0 ] || exit 4
exit 0
