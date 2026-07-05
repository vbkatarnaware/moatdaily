#!/usr/bin/env python3
"""
MoatDaily - Google Sheets Logger
Appends post data to Google Sheets (single source of truth).
Also saves local backup to data/log.json.

Usage: python scripts/log_to_sheets.py
"""

import json
from datetime import datetime
from pathlib import Path

import yaml

import sanitize

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("[WARN] gspread not installed. Will save locally only.")


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    return settings, root


POSTED_HISTORY_TAB = "PostedHistory"
POSTED_HISTORY_HEADERS = ["Article ID", "Title Key", "Headline", "Date"]


def _open_sheet(settings):
    """Authorize and open the spreadsheet. Returns (client, sheet) or (None, None)."""
    if not GSPREAD_AVAILABLE:
        return None, None

    # Resolve a relative credentials_path against the repo root, so one
    # settings.yaml works unchanged on any host (Mac, EC2, inside Docker where
    # the repo root is /app). Absolute paths are left as-is for back-compat.
    creds_path = Path(settings["sheets"]["credentials_path"])
    if not creds_path.is_absolute():
        creds_path = Path(__file__).parent.parent / creds_path
    creds_path = str(creds_path)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(settings["sheets"]["spreadsheet_id"])
        return client, sheet
    except Exception as e:
        print(f"[ERROR] Google Sheets connection failed: {e}")
        return None, None


def get_posted_history_worksheet(settings):
    """Get (or create) the PostedHistory tab used for cross-environment dedup.
    Returns the worksheet or None if Sheets is unavailable."""
    _, sheet = _open_sheet(settings)
    if not sheet:
        return None
    try:
        return sheet.worksheet(POSTED_HISTORY_TAB)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=POSTED_HISTORY_TAB, rows=2000, cols=4)
        ws.append_row(POSTED_HISTORY_HEADERS)
        return ws
    except Exception as e:
        print(f"[WARN] PostedHistory tab unavailable: {e}")
        return None


def read_posted_history_from_sheet(settings):
    """Return (ids_set, title_keys_set) from the PostedHistory tab, or
    (None, None) if Sheets is unavailable - caller then relies on local JSON."""
    ws = get_posted_history_worksheet(settings)
    if not ws:
        return None, None
    try:
        rows = ws.get_all_values()[1:]  # skip header
        ids = {r[0] for r in rows if r and r[0]}
        title_keys = {r[1] for r in rows if len(r) > 1 and r[1]}
        return ids, title_keys
    except Exception as e:
        print(f"[WARN] Could not read PostedHistory tab: {e}")
        return None, None


POSTS_HEADERS = [
    "Date", "Article ID", "Headline", "Post Type", "Status",
    "India Score", "Engagement Score", "Total Score",
    "Image Path", "Image Source", "Caption Preview", "Source", "URL",
    "Review Status", "Rendered At", "Posted Status", "Posted At", "Logged At"
]


def get_sheets_client(settings):
    """Initialize Google Sheets client for the main Posts tab."""
    if not GSPREAD_AVAILABLE:
        return None, None

    client, sheet = _open_sheet(settings)
    if not sheet:
        return None, None
    try:
        worksheet_name = settings["sheets"].get("worksheet_name", "Posts")
        try:
            worksheet = sheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=worksheet_name, rows=1000, cols=18)
            worksheet.append_row(POSTS_HEADERS)

        # Self-repair: an existing sheet's header can predate a schema change (it did -
        # a live run appended rows against a header missing "Image Source"/"Posted
        # Status", silently shifting every column). Re-check and fix it every time
        # rather than only at worksheet creation.
        last_col_letters = gspread.utils.rowcol_to_a1(1, len(POSTS_HEADERS))[:-1]
        if worksheet.row_values(1) != POSTS_HEADERS:
            worksheet.update(range_name=f"A1:{last_col_letters}1", values=[POSTS_HEADERS])

        return client, worksheet
    except Exception as e:
        print(f"[ERROR] Google Sheets connection failed: {e}")
        return None, None


