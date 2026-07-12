#!/usr/bin/env bash
# update-template.sh — pull the template's control plane into this child (D-34).
#
# The refreeze pattern (D-31) applied to the OTHER protected artifact class:
# stage the template's current template-owned files, show the human one diff,
# interactive y/N, apply, re-pin hashes, advance .template-version, commit
# [template-update <sha>]. This is the fix for the spark-class incident —
# control-plane improvements flow template -> children instead of by hand.
#
# Usage:
#   update-template.sh [--from <clone-dir>] [--ref <ref>] [--dry-run] [--review]
#   update-template.sh --approve <sha> [--from <clone-dir>] [--ref <ref>]
#   update-template.sh --stamp [--from <clone-dir>]
#
#   --from     use an existing local clone of the template (else: gh repo clone
#              into a temp dir — needs gh auth for a private template)
#   --ref      template ref to update to (default: the clone's HEAD)
#   --dry-run  show what would change and exit; no tty needed, nothing written.
#              Prints the DIFF-SHA the --approve mode binds to.
#   --review   emit a self-contained review bundle (claims + diff + reviewer
#              instructions) for pasting into a SECOND model before the CEO
#              approves; no tty needed, nothing written. The CEO gate stays a
#              human authorization — this delegates the technical reading.
#   --approve <sha>
#              non-interactive apply, D-61 (the D-42 refreeze pattern applied
#              here): the sha must match the recomputed diff hash, so what is
#              applied is byte-bound to what was reviewed. If the template or
#              the child changed since --dry-run, the hash mismatches and
#              nothing is written. Same honest caveat as D-42: a conductor
#              relays the diff, so the CEO's read is only as good as the relay
#              — the raw diff is deterministic and re-printable at any time.
#   --stamp    only (re)write ref= in .template-version to the template's HEAD —
#              retrofits a child created before D-33. No files are copied.
#
# The approval screen presents plain-language claims (the template's commit
# messages for the update range), because the CEO's y/N is an AUTHORIZATION
# that the control plane changed with a human aware — not a code review.
# Correctness is carried by the template's selftests and the next run's gates.
set -euo pipefail

# Self-update safety: this script is itself template-owned, so an update can
# overwrite the file WHILE BASH IS STILL READING IT — bash resumes at the old
# byte offset in the new content and executes garbage (testchat, 2026-07-08:
# died mid-apply on `ho`, the tail of an `echo`). Re-exec from a disposable
# copy before doing anything else; the repo root travels in the env var
# because dirname "$0" points at the temp copy after the exec.
if [ -z "${SWBP_UT_REEXEC:-}" ]; then
  _repo="$(cd "$(dirname "$0")/.." && pwd -P)"
  _tmp=$(mktemp)
  cp "$0" "$_tmp"
  SWBP_UT_REEXEC="$_repo" exec bash "$_tmp" "$@"
fi
cd "$SWBP_UT_REEXEC"
die() { echo "UPDATE-TEMPLATE FAIL: $*" >&2; exit 1; }
# Cross-platform sed -i (GNU vs BSD/macOS)
sed_inplace() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }

FROM=""; REF=""; DRY=0; STAMP=0; REVIEW=0; APPROVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from)    FROM="${2:?--from needs a path}"; shift 2 ;;
    --ref)     REF="${2:?--ref needs a ref}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --review)  REVIEW=1; shift ;;
    --approve) APPROVE="${2:?--approve needs the DIFF-SHA printed by --dry-run}"; shift 2 ;;
    --stamp)   STAMP=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -f .template-version ] || die ".template-version missing — this repo predates D-33; restore the file from the template first"
SLUG=$(grep '^repo=' .template-version | cut -d= -f2)
[ -n "$SLUG" ] || die ".template-version has no repo= line"

# Refuse to run inside the template itself — the template updates via git.
ORIGIN=$(git remote get-url origin 2>/dev/null || true)
case "$ORIGIN" in
  *"$SLUG"*) die "this IS the template repo ($SLUG) — nothing to pull from" ;;
esac

# --- Resolve a template clone ---
CLONE="$FROM"
if [ -z "$CLONE" ]; then
  CLONE=$(mktemp -d)/template
  trap 'rm -rf "$(dirname "$CLONE")"' EXIT
  echo "cloning $SLUG ..."
  gh repo clone "$SLUG" "$CLONE" -- --quiet || die "could not clone $SLUG (gh auth?)"
