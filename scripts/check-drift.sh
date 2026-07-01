#!/usr/bin/env bash
# check-drift.sh <template-clone-dir> — fleet drift detection (D-33).
#
# Compares this child's template-owned control plane (the file list in
# scripts/.manifest-template) three-way against the template repository:
#
#   child == template@HEAD                    -> IN_SYNC
#   child == template@birth  != template@HEAD -> BEHIND    (template advanced)
#   child != both                             -> LOCALLY_MODIFIED (drift!)
#   missing in child, present in template     -> MISSING_IN_CHILD (drift!)
#
# The birth ref comes from .template-version (stamped by bootstrap.sh, or
# retrofitted with update-template.sh --stamp). The file list is the UNION of
# the template@HEAD manifest and the child manifest, so files added upstream
# are seen as BEHIND, not silently ignored.
#
# Exit codes: 0 in sync · 1 drift (modified/missing — CI should fail)
#             2 behind only (CI should warn; run scripts/update-template.sh)
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd -P)"
CLONE="${1:?usage: check-drift.sh <template-clone-dir>}"
[ -d "$CLONE/.git" ] || { echo "check-drift: not a git clone: $CLONE" >&2; exit 1; }

REPO_SLUG=$(grep '^repo=' .template-version | cut -d= -f2)
BIRTH=$(grep '^ref=' .template-version | cut -d= -f2)
if [ "$BIRTH" = "UNSTAMPED" ] || [ -z "$BIRTH" ]; then
  echo "check-drift: this repo is unstamped (template itself, or a child born" >&2
  echo "before D-33) — stamp it first: scripts/update-template.sh --stamp" >&2
  exit 1
fi
HEAD_REF=$(git -C "$CLONE" rev-parse HEAD)
if ! git -C "$CLONE" cat-file -e "$BIRTH^{commit}" 2>/dev/null; then
  echo "check-drift: birth ref ${BIRTH:0:12} not present in $CLONE —" >&2
  echo "  fetch it first: git -C $CLONE fetch origin $BIRTH" >&2
  exit 1
fi

# hash_at is only ever called after exists_at confirms the blob exists —
# a failed `git show` piped into sha256sum would otherwise hash empty input.
hash_at()   { git -C "$CLONE" show "$1:$2" | sha256sum | cut -d' ' -f1; }
exists_at() { git -C "$CLONE" cat-file -e "$1:$2" 2>/dev/null; }

# union of file lists: template@HEAD manifest + child manifest
FILES=$(
  { git -C "$CLONE" show "$HEAD_REF:scripts/.manifest-template" 2>/dev/null | awk '{print $2}'
    awk '{print $2}' scripts/.manifest-template
  } | grep . | sort -u
)

rc=0
behind=0
echo "drift check: $REPO_SLUG  birth=${BIRTH:0:12}  head=${HEAD_REF:0:12}"
for f in $FILES; do
  if [ -f "$f" ]; then
    child=$(sha256sum "$f" | cut -d' ' -f1)
  else
    child=MISSING
  fi
  if exists_at "$HEAD_REF" "$f"; then head_h=$(hash_at "$HEAD_REF" "$f"); else head_h=MISSING; fi
  if exists_at "$BIRTH" "$f";    then birth_h=$(hash_at "$BIRTH" "$f");   else birth_h=MISSING; fi

  if [ "$child" = "$head_h" ]; then
    status=IN_SYNC
  elif [ "$child" = "MISSING" ] && [ "$head_h" != "MISSING" ]; then
    status=MISSING_IN_CHILD; rc=1
  elif [ "$child" = "$birth_h" ]; then
    status=BEHIND; behind=1
  elif [ "$head_h" = "MISSING" ] && [ "$birth_h" = "MISSING" ]; then
    status=CHILD_ONLY   # child added a template-owned file the template lacks
    rc=1
  else
    status=LOCALLY_MODIFIED; rc=1
  fi
  [ "$status" = "IN_SYNC" ] || echo "  $status: $f"
done

if [ "$rc" -eq 1 ]; then
  echo "DRIFT: template-owned files diverge from the template (see above)."
  echo "  If a change is a deliberate adaptation, it belongs in project-owned"
  echo "  files (.manifest-project), not the template's control plane."
  exit 1
elif [ "$behind" -eq 1 ]; then
  echo "BEHIND: template has advanced — run scripts/update-template.sh"
  exit 2
fi
echo "in sync with template@${HEAD_REF:0:12}"