def _post_data_to_row(post_data):
    return [
        post_data.get("date", ""),
        post_data.get("article_id", ""),
        post_data.get("headline", "")[:100],
        post_data.get("post_type", ""),
        post_data.get("status", ""),
        post_data.get("india_score", ""),
        post_data.get("engagement_score", ""),
        post_data.get("total_score", ""),
        post_data.get("image_path", ""),
        post_data.get("image_source", ""),
        post_data.get("caption_preview", "")[:200],
        post_data.get("source", ""),
        post_data.get("url", ""),
        post_data.get("review_status", ""),
        post_data.get("rendered_at", ""),
        post_data.get("posted_status", "not_posted"),
        post_data.get("posted_at", ""),
        datetime.now().isoformat(),
    ]


def log_to_sheets(worksheet, post_data_list):
    """Append all of this run's posts to Google Sheets in a single call.

    A slot's posts used to be appended one row at a time, which let two
    back-to-back append_row() calls race on "next empty row" and land one row
    shifted into the wrong columns (observed directly during testing). Batching
    into one append_rows() call is both the fix and fewer API calls per slot.
    """
    if not worksheet:
        return False

    try:
        rows = [_post_data_to_row(post_data) for post_data in post_data_list]
        worksheet.append_rows(rows, value_input_option="RAW")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to append rows: {e}")
        return False


def mark_posted_in_sheet(worksheet, article_id, posted_at):
    """
    Used by publish_instagram.py after a successful publish, to update the
    Posted Status / Posted At columns on that article's row (log-post already
    ran and appended the row with posted_status="not_posted").
    Finds the row by Article ID column (added most-recent-last, so the last
    match wins if a story was ever logged more than once).
    """
    if not worksheet:
        return False
    try:
        cell = worksheet.find(article_id, in_column=2)  # Article ID is column 2
        if not cell:
            return False
        header = worksheet.row_values(1)
        posted_status_col = header.index("Posted Status") + 1
        posted_at_col = header.index("Posted At") + 1
        worksheet.update_cell(cell.row, posted_status_col, "posted")
        worksheet.update_cell(cell.row, posted_at_col, posted_at)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update posted status in sheet: {e}")
        return False