fi
[ -d "$CLONE/.git" ] || die "not a git clone: $CLONE"

TARGET=$(git -C "$CLONE" rev-parse "${REF:-HEAD}") || die "cannot resolve ref '${REF:-HEAD}' in $CLONE"

# --- Stamp-only mode ---
if [ "$STAMP" = "1" ]; then
  BIRTH=$(grep '^ref=' .template-version | cut -d= -f2)
  sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
  bash scripts/regen-manifest.sh scripts/.manifest-project
  git add .template-version scripts/.manifest-project
  git commit -m "[template-stamp ${TARGET:0:12}]" >/dev/null 2>&1 \
    || echo "(already stamped at this ref — no commit needed)"
  echo "stamped: $SLUG @ ${TARGET:0:12} (was: $BIRTH)"
  exit 0
fi

# --- Collect the template-owned file list from the TEMPLATE at target ---
# (the template's list, not the child's: files added upstream must flow in)
TFILES=$(git -C "$CLONE" show "$TARGET:scripts/.manifest-template" 2>/dev/null | awk '{print $2}' | grep . ) \
  || die "template@${TARGET:0:12} has no scripts/.manifest-template — pre-D-33 ref?"

# --- Claims: plain-language record of the update range (commit messages) ---
BASE_REF=$(grep '^ref=' .template-version | cut -d= -f2)
CLAIMS=$(git -C "$CLONE" log --reverse --format='— %s%n%b' "$BASE_REF..$TARGET" -- 2>/dev/null | sed -e 's/^/  /' -e 's/[[:space:]]*$//' | grep -v '^$' || true)
[ -n "$CLAIMS" ] || CLAIMS="  (no commit-log claims available — child ref ${BASE_REF:0:12} not in this clone's history)"

# --- Diff: what would change (captured, so each mode presents it its own way) ---
CHANGED=""
DIFF_TMP=$(mktemp)
for f in $TFILES; do
  new_h=$(git -C "$CLONE" show "$TARGET:$f" | sha256sum | cut -d' ' -f1)
  cur_h=$([ -f "$f" ] && sha256sum "$f" | cut -d' ' -f1 || echo MISSING)
  [ "$new_h" = "$cur_h" ] && continue
  CHANGED="$CHANGED $f"
  {
    echo ""
    echo "--- $f ---"
    if [ -f "$f" ]; then
      git -C "$CLONE" show "$TARGET:$f" | diff -u "$f" - || true
    else
      echo "(new file from template)"
      git -C "$CLONE" show "$TARGET:$f" | head -40
    fi
  } >> "$DIFF_TMP"
done

# files the child tracks as template-owned that the template no longer lists
REMOVED=$(comm -23 \
  <(awk '{print $2}' scripts/.manifest-template | sort) \
  <(printf '%s\n' $TFILES | sort) )

# The approval token (D-61): sha256 of the exact diff text. Recomputed on
# every invocation, so --approve binds to what is true NOW — any change to
# template or child between review and approval changes the hash, fail-closed.
DIFF_SHA=$(sha256sum "$DIFF_TMP" | cut -d' ' -f1)

# --- Review-bundle mode: everything a second model needs, nothing written ---
if [ "$REVIEW" = "1" ]; then
  if [ -z "$CHANGED" ]; then echo "control plane already matches template@${TARGET:0:12} — nothing to review"; exit 0; fi
  echo "=== REVIEW BUNDLE: template update -> $SLUG @ ${TARGET:0:12} ==="
  echo ""
  echo "You are a cold adversarial reviewer. Below are (1) CLAIMS — what the"
  echo "author says this control-plane update does and why — and (2) the full"
  echo "DIFF. Judge exactly two questions:"
  echo "  1. Does the diff do what the claims say — and NOTHING else?"
  echo "     Name any change the claims do not account for."
  echo "  2. What is the worst plausible failure if this diff is wrong?"
  echo "Reply with a verdict line first — CONFIRM or MISMATCH — then your"
  echo "reasoning. Do not soften a MISMATCH; the human approves on your word."
  echo ""
  echo "=== CLAIMS (template commit log, ${BASE_REF:0:12}..${TARGET:0:12}) ==="
  echo "$CLAIMS"
  echo ""
  echo "=== DIFF (files:$CHANGED) ==="
  cat "$DIFF_TMP"
  echo "=== END REVIEW BUNDLE ==="
  echo ""
  echo "DIFF-SHA: $DIFF_SHA  (on CONFIRM, the CEO applies with: scripts/update-template.sh --approve $DIFF_SHA${FROM:+ --from $FROM}${REF:+ --ref $REF})"
  exit 0
