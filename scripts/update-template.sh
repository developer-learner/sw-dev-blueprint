#!/usr/bin/env bash
# update-template.sh — pull the template's control plane into this child (D-34).
#
# The refreeze pattern (D-31) applied to the OTHER protected artifact class:
# stage the template's current template-owned files, show one diff and the
# template's own commit-message claims for the update range, apply, re-pin
# hashes, advance .template-version, commit [template-update <sha>]. This
# is the fix for the spark-class incident — control-plane improvements
# flow template -> children instead of by hand.
#
# Usage:
#   update-template.sh [--from <clone-dir>] [--ref <ref>] [--dry-run] [--review]
#   update-template.sh --approve <sha> [--from <clone-dir>] [--ref <ref>]
#   update-template.sh --interactive [--from <clone-dir>] [--ref <ref>]
#   update-template.sh --stamp [--from <clone-dir>]
#
#   --from     use an existing local clone of the template (else: gh repo clone
#              into a temp dir — needs gh auth for a private template)
#   --ref      template ref to update to (default: the clone's HEAD)
#   --dry-run  show what would change and exit; no tty needed, nothing written.
#              Prints the DIFF-SHA the --approve mode binds to.
#   --review   emit a self-contained review bundle (claims + diff + reviewer
#              instructions) for pasting into a SECOND model before applying;
#              no tty needed, nothing written. Delegates the technical read.
#   --approve <sha>
#              explicit apply, D-61 (the D-42 refreeze pattern applied here):
#              the sha must match the recomputed diff hash, so what is
#              applied is byte-bound to what was reviewed. If the template or
#              the child changed since --dry-run, the hash mismatches and
#              nothing is written. Same honest caveat as D-42: a conductor
#              relays the diff, so the CEO's read is only as good as the relay
#              — the raw diff is deterministic and re-printable at any time.
#   --interactive
#              opt-in y/N prompt (the pre-D-96 default). For the rare case
#              where the operator wants to eyeball this specific pull before
#              it applies. Requires a terminal.
#   --stamp    only (re)write ref= in .template-version to the template's HEAD —
#              retrofits a child created before D-33. No files are copied.
#
# Default is auto (D-96, mirrors D-95): on all pre-diff checks green
# (clone resolvable, template manifest present, diff computable), the pull
# applies without a prompt. Correctness is carried by the template's own
# selftests (which ran green before the template committed) and the next
# run's gates in this child; the post-apply `phase-gate.sh manifest HEAD`
# still fails closed on integrity mismatch. The plain-language CLAIMS are
# printed on every invocation so a conductor or reviewer can react.
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

FROM=""; REF=""; DRY=0; STAMP=0; REVIEW=0; APPROVE=""; INTERACTIVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from)        FROM="${2:?--from needs a path}"; shift 2 ;;
    --ref)         REF="${2:?--ref needs a ref}"; shift 2 ;;
    --dry-run)     DRY=1; shift ;;
    --review)      REVIEW=1; shift ;;
    --approve)     APPROVE="${2:?--approve needs the DIFF-SHA printed by --dry-run}"; shift 2 ;;
    --interactive) INTERACTIVE=1; shift ;;
    --stamp)       STAMP=1; shift ;;
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
# Portable SHA-256 (D-152 class): template maintenance is documented as a
# Linux-VM operation (docs/DEV-VM-SETUP.md), but nothing structural stops a
# host-side run. Inline copy — selftest fixtures copy scripts by bytes, so
# keep this in sync with the helpers in manifest-drift-guard.sh,
# regen-manifest.sh, check-drift.sh (sync-pinned by selftest_gates.py).
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    die "no sha256sum or shasum found — cannot compare hashes"
  fi
}
CHANGED=""
DIFF_TMP=$(mktemp)
for f in $TFILES; do
  new_h=$(git -C "$CLONE" show "$TARGET:$f" | sha256_of)
  cur_h=$([ -f "$f" ] && sha256_of < "$f" || echo MISSING)
  [ "$new_h" = "$cur_h" ] && continue
  CHANGED="$CHANGED $f"
  {
    echo ""
    echo "--- $f ---"
    if [ -f "$f" ]; then
      # -L labels replace diff's filename+TIMESTAMP headers: the stdin side
      # would otherwise be stamped with the current time, making the diff
      # text — and therefore DIFF-SHA — different on every invocation, so no
      # --approve hash could ever match (caught by the D-61 scratch-child
      # test, 2026-07-11). Labels carry only deterministic content.
      git -C "$CLONE" show "$TARGET:$f" | diff -u -L "$f (child)" -L "$f (template@${TARGET:0:12})" "$f" - || true
    else
      echo "(new file from template)"
      git -C "$CLONE" show "$TARGET:$f" | head -40
    fi
  } >> "$DIFF_TMP"
