---
name: daily-pipeline
description: Master skill - runs the complete MoatDaily pipeline end-to-end. Fetches news, filters, writes copy, picks images, renders posts, reviews quality, and logs to Google Sheets. Use this for daily automated runs.
version: 2.0.0
author: moatdaily
---

# MoatDaily - Daily Pipeline (Master Skill)

## Objective
Run the complete content pipeline: fetch -> filter -> write -> select images -> render -> review -> log (-> publish, once Instagram credentials exist).
Produces 3-6 ready-to-publish Instagram posts about startup/business/AI/tech news for Indian audiences.

## When to Use
- Daily content generation (manually or via an orchestrator like Hermes)
- When someone says "generate today's posts" or "run moatdaily"

## Prerequisites
- Python 3.11+ with dependencies: `pip install -r requirements.txt`
- News source keys configured in `config/settings.yaml` (Currents API is optional; Google News RSS + publisher RSS need no key)
- Google Sheets credentials at the configured path (optional - logging degrades to local-only without it)
- Fonts in `templates/fonts/` (Inter Black, Inter Regular, Inter Bold)

## Full Pipeline

### Step 1: Fetch News
```bash
cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
source .venv/bin/activate
python scripts/fetch_news.py
```
Expected: `data/raw_news.json` with articles across all four verticals (startup, business, tech, AI).

### Step 2: Filter & Score
```bash
python scripts/filter_news.py --count 4
```
Expected: `data/filtered_news.json` with the top stories.
**AI Action**: Review selections, swap if any story is weak for the Indian audience.

### Step 3: Generate Copy Briefs
```bash
python scripts/write_copy.py
```
Expected: `data/copy.json` with empty text fields.
**AI Action**: Fill every `copy.*.text` field (headline/subline/caption/carousel_slides), grounded in `source_title`/`source_description`/`source_text` - reframing is fine, inventing facts is not. See the `write-copy` skill for the full rules.

### Step 4: Select Images
See the `select-images` skill. Preferred: search the web directly and write the chosen photo's URL into `assets.image_url`. Fallback (no browsing available): run `python scripts/gather_images.py`, then pick from `data/image_candidates.json`.

### Step 5: Render Posts
```bash
python scripts/render_html.py
```
Expected: PNG files in `output/posts/YYYY-MM-DD/` - reserved-panel layout (photo zone + solid text panel), 4:5 for both static and carousel.

### Step 6: Review Quality
```bash
python scripts/review_post.py
```
Expected: `data/review.json` with a mechanical PASS/FAIL per post.
**AI Action**: For every mechanical PASS, actually look at the rendered PNG and judge relevance, readability, and premium feel - write `ai_verdict`/`ai_notes` back into `data/review.json`. See the `review-post` skill. If FAIL -> fix and re-render (max 3 retries).

### Step 7: Log Results
```bash
python scripts/log_to_sheets.py
```
Expected: Rows appended to the Google Sheet + `data/log.json` backup.

### Step 8: Publish (once Instagram credentials are configured)
See the `publish-post` skill. Inert (logs "publish skipped") until `instagram.access_token` / `instagram.ig_user_id` are set in `config/settings.yaml`.

## Output
After the pipeline completes:
- 3-6 Instagram-ready PNG posts in `output/posts/YYYY-MM-DD/`
- Matching captions in `data/copy.json`
- Full log in Google Sheets
- Published to Instagram automatically once credentials are configured; otherwise ready for manual upload

## Scheduling (for Cron/Orchestrators like Hermes)
This pipeline has no built-in scheduler - it's designed to be run manually or triggered by whatever orchestrator sits on top (Hermes, cron, etc.):
```
Cron: 30 1 * * *
Task: Run the daily-pipeline skill
```
This is a 1:30 AM UTC = 7:00 AM IST run.
