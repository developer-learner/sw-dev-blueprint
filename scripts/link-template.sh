#!/usr/bin/env bash
# link-template.sh — install/update the Blueprint control plane as one linked
# dependency while keeping project spec, tests, configuration, and state local.
#
# Usage mirrors update-template.sh for the modes used by conductors:
#   link-template.sh --from <blueprint-clone> [--ref <ref>] --dry-run
#   link-template.sh --from <blueprint-clone> [--ref <ref>] --approve <plan-sha>
#   link-template.sh --from <blueprint-clone> [--ref <ref>]
#
# `.github/workflows/check-drift.yml` remains a real child file: GitHub must
# parse workflow YAML before checkout, when an external symlink cannot resolve.
set -euo pipefail

if [ -z "${SWBP_LINK_REEXEC:-}" ]; then
  _project="$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)"
  _tmp="$(mktemp)"
  cp "$0" "$_tmp"
  SWBP_LINK_REEXEC="$_project" exec bash "$_tmp" "$@"
fi
cd "$SWBP_LINK_REEXEC"

die() { echo "LINK-TEMPLATE FAIL: $*" >&2; exit 1; }
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 | cut -d' ' -f1
  else
    die "no sha256sum or shasum found"
  fi
}
sed_inplace() { if sed --version >/dev/null 2>&1; then sed -i "$@"; else sed -i '' "$@"; fi; }

FROM=""; REF=""; DRY=0; REVIEW=0; APPROVE=""; INTERACTIVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="${2:?--from needs a path}"; shift 2 ;;
    --ref) REF="${2:?--ref needs a ref}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --review) REVIEW=1; shift ;;
    --approve) APPROVE="${2:?--approve needs a plan sha}"; shift 2 ;;
    --interactive) INTERACTIVE=1; shift ;;
    --stamp) shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$FROM" ] || die "--from <blueprint-clone> is required for linked mode"
git -C "$FROM" rev-parse --show-toplevel >/dev/null 2>&1 \
  || die "not a Blueprint clone or worktree: $FROM"
[ -f .template-version ] || die ".template-version missing"
[ -f scripts/.manifest-template ] || die "scripts/.manifest-template missing"

PROJECT="$(pwd -P)"
SOURCE="$(cd "$FROM" && pwd -P)"
[ "$PROJECT" != "$SOURCE" ] || die "linked mode applies to a child, not the Blueprint repository"

# T7 M1 (D-174): provenance broker — link commits carry Swbp-Role: human.
# Fresh installs have no child broker yet (the plane being installed), so
# fall back to the source checkout's copy; fail closed if neither exists.
if [ -f scripts/git-provenance.sh ]; then
  source scripts/git-provenance.sh
elif [ -f "$SOURCE/scripts/git-provenance.sh" ]; then
  source "$SOURCE/scripts/git-provenance.sh"
else
  die "scripts/git-provenance.sh missing from child and source checkout"
fi
TARGET="$(git -C "$SOURCE" rev-parse "${REF:-HEAD}")" || die "cannot resolve ref ${REF:-HEAD}"
BASE_REF="$(grep '^ref=' .template-version | cut -d= -f2 | tr -d '[:space:]')"
TARGET_MANIFEST="$(mktemp)"
git -C "$SOURCE" show "$TARGET:scripts/.manifest-template" > "$TARGET_MANIFEST" \
  || die "target has no template manifest"

# Linked paths execute the source checkout directly outside immutable runs.
# Refuse a source whose bytes do not match the target commit being adopted.
while read -r expected path extra; do
  [ -n "$expected" ] || continue
  [ -n "$path" ] && [ -z "${extra:-}" ] || die "malformed target manifest row"
  [ -f "$SOURCE/$path" ] || die "source checkout missing $path"
  actual="$(sha256_of < "$SOURCE/$path")"
  [ "$actual" = "$expected" ] \
    || die "source checkout $path does not match target ${TARGET:0:12}; check out the target first"
done < "$TARGET_MANIFEST"