done

# The manifest itself is template-owned and must reach the child verbatim
# (the file list IS the sync contract). Include it in the diff so a
# template-side manifest change (new entries, re-pinned hashes) is treated
# like any other content change instead of being swallowed by the
# "ref advance only" shortcut.
MANIFEST_DRIFT=""
new_m=$(git -C "$CLONE" show "$TARGET:scripts/.manifest-template" | sha256_of)
cur_m=$([ -f scripts/.manifest-template ] && sha256_of < scripts/.manifest-template || echo MISSING)
if [ "$new_m" != "$cur_m" ]; then
  MANIFEST_DRIFT=1
  {
    echo ""
    echo "--- scripts/.manifest-template ---"
    if [ -f scripts/.manifest-template ]; then
      git -C "$CLONE" show "$TARGET:scripts/.manifest-template" | diff -u -L "scripts/.manifest-template (child)" -L "scripts/.manifest-template (template@${TARGET:0:12})" scripts/.manifest-template - || true
    else
      echo "(new manifest from template)"
      git -C "$CLONE" show "$TARGET:scripts/.manifest-template" | head -40
    fi
  } >> "$DIFF_TMP"
fi

# files the child tracks as template-owned that the template no longer lists
REMOVED=$(comm -23 \
  <(awk '{print $2}' scripts/.manifest-template | sort) \
  <(printf '%s\n' $TFILES | sort) )
for f in $REMOVED; do
  # The child manifest is normally trusted, but it directly drives deletion
  # here. Keep that authority repo-relative even if the manifest was damaged.
  case "$f" in
    ""|/*|../*|*/../*|*/..|..)
      die "refusing unsafe removed template path from child manifest: $f" ;;
  esac
  {
    echo ""
    echo "--- $f (removed upstream) ---"
    if [ -f "$f" ]; then
      diff -u -L "$f (child)" -L "$f (removed from template@${TARGET:0:12})" \
        "$f" /dev/null || true
    else
      echo "(already absent in child; upstream removal confirms deletion)"
    fi
  } >> "$DIFF_TMP"
done

# The approval token (D-61): sha256 of the exact diff text. Recomputed on
# every invocation, so --approve binds to what is true NOW — any change to
# template or child between review and approval changes the hash, fail-closed.
DIFF_SHA=$(sha256_of < "$DIFF_TMP")

# --- Review-bundle mode: everything a second model needs, nothing written ---
if [ "$REVIEW" = "1" ]; then
  if [ -z "$CHANGED$REMOVED$MANIFEST_DRIFT" ]; then echo "control plane already matches template@${TARGET:0:12} — nothing to review"; exit 0; fi
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
  echo "=== DIFF (changed:$CHANGED; removed:$REMOVED) ==="
  cat "$DIFF_TMP"
  echo "=== END REVIEW BUNDLE ==="
  echo ""
  echo "DIFF-SHA: $DIFF_SHA  (on CONFIRM, the CEO applies with: scripts/update-template.sh --approve $DIFF_SHA${FROM:+ --from $FROM}${REF:+ --ref $REF})"
  exit 0
fi

cat "$DIFF_TMP"
if [ -z "$CHANGED$REMOVED$MANIFEST_DRIFT" ]; then
  echo "control plane already matches template@${TARGET:0:12}"
else
  echo ""
  echo "=============================================="
  echo "  Template update -> $SLUG @ ${TARGET:0:12}"
  [ -n "$CHANGED" ] && echo "  Changed files:$CHANGED"
  [ -n "$REMOVED" ] && { echo "  Removed upstream (applied with this update):"; echo "$REMOVED" | sed 's/^/    /'; }
  [ -n "$MANIFEST_DRIFT" ] && echo "  Manifest updated: new file list from template (verbatim)"
  echo ""
  echo "  Claims (the template's own commit messages for this update range):"
  echo "$CLAIMS"
  echo ""
  echo "  D-96: default is auto — the pull applies after the diff prints."
  echo "  Correctness is carried by the template's selftests (green before it"
  echo "  committed) and the next run's gates in this child; post-apply"
  echo "  integrity is checked by phase-gate. For a second-model read before"
  echo "  applying: scripts/update-template.sh --review. For opt-in y/N:"
  echo "  scripts/update-template.sh --interactive."
  echo "=============================================="