def update_posted_history(data_dir, winners, settings=None):
    """
    Append this run's successfully-reviewed posts (article id + hashed URL,
    and a normalized title_key since Google News links are per-crawl proxy
    URLs) to data/posted_history.json (fast, offline-safe) AND, when settings
    is given, to the Sheet's PostedHistory tab - so dedup works across every
    host that shares the Sheet (Mac, EC2), not just one machine's local file.
    """
    history_path = data_dir / "posted_history.json"
    history = {"entries": []}
    if history_path.exists():
        with open(history_path) as f:
            history = json.load(f)

    seen_ids = {e["id"] for e in history["entries"]}
    new_entries = []
    for w in winners:
        if w["id"] in seen_ids:
            continue
        history["entries"].append(w)
        new_entries.append(w)
        seen_ids.add(w["id"])

    with open(history_path, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    # Mirror new entries to the Sheet for cross-environment dedup (best-effort).
    if settings and new_entries and GSPREAD_AVAILABLE:
        ws = get_posted_history_worksheet(settings)
        if ws:
            try:
                existing = set(ws.col_values(1))  # column 1 = Article ID (+ header)
                rows = [
                    [w["id"], w.get("title_key", ""), w.get("headline", "")[:100], w.get("date", "")]
                    for w in new_entries if w["id"] not in existing
                ]
                if rows:
                    ws.append_rows(rows)
            except Exception as e:
                print(f"[WARN] Could not append to PostedHistory tab: {e}")


def main():
    settings, root = load_config()
    data_dir = root / settings["output"]["data_dir"]

    # Load all pipeline data
    copy_path = data_dir / "copy.json"
    review_path = data_dir / "review.json"
    manifest_path = data_dir / "render_manifest.json"

    if not copy_path.exists():
        print("❌ copy.json not found.")
        return

    with open(copy_path) as f:
        copy_data = json.load(f)

    # Load review data if available
    review_map = {}
    if review_path.exists():
        with open(review_path) as f:
            review_data = json.load(f)
        for r in review_data.get("reviews", []):
            review_map[r["article_id"]] = r

    # Load render manifest if available
    rendered_map = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
        for r in manifest.get("rendered", []):
            rendered_map[r["article_id"]] = r

    # Connect to Google Sheets
    _, worksheet = get_sheets_client(settings)

    today = datetime.now().strftime("%Y-%m-%d")
    log_entries = []
    winners = []  # posts that passed review - go into posted_history.json

    print(f"📊 Logging {len(copy_data['briefs'])} posts...")

    for brief in copy_data["briefs"]:
        article_id = brief.get("article_id", "unknown")
        scores = brief.get("scores", {})
        review = review_map.get(article_id, {})
        render = rendered_map.get(article_id, {})

        # The vision agent's verdict (review-post skill) takes priority over the
        # mechanical pre-filter's PASS/FAIL - it's the real quality gate.
        review_status = review.get("ai_verdict") or review.get("mechanical_status", "pending")
        full_caption = sanitize.ensure_disclaimer(
            brief.get("copy", {}).get("caption", {}).get("text", "")
        )

        post_data = {
            "date": today,
            "article_id": article_id,
            "headline": sanitize.clean_text(brief.get("copy", {}).get("headline", {}).get("text", brief.get("source_title", ""))),
            "post_type": brief.get("post_type", "static"),
            "status": "ready" if review_status == "PASS" else "needs_fix",
            "india_score": scores.get("india_relevance", ""),
            "engagement_score": scores.get("engagement", ""),
            "total_score": scores.get("total", ""),
            "image_path": render.get("output_path", ""),
            "image_source": render.get("image_source", ""),
            "caption_preview": full_caption[:200],
            "source": brief.get("source", ""),
            "url": brief.get("source_url", brief.get("url", "")),
            "review_status": review_status,
            "rendered_at": render.get("rendered_at", ""),
            "posted_status": "not_posted",
            "posted_at": "",
        }

        log_entries.append(post_data)
        if post_data["status"] == "ready":
            winners.append({
                "id": article_id,
                "title_key": sanitize.title_key(brief.get("source_title", "")),
                "headline": post_data["headline"],
                "date": today,
            })

    # Log all of this run's posts to Google Sheets in one batched call.
    if worksheet:
        success = log_to_sheets(worksheet, log_entries)
        for post_data in log_entries:
            if success:
                print(f"  📊 Sheets: {post_data['headline'][:50]}...")
            else:
                print(f"  ⚠️  Sheets failed, saved locally: {post_data['headline'][:50]}...")
    else:
        for post_data in log_entries:
            print(f"  💾 Local only: {post_data['headline'][:50]}...")

    update_posted_history(data_dir, winners, settings)

    # Save local backup
    local_log = {
        "logged_at": datetime.now().isoformat(),
        "entries": log_entries,
    }

    log_path = data_dir / "log.json"
    # Append to existing log if present
    if log_path.exists():
        with open(log_path) as f:
            existing = json.load(f)
        existing["entries"].extend(log_entries)
        existing["logged_at"] = datetime.now().isoformat()
        local_log = existing

    with open(log_path, "w") as f:
        json.dump(local_log, f, indent=2, ensure_ascii=False)

    sheets_status = "✅ synced" if worksheet else "⚠️ offline (local only)"
    print(f"\n✅ Logged {len(log_entries)} entries. Sheets: {sheets_status}")
    print(f"   Local backup: {log_path}")


if __name__ == "__main__":
    main()
