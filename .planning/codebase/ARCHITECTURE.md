# System Architecture

## Architecture Pattern
The project follows a **Sequential Data Pipeline / Workflow Engine** architecture, orchestrated by an AI agent (or chron-job) invoking individual Python scripts in sequence. It relies on a file-based state-passing mechanism (JSON files).

## Data Flow
The data flows sequentially through 6 distinct stages, persisting state to disk at each step:
1. **Fetch**: `scripts/fetch_news.py` → Generates `data/raw_news.json`
2. **Filter**: `scripts/filter_news.py` → Reads `raw_news.json`, generates `data/filtered_news.json`
3. **Write**: `scripts/write_copy.py` → Reads `filtered_news.json`, generates structured prompts in `data/copy.json`
4. **AI Generation (Agent Role)**: An external AI agent fills the empty `text` fields within `data/copy.json`.
5. **Render**: `scripts/render_html.py` → Reads `copy.json`, generates PNG images in `output/posts/YYYY-MM-DD/`, creates `data/render_manifest.json`
6. **Review & Log**: `scripts/review_post.py` and `scripts/log_to_sheets.py` → Checks quality, outputs `data/review.json`, and uploads the final state to Google Sheets.

## Key Abstractions
- **Skills (`SKILL.md`)**: The interface layer for AI Agents. Instead of agents guessing how to run the Python scripts, they read standard `SKILL.md` files (e.g., `skills/fetch-news/SKILL.md`) that contain explicit bash commands and execution logic.
- **Config-Driven**: Behavior, weights for news scoring, and brand guidelines (colors, typography) are completely decoupled into `config/*.yaml` files to allow easy pivoting without code changes.

## Entry Points
- The primary entry point for a human/cron is the `daily-pipeline` master skill.
- Individual scripts in `scripts/*.py` serve as atomic entry points for specific tasks.
