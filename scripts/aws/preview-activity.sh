#!/usr/bin/env bash
set -euo pipefail
active_jobs="${1:-0}"
[[ "$active_jobs" =~ ^[0-9]+$ ]] || { echo "Usage: $0 ACTIVE_JOB_COUNT" >&2; exit 2; }
parameter="${PREVIEW_ACTIVITY_PARAMETER:-/keep-and-lease/preview/activity}"
aws ssm put-parameter --name "$parameter" --type String --overwrite --value "$(date +%s):${active_jobs}" >/dev/null

