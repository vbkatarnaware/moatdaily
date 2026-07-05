#!/usr/bin/env python3
"""
MoatDaily - Instagram Publisher (direct Graph API, inert until configured)
Reads copy.json + render_manifest.json -> publishes each review-PASSed post
to the user's own Instagram Business/Creator account via the Graph API ->
writes posted_status/posted_at back to the Sheet.

Inert by design: if instagram.access_token / ig_user_id / public_base_url
aren't all set in config/settings.yaml, this logs "publish skipped" and exits
cleanly - no code change needed once credentials exist, the human just keeps
uploading manually until then.

Requires: an IG Business/Creator account linked to a Facebook Page, a
long-lived Graph API access token, and the rendered PNGs hosted at a public
URL (the Graph API fetches media by URL, not raw bytes) - e.g. serve
output/posts/ from the EC2 box or sync it to S3, and set
instagram.public_base_url to that base URL.

Usage: python scripts/publish_instagram.py
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

import log_to_sheets
import refresh_ig_token
import sanitize

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
POLL_INTERVAL_SECS = 3
POLL_MAX_TRIES = 10


def load_config():
    root = Path(__file__).parent.parent
    with open(root / "config" / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    return settings, root


def is_configured(settings):
    ig = settings.get("instagram", {})
    return bool(ig.get("access_token") and ig.get("ig_user_id") and ig.get("public_base_url"))


def _rel_to_posts(output_path, settings, root):
    posts_dir = (root / settings["output"]["posts_dir"]).resolve()
    return Path(output_path).resolve().relative_to(posts_dir)


def resolve_public_url(output_path, settings, root):
    """Map a local output/posts/... path to its hosted public URL."""
    rel = _rel_to_posts(output_path, settings, root)
    base = settings["instagram"]["public_base_url"].rstrip("/")
    return f"{base}/{rel.as_posix()}"


def ensure_hosted(output_path, settings, root):
    """Make sure the rendered file exists at the location public_base_url serves,
    then return its public URL. This is what makes publishing location-agnostic:
    render anywhere (a laptop, any CLI), and the file is pushed to the serving
    host at publish time.

    Controlled by the optional instagram.host_upload config block:
        host_upload:
          ssh_target: "personalai"           # ssh alias serving public_base_url; "" = same host
          remote_dir: "/srv/moatdaily-posts"  # dir mapped to public_base_url on that host

    If host_upload is omitted (or has no remote_dir), the file is assumed to be
    served already (e.g. the render wrote straight into the served dir) and only
    the URL is returned - no copying.
    """
    upload = settings["instagram"].get("host_upload") or {}
    remote_dir = (upload.get("remote_dir") or "").rstrip("/")
    if remote_dir:
        rel = _rel_to_posts(output_path, settings, root)
        dest_dir = f"{remote_dir}/{rel.parent.as_posix()}".rstrip("/")
        ssh_target = (upload.get("ssh_target") or "").strip()
        src = str(Path(output_path).resolve())
        if ssh_target:
            # Off-server run (e.g. laptop): push to the serving host over SSH.
            subprocess.run(["ssh", ssh_target, "mkdir", "-p", dest_dir], check=True, timeout=30)
            subprocess.run(["scp", "-q", src, f"{ssh_target}:{dest_dir}/"], check=True, timeout=180)
        else:
            # Running on the serving host itself: just copy into the served dir.
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src, dest_dir)
    return resolve_public_url(output_path, settings, root)


def create_media_container(ig_user_id, access_token, image_url, caption=None, is_carousel_item=False):
    params = {"image_url": image_url, "access_token": access_token}
    if caption is not None:
        params["caption"] = caption
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    resp = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def create_carousel_container(ig_user_id, access_token, children_ids, caption):
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
        "access_token": access_token,
    }
    resp = requests.post(f"{GRAPH_BASE}/{ig_user_id}/media", data=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def wait_until_ready(container_id, access_token):
    """Graph API processes media containers async - poll status_code before publishing."""
    for _ in range(POLL_MAX_TRIES):
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=15,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return True
        if status == "ERROR":
            return False
        time.sleep(POLL_INTERVAL_SECS)
    return False


def publish_container(ig_user_id, access_token, container_id):
    resp = requests.post(
        f"{GRAPH_BASE}/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def publish_post(brief, render, settings, root):
    ig = settings["instagram"]
    ig_user_id, access_token = ig["ig_user_id"], ig["access_token"]
    caption = sanitize.ensure_disclaimer(brief.get("copy", {}).get("caption", {}).get("text", ""))

    if brief.get("post_type") == "carousel":
        children = [
            create_media_container(
                ig_user_id, access_token, ensure_hosted(path, settings, root), is_carousel_item=True
            )
            for path in render["files"]
        ]
        container_id = create_carousel_container(ig_user_id, access_token, children, caption)
    else:
        image_url = ensure_hosted(render["output_path"], settings, root)
        container_id = create_media_container(ig_user_id, access_token, image_url, caption=caption)

    if not wait_until_ready(container_id, access_token):
        raise RuntimeError(f"Media container {container_id} failed or timed out processing")

    return publish_container(ig_user_id, access_token, container_id)


def main():
    parser = argparse.ArgumentParser(description="Publish review-PASSed posts to Instagram.")
    parser.add_argument("--only", action="append", metavar="ARTICLE_ID",
                        help="publish only this article id (repeatable)")
    parser.add_argument("--post-type", choices=["static", "carousel"],
                        help="only publish posts of this type")
    parser.add_argument("--limit", type=int, help="publish at most N posts")
    parser.add_argument("--no-sheet", action="store_true",
                        help="do not write posted-status back to Google Sheets")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would publish (and the public image URLs) without posting")
    args = parser.parse_args()

    settings, root = load_config()
    data_dir = root / settings["output"]["data_dir"]

    if not is_configured(settings):
        print(
            "[SKIP] Instagram publishing not configured (instagram.access_token / ig_user_id / "
            "public_base_url blank in config/settings.yaml). Posts stay ready for manual upload."
        )
        return

    # Keep the long-lived token alive: since the pipeline runs regularly, a
    # just-in-time refresh here means the token never gets near its ~60-day
    # expiry, with no separate cron to maintain. Best-effort - never blocks.
    refresh_ig_token.ensure_fresh(settings)

    copy_path = data_dir / "copy.json"
    review_path = data_dir / "review.json"
    manifest_path = data_dir / "render_manifest.json"

    if not (copy_path.exists() and manifest_path.exists()):
        print("copy.json / render_manifest.json not found. Run the pipeline through render-post first.")
        return

    with open(copy_path) as f:
        copy_data = json.load(f)

    review_map = {}
    if review_path.exists():
        with open(review_path) as f:
            for r in json.load(f).get("reviews", []):
                review_map[r["article_id"]] = r

    with open(manifest_path) as f:
        rendered_map = {r["article_id"]: r for r in json.load(f).get("rendered", [])}

    # Only touch the Sheet if we're actually going to publish (and not --no-sheet).
    worksheet = None
    if not args.dry_run and not args.no_sheet:
        _, worksheet = log_to_sheets.get_sheets_client(settings)

    only = set(args.only or [])
    published = 0
    for brief in copy_data["briefs"]:
        article_id = brief["article_id"]

        if only and article_id not in only:
            continue
        if args.post_type and brief.get("post_type") != args.post_type:
            continue

        review = review_map.get(article_id, {})
        verdict = review.get("ai_verdict") or review.get("mechanical_status")
        if verdict != "PASS":
            print(f"  ⏭️  Skipping {article_id} (review status: {verdict})")
            continue

        render = rendered_map.get(article_id)
        if not render:
            print(f"  ⏭️  Skipping {article_id} (not rendered)")
            continue

        if args.limit is not None and published >= args.limit:
            print(f"  ⏭️  Reached --limit {args.limit}, stopping")
            break

        if args.dry_run:
            paths = render.get("files") or [render.get("output_path")]
            print(f"  [dry-run] would publish {article_id} ({brief.get('post_type')}):")
            for p in paths:
                print(f"             {resolve_public_url(p, settings, root)}")
            published += 1
            continue

        try:
            media_id = publish_post(brief, render, settings, root)
            posted_at = datetime.now().isoformat()
            print(f"  ✅ Published {article_id} -> media {media_id}")
            if worksheet:
                log_to_sheets.mark_posted_in_sheet(worksheet, article_id, posted_at)
            published += 1
        except Exception as e:
            print(f"  ❌ Publish failed for {article_id}: {e}")

    verb = "Would publish" if args.dry_run else "Published"
    print(f"\n✅ {verb} {published} post(s) to Instagram.")


if __name__ == "__main__":
    main()
