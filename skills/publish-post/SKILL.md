---
name: publish-post
description: Publish review-passed posts directly to the user's own Instagram Business/Creator account via the Graph API. Inert (logs "publish skipped") until instagram.access_token / ig_user_id / public_base_url are configured in config/settings.yaml - safe to always run as the last pipeline step.
version: 1.0.0
author: moatdaily
---

# Publish Post

## Objective
Push each post that passed review straight to Instagram, using the user's own account and token - no third-party posting service, no vendor lock-in.

## When to Use
- After `log-post` (the Sheet row must already exist so this step can update its Posted Status)
- Final step of the pipeline, always safe to run - it no-ops cleanly if Instagram isn't configured yet

## Prerequisites (all three, or it stays inert)
1. An Instagram **Business or Creator** account linked to a Facebook Page.
2. A long-lived Graph API `access_token` and the account's `ig_user_id` in `config/settings.yaml` → `instagram:`.
3. The rendered PNGs reachable at a **public URL** - the Graph API fetches media by URL, not raw bytes. Serve `output/posts/` from the EC2 box (e.g. nginx static route) or sync it to S3/CloudFront, then set `instagram.public_base_url` to that base URL (it must mirror the `output/posts/YYYY-MM-DD/...` structure).

## Steps
```bash
cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
source .venv/bin/activate
python scripts/publish_instagram.py
```
- If any of the three prerequisites are missing, it prints `[SKIP] Instagram publishing not configured` and exits - the posts stay ready for manual upload, nothing else to do.
- If configured, it publishes every post whose `review.json` verdict is `PASS` (static: single media container; carousel: child containers → one carousel container), polls until Instagram finishes processing, then publishes and writes `Posted Status` / `Posted At` back onto that post's row in the Sheet.
- Posts that aren't `PASS` are skipped and printed, not silently dropped.

## Troubleshooting
- `Media container ... failed or timed out processing`: the hosted image URL wasn't reachable/valid to Instagram - check `public_base_url` actually serves that exact path publicly.
- Graph API errors (400/190/etc): usually an expired or wrong-scope token - long-lived Page/IG tokens need the `instagram_content_publish` permission.
- Carousel posts require 2+ children; a single-image "carousel" brief should use `static` instead.

## Next Step
Pipeline complete. Re-run `daily-pipeline` tomorrow - `posted_history.json` (written by `log-post`) keeps the same story from being re-selected.