fi

if [ "$DRY" = "1" ]; then
  if [ -n "$CHANGED$REMOVED$MANIFEST_DRIFT" ]; then
    echo ""
    echo "DIFF-SHA: $DIFF_SHA"
    echo "(dry run — nothing written; to apply without a terminal, the CEO approves:"
    echo "  scripts/update-template.sh --approve $DIFF_SHA${FROM:+ --from $FROM}${REF:+ --ref $REF})"
  else
    echo "(dry run — nothing written)"
  fi
  exit 0
fi
if [ -z "$CHANGED$REMOVED$MANIFEST_DRIFT" ]; then
  # no content changes, removals, or manifest drift — advance the ref only
  sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
  bash scripts/regen-manifest.sh scripts/.manifest-project
  git add .template-version scripts/.manifest-project
  git commit -m "[template-update ${TARGET:0:12}] (ref advance only)" 2>/dev/null || echo "(ref already current)"
  exit 0
fi
if [ -n "$MANIFEST_DRIFT" ] && [ -z "$CHANGED$REMOVED" ]; then
  # no content changes, but the template's manifest itself changed (new
  # entries / re-pinned hashes) — install it verbatim so the file list flows
  sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
  bash scripts/regen-manifest.sh scripts/.manifest-project
  git -C "$CLONE" show "$TARGET:scripts/.manifest-template" > scripts/.manifest-template
  bash scripts/phase-gate.sh manifest HEAD || die "post-apply integrity check failed — do not commit; inspect"
  git add .template-version scripts/.manifest-project scripts/.manifest-template
  git commit -m "[template-update ${TARGET:0:12}] (manifest verbatim)" 2>/dev/null || echo "(ref already current)"
  exit 0
fi
[ -n "$CHANGED$REMOVED" ] || { echo "update-template: internal error — content changed yet no apply branch taken" >&2; exit 1; }

if [ -n "$APPROVE" ]; then
  # D-61: the hash IS the approval — it binds this apply to the exact diff
  # the human read after --dry-run. Any drift on either side fails closed.
  [ "$APPROVE" = "$DIFF_SHA" ] || die "approval hash mismatch — expected current DIFF-SHA $DIFF_SHA
  The template or this child changed since the diff was reviewed.
  Re-run --dry-run, read the new diff, and approve its hash (D-61)."
  echo "approval hash verified against the current diff (D-61) — applying"
elif [ "$INTERACTIVE" = "1" ]; then
  # Opt-in eyeball path (pre-D-96 default). Terminal required.
  [ -t 0 ] || die "--interactive requires a terminal — drop the flag (D-96 auto mode), use --dry-run + --approve <sha> (D-61), or --review for a second-model read"
  printf 'Apply this template update? [y/N] '
  read -r ANSWER
  case "$ANSWER" in y|Y|yes|YES) ;; *) echo "aborted — nothing changed"; exit 1 ;; esac
else
  # D-96 auto (default): every pre-diff check has already passed to reach
  # this line (clone resolvable, template manifest present, diff computed).
  # The material verdicts that actually catch defects are the template's
  # own selftests (green before the template committed) upstream and the
  # post-apply `phase-gate.sh manifest HEAD` downstream — the y/N in the
  # middle was authorization theater. Escalation paths that DO surface
  # this for review are unchanged: --dry-run for pre-review, --review for
  # a second-model read, --approve <sha> for hash-bound explicit apply,
  # --interactive for opt-in.
  echo "auto-approved (D-96): DIFF-SHA $DIFF_SHA — applying"
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

# Defer deletions until after the post-apply check: phase-gate.sh,
# regen-manifest.sh, or this updater itself may be among the files retired by
# the new template manifest, and the running old updater still needs them to
# finish validating the transition.
for f in $REMOVED; do
  rm -f -- "$f"
done

git add .template-version scripts/.manifest-template scripts/.manifest-project
for f in $CHANGED; do git add "$f"; done
for f in $REMOVED; do git add -A -- "$f"; done
git commit -m "[template-update ${TARGET:0:12}]"

echo ""
echo "=============================================="
echo "  Updated to $SLUG @ ${TARGET:0:12}"
[ -n "$REMOVED" ] && echo "  Removed upstream:$REMOVED"
echo "=============================================="
