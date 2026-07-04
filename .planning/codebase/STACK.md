# Tech Stack

## Core Language & Runtime
- **Python**: 3.11+ (Primary language for all pipeline scripts)

## Core Dependencies
- **Pillow (`Pillow>=10.0.0`)**: Image creation, text overlay, and compositing for the Instagram post visuals.
- **rembg (`rembg[cpu,cli]>=2.0.0`)**: AI background removal (using U²-Net models) for cleaning founder/product photos.
- **feedparser (`feedparser>=6.0.0`)**: Parsing RSS/Atom feeds as a fallback news ingestion source.
- **gspread (`gspread>=6.0.0`)**: Google Sheets read/write capabilities for logging.
- **oauth2client (`oauth2client>=4.1.3`)**: Authentication for Google Sheets via Service Account credentials.
- **requests (`requests>=2.31.0`)**: HTTP calls for fetching APIs, downloading images, and downloading logos.
- **PyYAML (`pyyaml>=6.0`)**: Parsing configuration files (`settings.yaml`, `brand.yaml`, `news_sources.yaml`).

## Build & Environment
- **Virtual Environment**: Standard Python `venv` (`.venv/`)
- **Package Management**: `pip` with `requirements.txt`

## Configuration & Assets
- **Configuration**: YAML files (`config/`)
- **State/Data**: JSON files (`data/` - e.g., `raw_news.json`, `copy.json`)
- **Fonts**: TrueType fonts (`templates/fonts/`) downloaded from Google Fonts / Inter GitHub releases.
