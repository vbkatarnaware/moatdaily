---
name: log-post
description: Log completed posts to Google Sheets (single source of truth) and local JSON backup, and record them in posted_history.json so the same story is never re-selected on a later day. Second-to-last step - publish-post runs after this.
version: 2.0.0
author: moatdaily
---

# Log Post

## Objective
Record all generated posts to Google Sheets for tracking and to local JSON as backup.

## When to Use
- After `review-post` has passed all posts (or flagged unfixable ones)
- Final step of the MoatDaily pipeline

## Steps
1. Run the logger:
   ```bash
   cd /Users/vipulkatarnaware/Documents/AI\ Agents/moatdaily
   python scripts/log_to_sheets.py
   ```
2. Verify the Google Sheet has new rows
3. Verify local backup at `data/log.json`

## What Gets Logged
Each row in Google Sheets contains:
| Column | Description |
|--------|-------------|
| Date | Post date |
| Article ID | Unique ID |
| Headline | Post headline |
| Post Type | static / carousel |
| Status | ready / needs_fix |
| India Score | 0-10 |
| Engagement Score | 0-10 |
| Total Score | Weighted total |
| Image Path | Path to rendered PNG |
| Image Source | Which sourcing-waterfall step won (direct/og:image/wikipedia/brave/fallback) |
| Caption Preview | First 200 chars of caption |
| Source | News source name |
| URL | Original article URL |
| Review Status | PASS / FAIL |
| Posted Status | `not_posted` until `publish-post` updates it to `posted` |
| Posted At | Filled in by `publish-post` on success |

## Also Writes: `data/posted_history.json`
Every post whose `status` is `ready` (review passed) gets appended here as `{id, title_key, headline, date}` - both the URL-hash `id` and a normalized `title_key` are stored, since Google News RSS links are per-crawl proxy URLs that change daily even for the same underlying story. `filter-news` reads this file to skip already-covered stories on later runs.

## Troubleshooting
- If Google Sheets fails: Check credentials at path in `config/settings.yaml`
- Make sure the service account email has Editor access to the spreadsheet
- Local backup always saves regardless of Sheets status

## Next Step
→ Run the `publish-post` skill. It stays inert (logs "publish skipped") until Instagram credentials are configured in `config/settings.yaml` - until then, posts are ready for manual upload.
