#!/usr/bin/env bash
# Warn when the root filesystem crosses a disk-usage threshold.
#
# A disk-full root volume crashed Hermes's cron scheduler on 2026-07-07 (its
# SQLite jobs.json couldn't be read/written), silently skipping every posting
# slot that day with no alert anywhere. docker_prune.sh + cleanup_posts.sh
# address the known causes (stale images, old rendered posts) but this is a
# tripwire for any *other* future cause (journal logs, containerd garbage, a
# runaway process) - so it surfaces before the scheduler goes down again,
# instead of being discovered the next day as "no posts went out."
#
# Only prints/logs a line when the threshold is crossed, so the cron log stays
# quiet on healthy days - same convention as cleanup_posts.sh only logging
# actual removals.
#
# Pure bash, no LLM, no Python - safe to run from OS cron independent of
# Hermes.
#
# Usage:
#   scripts/check_disk_space.sh
# Env (optional):
#   DISK_THRESHOLD_PCT  warn at/above this usage percentage (default 85)
#   DISK_MOUNT          filesystem to check (default /)
set -euo pipefail

DISK_THRESHOLD_PCT="${DISK_THRESHOLD_PCT:-85}"
DISK_MOUNT="${DISK_MOUNT:-/}"

used_pct="$(df -P "$DISK_MOUNT" | awk 'NR==2 {gsub("%","",$5); print $5}')"

if [ "$used_pct" -ge "$DISK_THRESHOLD_PCT" ]; then
  echo "[check_disk_space] WARNING $(date -u +%FT%TZ) ${DISK_MOUNT} at ${used_pct}% (threshold ${DISK_THRESHOLD_PCT}%)"
fi
