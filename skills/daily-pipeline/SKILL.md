---
name: daily-pipeline
description: Runs ONE MoatDaily posting slot end-to-end - fetch, filter a pool of 4, write copy, render, review, publish the best 2 that pass. Triggered 3x/day by Hermes cron. Use this for automated runs.
version: 3.0.0
author: moatdaily
---

# MoatDaily - Daily Pipeline (per-slot, server/Docker)

## Objective
Publish **up to 2 fresh Instagram posts** for one time slot, drawn from a pool of
**4** candidates - so if one or two candidates get rejected (bad image, failed
copy-accuracy check), the next-best candidate backfills instead of shrinking the
slot. Runs 3x/day (10 AM, 3 PM, 9 PM IST) as independent slots - each slot
fetches fresh news and posts up to 2, so a failure in one slot never affects the
others. Already-posted stories are skipped automatically (posted_history +
Sheets dedup), so slots self-coordinate with no shared "daily plan".
**Publishing fewer than 2, including zero, is a normal and correct outcome when
enough of the 4 candidates are rejected** - see Rules below.

## Rules (do not violate)
- Run each script below **exactly once, in order**. Never re-run a step that
  already completed - especially `publish_instagram.py`: running it twice will
  attempt to republish (it has its own idempotency ledger, but there is no
  reason to ever call it a second time in one slot).
- **Never edit `data/review.json`, `data/render_manifest.json`, or any other
  script output file.** `publish_instagram.py` independently re-verifies image
  presence, mechanical status, and a live Gemini check itself before publishing
  each post - it is authoritative and cannot be "fixed" by editing files.
- If `review_post.py` or `publish_instagram.py` rejects a post (wrong/missing
  image, failed copy-accuracy check), **accept that outcome**. Do not re-render,
  do not retry, do not patch data files to force it through. Just report what
  actually published.

## When to Use
- The Hermes cron job fires (3x/day). Each fire = one slot = up to 2 posts.
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

### 2. Filter (pool of 4 for this slot)
```bash
eval $D python scripts/filter_news.py --count 4
```
-> `data/filtered_news.json` with the top 4 UNPOSTED stories (dedup drops
anything already posted today/earlier). Mostly `static`, occasional `carousel`.
Deliberately larger than the 2 that will actually publish - `publish_instagram.py`
(step 8) publishes the best 2 that pass every gate, backfilling from this pool
when a candidate is rejected. Write copy for **all 4** in step 4; do not trim the
pool down to 2 yourself.

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
`ai_verdict`/`ai_notes` automatically - no separate vision step needed. A live AI
verdict is mandatory to publish (step 8 re-checks it itself): if Gemini is
unavailable on every path (direct free tier and the `review.openrouter_api_key`
last-resort fallback), the post is skipped even on a mechanical PASS - a
mechanical check alone cannot catch a wrong-identity photo or an invented fact.

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
This is the final, authoritative gate - it independently re-checks each post
(not already published this slot, a real image was found, mechanical PASS, and
a live Gemini re-check) before publishing, regardless of what `review.json`
says. It walks the pool of up to 4 candidates in ranked order, skips any that
fail a gate, and publishes the first 2 that pass - this is what makes the
pool-of-4 backfill work, with zero extra flags needed. Copies each published
image into `/srv/moatdaily-posts/` for Caddy, and the Graph API fetches it by
URL. The token self-refreshes here if near expiry. **Call this exactly once per
slot.**

## Failure handling
If any stage exits nonzero, stop and report - don't force later stages. The next
slot is independent and will run clean. Within a slot, stages 1-7 checkpoint via
`data/*.json`, so a re-run resumes rather than restarts - but do not re-run
`publish_instagram.py` (step 8) as a "fix"; see Rules above.

## Scheduling (Hermes cron)
One job, fires 3x/day: `30 4,9,15 * * *` UTC = 10 AM / 3 PM / 9 PM IST. Each fire
runs this skill once (2 posts). Registered via `hermes cron`, not by editing
jobs.json.
