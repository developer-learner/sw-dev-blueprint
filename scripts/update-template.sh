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
#   update-template.sh [--from <clone-dir>] [--ref <ref>] [--dry-run]
#   update-template.sh --stamp [--from <clone-dir>]
#
#   --from     use an existing local clone of the template (else: gh repo clone
#              into a temp dir — needs gh auth for a private template)
#   --ref      template ref to update to (default: the clone's HEAD)
#   --dry-run  show what would change and exit; no tty needed, nothing written
#   --stamp    only (re)write ref= in .template-version to the template's HEAD —
#              retrofits a child created before D-33. No files are copied.
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
die() { echo "UPDATE-TEMPLATE FAIL: $*" >&2; exit 1; }
# Cross-platform sed -i (GNU vs BSD/macOS)
sed_inplace() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }

FROM=""; REF=""; DRY=0; STAMP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from)    FROM="${2:?--from needs a path}"; shift 2 ;;
    --ref)     REF="${2:?--ref needs a ref}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
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
  git commit -m "[template-stamp ${TARGET:0:12}]"
  echo "stamped: $SLUG @ ${TARGET:0:12} (was: $BIRTH)"
  exit 0
fi

# --- Collect the template-owned file list from the TEMPLATE at target ---
# (the template's list, not the child's: files added upstream must flow in)
TFILES=$(git -C "$CLONE" show "$TARGET:scripts/.manifest-template" 2>/dev/null | awk '{print $2}' | grep . ) \
  || die "template@${TARGET:0:12} has no scripts/.manifest-template — pre-D-33 ref?"

# --- Diff: what would change ---
CHANGED=""
for f in $TFILES; do
  new_h=$(git -C "$CLONE" show "$TARGET:$f" | sha256sum | cut -d' ' -f1)
  cur_h=$([ -f "$f" ] && sha256sum "$f" | cut -d' ' -f1 || echo MISSING)
  [ "$new_h" = "$cur_h" ] && continue
  CHANGED="$CHANGED $f"
  echo ""
  echo "--- $f ---"
  if [ -f "$f" ]; then
    git -C "$CLONE" show "$TARGET:$f" | diff -u "$f" - || true
  else
    echo "(new file from template)"
    git -C "$CLONE" show "$TARGET:$f" | head -40
  fi
done

# files the child tracks as template-owned that the template no longer lists
REMOVED=$(comm -23 \
  <(awk '{print $2}' scripts/.manifest-template | sort) \
  <(printf '%s\n' $TFILES | sort) )

if [ -z "$CHANGED" ]; then
  echo "control plane already matches template@${TARGET:0:12}"
else
  echo ""
  echo "=============================================="
  echo "  Template update -> $SLUG @ ${TARGET:0:12}"
  echo "  Files:$CHANGED"
  [ -n "$REMOVED" ] && { echo "  Removed upstream (delete manually if agreed):"; echo "$REMOVED" | sed 's/^/    /'; }
  echo "=============================================="
fi

if [ "$DRY" = "1" ]; then
  echo "(dry run — nothing written)"
  exit 0
fi
[ -n "$CHANGED" ] || { # nothing to copy; still advance the ref stamp
  sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version
  bash scripts/regen-manifest.sh scripts/.manifest-project
  git add .template-version scripts/.manifest-project
  git commit -m "[template-update ${TARGET:0:12}] (ref advance only)" 2>/dev/null || echo "(ref already current)"
  exit 0
}

[ -t 0 ] || die "template updates require an interactive terminal — the human diff-approval IS the gate (use --dry-run to inspect)"
printf 'Apply this template update? [y/N] '
read -r ANSWER
case "$ANSWER" in y|Y|yes|YES) ;; *) echo "aborted — nothing changed"; exit 1 ;; esac

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
