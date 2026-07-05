---
name: daily-pipeline
description: Runs ONE MoatDaily posting slot end-to-end - fetch, filter, write copy, render, review, publish 2 fresh posts. Triggered 3x/day by Hermes cron. Use this for automated runs.
version: 3.0.0
author: moatdaily
---

# MoatDaily - Daily Pipeline (per-slot, server/Docker)

## Objective
Publish **2 fresh Instagram posts** for one time slot. Runs 3x/day (10 AM, 3 PM,
9 PM IST) as independent slots - each slot fetches fresh news and posts 2, so a
failure in one slot never affects the others. Already-posted stories are skipped
automatically (posted_history + Sheets dedup), so slots self-coordinate with no
shared "daily plan".

## When to Use
- The Hermes cron job fires (3x/day). Each fire = one slot = 2 posts.
- Or manually: "run a MoatDaily slot".

## Runtime: Docker on EC2
All mechanical stages run in the prebuilt image. Define the run prefix once:

```bash
D='docker run --rm \
  -v /home/ubuntu/moatdaily/config/settings.yaml:/app/config/settings.yaml:ro \
  -v /home/ubuntu/moatdaily/credentials:/app/credentials:ro \
  -v /home/ubuntu/moatdaily/data:/app/data \
  -v /home/ubuntu/moatdaily/output:/app/output \
  -v /srv/moatdaily-posts:/srv/moatdaily-posts \
  ghcr.io/vbkatarnaware/moatdaily:latest'
```
Notes: `data/` and `output/` are read-write (the pipeline reads/writes JSON +
PNGs). `/srv/moatdaily-posts` is where publish copies the image for Caddy to
serve. `settings.yaml`/`credentials` are read-only. On the server,
`instagram.host_upload.ssh_target` is `""` so publish copies locally into /srv.

## The slot (run in order)

### 1. Fetch
```bash
eval $D python scripts/fetch_news.py
```
-> `data/raw_news.json`.

### 2. Filter (only 2 for this slot)
```bash
eval $D python scripts/filter_news.py --count 2
```
-> `data/filtered_news.json` with the top 2 UNPOSTED stories (dedup drops
anything already posted today/earlier). Mostly `static`, occasional `carousel`.

### 3. Scaffold copy briefs
```bash
eval $D python scripts/write_copy.py
```
-> `data/copy.json` with empty `copy.*.text` fields + `source_title` /
`source_description` / `source_text` for grounding.

### 4. Write the copy  (the ONLY LLM step - you do this)
Edit `/home/ubuntu/moatdaily/data/copy.json`: fill every `copy.*.text` field
(kicker/headline/subline/caption, and `carousel_slides` for carousels), grounded
in the `source_*` fields. Reframing/condensing/opinion is fine; inventing facts,
numbers, dates, quotes, or names is NOT. No em dash characters anywhere. See the
`write-copy` skill for the full rules. The free text model is enough for this.

### 5. Render
```bash
eval $D python scripts/render_html.py
```
-> PNGs in `output/posts/YYYY-MM-DD/` + `data/render_manifest.json`. Images are
auto-selected mechanically (no vision model needed) - `assets.resolve_hero_image`
picks a real, non-logo photo per post/slide.

### 6. Review (mechanical + automated Gemini vision/copy-accuracy check)
```bash
eval $D python scripts/review_post.py
```
-> `data/review.json` with `mechanical_status` PASS/FAIL per post. When
`review.gemini_api_key` is set in `config/settings.yaml`, this script also calls
Gemini to judge photo relevance/watermarks and caption factual accuracy, filling
`ai_verdict`/`ai_notes` automatically - no separate vision step needed. Without a
key, `ai_verdict` stays null and a mechanical PASS is enough to publish (`publish`
falls back to `mechanical_status`).

### 7. Log
```bash
eval $D python scripts/log_to_sheets.py
```
-> appends to the Google Sheet (+ `data/log.json`) and updates
`data/posted_history.json` / the Sheet `PostedHistory` tab for dedup.

### 8. Publish
```bash
eval $D python scripts/publish_instagram.py --limit 2
```
Publishes the review-PASSed posts (max 2), copies each image into
`/srv/moatdaily-posts/` for Caddy, and the Graph API fetches it by URL. The token
self-refreshes here if near expiry.

## Failure handling
If any stage exits nonzero, stop and report - don't force later stages. The next
slot is independent and will run clean. Within a slot, stages checkpoint via
`data/*.json`, so a re-run resumes rather than restarts.

## Scheduling (Hermes cron)
One job, fires 3x/day: `30 4,9,15 * * *` UTC = 10 AM / 3 PM / 9 PM IST. Each fire
runs this skill once (2 posts). Registered via `hermes cron`, not by editing
jobs.json.
