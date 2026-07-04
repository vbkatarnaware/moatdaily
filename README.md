# MoatDaily

AI-agent-powered Instagram content pipeline for daily startup, business, AI, and tech news - targeting Indian audiences.

## What This Is
Scripts + skills that any CLI agent (Codex, Claude Code, Antigravity, Open Code) or orchestrator (Hermes, OpenClaw, etc.) can run to generate premium Instagram posts automatically.

**We build**: Skills, scripts, templates, configs.
**We don't build**: Agent runtimes, schedulers, memory - your agent platform handles that.

## Pipeline

```
Fetch -> Filter -> Write -> Select Images -> Render -> Review -> Log -> Publish
```

1. **Fetch** - Google News search RSS (India-geo-targeted, bucketed per vertical) + publisher RSS feeds, Currents API as an optional extra layer
2. **Filter** - Score on India relevance + engagement + uniqueness, skipping anything already in `posted_history.json`
3. **Write** - AI generates headlines, captions, hashtags, grounded in `source_title`/`source_description`/`source_text` (a real article-body scrape) - reframing is fine, inventing facts is not
4. **Select Images** - AI picks the single most relevant real photo per post, either directly from the web (preferred) or from a gathered candidate set
5. **Render** - Playwright + Jinja2 render a reserved-panel editorial template (4:5): photo zone on top, solid text panel on the bottom, so the subject never ends up under the headline
6. **Review** - A mechanical pre-filter (size, corruption, copy length, disclaimer, no em dashes, face-in-panel safety net) plus a real AI visual check (relevance, readability, premium feel), 3 retries
7. **Log** - Google Sheets + local JSON + `posted_history.json` (cross-day dedup)
8. **Publish** - Direct Instagram Graph API post to the user's own account; inert until credentials + a public image host are configured

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium   # if scrapling[fetchers] downgraded your Playwright install, rerun this

# Download fonts (one-time)
python scripts/download_fonts.py

# Run full pipeline
python scripts/fetch_news.py
python scripts/filter_news.py --count 4
python scripts/write_copy.py
# -> Fill copy text + assets.image_url (or entities/primary_query) in data/copy.json (AI agent does this)
python scripts/gather_images.py   # only needed if the agent didn't already pick assets.image_url directly
python scripts/render_html.py
python scripts/review_post.py
python scripts/log_to_sheets.py
python scripts/publish_instagram.py   # no-op until instagram.* is configured in config/settings.yaml
```

Or tell your AI agent: **"Run the daily-pipeline skill"**

## Skills (for AI Agents)
Each step has a `SKILL.md` in `skills/` - any agent that reads SKILL.md can run the pipeline:

| Skill | What It Does |
|-------|-------------|
| `fetch-news` | Google News search RSS + publisher RSS across startup/business/tech/AI |
| `filter-news` | Scores and picks top 3-6, skipping already-posted stories |
| `write-copy` | Generates copy briefs (AI fills text, grounded in the scraped source) |
| `select-images` | AI picks the most relevant real photo per post |
| `render-post` | Renders Instagram PNGs (reserved-panel layout) |
| `review-post` | Mechanical pre-filter + real AI visual quality gate, 3 retries |
| `log-post` | Logs to Google Sheets + local JSON, records `posted_history.json` |
| `publish-post` | Publishes to the user's own Instagram account (inert until configured) |
| `daily-pipeline` | Runs the whole pipeline end-to-end |

## Config
- `config/settings.yaml` - API keys, Sheet ID, Instagram credentials (gitignored - copy `settings.example.yaml` to get started)
- `config/brand.yaml` - Colors, fonts, layout, reserved-panel geometry, image finish
- `config/news_sources.yaml` - Google News query buckets, RSS feeds, scoring rules

## Tech Stack
- **Python 3.11+** (Playwright, Jinja2, Pillow, opencv-contrib-python-headless, rembg, feedparser, gspread)
- **Google News search RSS** (free, no key, India geo-targeted) + curated publisher RSS; **Currents API** optional
- **Scrapling** (`scripts/fetchers.py`) - stealth article fetching for og:image + body text past 403/hotlink blocks, with a plain-`requests` fallback if not installed
- **Image sourcing**: agent-direct web search (preferred), article og:image, Wikipedia lead image for named entities, Brave image search - all free
- **Google Sheets** (via gspread)
- **Instagram Graph API** (`scripts/publish_instagram.py`) - direct to the user's own account, no vendor lock-in
- **SKILL.md** (open standard, works with all agents)
