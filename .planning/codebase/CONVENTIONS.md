# Conventions

## Code Style
- **Python**: Standard PEP8 conventions. 
- **Simplicity over Object Orientation**: Scripts are largely procedural with functional blocks. They use a standard `if __name__ == "__main__": main()` execution pattern. No complex class hierarchies; functions take dictionaries as arguments.

## State Management Pattern
- **File-based Handoff**: Because the pipeline is designed to be executed by CLI agents (which are stateless between invocations), all state is passed via JSON files in the `data/` directory.
- `fetch_news.py` writes `data/raw_news.json`
- `filter_news.py` reads `data/raw_news.json` and writes `data/filtered_news.json`
- `write_copy.py` reads `data/filtered_news.json` and writes `data/copy.json`
- The AI Agent fills the blanks in `data/copy.json`.
- `render_post.py` reads `data/copy.json` and writes PNGs + `data/render_manifest.json`
- `review_post.py` reads `data/copy.json` + `data/render_manifest.json` and writes `data/review.json`
- `log_to_sheets.py` reads everything and writes to Google Sheets.

## Error Handling
- Scripts use simple `try-except` blocks for network calls (API fetching, Image downloading). 
- If an image download fails during rendering, the script falls back to a gradient background rather than crashing.
- Output warnings to STDOUT (e.g., `[WARN] Currents API returned 400`).

## Configuration Pattern
- Scripts use a standard `load_config()` helper function at the top to parse the YAML config files into Python dictionaries.
