#!/usr/bin/env bash
# Prints release notes for the range <previous tag>..<ref> built from the commit subjects.
# Usage: release_notes.sh <ref> [previous-tag]
set -euo pipefail
ref="${1:-HEAD}"
prev="${2:-$(git describe --tags --abbrev=0 "$ref^" 2>/dev/null || true)}"
range="${prev:+$prev..}$ref"
section() { # title, grep-pattern
  local lines
  lines=$(git log "$range" --no-merges --pretty='%s|%h' | grep -E "^($2)" | sed -E 's/^[^ ]+ //; s/\|([0-9a-f]+)$/ (\1)/; s/^/- /' || true)
  [ -n "$lines" ] && printf '### %s\n\n%s\n\n' "$1" "$lines"
  return 0
}
section "New" "✨"
section "Fixes" "🐛"
section "Other changes" "📝|📸|🎨|♻️|⚡|🔧|✅|🔒"
if [ -n "$prev" ]; then
  printf '**Full changelog**: https://github.com/%s/compare/%s...%s\n' "${GITHUB_REPOSITORY:-r3mcos3/recorder-studio}" "$prev" "${ref_name:-$ref}"
fi