SOURCE_REL="$(python3 - "$SOURCE" "$PROJECT" <<'PY'
import os, sys
print(os.path.relpath(sys.argv[1], sys.argv[2]))
PY
)"
EXCEPTION=".github/workflows/check-drift.yml"
PLAN="$(mktemp)"
{
  echo "mode=linked"
  echo "source=$SOURCE_REL"
  echo "from=$BASE_REF"
  echo "to=$TARGET"
  echo "exception=$EXCEPTION"
  while read -r expected path extra; do
    [ -n "$expected" ] || continue
    if [ "$path" = "$EXCEPTION" ]; then
      echo "COPY $path $expected"
    else
      target="$(python3 - "$SOURCE/$path" "$PROJECT/$(dirname "$path")" <<'PY'
import os, sys
print(os.path.relpath(sys.argv[1], sys.argv[2]))
PY
)"
      echo "LINK $path -> $target $expected"
    fi
  done < "$TARGET_MANIFEST"
  comm -23 \
    <(awk '{print $2}' scripts/.manifest-template | sort) \
    <(awk '{print $2}' "$TARGET_MANIFEST" | sort) \
    | sed 's/^/REMOVE /'
} > "$PLAN"
PLAN_SHA="$(sha256_of < "$PLAN")"

echo "=== LINKED BLUEPRINT PLAN @ ${TARGET:0:12} ==="
cat "$PLAN"
echo "PLAN-SHA: $PLAN_SHA"
if [ "$DRY" = "1" ] || [ "$REVIEW" = "1" ]; then
  echo "(preview only — nothing written)"
  exit 0
fi
if [ -n "$APPROVE" ]; then
  [ "$APPROVE" = "$PLAN_SHA" ] || die "approval hash mismatch; preview again"
elif [ "$INTERACTIVE" = "1" ]; then
  [ -t 0 ] || die "--interactive requires a terminal"
  printf 'Apply this linked Blueprint plan? [y/N] '
  read -r answer
  case "$answer" in y|Y|yes|YES) ;; *) die "aborted" ;; esac
else
  echo "auto-approved: linked-plan $PLAN_SHA"
fi

[ -z "$(git status --porcelain)" ] \
  || die "child working tree must be clean before linked-plane migration/adoption"

OLD_PATHS="$(awk '{print $2}' scripts/.manifest-template)"
NEW_PATHS="$(awk '{print $2}' "$TARGET_MANIFEST")"
for path in $OLD_PATHS; do
  printf '%s\n' "$NEW_PATHS" | grep -Fxq "$path" && continue
  case "$path" in ""|/*|../*|*/../*|*/..|..) die "unsafe retired path: $path" ;; esac
  rm -f -- "$path"
done

while read -r expected path extra; do
  [ -n "$expected" ] || continue
  mkdir -p "$(dirname "$path")"
  if [ "$path" = "$EXCEPTION" ]; then
    rm -f -- "$path"
    git -C "$SOURCE" show "$TARGET:$path" > "$path"
  else
    target="$(python3 - "$SOURCE/$path" "$PROJECT/$(dirname "$path")" <<'PY'
import os, sys
print(os.path.relpath(sys.argv[1], sys.argv[2]))
PY
)"
    rm -f -- "$path"
    ln -s "$target" "$path"
  fi
done < "$TARGET_MANIFEST"

cp "$TARGET_MANIFEST" scripts/.manifest-template
cat > .template-link <<EOF
mode=linked
source=$SOURCE_REL
exception=$EXCEPTION
EOF
sed_inplace "s/^ref=.*/ref=$TARGET/" .template-version

if ! awk '{print $2}' scripts/.manifest-project | grep -Fxq .template-link; then
  echo "PENDING  .template-link" >> scripts/.manifest-project
fi
bash scripts/regen-manifest.sh scripts/.manifest-project
bash scripts/phase-gate.sh manifest HEAD

git add -A -- .template-link .template-version scripts/.manifest-template \
  scripts/.manifest-project $OLD_PATHS $NEW_PATHS
swbp_commit human "[template-link ${TARGET:0:12}]"
echo "linked: $SOURCE_REL @ $TARGET"
