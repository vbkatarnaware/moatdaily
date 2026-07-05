#!/usr/bin/env bash
# Prune old rendered/served post images.
#
# Instagram fetches each image once at publish and keeps its own copy, so the
# files we render + serve are disposable after a couple of days. Nothing else
# grows on disk (data/*.json are tiny; temp HTML is auto-deleted at render).
# This deletes date-named subdirs (YYYY-MM-DD) older than RETENTION_DAYS from
# both the served dir and the render-output dir.
#
# Pure bash, no LLM, no Python - safe to run from OS cron independent of Hermes.
#
# Usage:
#   RETENTION_DAYS=3 scripts/cleanup_posts.sh
# Env (all optional):
#   RETENTION_DAYS  days to keep (default 3)
#   SERVED_DIR      Caddy-served images dir (default /srv/moatdaily-posts)
#   OUTPUT_DIR      pipeline render output dir (default <repo>/output/posts)
set -euo pipefail

RETENTION_DAYS="${RETENTION_DAYS:-3}"
SERVED_DIR="${SERVED_DIR:-/srv/moatdaily-posts}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/output/posts}"

prune() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  # Only touch date-named dirs at depth 1 so we never rm the parent itself.
  local removed=0
  while IFS= read -r -d '' d; do
    echo "  removing $(basename "$d")"
    rm -rf "$d"
    removed=$((removed + 1))
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" -print0)
  echo "[$dir] removed $removed dir(s) older than ${RETENTION_DAYS}d"
}

echo "[cleanup_posts] retention=${RETENTION_DAYS}d $(date -u +%FT%TZ)"
prune "$SERVED_DIR"
prune "$OUTPUT_DIR"
