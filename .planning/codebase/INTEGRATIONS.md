# External Integrations

## Core APIs
- **Currents API**
  - **Purpose**: Primary real-time news source.
  - **Auth**: API Key passed via `config/settings.yaml`.
  - **Endpoint**: `https://api.currentsapi.services/v1/latest-news`
  - **Usage**: Used in `scripts/fetch_news.py` to retrieve up to 1000 requests/day.

- **Google Sheets API**
  - **Purpose**: Logging generated posts and acting as a single source of truth database.
  - **Auth**: GCP Service Account JSON key (`credentials_path` in `settings.yaml`).
  - **Libraries**: `gspread`, `oauth2client`
  - **Usage**: Used in `scripts/log_to_sheets.py` to append rows to a specified spreadsheet.

## Ancillary Services
- **Logo.dev / Hunter.io Logos**
  - **Purpose**: Fetching company logos dynamically by domain name.
  - **Auth**: None (Public endpoints).
  - **Usage**: Used in `scripts/render_html.py` as a fallback for the deprecated Clearbit API (`https://logos.hunter.io/:domain`).

- **RSS Feeds**
  - **Purpose**: Secondary/fallback news ingestion from predefined Indian and Global tech/business publications.
  - **Auth**: None.
  - **Usage**: Parsed via `feedparser` in `scripts/fetch_news.py`.

- **GitHub Releases (Inter Fonts)**
  - **Purpose**: Downloading the Inter font family (Black, Bold, Regular).
  - **Usage**: Fetched by `scripts/download_fonts.py` from the official `rsms/inter` release ZIP.
