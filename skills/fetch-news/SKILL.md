---
name: fetch-news
description: Fetch fresh startup, business, tech, and AI news via Google News search RSS (India-geo-targeted, bucketed per vertical) and publisher RSS feeds, with Currents API as an optional extra layer. Run this first in the MoatDaily pipeline. Outputs raw_news.json.
version: 2.0.0
author: moatdaily
---

# Fetch News

## Objective
Fetch fresh news across all four verticals (startup, business, tech, AI) the way a person would google India-relevant news every morning - not just whatever a couple of RSS feeds happen to carry.

## When to Use
- First step of the daily MoatDaily content pipeline
- Run once daily (manually, or triggered by whatever orchestrator sits on top, e.g. Hermes/cron)

## Discovery Layers (in order)
1. **Google News search RSS** - `config/news_sources.yaml` → `google_news_queries` has several India-geo-targeted queries (`hl=en-IN&gl=IN&ceid=IN:en`) per vertical (startup/business/tech/ai), so every vertical gets guaranteed coverage each run instead of leaking through whatever a tech feed happens to carry. This is the primary "human googling" layer - free, no API key.
2. **Publisher RSS feeds** - curated, trusted sources per vertical (`config/news_sources.yaml` → `rss_feeds`), including a dedicated AI bucket (Analytics India Magazine, VentureBeat AI, MIT Technology Review).
3. **Currents API** - optional. Only runs if `news.currents_api_key` is set in `config/settings.yaml`; skipped cleanly (no warning) if blank.

All three layers are deduplicated by URL hash into one `raw_news.json`.

## Steps
```bash
cd "/Users/vipulkatarnaware/Documents/AI Agents/moatdaily"
source .venv/bin/activate
python scripts/fetch_news.py
```

## Expected Output
`data/raw_news.json` with articles tagged `category` (startup/business/tech/ai) and `fetch_source` (google_news/rss/currents_api). Each article has: title, description, source, url, image_url, published_at.

Note: Google News RSS `description` is HTML-stripped but still often thin (near-duplicate of the title) - `write-copy` compensates by scraping the full article body (`source_text`) from the actual `url` via `scripts/fetchers.py`, not this step's description field.

## Troubleshooting
- If 0 articles from Google News: check internet connectivity, or that the query strings in `news_sources.yaml` still resolve (Google occasionally changes RSS search syntax).
- Currents API failures are non-fatal and silent by design - it's an optional extra layer, not a dependency.
- If total article count is low: the per-vertical query list in `news_sources.yaml` can be extended.

## Next Step
→ Run the `filter-news` skill