fi

cat "$DIFF_TMP"
if [ -z "$CHANGED" ]; then
  echo "control plane already matches template@${TARGET:0:12}"
else
  echo ""
  echo "=============================================="
  echo "  Template update -> $SLUG @ ${TARGET:0:12}"
  echo "  Files:$CHANGED"
  [ -n "$REMOVED" ] && { echo "  Removed upstream (delete manually if agreed):"; echo "$REMOVED" | sed 's/^/    /'; }
  echo ""
  echo "  What you are approving (the template's own commit messages):"
  echo "$CLAIMS"
  echo ""
  echo "  Your y/N is an authorization — a human aware the pipeline's rules"
  echo "  are changing — not a code review. Correctness is carried by the"
  echo "  template's selftests and the next run's gates. To have a second"
  echo "  model read the diff first:  scripts/update-template.sh --review"
  echo "=============================================="
fi

if [ "$DRY" = "1" ]; then
  if [ -n "$CHANGED" ]; then
    echo ""
    echo "DIFF-SHA: $DIFF_SHA"
    echo "(dry run — nothing written; to apply without a terminal, the CEO approves:"
    echo "  scripts/update-template.sh --approve $DIFF_SHA${FROM:+ --from $FROM}${REF:+ --ref $REF})"
  else
    echo "(dry run — nothing written)"
  fi
  exit 0
fi
[ -n "$CHANGED" ] || { # nothing to copy; still advance the ref stamp
  sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
  bash scripts/regen-manifest.sh scripts/.manifest-project
  git add .template-version scripts/.manifest-project
  git commit -m "[template-update ${TARGET:0:12}] (ref advance only)" 2>/dev/null || echo "(ref already current)"
  exit 0
}

if [ -n "$APPROVE" ]; then
  # D-61: the hash IS the approval — it binds this apply to the exact diff
  # the human read after --dry-run. Any drift on either side fails closed.
  [ "$APPROVE" = "$DIFF_SHA" ] || die "approval hash mismatch — expected current DIFF-SHA $DIFF_SHA
  The template or this child changed since the diff was reviewed.
  Re-run --dry-run, read the new diff, and approve its hash (D-61)."
  echo "approval hash verified against the current diff (D-61) — applying"
else
  [ -t 0 ] || die "template updates require an interactive terminal — the human diff-approval IS the gate (no tty: use --dry-run, read the diff, then --approve <DIFF-SHA>, D-61)"
  printf 'Apply this template update? [y/N] '
  read -r ANSWER
  case "$ANSWER" in y|Y|yes|YES) ;; *) echo "aborted — nothing changed"; exit 1 ;; esac
fi

# --- Apply: contents + exec bits, then the template's own manifest verbatim ---
for f in $CHANGED; do
  mkdir -p "$(dirname "$f")"
  git -C "$CLONE" show "$TARGET:$f" > "$f"
  mode=$(git -C "$CLONE" ls-tree "$TARGET" -- "$f" | awk '{print $1}')
  [ "$mode" = "100755" ] && chmod +x "$f"
done
git -C "$CLONE" show "$TARGET:scripts/.manifest-template" > scripts/.manifest-template

sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
bash scripts/regen-manifest.sh scripts/.manifest-project

# The applied files must verify against the manifest we just installed.
bash scripts/phase-gate.sh manifest HEAD || die "post-apply integrity check failed — do not commit; inspect"

git add .template-version scripts/.manifest-template scripts/.manifest-project
for f in $CHANGED; do git add "$f"; done
git commit -m "[template-update ${TARGET:0:12}]"

echo ""
echo "=============================================="
echo "  Updated to $SLUG @ ${TARGET:0:12}"
[ -n "$REMOVED" ] && echo "  NOTE: files removed upstream need manual deletion:$REMOVED"
echo "=============================================="
