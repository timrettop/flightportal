#!/usr/bin/env bash
# Tag the next OTA release and push it. Usage:
#   scripts/tag_release.sh "commit message"
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 \"tag message\"" >&2
  exit 1
fi

NEXT=$(( $(git tag -l "v*" | sort -V | tail -1 | tr -d "v") + 1 ))
git tag -a "v$NEXT" -m "$1"
git push origin "v$NEXT"
echo "pushed v$NEXT"