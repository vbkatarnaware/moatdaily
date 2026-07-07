#!/usr/bin/env bash
# Prune dangling (untagged, <none>) Docker images.
#
# Every image update on the box is a manual `docker pull` with no cleanup step
# afterward, which leaves the previous image behind as a dangling ~3.5GB blob.
# Repeated over a week of deploys this silently filled the EC2 root volume to
# 100%, which crashed Hermes's cron scheduler (its SQLite jobs.json couldn't be
# read/written) and caused a full day of missed posting slots on 2026-07-07.
#
# `docker image prune -f` only removes images with no tag and no container
# referencing them - it never touches a running container or a currently
# tagged image (e.g. the live `moatdaily:latest`), so this is safe to run
# unattended.
#
# Pure bash, no LLM, no Python - safe to run from OS cron independent of
# Hermes, same as scripts/cleanup_posts.sh.
#
# Usage:
#   scripts/docker_prune.sh
set -euo pipefail

echo "[docker_prune] $(date -u +%FT%TZ)"
docker image prune -f
