# Directory Structure

```text
moatdaily/
├── config/                 # YAML configuration files (Settings, Brand, News Sources)
├── data/                   # Runtime state (JSON files passed between scripts)
├── output/                 # Final artifacts (Rendered Instagram post PNGs)
├── scripts/                # Atomic Python scripts for each pipeline step
├── skills/                 # SKILL.md wrappers for AI agent orchestration
└── templates/              # Static assets (fonts) used for rendering
```

## Key Locations
- **Configuration**:
  - `config/settings.yaml`: API keys and external IDs.
  - `config/brand.yaml`: Colors, typography sizes, layout dimensions.
  - `config/news_sources.yaml`: RSS endpoints and keyword scoring weights.
- **Business Logic (Scripts)**:
  - `scripts/fetch_news.py`, `scripts/filter_news.py`, `scripts/write_copy.py`, `scripts/render_html.py`, `scripts/review_post.py`, `scripts/log_to_sheets.py`.
- **Agent Interfaces**:
  - `skills/daily-pipeline/SKILL.md`: The master workflow definition.
  - `skills/<task>/SKILL.md`: Atomic instructions for agents to execute a specific script.

## Naming Conventions
- **Scripts**: `snake_case.py` (e.g., `fetch_news.py`).
- **Skills**: `kebab-case` directories containing a single `SKILL.md` (e.g., `fetch-news`).
- **Data Files**: `snake_case.json` (e.g., `raw_news.json`).
