#!/usr/bin/env bash
# Opens an issue in this repo when a watched upstream Home Assistant PR changes state
# (draft -> ready for review, merged or closed). Dedupes on the issue title.
set -euo pipefail
repo="${GITHUB_REPOSITORY:-r3mcos3/recorder-studio}"

# name | repo | number | why it matters for Recorder Studio | baseline state
watch=(
  "runtime recorder exclusions (entity registry)|home-assistant/core|152168|Recording on/off becomes runtime-changeable: Recorder Studio should stop needing a restart and move from recorder_studio.yaml to the new WS commands.|OPEN-DRAFT"
  "recorder database usage report (backend)|home-assistant/core|190600|Core gets its own database size/usage report, overlapping our size overview: consider reusing recorder/database_usage.|OPEN-READY"
  "database usage card on the Storage page|home-assistant/frontend|55659|Core UI for database usage; overlaps our Overview tab.|OPEN-READY"
)

for entry in "${watch[@]}"; do
  IFS='|' read -r name prrepo num why baseline <<<"$entry"
  read -r state draft merged <<<"$(gh api "repos/$prrepo/pulls/$num" -q '[.state, .draft, (.merged_at // "none")] | @tsv')"
  if [ "$merged" != "none" ]; then now="MERGED"
  elif [ "$state" = "closed" ]; then now="CLOSED"
  elif [ "$draft" = "true" ]; then now="OPEN-DRAFT"
  else now="OPEN-READY"; fi
  echo "$prrepo#$num ($name): $now (baseline $baseline)"
  if [ "$now" != "$baseline" ]; then
    title="Upstream change: $prrepo#$num is now $now"
    if [ -z "$(gh issue list -R "$repo" --state all --search "\"$title\" in:title" --json number -q '.[0].number')" ]; then
      gh issue create -R "$repo" --title "$title" --body "Watched upstream PR changed state: https://github.com/$prrepo/pull/$num

**$name** went from $baseline to **$now**.

Why it matters: $why

After handling it, update the baseline in \`.github/scripts/upstream_watch.sh\`."
    fi
  fi
done
